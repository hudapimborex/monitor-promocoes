"""Resolve credenciais (Firecrawl/Telegram) por usuário: prioriza o que foi
salvo no painel (/settings, tabela user_credentials) e cai para o .env
quando não há valor salvo — assim dá pra configurar tudo pela interface sem
precisar editar o .env e reiniciar o processo.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import UserCredentials


def get_user_credentials(db: Session, user_id: int) -> Optional[UserCredentials]:
    return db.query(UserCredentials).filter(UserCredentials.user_id == user_id).first()


def build_firecrawl_client(db: Session, user_id: int):
    from app.scraping.firecrawl_client import FirecrawlClient

    creds = get_user_credentials(db, user_id)
    api_key = (creds.firecrawl_api_key if creds else None) or None
    return FirecrawlClient(api_key=api_key)


def build_telegram_notifier(db: Session, user_id: int):
    from app.notifications.telegram import TelegramNotifier

    creds = get_user_credentials(db, user_id)
    bot_token = (creds.telegram_bot_token if creds else None) or None
    chat_id = (creds.telegram_chat_id if creds else None) or None
    return TelegramNotifier(bot_token=bot_token, default_chat_id=chat_id)
