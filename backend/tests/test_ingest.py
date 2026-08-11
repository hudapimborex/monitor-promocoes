import datetime as dt

from app.db.models import Category, Coupon, PriceHistory, SearchRun, User
from app.scraping.firecrawl_client import SearchResult
from app.scraping.ingest import ingest_result, normalize_url, url_hash


def _setup_user_category_run(db_session):
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(user_id=user.id, slug="porcelanato", name="Porcelanato")
    db_session.add(category)
    db_session.commit()

    run = SearchRun(
        user_id=user.id,
        category_id=category.id,
        query="porcelanato promoção",
        ran_at=dt.datetime(2026, 8, 10, 12, 0, 0),
    )
    db_session.add(run)
    db_session.commit()
    return user, category, run


def test_normalize_url_strips_tracking_params_and_trailing_slash():
    a = normalize_url("https://Loja.com.br/produto/123/?utm_source=fb&cor=branco")
    b = normalize_url("https://loja.com.br/produto/123?cor=branco")
    assert a == b


def test_ingest_creates_product_and_price_history(db_session):
    user, category, run = _setup_user_category_run(db_session)
    result = SearchResult(
        url="https://loja-exemplo.com.br/porcelanato-80x80",
        title="Porcelanato 80x80 promoção",
        markdown="Preço: R$ 89,90/m²",
        image_url="https://loja-exemplo.com.br/img.jpg",
    )

    outcome = ingest_result(db_session, user, category, run, result)

    assert outcome.is_new_product is True
    assert outcome.price_recorded is True
    assert outcome.price == 89.90
    assert outcome.product.store_domain == "loja-exemplo.com.br"

    history = db_session.query(PriceHistory).filter_by(product_id=outcome.product.id).all()
    assert len(history) == 1
    assert history[0].price == 89.90
    assert history[0].source_search_run_id == run.id


def test_ingest_dedupes_same_product_across_runs(db_session):
    user, category, run1 = _setup_user_category_run(db_session)
    result = SearchResult(
        url="https://loja-exemplo.com.br/porcelanato-80x80?utm_source=google",
        title="Porcelanato 80x80",
        markdown="R$ 89,90",
    )
    outcome1 = ingest_result(db_session, user, category, run1, result)

    run2 = SearchRun(
        user_id=user.id,
        category_id=category.id,
        query="porcelanato oferta",
        ran_at=dt.datetime(2026, 8, 11, 12, 0, 0),
    )
    db_session.add(run2)
    db_session.commit()

    result2 = SearchResult(
        url="https://loja-exemplo.com.br/porcelanato-80x80",  # mesma URL, sem utm
        title="Porcelanato 80x80",
        markdown="R$ 74,90",
    )
    outcome2 = ingest_result(db_session, user, category, run2, result2)

    assert outcome2.is_new_product is False
    assert outcome1.product.id == outcome2.product.id

    history = (
        db_session.query(PriceHistory)
        .filter_by(product_id=outcome1.product.id)
        .order_by(PriceHistory.captured_at)
        .all()
    )
    assert [h.price for h in history] == [89.90, 74.90]


def test_ingest_skips_when_no_price_found(db_session):
    user, category, run = _setup_user_category_run(db_session)
    result = SearchResult(url="https://loja-exemplo.com.br/sem-preco", markdown="sem preço aqui")

    outcome = ingest_result(db_session, user, category, run, result)

    assert outcome.price_recorded is False
    assert outcome.price is None


def test_ingest_records_coupon_found_in_markdown(db_session):
    user, category, run = _setup_user_category_run(db_session)
    result = SearchResult(
        url="https://loja-exemplo.com.br/porcelanato-80x80",
        title="Porcelanato 80x80",
        markdown="Preço: R$ 89,90/m². Use o cupom PROMO10 e ganhe 10% off!",
    )

    outcome = ingest_result(db_session, user, category, run, result)

    assert outcome.coupon_code == "PROMO10"
    coupons = db_session.query(Coupon).filter_by(product_id=outcome.product.id).all()
    assert len(coupons) == 1
    assert coupons[0].code == "PROMO10"
    assert coupons[0].store_domain == "loja-exemplo.com.br"


def test_ingest_does_not_duplicate_same_coupon_seen_again(db_session):
    user, category, run1 = _setup_user_category_run(db_session)
    result = SearchResult(
        url="https://loja-exemplo.com.br/produto",
        markdown="R$ 50,00 — cupom PROMO10",
    )
    ingest_result(db_session, user, category, run1, result)

    run2 = SearchRun(
        user_id=user.id,
        category_id=category.id,
        query="porcelanato oferta",
        ran_at=dt.datetime(2026, 8, 11, 12, 0, 0),
    )
    db_session.add(run2)
    db_session.commit()

    outcome2 = ingest_result(db_session, user, category, run2, result)

    assert outcome2.coupon_code == "PROMO10"  # ainda reporta, mas não duplica no banco
    coupons = db_session.query(Coupon).filter_by(product_id=outcome2.product.id).all()
    assert len(coupons) == 1


def test_ingest_returns_none_coupon_when_none_found(db_session):
    user, category, run = _setup_user_category_run(db_session)
    result = SearchResult(url="https://loja-exemplo.com.br/produto", markdown="R$ 50,00")

    outcome = ingest_result(db_session, user, category, run, result)

    assert outcome.coupon_code is None
    assert db_session.query(Coupon).count() == 0
