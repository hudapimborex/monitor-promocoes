"""Job principal: roda as buscas do dia (rodízio de categorias), grava
preços, detecta quedas reais e notifica.

É este job que o APScheduler dispara (app/scheduler/apscheduler_setup.py) e
que o Background Worker do Render mantém rodando 24/7 (ver README).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.formatting import format_brl
from app.core.run_state import finish_run, is_cancelled, is_paused, start_run
from app.core.user_credentials import build_firecrawl_client, build_telegram_notifier
from app.db.models import Category, SearchRun, User
from app.db.session import session_scope
from app.notifications.service import notify_alert, notify_status
from app.notifications.telegram import TelegramNotifier
from app.pricing.service import check_product_for_drop
from app.scraping.firecrawl_client import FirecrawlError
from app.scraping.ingest import ingest_result
from app.scraping.planner import plan_today
from app.scraping.query_builder import build_queries
from app.scraping.quota import record_credits, remaining_budget

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

        total_queries = sum(len(p.queries) for p in plans)
        logger.info(
            "▶ Iniciando busca: %d categoria(s) hoje — %s",
            len(plans),
            ", ".join(p.category.name for p in plans),
        )
        notify_status(
            db,
            user.id,
            "🔎 Começando a busca de hoje: "
            + ", ".join(p.category.name for p in plans)
            + f"\n{total_queries} busca(s) planejada(s) no total.",
            notifier=notifier,
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

        summary = (
            f"{stats['queries']} busca(s) feita(s), {stats['results']} resultado(s), "
            f"{stats['prices_recorded']} preço(s) gravado(s), {stats['alerts']} alerta(s) de queda, "
            f"{stats['coupons_found']} cupom(ns) encontrado(s)."
        )
        if stats["errors"]:
            summary += f"\n⚠️ {stats['errors']} busca(s) falharam."

        if cancelled:
            stats["cancelled"] = True
            logger.info("🏁 Busca interrompida: %s", summary)
            notify_status(db, user.id, f"⏹ Busca interrompida.\n{summary}", notifier=notifier)
        else:
            logger.info("🏁 Busca concluída: %s", summary)
            notify_status(db, user.id, f"🏁 Busca concluída.\n{summary}", notifier=notifier)
        return stats
    finally:
        finish_run()


def run_immediate_check(
    user_id: int,
    category_id: int,
    max_queries: int = 5,
    db: Optional[Session] = None,
    client=None,
    notifier: Optional[TelegramNotifier] = None,
) -> dict:
    """Checagem rápida e pontual de um único item, disparada pelo webhook do
    Telegram assim que o item é criado (ou sob pedido, com "buscar <nome>").
    Por padrão abre sua própria sessão (session_scope) porque é chamada como
    BackgroundTask do FastAPI, depois que a resposta já foi mandada pro
    Telegram — não tem por que segurar a resposta do webhook esperando a
    Firecrawl responder. `db`/`client`/`notifier` existem pra os testes
    poderem injetar stubs sem precisar de sessão/credenciais reais.

    Não passa pelo rodízio/cota do plan_today (isso é só pra economizar
    créditos na rotina diária) — só limita a poucas queries e checa o
    orçamento mensal restante antes de rodar, pra não estourar o
    orçamento com checagens manuais repetidas.
    """
    stats = {"queries": 0, "results": 0, "prices_recorded": 0, "alerts": 0, "coupons_found": 0, "errors": 0}
    owns_session = db is None
    if db is None:
        db = session_scope()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        category = db.query(Category).filter(Category.id == category_id).first()
        if user is None or category is None:
            return stats

        if notifier is None:
            notifier = build_telegram_notifier(db, user_id)
        settings = get_settings()
        scrape_top_n = settings.firecrawl_scrape_top_n
        credits_per_query = 2 + scrape_top_n

        if remaining_budget(db) < credits_per_query:
            notify_status(
                db,
                user_id,
                f'⚠️ Não consegui checar "{category.name}" agora — o orçamento de créditos '
                "do mês já está esgotado. Ele entra no rodízio normal do dia seguinte.",
                notifier=notifier,
            )
            return stats

        if client is None:
            client = build_firecrawl_client(db, user_id)
        queries = build_queries(category, max_queries=max_queries)

        for query in queries:
            search_run = SearchRun(user_id=user_id, category_id=category.id, query=query)
            db.add(search_run)
            db.commit()

            try:
                response = client.search(query, scrape_top_n=scrape_top_n)
            except FirecrawlError as exc:
                logger.error("❌ Checagem imediata falhou (%s): %s", query, exc)
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

            for result in response.results:
                outcome = ingest_result(db, user, category, search_run, result)
                if outcome is None:
                    continue

                if outcome.coupon_code:
                    stats["coupons_found"] += 1

                if not outcome.price_recorded:
                    continue
                stats["prices_recorded"] += 1

                alert = check_product_for_drop(db, outcome.product)
                if alert is None:
                    continue
                stats["alerts"] += 1
                notify_alert(db, outcome.product, alert, notifier=notifier)

        if stats["queries"] == 0:
            summary = f'🔍 Não consegui rodar nenhuma busca pra "{category.name}" agora — tenta de novo mais tarde.'
        else:
            summary = (
                f'🔍 Busca inicial de "{category.name}" concluída: {stats["queries"]} busca(s), '
                f'{stats["results"]} resultado(s), {stats["prices_recorded"]} preço(s) registrado(s).'
            )
            if stats["alerts"]:
                summary += f' 📉 {stats["alerts"]} queda de preço já confirmada (avisei acima)!'
            elif stats["prices_recorded"]:
                summary += " Ainda sem histórico suficiente pra confirmar queda — vou continuar de olho."
            if stats["coupons_found"]:
                summary += f' 🎟️ {stats["coupons_found"]} cupom(ns) encontrado(s).'
            if stats["errors"]:
                summary += f' ⚠️ {stats["errors"]} busca(s) falharam.'

        notify_status(db, user_id, summary, notifier=notifier)
        return stats
    except Exception:
        logger.exception(
            "Erro na checagem imediata (user_id=%s, category_id=%s)", user_id, category_id
        )
        return stats
    finally:
        if owns_session:
            db.close()


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
