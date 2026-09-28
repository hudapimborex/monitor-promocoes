"""Lógica de criar item de busca (categoria), compartilhada entre o painel
web (app/web/items_routes.py) e o webhook do Telegram
(app/web/telegram_webhook.py) — os dois caminhos criam o mesmo tipo de
registro, só muda de onde vem o pedido.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.formatting import format_brl, slugify
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


def parse_name_and_priority(text: str) -> tuple[str, Optional[int]]:
    """Extrai uma prioridade opcional do fim do texto, separada por vírgula
    (ex: "Fogão, 1" -> ("Fogão", 1)). Sem vírgula com número no final,
    devolve o texto inteiro como nome e prioridade None (fica o padrão)."""
    if "," in text:
        name_part, _, priority_part = text.rpartition(",")
        priority_part = priority_part.strip()
        if priority_part.isdigit():
            priority = int(priority_part)
            if 1 <= priority <= 99:
                return name_part.strip(), priority
    return text.strip(), None


def find_category_by_name(db: Session, user: User, query: str) -> Optional[Category]:
    """Procura um item do usuário pelo nome — prioriza igualdade exata
    (sem diferenciar maiúsculas), cai pra a primeira que contém o texto
    buscado como substring."""
    query_norm = query.strip().lower()
    if not query_norm:
        return None
    categories = db.query(Category).filter(Category.user_id == user.id).all()
    for category in categories:
        if category.name.strip().lower() == query_norm:
            return category
    for category in categories:
        if query_norm in category.name.strip().lower():
            return category
    return None


def build_status_message(db: Session, category: Category) -> str:
    """Monta um resumo do que já rolou de busca pra um item — usado no
    comando "status <nome>" do webhook do Telegram."""
    run_count = db.query(SearchRun).filter(SearchRun.category_id == category.id).count()
    last_run = (
        db.query(SearchRun)
        .filter(SearchRun.category_id == category.id)
        .order_by(SearchRun.ran_at.desc())
        .first()
    )

    product_ids = [pid for (pid,) in db.query(Product.id).filter(Product.category_id == category.id).all()]

    latest = None
    if product_ids:
        latest = (
            db.query(PriceHistory, Product)
            .join(Product, PriceHistory.product_id == Product.id)
            .filter(Product.category_id == category.id)
            .order_by(PriceHistory.captured_at.desc())
            .first()
        )

    alert_count = 0
    coupon_count = 0
    if product_ids:
        alert_count = db.query(PriceAlert).filter(PriceAlert.product_id.in_(product_ids)).count()
        coupon_count = db.query(Coupon).filter(Coupon.product_id.in_(product_ids)).count()

    status_label = "ativo" if category.active else "pausado"
    lines = [f"📊 {category.name}", f"Status: {status_label} (prioridade {category.priority})"]

    runs_line = f"{run_count} busca(s) já feita(s)"
    if last_run:
        runs_line += f" — última em {last_run.ran_at.strftime('%d/%m %H:%M')}"
    lines.append(runs_line)
    lines.append(f"{len(product_ids)} produto(s) monitorado(s)")

    if latest:
        price_row, product = latest
        lines.append(
            f"Preço mais recente: {format_brl(price_row.price)} — {product.store_domain} "
            f"({price_row.captured_at.strftime('%d/%m')})"
        )
    if alert_count:
        lines.append(f"📉 {alert_count} alerta(s) de queda de preço já enviado(s)")
    if coupon_count:
        lines.append(f"🎟️ {coupon_count} cupom(ns) encontrado(s)")

    return "\n".join(lines)


def build_items_list_message(db: Session, user: User) -> str:
    """Lista todos os itens do usuário com status/prioridade — usado no
    comando "itens" do webhook do Telegram, pra ver o rodízio atual sem
    abrir o painel."""
    categories = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.priority.asc(), Category.name.asc())
        .all()
    )
    if not categories:
        return "Nenhum item cadastrado ainda — manda o nome de um item pra começar."

    lines = [f"📋 Seus itens ({len(categories)}):"]
    for category in categories:
        icon = "✅" if category.active else "⏸"
        lines.append(f"{icon} {category.name} (prioridade {category.priority})")
    return "\n".join(lines)


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
