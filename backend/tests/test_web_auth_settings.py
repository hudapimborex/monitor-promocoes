import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password, verify_password
from app.db.models import User, UserCredentials
from app.db.session import get_db
from main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_user(db_session, password="segredo123"):
    user = User(email="painel@example.com", hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()
    return user


def test_dashboard_redirects_to_login_when_not_authenticated(client, db_session):
    _seed_user(db_session)
    resp = client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_wrong_password_redirects_with_error(client, db_session):
    _seed_user(db_session)
    resp = client.post("/login", data={"email": "painel@example.com", "password": "errada"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?error=1"
    assert "session" not in client.cookies


def test_login_success_sets_cookie_and_allows_dashboard_access(client, db_session):
    _seed_user(db_session)
    resp = client.post(
        "/login", data={"email": "painel@example.com", "password": "segredo123"}
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "session" in client.cookies

    dashboard = client.get("/")
    assert dashboard.status_code == 200


def test_logout_clears_cookie_and_redirects_to_login(client, db_session):
    _seed_user(db_session)
    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})
    assert "session" in client.cookies

    resp = client.get("/logout")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    dashboard = client.get("/")
    assert dashboard.status_code == 303  # sessão foi limpa, volta pro login


def test_settings_requires_login(client, db_session):
    _seed_user(db_session)
    resp = client.get("/settings")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_save_credentials_creates_row_and_masks_on_reload(client, db_session):
    user = _seed_user(db_session)
    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})

    resp = client.post(
        "/settings/credentials",
        data={
            "firecrawl_api_key": "fc-abcdef1234",
            "telegram_bot_token": "123456:ABCDEF",
            "telegram_chat_id": "999888777",
        },
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings?saved=credentials"

    creds = db_session.query(UserCredentials).filter_by(user_id=user.id).first()
    assert creds.firecrawl_api_key == "fc-abcdef1234"
    assert creds.telegram_bot_token == "123456:ABCDEF"
    assert creds.telegram_chat_id == "999888777"

    page = client.get("/settings")
    assert page.status_code == 200
    assert "1234" in page.text  # últimos 4 chars da api key aparecem mascarados
    assert "fc-abcdef1234" not in page.text  # valor completo não reaparece


def test_save_credentials_blank_field_keeps_existing_value(client, db_session):
    user = _seed_user(db_session)
    db_session.add(
        UserCredentials(user_id=user.id, firecrawl_api_key="fc-original-key", telegram_bot_token="tok")
    )
    db_session.commit()

    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})
    client.post(
        "/settings/credentials",
        data={"firecrawl_api_key": "", "telegram_bot_token": "", "telegram_chat_id": "111"},
    )

    creds = db_session.query(UserCredentials).filter_by(user_id=user.id).first()
    assert creds.firecrawl_api_key == "fc-original-key"  # não foi apagado
    assert creds.telegram_bot_token == "tok"
    assert creds.telegram_chat_id == "111"


def test_change_password_wrong_current_password(client, db_session):
    _seed_user(db_session)
    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})

    resp = client.post(
        "/settings/password",
        data={
            "current_password": "errada",
            "new_password": "novasenha123",
            "confirm_new_password": "novasenha123",
        },
    )
    assert resp.headers["location"] == "/settings?error=senha_atual_incorreta"


def test_change_password_mismatch(client, db_session):
    _seed_user(db_session)
    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})

    resp = client.post(
        "/settings/password",
        data={
            "current_password": "segredo123",
            "new_password": "novasenha123",
            "confirm_new_password": "outracoisa123",
        },
    )
    assert resp.headers["location"] == "/settings?error=senhas_nao_conferem"


def test_change_password_success_updates_hash(client, db_session):
    user = _seed_user(db_session)
    client.post("/login", data={"email": "painel@example.com", "password": "segredo123"})

    resp = client.post(
        "/settings/password",
        data={
            "current_password": "segredo123",
            "new_password": "novasenha123",
            "confirm_new_password": "novasenha123",
        },
    )
    assert resp.headers["location"] == "/settings?saved=password"

    db_session.refresh(user)
    assert verify_password("novasenha123", user.hashed_password)
    assert not verify_password("segredo123", user.hashed_password)
