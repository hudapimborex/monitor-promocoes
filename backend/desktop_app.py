"""Entrypoint do app desktop (.exe).

Sobe o mesmo painel web (main.py) numa thread, roda o agendador diário em
segundo plano (sem bloquear), mostra um ícone na bandeja do Windows e abre o
navegador automaticamente. Pensado pra ser empacotado com PyInstaller (ver
README) e ficar rodando o tempo todo, buscando promoções sozinho enquanto o
PC estiver ligado.

Uso local (sem empacotar):
    python desktop_app.py
"""

from __future__ import annotations

import logging
import sys
import threading
import webbrowser

# Empacotado com --windowed (sem console), sys.stdout/stderr são None — não
# apenas fechados, None mesmo. Qualquer coisa que tente escrever neles (a
# própria logging.basicConfig() já faz isso) derruba o app antes de mostrar
# qualquer erro. Redireciona pra um arquivo de log em vez de crashar cedo.
if sys.stdout is None or sys.stderr is None:
    from app.core.paths import env_file_dir

    _log_path = env_file_dir() / "desktop_app.log"
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file

import pystray
import uvicorn
from PIL import Image, ImageDraw

from app.core.live_log import install_live_log_handler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("desktop_app")
install_live_log_handler()

HOST = "127.0.0.1"
PORT = 8756  # porta pouco comum, evita colidir com outros serviços locais


def _ensure_database() -> None:
    """Cria as tabelas (se não existirem) e semeia planos/usuário/categorias.

    O .exe não roda Alembic (não faz sentido bundlar migrações pra uma
    instalação nova) — `create_all` já cobre o schema atual direto.
    """
    from app.db.base import Base
    from app.db.seed import run_seed
    from app.db.session import engine, session_scope

    Base.metadata.create_all(bind=engine)
    db = session_scope()
    try:
        run_seed(db)
    finally:
        db.close()


def _build_icon_image() -> Image.Image:
    """Ícone simples (uma "casinha" estilizada) gerado em código — evita
    depender de um arquivo .ico externo no bundle."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((12, 30, 52, 54), fill="#4fd1c5")
    draw.polygon([(8, 30), (32, 10), (56, 30)], fill="#4fd1c5")
    return img


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


def _run_search_now() -> None:
    from app.scheduler.jobs import run_daily_search_job

    threading.Thread(target=run_daily_search_job, daemon=True).start()
    logger.info("Busca manual disparada em segundo plano.")


def main() -> None:
    logger.info("Iniciando Monitor de Promoções...")
    _ensure_database()

    import main as web_app  # import tardio: precisa rodar depois do _ensure_database
    from app.scheduler.apscheduler_setup import build_background_scheduler

    scheduler = build_background_scheduler()
    scheduler.start()

    config = uvicorn.Config(web_app.app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    _open_browser()

    def _quit(icon: pystray.Icon) -> None:
        logger.info("Encerrando...")
        scheduler.shutdown(wait=False)
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "promo-monitor",
        _build_icon_image(),
        "Monitor de Promoções",
        menu=pystray.Menu(
            pystray.MenuItem("Abrir painel", lambda icon, item: _open_browser(), default=True),
            pystray.MenuItem("Rodar análise agora", lambda icon, item: _run_search_now()),
            pystray.MenuItem("Sair", lambda icon, item: _quit(icon)),
        ),
    )
    icon.run()


if __name__ == "__main__":
    main()
