"""Painel web MVP (server-rendered com Jinja2) + export CSV.

Protegido por login (app/web/auth_web.py) — só quem tem a senha do usuário
semeado (scripts/bootstrap.py) entra.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.formatting import format_brl
from app.core.live_log import get_entries_since
from app.core.user_credentials import build_firecrawl_client, build_telegram_notifier
from app.db.models import Product, User
from app.db.session import get_db
from app.scheduler.jobs import run_search_for_user
from app.web.auth_web import get_current_web_user
from app.web.dashboard_data import (
    dashboard_summary,
    get_product_history,
    list_products_with_prices,
    list_recent_alerts,
    list_recent_search_runs,
)
from app.web.export import export_alerts_csv, export_history_csv

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/")
def dashboard(
    request: Request,
    run: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    settings = get_settings()
    summary = dashboard_summary(db, user.id)
    summary["credits_budget"] = settings.firecrawl_monthly_credit_budget

    alerts = list_recent_alerts(db, user.id)
    for a in alerts:
        a.old_price_fmt = format_brl(a.old_price)
        a.new_price_fmt = format_brl(a.new_price)

    products = list_products_with_prices(db, user.id)
    search_runs = list_recent_search_runs(db, user.id)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            **summary,
            "alerts": alerts,
            "products": products,
            "search_runs": search_runs,
            "run_started": run == "started",
        },
    )


@router.post("/run-now")
def run_now(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    """Dispara a busca do dia em background, usando as credenciais salvas em
    /settings (com fallback pro .env — ver app/core/user_credentials.py).

    Roda na mesma sessão de banco da requisição: o FastAPI garante que a
    dependency `get_db` só fecha a sessão depois que a background task
    termina, então isso é seguro (ver docs do FastAPI sobre
    "Dependencies with yield and background tasks").
    """
    client = build_firecrawl_client(db, user.id)
    notifier = build_telegram_notifier(db, user.id)
    background_tasks.add_task(run_search_for_user, db, user, client, notifier)
    return RedirectResponse(url="/?run=started", status_code=303)


@router.get("/run-log")
def run_log(since: int = 0, user: User = Depends(get_current_web_user)):
    """Usado pelo painel (polling via JS) pra mostrar a busca "ao vivo".

    `since`: id da última entrada já recebida pelo cliente — só devolve o
    que é novo, pra caixa de log no painel só ir crescendo em vez de
    recarregar tudo a cada poll.
    """
    entries = get_entries_since(since)
    return {
        "entries": [
            {"id": e.id, "time": e.time, "level": e.level, "message": e.message} for e in entries
        ]
    }


@router.get("/products/{product_id}")
def product_detail(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    product = (
        db.query(Product).filter(Product.id == product_id, Product.user_id == user.id).first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    history = get_product_history(db, product.id)
    return templates.TemplateResponse(
        request, "product_detail.html", {"product": product, "history": history}
    )


@router.get("/export/csv")
def export_csv(
    type: str = "history",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_web_user),
):
    if type == "alerts":
        content, filename = export_alerts_csv(db, user.id), "alertas.csv"
    else:
        content, filename = export_history_csv(db, user.id), "historico_precos.csv"
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
