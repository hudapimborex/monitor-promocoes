import datetime as dt

from app.pricing.detector import PricePoint, evaluate_drop

D0 = dt.datetime(2026, 8, 10, 12, 0, 0)


def days_ago(n: int) -> dt.datetime:
    return D0 - dt.timedelta(days=n)


def test_no_history_is_not_a_drop():
    result = evaluate_drop(history=[], new_price=50, new_captured_at=D0)
    assert result.is_real_drop is False
    assert "histórico" in result.reason


def test_price_that_did_not_fall_is_not_a_drop():
    history = [PricePoint(100, days_ago(10)), PricePoint(100, days_ago(4))]
    result = evaluate_drop(history=history, new_price=100, new_captured_at=D0)
    assert result.is_real_drop is False
    assert result.reason == "preço não caiu"


def test_small_drop_below_threshold_is_not_a_real_drop():
    history = [PricePoint(100, days_ago(10)), PricePoint(100, days_ago(4))]
    # 10% de queda, abaixo do limiar padrão de 15%
    result = evaluate_drop(history=history, new_price=90, new_captured_at=D0)
    assert result.is_real_drop is False
    assert result.drop_pct == 10.0


def test_big_drop_without_stable_history_is_not_a_real_drop():
    # só um ponto de histórico -> não dá pra confirmar estabilidade mínima
    history = [PricePoint(100, days_ago(1))]
    result = evaluate_drop(history=history, new_price=70, new_captured_at=D0)
    assert result.is_real_drop is False
    assert "estável" in result.reason


def test_big_drop_with_stable_history_is_a_real_drop():
    history = [PricePoint(100, days_ago(10)), PricePoint(100, days_ago(4))]
    result = evaluate_drop(history=history, new_price=70, new_captured_at=D0)
    assert result.is_real_drop is True
    assert result.baseline_price == 100
    assert result.drop_pct == 30.0


def test_does_not_renotify_same_price_level():
    # 100 estável por um tempo, depois 70 estável por 6 dias (já alertado antes)
    history = [
        PricePoint(100, days_ago(20)),
        PricePoint(100, days_ago(15)),
        PricePoint(70, days_ago(10)),
        PricePoint(70, days_ago(4)),
    ]
    result = evaluate_drop(
        history=history, new_price=70, new_captured_at=D0, last_alert_price=70
    )
    assert result.is_real_drop is False
    assert "já notificado" in result.reason


def test_renotifies_when_price_drops_further_than_last_alert():
    history = [
        PricePoint(100, days_ago(20)),
        PricePoint(100, days_ago(15)),
        PricePoint(70, days_ago(10)),
        PricePoint(70, days_ago(4)),
    ]
    result = evaluate_drop(
        history=history, new_price=60, new_captured_at=D0, last_alert_price=70
    )
    assert result.is_real_drop is True
    assert result.baseline_price == 85
    assert round(result.drop_pct, 2) == 29.41
