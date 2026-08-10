"""Envio de notificações via Telegram Bot API.

Setup (ver README): crie um bot com o @BotFather, pegue o token
(TELEGRAM_BOT_TOKEN) e descubra o chat_id conversando com o bot e chamando
GET https://api.telegram.org/bot<token>/getUpdates (ou @userinfobot pro seu
próprio chat_id, se for uma conversa 1:1 com o bot).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, default_chat_id: Optional[str] = None):
        settings = get_settings()
        self.bot_token = bot_token or settings.telegram_bot_token
        self.default_chat_id = default_chat_id or settings.telegram_default_chat_id

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        chat_id = chat_id or self.default_chat_id
        if not self.bot_token or not chat_id:
            logger.warning(
                "Telegram não configurado (TELEGRAM_BOT_TOKEN/chat_id ausente); pulando envio."
            )
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.error("Erro de rede ao enviar mensagem no Telegram: %s", exc)
            return False

        if resp.status_code != 200:
            logger.error("Telegram sendMessage falhou (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
