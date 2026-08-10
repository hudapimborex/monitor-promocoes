"""Monta as strings de busca a partir dos termos configurados de uma categoria.

Prioriza combinações mais genéricas primeiro (termo base + desconto) e deixa
as mais específicas (+ tamanho) por último, para que, quando a cota diária
for pequena, as queries mais úteis/baratas rodem primeiro.
"""

from __future__ import annotations

from typing import Optional

from app.db.models import Category


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

    # 2) termo base + tamanho + desconto — mais específico, roda depois.
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
