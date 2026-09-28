import datetime as dt

from app.db.models import Category, PriceHistory, Product, SearchRun, User
from app.scraping.item_management import (
    build_items_list_message,
    build_status_message,
    find_category_by_name,
    parse_name_and_priority,
)


def test_parse_name_and_priority_extracts_trailing_number():
    assert parse_name_and_priority("Fogão, 1") == ("Fogão", 1)
    assert parse_name_and_priority("Fogão,3") == ("Fogão", 3)


def test_parse_name_and_priority_without_comma_returns_none():
    assert parse_name_and_priority("Fogão") == ("Fogão", None)


def test_parse_name_and_priority_ignores_non_numeric_suffix():
    assert parse_name_and_priority("Fogão, 5 bocas") == ("Fogão, 5 bocas", None)


def test_parse_name_and_priority_ignores_out_of_range_priority():
    assert parse_name_and_priority("Fogão, 0") == ("Fogão, 0", None)
    assert parse_name_and_priority("Fogão, 100") == ("Fogão, 100", None)


def test_find_category_by_name_prefers_exact_match(db_session):
    user = User(email="itemmgmt@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    exact = Category(user_id=user.id, slug="fogao", name="Fogão", active=True)
    partial = Category(user_id=user.id, slug="fogao-cooktop", name="Fogão Cooktop 5 bocas", active=True)
    db_session.add_all([partial, exact])
    db_session.commit()

    found = find_category_by_name(db_session, user, "fogão")
    assert found.id == exact.id


def test_find_category_by_name_falls_back_to_substring(db_session):
    user = User(email="itemmgmt2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(user_id=user.id, slug="fogao-cooktop", name="Fogão Cooktop 5 bocas", active=True)
    db_session.add(category)
    db_session.commit()

    found = find_category_by_name(db_session, user, "cooktop")
    assert found.id == category.id


def test_find_category_by_name_returns_none_when_no_match(db_session):
    user = User(email="itemmgmt3@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    assert find_category_by_name(db_session, user, "geladeira") is None


def test_build_status_message_with_no_activity_yet(db_session):
    user = User(email="itemmgmt4@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    category = Category(user_id=user.id, slug="fogao", name="Fogão", active=True, priority=2)
    db_session.add(category)
    db_session.commit()

    message = build_status_message(db_session, category)
    assert "Fogão" in message
    assert "0 busca(s)" in message
    assert "0 produto(s)" in message


def test_build_status_message_includes_latest_price_and_run_count(db_session):
    user = User(email="itemmgmt5@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    category = Category(user_id=user.id, slug="fogao", name="Fogão", active=True, priority=1)
    db_session.add(category)
    db_session.commit()

    db_session.add(SearchRun(user_id=user.id, category_id=category.id, query="fogão promoção"))
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Fogão 5 Bocas",
        store_domain="loja.com",
        url="https://loja.com/fogao",
        url_hash="hash-status-unit-1",
    )
    db_session.add(product)
    db_session.commit()
    db_session.add(
        PriceHistory(product_id=product.id, price=899.0, captured_at=dt.datetime(2026, 9, 28, 14, 0))
    )
    db_session.commit()

    message = build_status_message(db_session, category)
    assert "1 busca(s)" in message
    assert "1 produto(s)" in message
    assert "899" in message
    assert "loja.com" in message


def test_build_items_list_message_orders_by_priority_then_name(db_session):
    user = User(email="itemmgmt6@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add_all(
        [
            Category(user_id=user.id, slug="b", name="B Item", active=True, priority=2),
            Category(user_id=user.id, slug="a", name="A Item", active=False, priority=1),
        ]
    )
    db_session.commit()

    message = build_items_list_message(db_session, user)
    lines = message.splitlines()
    assert "A Item" in lines[1]
    assert "⏸" in lines[1]
    assert "B Item" in lines[2]
    assert "✅" in lines[2]


def test_build_items_list_message_when_empty(db_session):
    user = User(email="itemmgmt7@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    message = build_items_list_message(db_session, user)
    assert "Nenhum item" in message
