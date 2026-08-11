"""Monta as strings de busca a partir dos termos configurados de uma categoria.

Prioriza combinações mais genéricas primeiro (termo base + desconto), depois
os marketplaces/lojas prioritários (busca ampla nem sempre ranqueia eles bem
pros nossos termos, então forçamos com `site:`), depois sites agregadores de
cupom, e deixa as mais específicas (+ tamanho) por último — assim, quando a
cota diária for pequena, as queries mais úteis rodam primeiro e as mais
caras/opcionais são as primeiras a ficar de fora.
"""

from __future__ import annotations

from typing import Optional

from app.core.config import get_settings
from app.db.models import Category


def _split_domains(raw: str) -> list[str]:
    return [d.strip() for d in raw.split(",") if d.strip()]


def _marketplace_domains() -> list[str]:
    return _split_domains(get_settings().marketplace_priority_domains)


def _coupon_site_domains() -> list[str]:
    return _split_domains(get_settings().coupon_site_domains)


def build_queries(category: Category, max_queries: Optional[int] = None) -> list[str]:
    kw = category.keywords_json or {}
    base_terms = kw.get("base_terms") or [category.name]
    discount_terms = kw.get("discount_terms") or ["promoção"]
    sizes = kw.get("sizes") or []

    queries: list[str] = []

    # 1) termo base + desconto — combinação mais genérica.
    for base in base_terms:
        for discount in discount_terms:
            queries.append(f"{base} {discount}")

    # 2) marketplaces/lojas prioritários — busca dedicada com `site:` em
    #    todo item, pra garantir cobertura deles em vez de depender da busca
    #    ampla ranquear eles bem.
    for base in base_terms:
        for domain in _marketplace_domains():
            queries.append(f"site:{domain} {base} promoção")

    # 3) sites agregadores de cupom — mesma ideia, prioridade um degrau
    #    abaixo dos marketplaces (é o primeiro corte quando a cota aperta).
    for base in base_terms:
        for domain in _coupon_site_domains():
            queries.append(f"site:{domain} {base} cupom desconto")

    # 4) termo base + tamanho + desconto — mais específico, roda por último.
    for base in base_terms:
        for size in sizes:
            for discount in discount_terms:
                queries.append(f"{base} {size} {discount}")

    # remove duplicatas mantendo a ordem de prioridade
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    if max_queries is not None:
        unique = unique[:max_queries]
    return unique
