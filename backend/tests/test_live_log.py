import logging

from app.core.live_log import get_entries_since, install_live_log_handler


def test_install_is_idempotent_and_captures_app_logger_records():
    install_live_log_handler()
    install_live_log_handler()  # não deve duplicar o handler

    logger = logging.getLogger("app.scheduler.jobs")
    logger.info("mensagem de teste %s", "abc")

    entries = get_entries_since(0)
    assert any(e.message == "mensagem de teste abc" for e in entries)


def test_get_entries_since_only_returns_newer_entries():
    install_live_log_handler()
    logger = logging.getLogger("app.scraping.ingest")

    logger.info("linha 1")
    baseline = get_entries_since(0)
    last_id = baseline[-1].id

    logger.info("linha 2")
    logger.info("linha 3")

    fresh = get_entries_since(last_id)
    messages = [e.message for e in fresh]
    assert "linha 2" in messages
    assert "linha 3" in messages
    assert "linha 1" not in messages
