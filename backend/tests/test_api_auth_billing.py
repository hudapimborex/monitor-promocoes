import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import Plan, User
from app.db.session import get_db
from main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_user_and_plans(db_session):
    free = Plan(name="free", price_cents=0, is_default=True)
    pro = Plan(name="pro", price_cents=2990, is_default=False)
    db_session.add_all([free, pro])
    db_session.commit()

    user = User(email="api@example.com", hashed_password=hash_password("segredo123"), plan_id=free.id)
    db_session.add(user)
    db_session.commit()
    return user, free, pro


def test_login_success_returns_token(client, db_session):
    _seed_user_and_plans(db_session)
    resp = client.post("/auth/login", json={"email": "api@example.com", "password": "segredo123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password_returns_401(client, db_session):
    _seed_user_and_plans(db_session)
    resp = client.post("/auth/login", json={"email": "api@example.com", "password": "errada"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client, db_session):
    resp = client.post("/auth/login", json={"email": "nao-existe@example.com", "password": "x"})
    assert resp.status_code == 401


def test_me_requires_token(client, db_session):
    _seed_user_and_plans(db_session)
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_user_with_valid_token(client, db_session):
    _seed_user_and_plans(db_session)
    login = client.post("/auth/login", json={"email": "api@example.com", "password": "segredo123"})
    token = login.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "api@example.com"
    assert body["plan"] == "free"


def test_list_plans_is_public(client, db_session):
    _seed_user_and_plans(db_session)
    resp = client.get("/plans")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert names == {"free", "pro"}


def test_subscribe_requires_auth(client, db_session):
    _seed_user_and_plans(db_session)
    resp = client.post("/subscribe", json={"plan_name": "free"})
    assert resp.status_code == 401


def test_subscribe_free_plan_activates_immediately(client, db_session):
    user, free, _ = _seed_user_and_plans(db_session)
    login = client.post("/auth/login", json={"email": "api@example.com", "password": "segredo123"})
    token = login.json()["access_token"]

    resp = client.post(
        "/subscribe", json={"plan_name": "free"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_subscribe_paid_plan_returns_pending_not_charged(client, db_session):
    _seed_user_and_plans(db_session)
    login = client.post("/auth/login", json={"email": "api@example.com", "password": "segredo123"})
    token = login.json()["access_token"]

    resp = client.post(
        "/subscribe", json={"plan_name": "pro"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert "não implementada" in body["message"]


def test_subscribe_unknown_plan_returns_404(client, db_session):
    _seed_user_and_plans(db_session)
    login = client.post("/auth/login", json={"email": "api@example.com", "password": "segredo123"})
    token = login.json()["access_token"]

    resp = client.post(
        "/subscribe", json={"plan_name": "nao-existe"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404
