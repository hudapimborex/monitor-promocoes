"""Extrai código de cupom de desconto do texto (markdown) raspado.

Roda em cima do mesmo conteúdo que já é raspado pra achar preço — não
consome crédito extra da Firecrawl. Heurística aproximada (igual o
price_parser): procura padrões comuns em português/inglês tipo "cupom
XPTO10", "use o código XPTO10", "CUPOM: XPTO10". Cada loja anuncia cupom de
um jeito diferente, então nem sempre vai achar mesmo quando existe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# "cupom", "código"/"code", "coupon" seguido (opcionalmente) de : ou - e um
# código alfanumérico de 3 a 15 caracteres.
_COUPON_RE = re.compile(
    r"(?:cupom|c[oó]digo|coupon|code)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{2,14})",
    re.IGNORECASE,
)

# Palavras genéricas que às vezes casam com o regex mas não são código de
# cupom de verdade (ex: "use o código abaixo" -> "ABAIXO" não é cupom).
_BLOCKLIST = {
    "AQUI",
    "PROMO",
    "PROMOCIONAL",
    "DESCONTO",
    "AGORA",
    "HOJE",
    "VALIDO",
    "VÁLIDO",
    "ABAIXO",
    "ACIMA",
    "PROMOCAO",
    "PROMOÇÃO",
    "POSTAL",
}


@dataclass
class CouponMatch:
    code: str
    context: str


def extract_coupon(text: str) -> Optional[CouponMatch]:
    if not text:
        return None
    for match in _COUPON_RE.finditer(text):
        code = match.group(1).upper()
        if code in _BLOCKLIST:
            continue
        if not re.search(r"\d", code):
            # cupons de verdade quase sempre têm número — sem isso, é bem
            # mais provável ser uma palavra comum casando por acaso.
            continue
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 40)
        return CouponMatch(code=code, context=text[start:end].strip())
    return None
