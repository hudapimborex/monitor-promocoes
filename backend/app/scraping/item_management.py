"""Lógica de criar item de busca (categoria), compartilhada entre o painel
web (app/web/items_routes.py) e o webhook do Telegram
(app/web/telegram_webhook.py) — os dois caminhos criam o mesmo tipo de
registro, só muda de onde vem o pedido.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.formatting import slugify
from app.db.models import Category, Coupon, PriceAlert, PriceHistory, Product, SearchRun, User

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


def delete_item_cascade(db: Session, category: Category) -> None:
    """Apaga o item de vez — incluindo todo histórico de preço, alertas e
    cupons ligados aos produtos encontrados nele. Irreversível; não faz
    commit sozinho quando chamado em lote (ver delete_all_items_cascade)."""
    product_ids = [pid for (pid,) in db.query(Product.id).filter(Product.category_id == category.id).all()]

    if product_ids:
        db.query(PriceAlert).filter(PriceAlert.product_id.in_(product_ids)).delete(synchronize_session=False)
        db.query(Coupon).filter(Coupon.product_id.in_(product_ids)).delete(synchronize_session=False)
        db.query(PriceHistory).filter(PriceHistory.product_id.in_(product_ids)).delete(synchronize_session=False)
        db.query(Product).filter(Product.category_id == category.id).delete(synchronize_session=False)

    db.query(SearchRun).filter(SearchRun.category_id == category.id).delete(synchronize_session=False)
    db.delete(category)


def delete_all_items_cascade(db: Session, user: User) -> int:
    """Apaga todos os itens de busca do usuário de uma vez (mesmo cascade do
    delete_item_cascade). Retorna quantos itens foram apagados."""
    categories = db.query(Category).filter(Category.user_id == user.id).all()
    for category in categories:
        delete_item_cascade(db, category)
    db.commit()
    return len(categories)
