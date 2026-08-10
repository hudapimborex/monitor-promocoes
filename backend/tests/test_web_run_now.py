import pytest
from fastapi.testclient import TestClient

from app.core.run_state import finish_run
from app.core.security import hash_password
from app.db.models import Category, SearchRun, User
from app.db.session import get_db
from main import app


def setup_function():
    finish_run()  # run_state é um singleton global — garante estado limpo entre testes


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_user_with_category(db_session, password="segredo123"):
    user = User(email="run@example.com", hashed_password=hash_password(password))
    db_session.add(user)
    db_session.commit()

    category = Category(
        user_id=user.id,
        slug="porcelanato",
        name="Porcelanato",
        priority=1,
        keywords_json={"base_terms": ["porcelanato"], "discount_terms": ["promoção"], "sizes": []},
    )
    db_session.add(category)
    db_session.commit()
    return user


def test_run_now_requires_login(client, db_session):
    _seed_user_with_category(db_session)
    resp = client.post("/run-now")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_run_now_triggers_search_pipeline_and_redirects(client, db_session):
    user = _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    resp = client.post("/run-now")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?run=started"

    # sem FIRECRAWL_API_KEY configurada, a busca falha graciosamente, mas o
    # SearchRun precisa existir — prova que /run-now -> planner -> job rodou.
    runs = db_session.query(SearchRun).filter_by(user_id=user.id).all()
    assert len(runs) > 0
    assert runs[0].status == "error"
    assert "FIRECRAWL_API_KEY" in runs[0].error_message


def test_dashboard_shows_flash_message_after_run_started(client, db_session):
    _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    resp = client.get("/", params={"run": "started"})
    assert resp.status_code == 200
    assert "iniciada em segundo plano" in resp.text


def test_dashboard_lists_recent_search_runs(client, db_session):
    user = _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})
    client.post("/run-now")

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Execuções recentes" in resp.text
    assert "Porcelanato" in resp.text


def test_run_log_requires_login(client, db_session):
    _seed_user_with_category(db_session)
    resp = client.get("/run-log")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_run_log_reflects_search_activity(client, db_session):
    _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    baseline = client.get("/run-log").json()
    last_id = baseline["entries"][-1]["id"] if baseline["entries"] else 0

    client.post("/run-now")

    resp = client.get("/run-log", params={"since": last_id})
    assert resp.status_code == 200
    messages = [e["message"] for e in resp.json()["entries"]]
    assert any("Buscando" in m or "Categoria" in m for m in messages)


def test_run_log_includes_status(client, db_session):
    _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    resp = client.get("/run-log")
    assert resp.status_code == 200
    status = resp.json()["status"]
    assert status == {"running": False, "paused": False, "cancel_requested": False}


def test_run_now_rejects_when_already_running(client, db_session):
    from app.core.run_state import start_run

    _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    start_run()  # simula uma busca já em andamento
    resp = client.post("/run-now")
    assert resp.headers["location"] == "/?run=already_running"


def test_pause_resume_cancel_endpoints_require_login(client, db_session):
    _seed_user_with_category(db_session)
    for path in ("/run-pause", "/run-resume", "/run-cancel"):
        resp = client.post(path)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"


def test_pause_resume_cancel_endpoints_update_status(client, db_session):
    from app.core.run_state import get_status, start_run

    _seed_user_with_category(db_session)
    client.post("/login", data={"email": "run@example.com", "password": "segredo123"})

    start_run()

    resp = client.post("/run-pause")
    assert resp.status_code == 200
    assert get_status()["paused"] is True

    resp = client.post("/run-resume")
    assert resp.status_code == 200
    assert get_status()["paused"] is False

    resp = client.post("/run-cancel")
    assert resp.status_code == 200
    assert get_status()["cancel_requested"] is True
