"""Seed inicial: planos padrão e usuário único do MVP.

Roda de forma idempotente — pode ser chamado toda vez que a app sobe sem
duplicar nada (útil em deploys no Render, que reiniciam o processo).

Não semeia categorias: os itens de busca são só os que o usuário adiciona
pelo painel ou mandando mensagem pro bot do Telegram — nada é criado
automaticamente (ver app/scraping/item_management.py).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Plan, User

DEFAULT_PLANS = [
    {
        "name": "free",
        "max_searches_per_day": 30,
        "max_categories": 2,
        "max_notifications_per_day": 50,
        "price_cents": 0,
        "is_default": True,
    },
    {
        # Ainda não vendido — só existe pra o /subscribe ter pra onde apontar.
        "name": "pro",
        "max_searches_per_day": 200,
        "max_categories": 10,
        "max_notifications_per_day": 500,
        "price_cents": 2990,
        "is_default": False,
    },
]


def seed_plans(db: Session) -> Plan:
    """Garante que os planos padrão existem. Retorna o plano default (free)."""
    existing = {p.name: p for p in db.query(Plan).all()}
    default_plan = None
    for plan_data in DEFAULT_PLANS:
        plan = existing.get(plan_data["name"])
        if plan is None:
            plan = Plan(**plan_data)
            db.add(plan)
            db.flush()
        if plan_data["is_default"]:
            default_plan = plan
    db.commit()
    return default_plan


def seed_bootstrap_user(db: Session, default_plan: Plan) -> User:
    settings = get_settings()
    user = db.query(User).filter(User.email == settings.bootstrap_user_email).first()
    if user is None:
        user = User(
            email=settings.bootstrap_user_email,
            hashed_password=hash_password(settings.bootstrap_user_password),
            plan_id=default_plan.id if default_plan else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def run_seed(db: Session) -> None:
    default_plan = seed_plans(db)
    seed_bootstrap_user(db, default_plan)
