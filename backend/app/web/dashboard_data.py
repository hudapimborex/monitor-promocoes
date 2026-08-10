"""Consultas usadas pelo painel MVP (app/web/routes.py) — separadas das
rotas pra ficar fácil de testar sem precisar de um client HTTP.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.formatting import format_brl
from app.db.models import PriceAlert, PriceHistory, Product, SearchRun
from app.scraping.quota import get_or_create_usage


@dataclass
class ProductRow:
    id: int
    name: str
    store_domain: str
    url: str
    current_price: Optional[float]
    min_price: Optional[float]
    last_seen_at: dt.datetime

    @property
    def current_price_fmt(self) -> str:
        return format_brl(self.current_price) if self.current_price is not None else "—"

    @property
    def min_price_fmt(self) -> str:
        return format_brl(self.min_price) if self.min_price is not None else "—"


@dataclass
class HistoryRow:
    captured_at: dt.datetime
    price: float

    @property
    def price_fmt(self) -> str:
        return format_brl(self.price)


def list_products_with_prices(db: Session, user_id: int) -> list[ProductRow]:
    products = (
        db.query(Product)
        .filter(Product.user_id == user_id)
        .order_by(Product.last_seen_at.desc())
        .all()
    )
    rows = []
    for p in products:
        prices = [h.price for h in p.price_history]  # já vem ordenado por captured_at (relationship)
        current = prices[-1] if prices else None
        min_price = min(prices) if prices else None
        rows.append(
            ProductRow(
                id=p.id,
                name=p.name,
                store_domain=p.store_domain,
                url=p.url,
                current_price=current,
                min_price=min_price,
                last_seen_at=p.last_seen_at,
            )
        )
    return rows


def get_product_history(db: Session, product_id: int) -> list[HistoryRow]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product_id)
        .order_by(PriceHistory.captured_at.desc())
        .all()
    )
    return [HistoryRow(captured_at=r.captured_at, price=r.price) for r in rows]


def list_recent_search_runs(db: Session, user_id: int, limit: int = 15) -> list[SearchRun]:
    return (
        db.query(SearchRun)
        .filter(SearchRun.user_id == user_id)
        .order_by(SearchRun.ran_at.desc())
        .limit(limit)
        .all()
    )


def list_recent_alerts(db: Session, user_id: int, limit: int = 50) -> list[PriceAlert]:
    return (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user_id)
        .order_by(PriceAlert.created_at.desc())
        .limit(limit)
        .all()
    )


def dashboard_summary(db: Session, user_id: int) -> dict:
    products_count = db.query(func.count(Product.id)).filter(Product.user_id == user_id).scalar() or 0

    week_ago = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=7)
    alerts_7d = (
        db.query(func.count(PriceAlert.id))
        .filter(PriceAlert.user_id == user_id, PriceAlert.created_at >= week_ago)
        .scalar()
        or 0
    )

    usage = get_or_create_usage(db)
    return {
        "products_count": products_count,
        "alerts_count_7d": alerts_7d,
        "credits_used": round(usage.credits_used, 1),
    }
