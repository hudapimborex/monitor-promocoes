from typing import Optional


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
