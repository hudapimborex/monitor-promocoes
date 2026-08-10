"""Decide quais categorias rodam hoje e quantas queries cada uma pode fazer,
respeitando a cota mensal de créditos (app/scraping/quota.py) e o rodízio
configurado em config/categories.yml.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import yaml
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Category
from app.scraping.query_builder import build_queries
from app.scraping.quota import daily_query_allowance


@dataclass
class CategoryPlan:
    category: Category
    queries: list[str]
    scrape_top_n: int


def _load_rotation_config() -> tuple[dict, dict]:
    settings = get_settings()
    with open(settings.categories_config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    return config.get("scraping", {}) or {}, config.get("rotation", {}) or {}


def plan_today(db: Session, user_id: int, today: Optional[dt.date] = None) -> list[CategoryPlan]:
    settings = get_settings()
    scraping_cfg, rotation_cfg = _load_rotation_config()
    scrape_top_n = scraping_cfg.get("scrape_top_n", settings.firecrawl_scrape_top_n)
    categories_per_day = max(1, rotation_cfg.get("categories_per_day", 2))

    # Aproximação usada no orçamento aprovado no plano: 2 créditos "base" da
    # busca + 1 crédito por página raspada.
    credits_per_query = 2 + scrape_top_n
    total_allowance = daily_query_allowance(db, credits_per_query)
    if total_allowance <= 0:
        return []

    categories = (
        db.query(Category)
        .filter(Category.user_id == user_id, Category.active.is_(True))
        .order_by(Category.priority.asc(), Category.id.asc())
        .all()
    )
    if not categories:
        return []

    # Rodízio simples: o dia do ano decide o offset, assim cada categoria
    # tem sua vez ao longo dos dias em vez de sempre rodarem as mesmas primeiro.
    day_offset = (today or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).date()).toordinal()
    offset = day_offset % len(categories)
    rotated = categories[offset:] + categories[:offset]
    todays_categories = rotated[:categories_per_day]

    per_category_allowance = max(1, total_allowance // max(1, len(todays_categories)))

    plans: list[CategoryPlan] = []
    for category in todays_categories:
        queries = build_queries(category, max_queries=per_category_allowance)
        if queries:
            plans.append(
                CategoryPlan(category=category, queries=queries, scrape_top_n=scrape_top_n)
            )
    return plans
