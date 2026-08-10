"""Gerenciamento de itens de busca (categorias) pelo próprio usuário.

Antes, as categorias só vinham de config/categories.yml no seed inicial.
Agora o usuário pode adicionar qualquer item (ex: "trinco de porta", "janela
de alumínio") direto pelo painel — cada item vira uma Category (o modelo já
era multi-tenant e dava suporte a isso, só faltava a interface).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.formatting import slugify
from app.db.models import Category, Product, SearchRun, User
from app.db.session import get_db
from app.web.auth_web import get_current_web_user

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

DEFAULT_DISCOUNT_TERMS = "promoção, desconto, oferta"


def _split_terms(raw: str) -> list:
    return [t.strip() for t in raw.split(",") if t.strip()]


def _unique_slug(db: Session, user_id: int, base_slug: str) -> str:
    slug = base_slug
    n = 2
    existing = {c.slug for c in db.query(Category.slug).filter(Category.user_id == user_id).all()}
    while slug in existing:
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


@router.get("/items")
def list_items(
    request: Request,
    added: Optional[str] = None,
    deleted: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    items = (
        db.query(Category)
        .filter(Category.user_id == user.id)
        .order_by(Category.priority.asc(), Category.name.asc())
        .all()
    )
    rows = []
    for c in items:
        kw = c.keywords_json or {}
        has_history = (
            db.query(Product.id).filter(Product.category_id == c.id).first() is not None
            or db.query(SearchRun.id).filter(SearchRun.category_id == c.id).first() is not None
        )
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "active": c.active,
                "priority": c.priority,
                "base_terms": ", ".join(kw.get("base_terms", [])),
                "discount_terms": ", ".join(kw.get("discount_terms", [])),
                "sizes": ", ".join(kw.get("sizes", [])),
                "can_delete": not has_history,
            }
        )
    return templates.TemplateResponse(
        request,
        "items.html",
        {
            "items": rows,
            "default_discount_terms": DEFAULT_DISCOUNT_TERMS,
            "added": added,
            "deleted": deleted,
            "error": error,
        },
    )


@router.post("/items")
def create_item(
    name: str = Form(...),
    discount_terms: str = Form(DEFAULT_DISCOUNT_TERMS),
    sizes: str = Form(""),
    priority: int = Form(2),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/items?error=nome_vazio", status_code=303)

    slug = _unique_slug(db, user.id, slugify(name))
    category = Category(
        user_id=user.id,
        slug=slug,
        name=name,
        priority=max(1, priority),
        active=True,
        keywords_json={
            "base_terms": [name],
            "discount_terms": _split_terms(discount_terms) or _split_terms(DEFAULT_DISCOUNT_TERMS),
            "sizes": _split_terms(sizes),
        },
    )
    db.add(category)
    db.commit()
    return RedirectResponse(url="/items?added=1", status_code=303)


@router.post("/items/{item_id}/toggle")
def toggle_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    category = db.query(Category).filter(Category.id == item_id, Category.user_id == user.id).first()
    if category is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    category.active = not category.active
    db.commit()
    return RedirectResponse(url="/items", status_code=303)


@router.post("/items/{item_id}/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    category = db.query(Category).filter(Category.id == item_id, Category.user_id == user.id).first()
    if category is None:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    has_history = (
        db.query(Product.id).filter(Product.category_id == category.id).first() is not None
        or db.query(SearchRun.id).filter(SearchRun.category_id == category.id).first() is not None
    )
    if has_history:
        # Não apaga pra não quebrar produtos/histórico já ligados a essa
        # categoria — só desativa, o que já tira do rodízio de buscas.
        category.active = False
        db.commit()
        return RedirectResponse(url="/items?error=tem_historico", status_code=303)

    db.delete(category)
    db.commit()
    return RedirectResponse(url="/items?deleted=1", status_code=303)
