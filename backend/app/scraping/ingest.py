"""Transforma um SearchResult da Firecrawl em Product + PriceHistory no banco.

Fluxo: normaliza a URL (base da deduplicação), acha ou cria o Product,
extrai o preço do markdown raspado e, se encontrado, grava uma nova linha em
PriceHistory vinculada ao SearchRun que originou a observação. A detecção de
"queda real" (app/pricing) roda depois, em cima do histórico gravado aqui.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.db.models import Category, PriceHistory, Product, SearchRun, User
from app.scraping.firecrawl_client import SearchResult
from app.scraping.price_parser import extract_best_price

logger = logging.getLogger(__name__)

# Parâmetros de tracking comuns que não devem afetar a deduplicação da URL.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "igshid",
}


def normalize_url(raw_url: str) -> str:
    parts = urlsplit(raw_url)
    query_pairs = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    normalized_path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), normalized_path, urlencode(query_pairs), "")
    )


def url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


@dataclass
class IngestOutcome:
    product: Product
    price: Optional[float]
    is_new_product: bool
    price_recorded: bool


def ingest_result(
    db: Session,
    user: User,
    category: Category,
    search_run: SearchRun,
    result: SearchResult,
) -> Optional[IngestOutcome]:
    if not result.url:
        return None

    normalized = normalize_url(result.url)
    h = url_hash(normalized)
    domain = urlsplit(normalized).netloc

    product = (
        db.query(Product).filter(Product.user_id == user.id, Product.url_hash == h).first()
    )
    is_new = product is None
    now = search_run.ran_at

    if product is None:
        product = Product(
            user_id=user.id,
            category_id=category.id,
            name=result.title or normalized,
            store_domain=domain,
            url=normalized,
            url_hash=h,
            image_url=result.image_url,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(product)
        db.flush()
    else:
        product.last_seen_at = now
        if result.title:
            product.name = result.title
        if result.image_url:
            product.image_url = result.image_url

    price = extract_best_price(result.markdown or "")
    price_recorded = False
    if price is not None:
        db.add(
            PriceHistory(
                product_id=product.id,
                price=price,
                currency="BRL",
                captured_at=now,
                source_search_run_id=search_run.id,
            )
        )
        price_recorded = True
    else:
        logger.info("Não foi possível extrair preço de %s", normalized)

    db.commit()
    return IngestOutcome(
        product=product, price=price, is_new_product=is_new, price_recorded=price_recorded
    )
