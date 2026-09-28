"""Lógica de criar item de busca (categoria), compartilhada entre o painel
web (app/web/items_routes.py) e o webhook do Telegram
(app/web/telegram_webhook.py) — os dois caminhos criam o mesmo tipo de
registro, só muda de onde vem o pedido.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.formatting import slugify
from app.db.models import Category, User

DEFAULT_DISCOUNT_TERMS = "promoção, desconto, oferta"


def split_terms(raw: str) -> list:
    return [t.strip() for t in raw.split(",") if t.strip()]


def unique_slug(db: Session, user_id: int, base_slug: str) -> str:
    slug = base_slug
    n = 2
    existing = {c.slug for c in db.query(Category.slug).filter(Category.user_id == user_id).all()}
    while slug in existing:
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


def create_item(
    db: Session,
    user: User,
    name: str,
    discount_terms: str = DEFAULT_DISCOUNT_TERMS,
    sizes: str = "",
    priority: int = 2,
) -> Category:
    """Cria um novo item de busca (Category) pro usuário. Não valida nome
    vazio — quem chama decide o que fazer nesse caso (o form web mostra um
    erro; o webhook do Telegram simplesmente ignora)."""
    name = name.strip()
    slug = unique_slug(db, user.id, slugify(name))
    category = Category(
        user_id=user.id,
        slug=slug,
        name=name,
        priority=max(1, priority),
        active=True,
        keywords_json={
            "base_terms": [name],
            "discount_terms": split_terms(discount_terms) or split_terms(DEFAULT_DISCOUNT_TERMS),
            "sizes": split_terms(sizes),
        },
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category
