"""Extrai preço em reais de texto (markdown) raspado pela Firecrawl.

Não existe um jeito 100% confiável de achar "o" preço de uma página de
produto sem parsing especializado por loja — a heurística aqui pega os
valores próximos do símbolo "R$" e ignora os que parecem parcela
("12x de R$ ..."), ficando com o menor valor plausível restante (o preço
"de/por" mais caro tende a aparecer riscado antes do promocional).

Isso é aproximado por natureza. Se notar preços errados vindos de uma loja
específica, o próximo passo natural é um parser dedicado por domínio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# R$ 1.234,56 | R$1234,56 | R$ 89,90 | R$ 89
_PRICE_RE = re.compile(
    r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?|[0-9]+(?:,[0-9]{2})?)"
)

_INSTALLMENT_HINT_RE = re.compile(r"\d+\s*x\b", re.IGNORECASE)


def _to_float(raw: str) -> Optional[float]:
    cleaned = raw.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


@dataclass
class PriceCandidate:
    value: float
    context: str


def extract_price_candidates(text: str) -> list[PriceCandidate]:
    if not text:
        return []
    candidates = []
    for match in _PRICE_RE.finditer(text):
        value = _to_float(match.group(1))
        if value is None or value <= 0:
            continue
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 20)
        candidates.append(PriceCandidate(value=value, context=text[start:end]))
    return candidates


def extract_best_price(text: str) -> Optional[float]:
    candidates = extract_price_candidates(text)
    if not candidates:
        return None

    non_installment = [c for c in candidates if not _INSTALLMENT_HINT_RE.search(c.context)]
    pool = non_installment or candidates
    return min(c.value for c in pool)
