"""Gerenciador de cota de créditos Firecrawl.

Garante que o app não ultrapasse o orçamento mensal configurado
(FIRECRAWL_MONTHLY_CREDIT_BUDGET) — em vez de estourar a cota grátis no meio
do mês, o orçamento restante é dividido pelos dias que faltam, reduzindo o
rodízio automaticamente conforme o mês avança.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import CreditUsage


def _current_year_month() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m")


def get_or_create_usage(db: Session) -> CreditUsage:
    ym = _current_year_month()
    usage = db.query(CreditUsage).filter(CreditUsage.year_month == ym).first()
    if usage is None:
        usage = CreditUsage(year_month=ym, credits_used=0.0)
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


def record_credits(db: Session, credits: float) -> CreditUsage:
    usage = get_or_create_usage(db)
    usage.credits_used += credits
    db.commit()
    db.refresh(usage)
    return usage


def remaining_budget(db: Session) -> float:
    settings = get_settings()
    usage = get_or_create_usage(db)
    return max(0.0, settings.firecrawl_monthly_credit_budget - usage.credits_used)


def days_left_in_month(today: Optional[dt.date] = None) -> int:
    today = today or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).date()
    if today.month == 12:
        next_month = dt.date(today.year + 1, 1, 1)
    else:
        next_month = dt.date(today.year, today.month + 1, 1)
    return max(1, (next_month - today).days)


def daily_query_allowance(db: Session, credits_per_query: float) -> int:
    """Quantas queries ainda cabem hoje, dado o orçamento restante do mês.

    Divide o orçamento restante igualmente pelos dias que faltam no mês —
    isso evita gastar tudo nos primeiros dias e ficar sem cota no resto dele.
    """
    if credits_per_query <= 0:
        return 0
    remaining = remaining_budget(db)
    days_left = days_left_in_month()
    daily_budget = remaining / days_left
    return max(0, int(daily_budget // credits_per_query))
