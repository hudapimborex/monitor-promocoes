"""Registra (ou re-registra) a URL do webhook do Telegram — só precisa rodar
isso uma vez, ou de novo se a URL do Render mudar.

Uso:
    python scripts/register_telegram_webhook.py [https://sua-url.onrender.com]

Sem argumento, usa a URL padrão do deploy (promo-monitor-web.onrender.com).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.web.telegram_webhook import webhook_secret  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        print("Defina TELEGRAM_BOT_TOKEN no .env antes de rodar este script.")
        return

    base_url = sys.argv[1] if len(sys.argv) > 1 else "https://promo-monitor-web.onrender.com"
    webhook_url = f"{base_url.rstrip('/')}/telegram/webhook/{webhook_secret()}"

    resp = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook",
        json={"url": webhook_url},
        timeout=15,
    )
    resp.raise_for_status()
    print(resp.json())
    print(f"\nWebhook registrado em: {webhook_url}")


if __name__ == "__main__":
    main()
