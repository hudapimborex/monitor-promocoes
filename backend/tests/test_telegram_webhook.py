import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.db.models import Category, NotificationSettings, PriceHistory, Product, SearchRun, User
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


@pytest.fixture()
def fake_immediate_check(monkeypatch):
    """Mocka a checagem imediata (BackgroundTask) — ela abre sua própria
    sessão de banco (session_scope), separada da sessão isolada de teste, e
    de fato chamaria a Firecrawl; nos testes do webhook só queremos
    confirmar que ela foi agendada com os IDs certos, não executá-la.
    Como o TestClient roda BackgroundTasks antes de devolver a resposta,
    sem esse mock o teste chamaria código de rede/DB de verdade."""
    calls = []

    def fake_run(user_id, category_id, max_queries=5):
        calls.append({"user_id": user_id, "category_id": category_id})

    monkeypatch.setattr("app.web.telegram_webhook.run_immediate_check", fake_run)
    return calls


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


def test_authorized_chat_creates_item_and_confirms(
    client, db_session, fake_telegram_send, fake_immediate_check
):
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

    # item novo dispara a checagem imediata em background
    assert fake_immediate_check == [{"user_id": user.id, "category_id": category.id}]


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


def test_second_chat_id_in_comma_separated_list_is_also_authorized(
    client, db_session, fake_telegram_send, fake_immediate_check
):
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


def test_adding_item_with_priority_suffix(
    client, db_session, fake_telegram_send, fake_immediate_check
):
    user = _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "Fogão, 1")
    )
    assert resp.status_code == 200

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category is not None
    assert category.name == "Fogão"
    assert category.priority == 1
    assert "prioridade 1" in fake_telegram_send[0]["text"]


def test_adding_item_without_priority_suffix_uses_default(
    client, db_session, fake_telegram_send, fake_immediate_check
):
    user = _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "Fogão")
    )
    assert resp.status_code == 200

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category.priority == 2
    assert "prioridade 2" in fake_telegram_send[0]["text"]


def test_name_with_trailing_non_numeric_comma_is_kept_as_is(
    client, db_session, fake_telegram_send, fake_immediate_check
):
    user = _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}",
        json=_telegram_update("999888777", "Fogão, 5 bocas"),
    )
    assert resp.status_code == 200

    category = db_session.query(Category).filter_by(user_id=user.id).first()
    assert category.name == "Fogão, 5 bocas"
    assert category.priority == 2


def test_status_command_reports_search_activity(client, db_session, fake_telegram_send):
    user = _seed_user_with_chat_id(db_session)
    category = Category(user_id=user.id, slug="fogao", name="Fogão", active=True, priority=1)
    db_session.add(category)
    db_session.commit()

    run = SearchRun(user_id=user.id, category_id=category.id, query="fogão promoção")
    db_session.add(run)
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Fogão 5 Bocas",
        store_domain="loja.com",
        url="https://loja.com/fogao",
        url_hash="hash-status-1",
    )
    db_session.add(product)
    db_session.commit()
    db_session.add(
        PriceHistory(product_id=product.id, price=899.0, captured_at=dt.datetime(2026, 9, 28, 14, 0))
    )
    db_session.commit()

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "status Fogão")
    )
    assert resp.status_code == 200

    assert len(fake_telegram_send) == 1
    text = fake_telegram_send[0]["text"]
    assert "Fogão" in text
    assert "1 busca" in text
    assert "1 produto" in text
    assert "899" in text
    # não deve criar item novo nenhum
    assert db_session.query(Category).filter_by(user_id=user.id).count() == 1


def test_status_command_for_unknown_item_replies_not_found(client, db_session, fake_telegram_send):
    _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "status Geladeira")
    )
    assert resp.status_code == 200
    assert len(fake_telegram_send) == 1
    assert "Geladeira" in fake_telegram_send[0]["text"]
    assert db_session.query(Category).count() == 0


def test_help_keyword_replies_with_instructions_and_creates_nothing(client, db_session, fake_telegram_send):
    _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "ajuda")
    )
    assert resp.status_code == 200
    assert len(fake_telegram_send) == 1
    assert "status" in fake_telegram_send[0]["text"].lower()
    assert db_session.query(Category).count() == 0


def test_itens_keyword_lists_all_items_and_creates_nothing(client, db_session, fake_telegram_send):
    user = _seed_user_with_chat_id(db_session)
    db_session.add_all(
        [
            Category(user_id=user.id, slug="fogao", name="Fogão", active=True, priority=1),
            Category(user_id=user.id, slug="cooktop", name="Cooktop", active=False, priority=2),
        ]
    )
    db_session.commit()

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "itens")
    )
    assert resp.status_code == 200
    assert len(fake_telegram_send) == 1
    text = fake_telegram_send[0]["text"]
    assert "Fogão" in text
    assert "Cooktop" in text
    assert "✅" in text
    assert "⏸" in text
    # não cria item nenhum, só lista
    assert db_session.query(Category).filter_by(user_id=user.id).count() == 2


def test_itens_keyword_with_no_items_says_so(client, db_session, fake_telegram_send):
    _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "itens")
    )
    assert resp.status_code == 200
    assert "Nenhum item" in fake_telegram_send[0]["text"]
    assert db_session.query(Category).count() == 0


def test_buscar_command_triggers_immediate_check_for_existing_item(
    client, db_session, fake_telegram_send, fake_immediate_check
):
    user = _seed_user_with_chat_id(db_session)
    category = Category(user_id=user.id, slug="fogao", name="Fogão", active=True, priority=1)
    db_session.add(category)
    db_session.commit()

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "buscar Fogão")
    )
    assert resp.status_code == 200
    assert "Fogão" in fake_telegram_send[0]["text"]
    assert fake_immediate_check == [{"user_id": user.id, "category_id": category.id}]
    # não cria item novo, só dispara a checagem do que já existe
    assert db_session.query(Category).filter_by(user_id=user.id).count() == 1


def test_buscar_command_for_unknown_item_replies_not_found_and_does_not_check(
    client, db_session, fake_telegram_send, fake_immediate_check
):
    _seed_user_with_chat_id(db_session)

    resp = client.post(
        f"/telegram/webhook/{webhook_secret()}", json=_telegram_update("999888777", "buscar Geladeira")
    )
    assert resp.status_code == 200
    assert "Geladeira" in fake_telegram_send[0]["text"]
    assert fake_immediate_check == []
