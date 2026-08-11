"""Job principal: roda as buscas do dia (rodízio de categorias), grava
preços, detecta quedas reais e notifica.

É este job que o APScheduler dispara (app/scheduler/apscheduler_setup.py) e
que o Background Worker do Render mantém rodando 24/7 (ver README).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.core.formatting import format_brl
from app.core.run_state import finish_run, is_cancelled, is_paused, start_run
from app.core.user_credentials import build_firecrawl_client, build_telegram_notifier
from app.db.models import SearchRun, User
from app.db.session import session_scope
from app.notifications.service import notify_alert
from app.notifications.telegram import TelegramNotifier
from app.pricing.service import check_product_for_drop
from app.scraping.firecrawl_client import FirecrawlError
from app.scraping.ingest import ingest_result
from app.scraping.planner import plan_today
from app.scraping.quota import record_credits

logger = logging.getLogger(__name__)


def run_search_for_user(db: Session, user: User, client, notifier: TelegramNotifier) -> dict:
    """Roda o plano do dia para um usuário. `client` só precisa ter um método
    `.search(query, scrape_top_n)` — assim os testes podem passar um stub em
    vez de bater na API real da Firecrawl.

    Respeita pausar/cancelar (app/core/run_state.py) — checado entre cada
    query, não no meio de uma chamada de busca já em andamento.
    """
    stats = {
        "categories": 0,
        "queries": 0,
        "results": 0,
        "prices_recorded": 0,
        "alerts": 0,
        "errors": 0,
        "coupons_found": 0,
    }

    if not start_run():
        logger.warning("⚠️ Já existe uma busca em andamento — ignorando novo pedido.")
        stats["skipped"] = "already_running"
        return stats

    try:
        plans = plan_today(db, user.id)
        if not plans:
            logger.info(
                "Nenhuma categoria para rodar hoje (user_id=%s) — cota esgotada ou sem categorias ativas.",
                user.id,
            )
            return stats

        logger.info(
            "▶ Iniciando busca: %d categoria(s) hoje — %s",
            len(plans),
            ", ".join(p.category.name for p in plans),
        )

        cancelled = False
        for plan in plans:
            if cancelled:
                break
            stats["categories"] += 1
            logger.info(
                "📂 Categoria: %s (%d busca(s) planejada(s))", plan.category.name, len(plan.queries)
            )
            for query in plan.queries:
                if _wait_while_paused_or_cancelled():
                    cancelled = True
                    logger.info("⏹ Busca cancelada pelo usuário.")
                    break

                search_run = SearchRun(user_id=user.id, category_id=plan.category.id, query=query)
                db.add(search_run)
                db.commit()

                logger.info('🔍 Buscando: "%s"', query)
                try:
                    response = client.search(query, scrape_top_n=plan.scrape_top_n)
                except FirecrawlError as exc:
                    logger.error("❌ Busca falhou (%s): %s", query, exc)
                    search_run.status = "error"
                    search_run.error_message = str(exc)[:1000]
                    db.commit()
                    stats["errors"] += 1
                    continue

                search_run.results_count = len(response.results)
                search_run.credits_used = response.credits_used
                db.commit()
                record_credits(db, response.credits_used)
                stats["queries"] += 1
                stats["results"] += len(response.results)
                logger.info(
                    "✅ %d resultado(s) (%.1f créditos usados)",
                    len(response.results),
                    response.credits_used,
                )

                for result in response.results:
                    outcome = ingest_result(db, user, plan.category, search_run, result)
                    if outcome is None:
                        continue

                    if outcome.coupon_code:
                        stats["coupons_found"] += 1
                        logger.info(
                            "🎟️ Cupom encontrado: %s — %s — %s",
                            outcome.coupon_code,
                            outcome.product.name,
                            outcome.product.store_domain,
                        )

                    if not outcome.price_recorded:
                        logger.info("⚠️ Sem preço identificável: %s", result.url)
                        continue
                    stats["prices_recorded"] += 1
                    logger.info(
                        "💰 %s — %s — %s",
                        outcome.product.name,
                        outcome.product.store_domain,
                        format_brl(outcome.price),
                    )

                    alert = check_product_for_drop(db, outcome.product)
                    if alert is None:
                        continue
                    stats["alerts"] += 1
                    logger.info(
                        "📉 Queda real detectada! %s: %s → %s (-%.0f%%). Notificando...",
                        outcome.product.name,
                        format_brl(alert.old_price),
                        format_brl(alert.new_price),
                        alert.drop_pct,
                    )
                    notify_alert(db, outcome.product, alert, notifier=notifier)

        if cancelled:
            stats["cancelled"] = True
            logger.info(
                "🏁 Busca interrompida: %d query(s), %d resultado(s), %d preço(s) gravado(s), "
                "%d alerta(s), %d cupom(ns)",
                stats["queries"],
                stats["results"],
                stats["prices_recorded"],
                stats["alerts"],
                stats["coupons_found"],
            )
        else:
            logger.info(
                "🏁 Busca concluída: %d query(s), %d resultado(s), %d preço(s) gravado(s), "
                "%d alerta(s), %d cupom(ns)",
                stats["queries"],
                stats["results"],
                stats["prices_recorded"],
                stats["alerts"],
                stats["coupons_found"],
            )
        return stats
    finally:
        finish_run()


def _wait_while_paused_or_cancelled() -> bool:
    """Bloqueia enquanto pausado (checando cancelamento a cada segundo).
    Retorna True se deve cancelar a busca, False se pode seguir normalmente."""
    if is_cancelled():
        return True
    if not is_paused():
        return False

    logger.info("⏸ Busca pausada — aguardando retomar...")
    while is_paused():
        if is_cancelled():
            return True
        time.sleep(1)
    logger.info("▶ Busca retomada.")
    return is_cancelled()


def run_daily_search_job() -> None:
    """Entry point chamado pelo scheduler — roda para todos os usuários (MVP: 1).

    As credenciais (Firecrawl/Telegram) são resolvidas por usuário — prioriza
    o que foi salvo no painel (/settings) e cai para o .env quando não há
    valor salvo (ver app/core/user_credentials.py).
    """
    db = session_scope()
    try:
        users = db.query(User).all()
        for user in users:
            client = build_firecrawl_client(db, user.id)
            notifier = build_telegram_notifier(db, user.id)
            stats = run_search_for_user(db, user, client, notifier)
            logger.info("Busca diária concluída para user_id=%s: %s", user.id, stats)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_daily_search_job()
