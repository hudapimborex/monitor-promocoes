from app.core.run_state import (
    finish_run,
    get_status,
    is_cancelled,
    is_paused,
    request_cancel,
    request_pause,
    request_resume,
    start_run,
)


def setup_function():
    finish_run()  # garante estado limpo entre testes (módulo é um singleton global)


def test_start_run_succeeds_when_idle():
    assert start_run() is True
    status = get_status()
    assert status == {"running": True, "paused": False, "cancel_requested": False}


def test_start_run_fails_when_already_running():
    start_run()
    assert start_run() is False


def test_finish_run_resets_state():
    start_run()
    request_pause()
    finish_run()
    assert get_status() == {"running": False, "paused": False, "cancel_requested": False}


def test_pause_resume_cycle():
    start_run()
    request_pause()
    assert is_paused() is True
    request_resume()
    assert is_paused() is False


def test_pause_only_applies_when_running():
    request_pause()  # sem start_run antes
    assert is_paused() is False


def test_cancel_clears_pause():
    start_run()
    request_pause()
    request_cancel()
    assert is_cancelled() is True
    assert is_paused() is False
