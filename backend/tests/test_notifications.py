import datetime as dt

import httpx

from app.core.formatting import format_brl
from app.db.models import Category, NotificationSettings, PriceAlert, Product, User
from app.notifications.service import (
    format_alert_message,
    notify_alert,
    notify_pending_alerts,
    notify_status,
    split_chat_ids,
)
from app.notifications.telegram import TelegramNotifier


def test_format_brl():
    assert format_brl(1234.5) == "R$ 1.234,50"
    assert format_brl(89.9) == "R$ 89,90"


def test_split_chat_ids_handles_comma_separated_and_whitespace():
    assert split_chat_ids("123456789, 987654321") == ["123456789", "987654321"]
    assert split_chat_ids("  111 ,,222  ,") == ["111", "222"]


def test_split_chat_ids_handles_empty_and_none():
    assert split_chat_ids("") == []
    assert split_chat_ids(None) == []


def test_split_chat_ids_single_value():
    assert split_chat_ids("999") == ["999"]


def test_send_message_returns_false_when_not_configured():
    notifier = TelegramNotifier(bot_token="", default_chat_id="")
    assert notifier.send_message("oi") is False


def test_send_message_success(monkeypatch):
    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="123")

    def fake_post(self, url, json=None, **kwargs):
        assert "fake-token" in url
        assert json["chat_id"] == "123"
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    assert notifier.send_message("Queda de preço!") is True


def test_send_message_failure(monkeypatch):
    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="123")

    def fake_post(self, url, json=None, **kwargs):
        return httpx.Response(400, text="bad request", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    assert notifier.send_message("Queda de preço!") is False


def _make_product_and_alert(db_session, name="Porcelanato <Premium> & Cia"):
    user = User(email="notif@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    category = Category(user_id=user.id, slug="porcelanato", name="Porcelanato")
    db_session.add(category)
    db_session.commit()

    product = Product(
        user_id=user.id,
        category_id=category.id,
        name=name,
        store_domain="loja.com.br",
        url="https://loja.com.br/produto",
        url_hash="hash-1",
        first_seen_at=dt.datetime(2026, 8, 1),
        last_seen_at=dt.datetime(2026, 8, 10),
    )
    db_session.add(product)
    db_session.commit()

    alert = PriceAlert(
        product_id=product.id,
        user_id=user.id,
        old_price=100.0,
        new_price=70.0,
        drop_pct=30.0,
    )
    db_session.add(alert)
    db_session.commit()
    return user, product, alert


def test_format_alert_message_escapes_html_and_formats_currency(db_session):
    _, product, alert = _make_product_and_alert(db_session)
    message = format_alert_message(product, alert)

    assert "&lt;Premium&gt;" in message
    assert "R$ 100,00" in message
    assert "R$ 70,00" in message
    assert "-30%" in message


def test_notify_alert_marks_as_notified_on_success(db_session, monkeypatch):
    user, product, alert = _make_product_and_alert(db_session)
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="999"))
    db_session.commit()

    def fake_post(self, url, json=None, **kwargs):
        assert json["chat_id"] == "999"
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is True
    assert alert.notified_at is not None
    assert alert.channel == "telegram"


def test_notify_alert_does_not_resend_already_notified(db_session, monkeypatch):
    _, product, alert = _make_product_and_alert(db_session)
    alert.notified_at = dt.datetime(2026, 8, 10)
    db_session.commit()

    calls = []
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, json=None, **kwargs: calls.append(1)
        or httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url)),
    )

    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="1")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is False
    assert calls == []


def test_notify_alert_sends_to_multiple_chat_ids(db_session, monkeypatch):
    user, product, alert = _make_product_and_alert(db_session)
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="111, 222"))
    db_session.commit()

    sent_to = []

    def fake_post(self, url, json=None, **kwargs):
        sent_to.append(json["chat_id"])
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is True
    assert sorted(sent_to) == ["111", "222"]
    assert alert.notified_at is not None


def test_notify_alert_still_marks_sent_if_only_one_of_several_succeeds(db_session, monkeypatch):
    user, product, alert = _make_product_and_alert(db_session)
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="111, 222"))
    db_session.commit()

    def fake_post(self, url, json=None, **kwargs):
        if json["chat_id"] == "111":
            return httpx.Response(400, text="bad", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is True  # pelo menos um dos dois recebeu


def test_notify_alert_falls_back_to_notifier_default_chat_id_without_settings_row(db_session, monkeypatch):
    _, product, alert = _make_product_and_alert(db_session)
    # sem NotificationSettings cadastrada pra esse usuário

    def fake_post(self, url, json=None, **kwargs):
        assert json["chat_id"] == "555"
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="555")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is True


def test_notify_alert_returns_false_without_any_chat_id(db_session, monkeypatch):
    _, product, alert = _make_product_and_alert(db_session)

    calls = []
    monkeypatch.setattr(
        httpx.Client, "post", lambda self, url, json=None, **kwargs: calls.append(1)
    )

    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="")
    sent = notify_alert(db_session, product, alert, notifier=notifier)

    assert sent is False
    assert calls == []


def test_notify_pending_alerts_sends_all_unsent(db_session, monkeypatch):
    user, product, alert1 = _make_product_and_alert(db_session)
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="999"))
    db_session.commit()

    alert2 = PriceAlert(
        product_id=product.id, user_id=user.id, old_price=70.0, new_price=50.0, drop_pct=28.6
    )
    db_session.add(alert2)
    db_session.commit()

    sent_calls = []

    def fake_post(self, url, json=None, **kwargs):
        sent_calls.append(json)
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token")
    count = notify_pending_alerts(db_session, user_id=user.id, notifier=notifier)

    assert count == 2
    assert len(sent_calls) == 2


def test_notify_status_sends_to_all_configured_chat_ids(db_session, monkeypatch):
    user = User(email="status@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(NotificationSettings(user_id=user.id, telegram_chat_id="111, 222"))
    db_session.commit()

    sent_to = []

    def fake_post(self, url, json=None, **kwargs):
        sent_to.append((json["chat_id"], json["text"]))
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    notifier = TelegramNotifier(bot_token="fake-token")
    sent = notify_status(db_session, user.id, "🔎 Começando a busca de hoje", notifier=notifier)

    assert sent is True
    assert sorted(chat_id for chat_id, _ in sent_to) == ["111", "222"]
    assert all(text == "🔎 Começando a busca de hoje" for _, text in sent_to)


def test_notify_status_returns_false_without_any_chat_id(db_session, monkeypatch):
    user = User(email="status2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    calls = []
    monkeypatch.setattr(
        httpx.Client, "post", lambda self, url, json=None, **kwargs: calls.append(1)
    )

    notifier = TelegramNotifier(bot_token="fake-token", default_chat_id="")
    sent = notify_status(db_session, user.id, "oi", notifier=notifier)

    assert sent is False
    assert calls == []


def test_notify_status_respects_disabled_telegram_channel(db_session, monkeypatch):
    user = User(email="status3@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(
        NotificationSettings(user_id=user.id, telegram_chat_id="111", channels_enabled_json=["dashboard"])
    )
    db_session.commit()

    calls = []
    monkeypatch.setattr(
        httpx.Client, "post", lambda self, url, json=None, **kwargs: calls.append(1)
    )

    notifier = TelegramNotifier(bot_token="fake-token")
    sent = notify_status(db_session, user.id, "oi", notifier=notifier)

    assert sent is False
    assert calls == []
