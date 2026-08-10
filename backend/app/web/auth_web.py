"""Login do painel web via cookie de sessão.

Reaproveita create_access_token/decode_access_token (mesmo mecanismo JWT da
API em app/api/auth.py), só que aqui o token vive num cookie httpOnly em vez
do header Authorization — é assim que faz sentido pra um app server-rendered
com navegação normal de páginas.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

SESSION_COOKIE_NAME = "session"


class NotAuthenticatedError(Exception):
    """Levantada pelo dependency quando não há sessão válida — um exception
    handler em main.py captura isso e redireciona pra /login."""


def get_current_web_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    email = decode_access_token(token) if token else None
    if not email:
        raise NotAuthenticatedError()

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise NotAuthenticatedError()
    return user
