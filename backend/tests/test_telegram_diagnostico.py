import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import NotificationSettings, User, UserCredentials
from app.db.session import get_db
from main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_and_login(client, db_session, password="segredo123"):
    user = User(email="diag@example.com", hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    client.post("/login", data={"email": "diag@example.com", "password": password})
    return user


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_diagnostico_without_token_flags_missing_token(client, db_session):
    _seed_and_login(client, db_session)
    resp = client.get("/settings/telegram-diagnostico")
    assert resp.status_code == 200
    assert "Nenhum Telegram Bot Token salvo" in resp.text


def test_diagnostico_no_webhook_registered(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="123:ABC", telegram_chat_id="999"))
    db_session.commit()

    def fake_get(url, timeout=None):
        return _FakeResponse({"ok": True, "result": {"url": "", "pending_update_count": 0}})

    monkeypatch.setattr("app.web.settings_routes.httpx.get", fake_get)

    resp = client.get("/settings/telegram-diagnostico")
    assert resp.status_code == 200
    assert "Nenhum webhook registrado" in resp.text


def test_diagnostico_reports_last_error_from_telegram(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="123:ABC", telegram_chat_id="999"))
    db_session.commit()

    def fake_get(url, timeout=None):
        return _FakeResponse(
            {
                "ok": True,
                "result": {
                    "url": "https://promo-monitor-web.onrender.com/telegram/webhook/algumsegredo",
                    "pending_update_count": 3,
                    "last_error_message": "Wrong response from the webhook: 500 Internal Server Error",
                },
            }
        )

    monkeypatch.setattr("app.web.settings_routes.httpx.get", fake_get)

    resp = client.get("/settings/telegram-diagnostico")
    assert resp.status_code == 200
    assert "500 Internal Server Error" in resp.text
    assert "3 mensagem" in resp.text


def test_diagnostico_flags_missing_authorized_chat_id(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="123:ABC"))
    db_session.commit()

    def fake_get(url, timeout=None):
        return _FakeResponse({"ok": True, "result": {"url": "", "pending_update_count": 0}})

    monkeypatch.setattr("app.web.settings_routes.httpx.get", fake_get)

    resp = client.get("/settings/telegram-diagnostico")
    assert resp.status_code == 200
    assert "Nenhum chat_id autorizado salvo" in resp.text


def test_diagnostico_lists_authorized_chat_ids_from_both_tables(client, db_session, monkeypatch):
    user = _seed_and_login(client, db_session)
    db_session.add(UserCredentials(user_id=user.id, telegram_bot_token="123:ABC", telegram_chat_id="111"))
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="222"))
    db_session.commit()

    def fake_get(url, timeout=None):
        return _FakeResponse({"ok": True, "result": {"url": "", "pending_update_count": 0}})

    monkeypatch.setattr("app.web.settings_routes.httpx.get", fake_get)

    resp = client.get("/settings/telegram-diagnostico")
    assert resp.status_code == 200
    assert "111" in resp.text
    assert "222" in resp.text
