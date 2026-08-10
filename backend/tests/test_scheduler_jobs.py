import datetime as dt

from app.core.run_state import finish_run, get_status, request_cancel, start_run
from app.db.models import Category, PriceAlert, PriceHistory, Product, SearchRun, User
from app.notifications.telegram import TelegramNotifier
from app.scheduler import jobs as jobs_module
from app.scheduler.jobs import run_search_for_user
from app.scraping.firecrawl_client import SearchResponse, SearchResult
from app.scraping.ingest import normalize_url, url_hash


def setup_function():
    finish_run()  # run_state é um singleton global — garante estado limpo entre testes


class StubFirecrawlClient:
    """Substitui a Firecrawl real nos testes — devolve respostas pré-definidas."""

    def __init__(self, responses: dict[str, SearchResponse]):
        self.responses = responses
        self.calls: list[str] = []

    def search(self, query: str, scrape_top_n: int = 3) -> SearchResponse:
        self.calls.append(query)
        return self.responses[query]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def test_run_search_for_user_records_price_without_alert_on_first_observation(db_session, monkeypatch):
    user = User(email="job@example.com", hashed_password="x")
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

    query = "porcelanato promoção"
    response = SearchResponse(
        query=query,
        results=[
            SearchResult(url="https://loja.com.br/produto-1", title="Porcelanato 80x80", markdown="R$ 89,90")
        ],
        credits_used=3.0,
    )
    client = StubFirecrawlClient({query: response})

    notifier = TelegramNotifier(bot_token="fake", default_chat_id="1")
    sent = []
    monkeypatch.setattr(notifier, "send_message", lambda text, chat_id=None: sent.append(text) or True)

    stats = run_search_for_user(db_session, user, client, notifier)

    assert stats["queries"] == 1
    assert stats["results"] == 1
    assert stats["prices_recorded"] == 1
    assert stats["alerts"] == 0  # primeira observação: sem baseline, não pode confirmar queda
    assert sent == []

    products = db_session.query(Product).filter_by(user_id=user.id).all()
    assert len(products) == 1
    assert db_session.query(PriceHistory).filter_by(product_id=products[0].id).count() == 1

    runs = db_session.query(SearchRun).filter_by(user_id=user.id).all()
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].credits_used == 3.0


def test_run_search_for_user_creates_and_sends_alert_on_real_drop(db_session, monkeypatch):
    user = User(email="job2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(
        user_id=user.id,
        slug="piso_laminado",
        name="Piso Laminado",
        priority=1,
        keywords_json={"base_terms": ["piso laminado"], "discount_terms": ["promoção"], "sizes": []},
    )
    db_session.add(category)
    db_session.commit()

    url = "https://loja.com.br/piso-laminado"
    normalized = normalize_url(url)
    product = Product(
        user_id=user.id,
        category_id=category.id,
        name="Piso Laminado",
        store_domain="loja.com.br",
        url=normalized,
        url_hash=url_hash(normalized),
        first_seen_at=_now() - dt.timedelta(days=20),
        last_seen_at=_now() - dt.timedelta(days=15),
    )
    db_session.add(product)
    db_session.commit()

    for price, days_ago in [(100, 20), (100, 15)]:
        db_session.add(
            PriceHistory(product_id=product.id, price=price, captured_at=_now() - dt.timedelta(days=days_ago))
        )
    db_session.commit()

    query = "piso laminado promoção"
    response = SearchResponse(
        query=query,
        results=[SearchResult(url=url, title="Piso Laminado", markdown="R$ 70,00")],
        credits_used=3.0,
    )
    client = StubFirecrawlClient({query: response})

    notifier = TelegramNotifier(bot_token="fake", default_chat_id="1")
    sent = []
    monkeypatch.setattr(notifier, "send_message", lambda text, chat_id=None: sent.append(text) or True)

    stats = run_search_for_user(db_session, user, client, notifier)

    assert stats["alerts"] == 1
    assert len(sent) == 1

    alerts = db_session.query(PriceAlert).filter_by(product_id=product.id).all()
    assert len(alerts) == 1
    assert alerts[0].notified_at is not None
    assert alerts[0].channel == "telegram"


def test_run_search_for_user_marks_search_run_as_error_on_failure(db_session):
    user = User(email="job3@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(
        user_id=user.id,
        slug="revestimento_ceramico",
        name="Revestimento Cerâmico",
        priority=1,
        keywords_json={"base_terms": ["revestimento"], "discount_terms": ["oferta"], "sizes": []},
    )
    db_session.add(category)
    db_session.commit()

    class FailingClient:
        def search(self, query, scrape_top_n=3):
            from app.scraping.firecrawl_client import FirecrawlError

            raise FirecrawlError("simulated failure")

    notifier = TelegramNotifier(bot_token="", default_chat_id="")
    stats = run_search_for_user(db_session, user, FailingClient(), notifier)

    assert stats["errors"] == 1
    assert stats["queries"] == 0

    runs = db_session.query(SearchRun).filter_by(user_id=user.id).all()
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert "simulated failure" in runs[0].error_message


def test_run_search_for_user_rejects_when_already_running(db_session):
    start_run()  # simula uma busca já em andamento

    user = User(email="busy@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    notifier = TelegramNotifier(bot_token="", default_chat_id="")
    stats = run_search_for_user(db_session, user, object(), notifier)

    assert stats.get("skipped") == "already_running"


def test_run_search_for_user_stops_early_when_cancelled(db_session):
    user = User(email="cancel@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(
        user_id=user.id,
        slug="porcelanato",
        name="Porcelanato",
        priority=1,
        keywords_json={
            "base_terms": ["porcelanato"],
            "discount_terms": ["promoção", "desconto", "oferta"],
            "sizes": [],
        },
    )
    db_session.add(category)
    db_session.commit()

    class CancellingClient:
        def __init__(self):
            self.calls = 0

        def search(self, query, scrape_top_n=3):
            self.calls += 1
            request_cancel()  # cancela assim que a primeira busca roda
            return SearchResponse(query=query, results=[], credits_used=2.0)

    client = CancellingClient()
    notifier = TelegramNotifier(bot_token="", default_chat_id="")
    stats = run_search_for_user(db_session, user, client, notifier)

    assert client.calls == 1  # não chegou a rodar a segunda query
    assert stats["cancelled"] is True
    assert get_status()["running"] is False  # finish_run rodou no finally


def test_wait_while_paused_or_cancelled_returns_false_when_idle():
    start_run()
    try:
        assert jobs_module._wait_while_paused_or_cancelled() is False
    finally:
        finish_run()


def test_wait_while_paused_or_cancelled_blocks_then_resumes(monkeypatch):
    from app.core.run_state import request_pause, request_resume

    start_run()
    request_pause()

    sleeps = {"n": 0}

    def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:
            request_resume()

    monkeypatch.setattr(jobs_module.time, "sleep", fake_sleep)

    try:
        result = jobs_module._wait_while_paused_or_cancelled()
        assert result is False
        assert sleeps["n"] >= 2
    finally:
        finish_run()


def test_wait_while_paused_or_cancelled_returns_true_if_cancelled_during_pause(monkeypatch):
    from app.core.run_state import request_pause

    start_run()
    request_pause()

    def fake_sleep(seconds):
        request_cancel()

    monkeypatch.setattr(jobs_module.time, "sleep", fake_sleep)

    try:
        assert jobs_module._wait_while_paused_or_cancelled() is True
    finally:
        finish_run()
