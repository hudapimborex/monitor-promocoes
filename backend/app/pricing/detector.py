"""Decide se uma nova observação de preço é uma "queda real" que merece alerta.

Função pura (sem I/O), fácil de testar com séries sintéticas — a integração
com o banco fica em app/pricing/service.py.

Regras (configuráveis via .env, ver app/core/config.py):
- `baseline` = mediana dos preços dos últimos `price_baseline_window_days`
  dias, excluindo a observação mais recente.
- só é queda real se o preço novo estiver pelo menos
  `price_drop_threshold_pct`% abaixo dessa baseline.
- exige que o preço que formou a baseline tenha ficado estável por pelo
  menos `price_min_stable_days` dias — evita disparar em produtos que
  "sempre estão em promoção" ou com preço mudando por outro motivo (ex: uma
  única leitura isolada não é suficiente pra confirmar um patamar estável).
- não renotifica no mesmo patamar: só é queda real de novo se o preço atual
  for menor que o preço do último alerta já disparado para o produto.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from app.core.config import get_settings


@dataclass
class PricePoint:
    price: float
    captured_at: dt.datetime


@dataclass
class DropEvaluation:
    is_real_drop: bool
    baseline_price: Optional[float] = None
    drop_pct: Optional[float] = None
    reason: str = ""


def _baseline_price(
    history: Sequence[PricePoint], as_of: dt.datetime, window_days: int
) -> Optional[float]:
    cutoff = as_of - dt.timedelta(days=window_days)
    window = [p.price for p in history if cutoff <= p.captured_at < as_of]
    if not window:
        return None
    return statistics.median(window)


def _stable_days_before(history: Sequence[PricePoint], as_of: dt.datetime) -> float:
    """Há quantos dias o preço não muda, olhando para trás a partir do ponto
    mais recente do histórico (o que formou a baseline)."""
    prior = sorted((p for p in history if p.captured_at < as_of), key=lambda p: p.captured_at)
    if len(prior) < 2:
        return 0.0

    last_price = prior[-1].price
    stable_since = prior[-1].captured_at
    for point in reversed(prior[:-1]):
        if point.price != last_price:
            break
        stable_since = point.captured_at
    return (prior[-1].captured_at - stable_since).total_seconds() / 86400


def evaluate_drop(
    history: Sequence[PricePoint],
    new_price: float,
    new_captured_at: dt.datetime,
    last_alert_price: Optional[float] = None,
) -> DropEvaluation:
    settings = get_settings()

    baseline = _baseline_price(history, new_captured_at, settings.price_baseline_window_days)
    if baseline is None or baseline <= 0:
        return DropEvaluation(is_real_drop=False, reason="sem histórico suficiente para baseline")

    if new_price >= baseline:
        return DropEvaluation(is_real_drop=False, baseline_price=baseline, reason="preço não caiu")

    drop_pct = round((baseline - new_price) / baseline * 100, 2)
    if drop_pct < settings.price_drop_threshold_pct:
        return DropEvaluation(
            is_real_drop=False,
            baseline_price=baseline,
            drop_pct=drop_pct,
            reason=f"queda de {drop_pct}% abaixo do limiar de {settings.price_drop_threshold_pct}%",
        )

    stable_days = _stable_days_before(history, new_captured_at)
    if stable_days < settings.price_min_stable_days:
        return DropEvaluation(
            is_real_drop=False,
            baseline_price=baseline,
            drop_pct=drop_pct,
            reason=(
                f"preço anterior só ficou estável {stable_days:.1f} dias "
                f"(mínimo {settings.price_min_stable_days})"
            ),
        )

    if last_alert_price is not None and new_price >= last_alert_price:
        return DropEvaluation(
            is_real_drop=False,
            baseline_price=baseline,
            drop_pct=drop_pct,
            reason="já notificado nesse patamar (preço não caiu mais desde o último alerta)",
        )

    return DropEvaluation(
        is_real_drop=True, baseline_price=baseline, drop_pct=drop_pct, reason="queda real confirmada"
    )
