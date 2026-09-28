"""Gerenciamento de itens de busca (categorias) pelo próprio usuário.

Antes, as categorias só vinham de config/categories.yml no seed inicial.
Agora o usuário pode adicionar qualquer item (ex: "trinco de porta", "janela
de alumínio") direto pelo painel — cada item vira uma Category (o modelo já
era multi-tenant e dava suporte a isso, só faltava a interface).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.models import Category, User
from app.db.session import get_db
from app.scraping.item_management import (
    DEFAULT_DISCOUNT_TERMS,
    create_item as create_item_row,
    delete_all_items_cascade,
    delete_item_cascade,
)
from app.web.auth_web import get_current_web_user

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


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
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "active": c.active,
                "priority": c.priority,
                "base_terms": ", ".join(kw.get("base_terms", [])),
                "discount_terms": ", ".join(kw.get("discount_terms", [])),
                "sizes": ", ".join(kw.get("sizes", [])),
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

    create_item_row(db, user, name, discount_terms=discount_terms, sizes=sizes, priority=priority)
    return RedirectResponse(url="/items?added=1", status_code=303)


@router.post("/items/{item_id}/toggle")
def toggle_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    category = db.query(Category).filter(Category.id == item_id, Category.user_id == user.id).first()
    if category is None:
        # Provavelmente clique duplo ou aba desatualizada num item que já
        # foi apagado — volta pro painel com um aviso em vez de uma página
        # de erro crua.
        return RedirectResponse(url="/items?error=item_nao_encontrado", status_code=303)
    category.active = not category.active
    db.commit()
    return RedirectResponse(url="/items", status_code=303)


@router.post("/items/{item_id}/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    """Apaga o item de vez — incluindo todo histórico de preço, alertas e
    cupons ligados aos produtos encontrados nele. Irreversível (por isso o
    botão no painel pede confirmação antes de chamar essa rota).
    """
    category = db.query(Category).filter(Category.id == item_id, Category.user_id == user.id).first()
    if category is None:
        # Idempotente na prática: se já foi apagado (clique duplo, aba
        # desatualizada), trata como sucesso em vez de mostrar erro cru.
        return RedirectResponse(url="/items?deleted=1", status_code=303)

    delete_item_cascade(db, category)
    db.commit()
    return RedirectResponse(url="/items?deleted=1", status_code=303)


@router.post("/items/delete-all")
def delete_all_items(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    """Apaga todos os itens de busca de uma vez (com todo o histórico
    ligado a eles) — útil pra zerar a lista e recomeçar só com itens
    adicionados pelo Telegram."""
    delete_all_items_cascade(db, user)
    return RedirectResponse(url="/items?deleted=all", status_code=303)
