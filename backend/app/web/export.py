"""Export CSV do histórico de preços e dos alertas.

Pedido explícito do MVP: "painel local ou export para planilha" — os dois
convivem, o CSV é só outra forma de olhar os mesmos dados do painel.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy.orm import Session

from app.db.models import PriceAlert, PriceHistory, Product


def export_history_csv(db: Session, user_id: int) -> str:
    rows = (
        db.query(PriceHistory, Product)
        .join(Product, PriceHistory.product_id == Product.id)
        .filter(Product.user_id == user_id)
        .order_by(Product.name, PriceHistory.captured_at)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["produto", "loja", "preco", "moeda", "capturado_em", "url"])
    for history, product in rows:
        writer.writerow(
            [
                product.name,
                product.store_domain,
                f"{history.price:.2f}",
                history.currency,
                history.captured_at.isoformat(),
                product.url,
            ]
        )
    return buffer.getvalue()


def export_alerts_csv(db: Session, user_id: int) -> str:
    alerts = (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user_id)
        .order_by(PriceAlert.created_at.desc())
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "produto",
            "loja",
            "preco_anterior",
            "preco_novo",
            "queda_pct",
            "detectado_em",
            "notificado_em",
            "canal",
            "url",
        ]
    )
    for alert in alerts:
        product = alert.product
        writer.writerow(
            [
                product.name,
                product.store_domain,
                f"{alert.old_price:.2f}",
                f"{alert.new_price:.2f}",
                f"{alert.drop_pct:.1f}",
                alert.created_at.isoformat(),
                alert.notified_at.isoformat() if alert.notified_at else "",
                alert.channel or "",
                product.url,
            ]
        )
    return buffer.getvalue()
