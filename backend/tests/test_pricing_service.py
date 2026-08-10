import datetime as dt

from app.db.models import Category, PriceAlert, PriceHistory, Product, User
from app.pricing.service import check_product_for_drop


def _make_product_with_history(db_session, prices_and_days_ago):
    user = User(email="u2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(user_id=user.id, slug="piso_laminado", name="Piso Laminado")
    db_session.add(category)
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Piso Laminado 7mm",
        store_domain="loja.com.br",
        url="https://loja.com.br/piso",
        url_hash="hash-piso-1",
        first_seen_at=dt.datetime(2026, 8, 1),
        last_seen_at=dt.datetime(2026, 8, 1),
    )
    db_session.add(product)
    db_session.commit()

    now = dt.datetime(2026, 8, 10, 12, 0, 0)
    for price, days_ago in prices_and_days_ago:
        db_session.add(
            PriceHistory(
                product_id=product.id,
                price=price,
                captured_at=now - dt.timedelta(days=days_ago),
            )
        )
    db_session.commit()
    return product


def test_check_product_for_drop_creates_alert_on_real_drop(db_session):
    product = _make_product_with_history(
        db_session, [(100, 20), (100, 15), (70, 0)]
    )

    alert = check_product_for_drop(db_session, product)

    assert alert is not None
    assert alert.new_price == 70
    assert alert.old_price == 100
    assert alert.drop_pct == 30.0

    stored = db_session.query(PriceAlert).filter_by(product_id=product.id).all()
    assert len(stored) == 1


def test_check_product_for_drop_is_idempotent_for_same_observation(db_session):
    product = _make_product_with_history(
        db_session, [(100, 20), (100, 15), (70, 0)]
    )

    first = check_product_for_drop(db_session, product)
    second = check_product_for_drop(db_session, product)

    assert first is not None
    assert second is None  # já existe alerta pra essa observação exata

    stored = db_session.query(PriceAlert).filter_by(product_id=product.id).all()
    assert len(stored) == 1


def test_check_product_for_drop_returns_none_when_no_real_drop(db_session):
    product = _make_product_with_history(db_session, [(100, 10), (100, 0)])

    alert = check_product_for_drop(db_session, product)

    assert alert is None
    assert db_session.query(PriceAlert).filter_by(product_id=product.id).count() == 0
