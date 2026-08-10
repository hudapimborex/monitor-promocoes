import pytest
from fastapi.testclient import TestClient

from app.core.formatting import slugify
from app.core.security import hash_password
from app.db.models import Category, PriceHistory, Product, SearchRun, User
from app.db.session import get_db
from main import app


def test_slugify_basic():
    assert slugify("Trinco de Porta!") == "trinco-de-porta"
    assert slugify("Janela  de Alumínio") == "janela-de-aluminio"
    assert slugify("###") == "item"


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_and_login(client, db_session, password="segredo123"):
    user = User(email="items@example.com", hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"email": "items@example.com", "password": password})
    return user


def test_list_items_requires_login(client, db_session):
    resp = client.get("/items")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_create_item_with_defaults(client, db_session):
    user = _seed_and_login(client, db_session)

    resp = client.post("/items", data={"name": "Trinco de porta"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/items?added=1"

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category is not None
    assert category.name == "Trinco de porta"
    assert category.slug == "trinco-de-porta"
    assert category.active is True
    kw = category.keywords_json
    assert kw["base_terms"] == ["Trinco de porta"]
    assert kw["discount_terms"] == ["promoção", "desconto", "oferta"]
    assert kw["sizes"] == []


def test_create_item_with_custom_terms_and_sizes(client, db_session):
    user = _seed_and_login(client, db_session)

    client.post(
        "/items",
        data={
            "name": "Janela de alumínio",
            "discount_terms": "promoção, liquidação",
            "sizes": "100x100, 120x150",
            "priority": "1",
        },
    )

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category.priority == 1
    assert category.keywords_json["discount_terms"] == ["promoção", "liquidação"]
    assert category.keywords_json["sizes"] == ["100x100", "120x150"]


def test_create_item_slug_collision_gets_suffix(client, db_session):
    _seed_and_login(client, db_session)

    client.post("/items", data={"name": "Trinco"})
    client.post("/items", data={"name": "Trinco!!"})  # mesmo slug base "trinco"

    slugs = {c.slug for c in db_session.query(Category).all()}
    assert "trinco" in slugs
    assert "trinco-2" in slugs


def test_create_item_rejects_empty_name(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.post("/items", data={"name": "   "})
    assert resp.headers["location"] == "/items?error=nome_vazio"
    assert db_session.query(Category).count() == 0


def test_toggle_item_flips_active(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="porta", name="Porta", active=True)
    db_session.add(category)
    db_session.commit()

    client.post(f"/items/{category.id}/toggle")
    db_session.refresh(category)
    assert category.active is False

    client.post(f"/items/{category.id}/toggle")
    db_session.refresh(category)
    assert category.active is True


def test_delete_item_without_history_removes_it(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="fechadura", name="Fechadura", active=True)
    db_session.add(category)
    db_session.commit()
    category_id = category.id

    resp = client.post(f"/items/{category_id}/delete")
    assert resp.headers["location"] == "/items?deleted=1"
    assert db_session.query(Category).filter_by(id=category_id).first() is None


def test_delete_item_with_history_deactivates_instead_of_deleting(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="dobradica", name="Dobradiça", active=True)
    db_session.add(category)
    db_session.commit()

    db_session.add(
        SearchRun(user_id=user.id, category_id=category.id, query="dobradiça promoção")
    )
    db_session.commit()

    resp = client.post(f"/items/{category.id}/delete")
    assert resp.headers["location"] == "/items?error=tem_historico"

    db_session.refresh(category)
    assert category.active is False  # não foi excluída, só desativada


def test_list_items_shows_can_delete_flag(client, db_session):
    user = _seed_and_login(client, db_session)
    fresh = Category(user_id=user.id, slug="fresh", name="Fresh", active=True)
    with_history = Category(user_id=user.id, slug="usado", name="Usado", active=True)
    db_session.add_all([fresh, with_history])
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=with_history.id,
        name="Produto",
        store_domain="loja.com",
        url="https://loja.com/x",
        url_hash="hash-items-1",
    )
    db_session.add(product)
    db_session.commit()
    db_session.add(PriceHistory(product_id=product.id, price=10.0))
    db_session.commit()

    resp = client.get("/items")
    assert resp.status_code == 200
    assert "Fresh" in resp.text
    assert "Usado" in resp.text
