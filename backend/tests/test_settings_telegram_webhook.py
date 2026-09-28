import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import User, UserCredentials
from app.db.session import get_db
from main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_and_login(client, db_session, password="segredo123"):
    user = User(email="webhookbtn@example.com", hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"email": "webhookbtn@example.com", "password": password})
    return user


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_register_webhook_without_token_configured_redirects_with_error(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.post("/settings/telegram-webhook")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?error=telegram_nao_configurado"


def test_register_webhook_calls_telegram_with_saved_token_and_derived_secret(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="123:ABC", telegram_chat_id="999"))
    db_session.commit()

    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse({"ok": True, "result": True})

    monkeypatch.setattr("app.web.settings_routes.httpx.post", fake_post)

    resp = client.post("/settings/telegram-webhook")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?saved=webhook"

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/bot123:ABC/setWebhook"
    assert calls[0]["json"]["url"].startswith("https://")
    assert "/telegram/webhook/" in calls[0]["json"]["url"]


def test_register_webhook_telegram_rejection_redirects_with_error(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="token-invalido", telegram_chat_id="999"))
    db_session.commit()

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse({"ok": False, "description": "Unauthorized"})

    monkeypatch.setattr("app.web.settings_routes.httpx.post", fake_post)

    resp = client.post("/settings/telegram-webhook")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?error=telegram_webhook_falhou"
