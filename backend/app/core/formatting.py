import re
import unicodedata
from typing import Optional


def slugify(text: str) -> str:
    """Vira um slug ASCII simples (usado como identificador único de
    categoria/item de busca). "Trinco de Porta!" -> "trinco-de-porta"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def format_brl(value: float) -> str:
    """Formata um float como moeda brasileira (R$ 1.234,56) sem depender de locale."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mask_secret(value: Optional[str]) -> str:
    """Usado na página de Configurações pra mostrar que um segredo já está
    salvo sem reexpor o valor inteiro."""
    if not value:
        return "não configurado"
    if len(value) <= 4:
        return "••••"
    return f"•••• (termina em {value[-4:]})"
