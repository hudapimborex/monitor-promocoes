"""Entrypoint do job de busca.

Deploy gratuito recomendado (ver README): GitHub Actions dispara
`python worker.py --run-now` uma vez por dia via cron — Render free não tem
Background Worker, só Web Service, então o agendamento roda fora dele.

Uso local:
    python worker.py               # fica rodando em loop, dispara o job todo dia às 07:00
                                    # (útil se você rodar isso numa máquina/VM sempre ligada)
    python worker.py --run-now      # roda o job uma vez imediatamente e sai
"""

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.scheduler.apscheduler_setup import build_blocking_scheduler  # noqa: E402
from app.scheduler.jobs import run_daily_search_job  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-now", action="store_true", help="Roda o job uma vez e sai (não fica em loop)."
    )
    args = parser.parse_args()

    if args.run_now:
        run_daily_search_job()
        return

    scheduler = build_blocking_scheduler()
    logging.info("Scheduler iniciado. Próxima busca às 07:00 (America/Sao_Paulo).")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
