"""Ajuda a descobrir o seu chat_id do Telegram.

Uso:
    1. Crie um bot com o @BotFather e pegue o token.
    2. Coloque o token em TELEGRAM_BOT_TOKEN no .env.
    3. Mande qualquer mensagem pro seu bot no Telegram.
    4. Rode: python scripts/telegram_get_chat_id.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        print("Defina TELEGRAM_BOT_TOKEN no .env antes de rodar este script.")
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
    resp = httpx.get(url, timeout=15.0)
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    if not updates:
        print("Nenhuma mensagem encontrada. Mande uma mensagem pro bot no Telegram e rode de novo.")
        return

    seen = {}
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("username") or chat.get("first_name") or "?"

    print("Chat IDs encontrados:")
    for chat_id, name in seen.items():
        print(f"  {chat_id}  ({name})")
    print("\nColoque um desses valores em TELEGRAM_DEFAULT_CHAT_ID no .env.")


if __name__ == "__main__":
    main()
