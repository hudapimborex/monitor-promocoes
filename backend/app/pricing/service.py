"""Roda a detecção de queda real (app/pricing/detector.py) sobre o histórico
gravado no banco e cria PriceAlert quando confirmado.

Chamado pelo job do scheduler logo depois de uma nova linha ser gravada em
PriceHistory (app/scraping/ingest.py) — não deve ser chamado "à toa" sem uma
observação nova, para não reavaliar sempre o mesmo último preço.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import PriceAlert, PriceHistory, Product
from app.pricing.detector import PricePoint, evaluate_drop


def check_product_for_drop(db: Session, product: Product) -> Optional[PriceAlert]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.product_id == product.id)
        .order_by(PriceHistory.captured_at.asc())
        .all()
    )
    if len(rows) < 2:
        return None  # precisa de pelo menos uma observação anterior + a atual

    latest = rows[-1]

    # Idempotência: se já existe um alerta para esta observação exata, não
    # recria (evita duplicar caso o job rode de novo sobre o mesmo dado).
    already_alerted = (
        db.query(PriceAlert)
        .filter(
            PriceAlert.product_id == product.id,
            PriceAlert.source_price_history_id == latest.id,
        )
        .first()
    )
    if already_alerted:
        return None

    history = [PricePoint(price=r.price, captured_at=r.captured_at) for r in rows[:-1]]

    last_alert = (
        db.query(PriceAlert)
        .filter(PriceAlert.product_id == product.id)
        .order_by(PriceAlert.created_at.desc())
        .first()
    )
    last_alert_price = last_alert.new_price if last_alert else None

    evaluation = evaluate_drop(
        history=history,
        new_price=latest.price,
        new_captured_at=latest.captured_at,
        last_alert_price=last_alert_price,
    )
    if not evaluation.is_real_drop:
        return None

    alert = PriceAlert(
        product_id=product.id,
        user_id=product.user_id,
        old_price=evaluation.baseline_price,
        new_price=latest.price,
        drop_pct=evaluation.drop_pct,
        source_price_history_id=latest.id,
        channel=None,  # preenchido pelo notificador (app/notifications) ao enviar
    )
    db.add(alert)
    try:
        db.commit()
    except IntegrityError:
        # corrida rara (ex: dois workers processando o mesmo produto): outro
        # processo já criou o alerta pra essa mesma observação.
        db.rollback()
        return None
    db.refresh(alert)
    return alert
