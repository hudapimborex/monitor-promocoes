"""Webhook do Telegram: deixa adicionar item de busca mandando o nome dele
direto pro bot, sem precisar abrir o painel. Também aceita "status <nome>"
pra consultar o que já foi buscado, e uma prioridade opcional no fim do
nome (separada por vírgula) na hora de adicionar.

Só aceita mensagem vinda de um chat_id que já está configurado em
Configurações pra receber alertas — qualquer outra é ignorada (sem
resposta), pra não deixar estranho adicionando item na sua lista.

A URL do webhook tem um segredo no caminho (derivado do JWT_SECRET, que já
existe) em vez de depender de outra variável de ambiente nova — só o
Telegram sabe essa URL depois que a gente registra ela (ver
scripts/register_telegram_webhook.py).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.user_credentials import build_telegram_notifier
from app.db.models import NotificationSettings, User, UserCredentials
from app.db.session import get_db
from app.notifications.service import split_chat_ids
from app.scraping.item_management import (
    build_items_list_message,
    build_status_message,
    create_item,
    find_category_by_name,
    parse_name_and_priority,
)

logger = logging.getLogger(__name__)
router = APIRouter()

STATUS_KEYWORDS = ("status", "buscas", "busca")
LIST_KEYWORDS = ("itens", "item", "lista")

HELP_TEXT = (
    "📋 Como usar:\n"
    '• Manda o nome de um item (ex: "Fogão") pra adicionar — opcionalmente '
    'com a prioridade no rodízio no fim, separada por vírgula (ex: "Fogão, '
    '1"; 1 = mais prioritário). Sem isso, a prioridade padrão é 2.\n'
    '• Manda "status <nome>" (ex: "status Fogão") pra ver quantas buscas já '
    "rolaram e o que foi encontrado até agora.\n"
    '• Manda "itens" pra ver a lista completa do que está sendo monitorado.'
)


def webhook_secret() -> str:
    """Deriva um segredo estável a partir do JWT_SECRET já configurado —
    evita precisar de mais uma variável de ambiente só pra isso."""
    settings = get_settings()
    return hashlib.sha256(f"telegram-webhook:{settings.jwt_secret}".encode()).hexdigest()[:32]


def find_user_by_telegram_chat_id(db: Session, chat_id: str) -> Optional[User]:
    """Procura, entre as credenciais salvas em /settings e as
    NotificationSettings, qual usuário tem esse chat_id configurado (o campo
    aceita vários separados por vírgula — ver app/notifications/service.py).
    """
    for creds in db.query(UserCredentials).filter(UserCredentials.telegram_chat_id.isnot(None)).all():
        if chat_id in split_chat_ids(creds.telegram_chat_id):
            return db.query(User).filter(User.id == creds.user_id).first()

    for row in db.query(NotificationSettings).filter(NotificationSettings.telegram_chat_id.isnot(None)).all():
        if chat_id in split_chat_ids(row.telegram_chat_id):
            return db.query(User).filter(User.id == row.user_id).first()

    return None


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request, db: Session = Depends(get_db)):
    if secret != webhook_secret():
        # Finge que a rota nem existe pra quem não souber a URL certa.
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    text = (message.get("text") or "").strip()

    # Sempre responde 200 pro Telegram (mesmo ignorando a mensagem) — um erro
    # faria ele ficar reenviando a mesma atualização várias vezes.
    if not chat_id or not text or text.startswith("/"):
        return {"ok": True}

    try:
        user = find_user_by_telegram_chat_id(db, chat_id)
        if user is None:
            logger.info("Telegram webhook: chat_id %s não autorizado, ignorando.", chat_id)
            return {"ok": True}

        notifier = build_telegram_notifier(db, user.id)

        if text.strip().lower() in ("ajuda", "help", "?"):
            notifier.send_message(HELP_TEXT, chat_id=chat_id)
            return {"ok": True}

        if text.strip().lower() in LIST_KEYWORDS:
            notifier.send_message(build_items_list_message(db, user), chat_id=chat_id)
            return {"ok": True}

        first_word, _, rest = text.partition(" ")
        if first_word.lower() in STATUS_KEYWORDS and rest.strip():
            category = find_category_by_name(db, user, rest.strip())
            if category is None:
                notifier.send_message(f'Não achei nenhum item chamado "{rest.strip()}".', chat_id=chat_id)
            else:
                notifier.send_message(build_status_message(db, category), chat_id=chat_id)
            return {"ok": True}

        name, priority = parse_name_and_priority(text)
        category = create_item(db, user, name, priority=priority or 2)
        logger.info('Item "%s" criado via Telegram por chat_id %s.', category.name, chat_id)

        notifier.send_message(
            f'✅ Item adicionado: "{category.name}" (prioridade {category.priority}) — '
            "já entra no rodízio de buscas.",
            chat_id=chat_id,
        )
    except Exception:
        logger.exception("Erro processando mensagem do webhook do Telegram")

    return {"ok": True}
