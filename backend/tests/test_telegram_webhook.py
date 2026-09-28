import pytest
from fastapi.testclient import TestClient

from app.db.models import Category, NotificationSettings, User
from app.db.session import get_db
from app.notifications.telegram import TelegramNotifier
from app.web.telegram_webhook import webhook_secret
from main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def fake_telegram_send(monkeypatch):
    """Mocka só o envio de mensagem do bot (não o httpx.Client inteiro — ele
    é usado pelo próprio TestClient por baixo dos panos, então mockar a
    classe toda quebraria as chamadas do teste pra dentro da app)."""
    sent = []

    def fake_send(self, text, chat_id=None):
        sent.append({"text": text, "chat_id": chat_id or self.default_chat_id})
        return True

    monkeypatch.setattr(TelegramNotifier, "send_message", fake_send)
    return sent


def _seed_user_with_chat_id(db_session, chat_id="999888777", email="webhook@example.com"):
    user = User(email=email, hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id=chat_id))
    db_session.commit()
    return user


def _telegram_update(chat_id: str, text: str) -> dict:
    return {"message": {"chat": {"id": int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id}, "text": text}}


def test_wrong_secret_returns_404(client, db_session):
    resp = client.post("/telegram/webhook/algum-segredo-errado", json={})
    assert resp.status_code == 404


def test_authorized_chat_creates_item_and_confirms(client, db_session, fake_telegram_send):
    user = _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "Fogão")
    )
    assert resp.status_code == 200

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category is not None
    assert category.name == "Fogão"
    assert category.keywords_json["base_terms"] == ["Fogão"]

    assert len(fake_telegram_send) == 1
    assert fake_telegram_send[0]["chat_id"] == "999888777"
    assert "Fogão" in fake_telegram_send[0]["text"]


def test_unauthorized_chat_id_does_not_create_item(client, db_session, fake_telegram_send):
    _seed_user_with_chat_id(db_session, chat_id="111")

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("222222222", "Item suspeito")
    )
    assert resp.status_code == 200
    assert db_session.query(Category).count() == 0
    assert fake_telegram_send == []


def test_command_text_is_ignored(client, db_session, fake_telegram_send):
    _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "/start")
    )
    assert resp.status_code == 200
    assert db_session.query(Category).count() == 0
    assert fake_telegram_send == []


def test_empty_text_is_ignored(client, db_session):
    _seed_user_with_chat_id(db_session)
    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}",
        json={"message": {"chat": {"id": 999888777}, "text": ""}},
    )
    assert resp.status_code == 200
    assert db_session.query(Category).count() == 0


def test_second_chat_id_in_comma_separated_list_is_also_authorized(client, db_session, fake_telegram_send):
    user = _seed_user_with_chat_id(db_session, chat_id="111111111, 222222222")

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("222222222", "Cooktop")
    )
    assert resp.status_code == 200

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category is not None
    assert category.name == "Cooktop"
    assert fake_telegram_send[0]["chat_id"] == "222222222"


def test_malformed_payload_does_not_crash(client, db_session):
    resp = client.post(f"/telegram/webhook/{webhook_secret()}", json={"unexpected": "shape"})
    assert resp.status_code == 200
