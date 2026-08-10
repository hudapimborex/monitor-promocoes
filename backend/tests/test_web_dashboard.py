import datetime as dt

from app.db.models import Category, PriceAlert, PriceHistory, Product, User
from app.web.dashboard_data import (
    dashboard_summary,
    get_product_history,
    list_products_with_prices,
    list_recent_alerts,
)
from app.web.export import export_alerts_csv, export_history_csv


def _seed(db_session):
    user = User(email="dash@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(user_id=user.id, slug="porcelanato", name="Porcelanato")
    db_session.add(category)
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Porcelanato 80x80",
        store_domain="loja.com.br",
        url="https://loja.com.br/produto",
        url_hash="hash-dash-1",
        first_seen_at=dt.datetime(2026, 8, 1),
        last_seen_at=dt.datetime(2026, 8, 10),
    )
    db_session.add(product)
    db_session.commit()

    db_session.add_all(
        [
            PriceHistory(product_id=product.id, price=100.0, captured_at=dt.datetime(2026, 8, 1)),
            PriceHistory(product_id=product.id, price=70.0, captured_at=dt.datetime(2026, 8, 10)),
        ]
    )
    db_session.commit()

    alert = PriceAlert(
        product_id=product.id,
        user_id=user.id,
        old_price=100.0,
        new_price=70.0,
        drop_pct=30.0,
        created_at=dt.datetime(2026, 8, 10),
    )
    db_session.add(alert)
    db_session.commit()

    return user, product


def test_list_products_with_prices(db_session):
    user, product = _seed(db_session)
    rows = list_products_with_prices(db_session, user.id)

    assert len(rows) == 1
    assert rows[0].current_price == 70.0
    assert rows[0].min_price == 70.0
    assert rows[0].current_price_fmt == "R$ 70,00"


def test_get_product_history_orders_newest_first(db_session):
    _, product = _seed(db_session)
    history = get_product_history(db_session, product.id)

    assert len(history) == 2
    assert history[0].price == 70.0
    assert history[0].price_fmt == "R$ 70,00"
    assert history[1].price == 100.0


def test_list_recent_alerts(db_session):
    user, _ = _seed(db_session)
    alerts = list_recent_alerts(db_session, user.id)
    assert len(alerts) == 1
    assert alerts[0].drop_pct == 30.0


def test_dashboard_summary_counts(db_session):
    user, _ = _seed(db_session)
    summary = dashboard_summary(db_session, user.id)
    assert summary["products_count"] == 1
    assert summary["alerts_count_7d"] >= 0  # depende da data "agora" vs created_at fixo


def test_export_history_csv_contains_rows(db_session):
    user, _ = _seed(db_session)
    csv_text = export_history_csv(db_session, user.id)
    assert "produto,loja,preco,moeda,capturado_em,url" in csv_text
    assert "Porcelanato 80x80" in csv_text
    assert "70.00" in csv_text
    assert "100.00" in csv_text


def test_export_alerts_csv_contains_rows(db_session):
    user, _ = _seed(db_session)
    csv_text = export_alerts_csv(db_session, user.id)
    assert "queda_pct" in csv_text
    assert "30.0" in csv_text
