"""Página de Configurações: credenciais (Firecrawl/Telegram) e troca de senha.

Guardar aqui em vez de só no `.env` permite configurar tudo pelo painel sem
editar arquivo/redeploy — útil já que o app roda numa nuvem gratuita onde
mexer no `.env` de produção não é tão direto quanto localmente. Os valores
salvos aqui têm prioridade sobre o `.env` (ver app/core/user_credentials.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import logging

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.formatting import mask_secret
from app.core.security import hash_password, verify_password
from app.core.user_credentials import build_telegram_notifier
from app.db.models import User, UserCredentials
from app.db.session import get_db
from app.web.auth_web import get_current_web_user
from app.web.telegram_webhook import webhook_secret

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _get_or_create_credentials(db: Session, user_id: int) -> UserCredentials:
    creds = db.query(UserCredentials).filter(UserCredentials.user_id == user_id).first()
    if creds is None:
        creds = UserCredentials(user_id=user_id)
        db.add(creds)
        db.commit()
        db.refresh(creds)
    return creds


@router.get("/settings")
def settings_page(
    request: Request,
    saved: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    creds = _get_or_create_credentials(db, user.id)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "firecrawl_masked": mask_secret(creds.firecrawl_api_key),
            "telegram_token_masked": mask_secret(creds.telegram_bot_token),
            "telegram_chat_id": creds.telegram_chat_id or "",
            "saved": saved,
            "error": error,
        },
    )


@router.post("/settings/credentials")
def save_credentials(
    firecrawl_api_key: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    creds = _get_or_create_credentials(db, user.id)

    # campo em branco = mantém o valor atual (evita apagar sem querer ao só
    # querer atualizar um dos três campos)
    if firecrawl_api_key.strip():
        creds.firecrawl_api_key = firecrawl_api_key.strip()
    if telegram_bot_token.strip():
        creds.telegram_bot_token = telegram_bot_token.strip()
    # chat_id não é segredo, então esse aqui pode ser limpo enviando vazio
    creds.telegram_chat_id = telegram_chat_id.strip() or None

    db.commit()
    return RedirectResponse(url="/settings?saved=credentials", status_code=303)


@router.post("/settings/password")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_new_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    if not verify_password(current_password, user.hashed_password):
        return RedirectResponse(url="/settings?error=senha_atual_incorreta", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse(url="/settings?error=senha_muito_curta", status_code=303)
    if new_password != confirm_new_password:
        return RedirectResponse(url="/settings?error=senhas_nao_conferem", status_code=303)

    user.hashed_password = hash_password(new_password)
    db.commit()
    return RedirectResponse(url="/settings?saved=password", status_code=303)


@router.post("/settings/telegram-webhook")
def register_telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    """Registra a URL do webhook do Telegram (setWebhook) usando o token já
    salvo em Configurações — assim quem clica no botão nunca precisa colar
    token nenhum em lugar nenhum, o servidor usa a própria credencial que já
    tem guardada."""
    notifier = build_telegram_notifier(db, user.id)
    if not notifier.is_configured:
        return RedirectResponse(url="/settings?error=telegram_nao_configurado", status_code=303)

    base_url = str(request.base_url).rstrip("/")
    if base_url.startswith("http://"):
        base_url = "https://" + base_url[len("http://") :]
    webhook_url = f"{base_url}/telegram/webhook/{webhook_secret()}"

    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{notifier.bot_token}/setWebhook",
            json={"url": webhook_url},
            timeout=15,
        )
        data = resp.json()
    except httpx.HTTPError:
        logger.exception("Erro ao registrar webhook do Telegram")
        return RedirectResponse(url="/settings?error=telegram_webhook_falhou", status_code=303)

    if not data.get("ok"):
        logger.error("Telegram setWebhook recusou: %s", data)
        return RedirectResponse(url="/settings?error=telegram_webhook_falhou", status_code=303)

    return RedirectResponse(url="/settings?saved=webhook", status_code=303)
