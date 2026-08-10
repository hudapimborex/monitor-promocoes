"""Formata e envia notificações para os PriceAlert criados (app/pricing).

Hoje só existe o canal Telegram; NotificationSettings.channels_enabled_json e
PriceAlert.channel já deixam espaço pra outros canais (e-mail etc.) depois
sem mudar o resto do fluxo.
"""

from __future__ import annotations

import datetime as dt
import logging
from html import escape
from typing import Optional

from sqlalchemy.orm import Session

from app.core.formatting import format_brl
from app.db.models import NotificationSettings, PriceAlert, Product
from app.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


def format_alert_message(product: Product, alert: PriceAlert) -> str:
    return (
        "📉 <b>Queda de preço confirmada!</b>\n\n"
        f"<b>{escape(product.name)}</b>\n"
        f"Loja: {escape(product.store_domain)}\n"
        f"De {format_brl(alert.old_price)} para {format_brl(alert.new_price)} "
        f"(-{alert.drop_pct:.0f}%)\n\n"
        f"{product.url}"
    )


def notify_alert(
    db: Session, product: Product, alert: PriceAlert, notifier: Optional[TelegramNotifier] = None
) -> bool:
    """Envia a notificação de um alerta já criado e marca notified_at/channel.

    Idempotente na prática: se `alert.notified_at` já estiver preenchido, não
    reenvia (chame só para alertas novos — é assim que o scheduler usa).
    """
    if alert.notified_at is not None:
        return False

    notifier = notifier or TelegramNotifier()

    settings_row = db.query(NotificationSettings).filter_by(user_id=product.user_id).first()
    chat_id = settings_row.telegram_chat_id if settings_row else None
    channels = settings_row.channels_enabled_json if settings_row else ["telegram", "dashboard"]

    if "telegram" not in (channels or []):
        logger.info("Canal telegram desativado para user_id=%s; alerta fica só no painel.", product.user_id)
        return False

    message = format_alert_message(product, alert)
    sent = notifier.send_message(message, chat_id=chat_id)
    if sent:
        alert.notified_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        alert.channel = "telegram"
        db.commit()
    return sent


def notify_pending_alerts(db: Session, user_id: int, notifier: Optional[TelegramNotifier] = None) -> int:
    """Envia todos os alertas ainda não notificados de um usuário. Retorna quantos foram enviados."""
    notifier = notifier or TelegramNotifier()
    pending = (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user_id, PriceAlert.notified_at.is_(None))
        .all()
    )
    sent_count = 0
    for alert in pending:
        product = alert.product
        if notify_alert(db, product, alert, notifier=notifier):
            sent_count += 1
    return sent_count
