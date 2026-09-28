import pytest
from fastapi.testclient import TestClient

from app.core.formatting import slugify
from app.core.security import hash_password
from app.db.models import Category, Coupon, PriceAlert, PriceHistory, Product, SearchRun, User
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


def test_toggle_nonexistent_item_redirects_with_friendly_error(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.post("/items/99999/toggle")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/items?error=item_nao_encontrado"


def test_delete_nonexistent_item_is_idempotent_not_an_error(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.post("/items/99999/delete")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/items?deleted=1"


def test_delete_already_deleted_item_on_second_click_still_redirects_cleanly(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="dobro-clique", name="Item", active=True)
    db_session.add(category)
    db_session.commit()
    category_id = category.id

    first = client.post(f"/items/{category_id}/delete")
    assert first.headers["location"] == "/items?deleted=1"

    second = client.post(f"/items/{category_id}/delete")
    assert second.status_code == 303
    assert second.headers["location"] == "/items?deleted=1"


def test_toggle_or_delete_item_belonging_to_another_user_is_treated_as_not_found(client, db_session):
    _seed_and_login(client, db_session)

    other_user = User(email="other@example.com", hashed_password=hash_password("outro123"))
    db_session.add(other_user)
    db_session.commit()
    other_category = Category(user_id=other_user.id, slug="nao-meu", name="Não Meu", active=True)
    db_session.add(other_category)
    db_session.commit()

    toggle_resp = client.post(f"/items/{other_category.id}/toggle")
    assert toggle_resp.headers["location"] == "/items?error=item_nao_encontrado"

    delete_resp = client.post(f"/items/{other_category.id}/delete")
    assert delete_resp.headers["location"] == "/items?deleted=1"
    # o item do outro usuário continua intacto, não foi apagado de verdade
    assert db_session.query(Category).filter_by(id=other_category.id).first() is not None


def test_delete_item_without_history_removes_it(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="fechadura", name="Fechadura", active=True)
    db_session.add(category)
    db_session.commit()
    category_id = category.id

    resp = client.post(f"/items/{category_id}/delete")
    assert resp.headers["location"] == "/items?deleted=1"
    assert db_session.query(Category).filter_by(id=category_id).first() is None


def test_delete_item_with_only_search_run_history_cascades(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="dobradica", name="Dobradiça", active=True)
    db_session.add(category)
    db_session.commit()

    db_session.add(SearchRun(user_id=user.id, category_id=category.id, query="dobradiça promoção"))
    db_session.commit()
    category_id = category.id

    resp = client.post(f"/items/{category_id}/delete")
    assert resp.headers["location"] == "/items?deleted=1"

    assert db_session.query(Category).filter_by(id=category_id).first() is None
    assert db_session.query(SearchRun).filter_by(category_id=category_id).count() == 0


def test_delete_item_cascades_products_prices_alerts_and_coupons(client, db_session):
    user = _seed_and_login(client, db_session)
    category = Category(user_id=user.id, slug="usado", name="Usado", active=True)
    db_session.add(category)
    db_session.commit()

    run = SearchRun(user_id=user.id, category_id=category.id, query="usado promoção")
    db_session.add(run)
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Produto",
        store_domain="loja.com",
        url="https://loja.com/x",
        url_hash="hash-items-1",
    )
    db_session.add(product)
    db_session.commit()

    history = PriceHistory(product_id=product.id, price=10.0, source_search_run_id=run.id)
    db_session.add(history)
    db_session.commit()

    alert = PriceAlert(
        product_id=product.id,
        user_id=user.id,
        old_price=20.0,
        new_price=10.0,
        drop_pct=50.0,
        source_price_history_id=history.id,
    )
    coupon = Coupon(
        user_id=user.id,
        product_id=product.id,
        code="TESTE10",
        source_url="https://loja.com/x",
    )
    db_session.add_all([alert, coupon])
    db_session.commit()

    category_id, product_id = category.id, product.id

    resp = client.post(f"/items/{category_id}/delete")
    assert resp.headers["location"] == "/items?deleted=1"

    assert db_session.query(Category).filter_by(id=category_id).first() is None
    assert db_session.query(Product).filter_by(id=product_id).first() is None
    assert db_session.query(PriceHistory).filter_by(product_id=product_id).count() == 0
    assert db_session.query(PriceAlert).filter_by(product_id=product_id).count() == 0
    assert db_session.query(Coupon).filter_by(product_id=product_id).count() == 0
    assert db_session.query(SearchRun).filter_by(category_id=category_id).count() == 0


def test_list_items_always_renders_delete_form(client, db_session):
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
    assert resp.text.count(f"/items/{fresh.id}/delete") == 1
    assert resp.text.count(f"/items/{with_history.id}/delete") == 1


def test_delete_all_items_removes_everything_for_the_user(client, db_session):
    user = _seed_and_login(client, db_session)
    other = User(email="outro@example.com", hashed_password=hash_password("x"))
    db_session.add(other)
    db_session.commit()

    cat_a = Category(user_id=user.id, slug="fogao", name="Fogão", active=True)
    cat_b = Category(user_id=user.id, slug="cooktop", name="Cooktop", active=True)
    other_cat = Category(user_id=other.id, slug="alheio", name="Alheio", active=True)
    db_session.add_all([cat_a, cat_b, other_cat])
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=cat_a.id,
        name="Produto",
        store_domain="loja.com",
        url="https://loja.com/y",
        url_hash="hash-items-delete-all",
    )
    db_session.add(product)
    db_session.commit()
    db_session.add(PriceHistory(product_id=product.id, price=10.0))
    db_session.commit()

    other_cat_id = other_cat.id

    resp = client.post("/items/delete-all")
    assert resp.headers["location"] == "/items?deleted=all"

    assert db_session.query(Category).filter_by(user_id=user.id).count() == 0
    assert db_session.query(Product).filter_by(user_id=user.id).count() == 0
    assert db_session.query(PriceHistory).count() == 0
    # não mexe nos itens de outro usuário
    assert db_session.query(Category).filter_by(id=other_cat_id).first() is not None


def test_delete_all_items_with_no_items_is_a_no_op(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.post("/items/delete-all")
    assert resp.headers["location"] == "/items?deleted=all"
