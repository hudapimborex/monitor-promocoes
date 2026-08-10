"""Configura os agendadores que disparam o job diário de busca.

Dois modos, pro mesmo job (run_daily_search_job):
- `build_blocking_scheduler`: usado por `python worker.py` (sem --run-now) —
  bom se você for rodar isso numa máquina/VM sempre ligada. No deploy
  gratuito em nuvem (Render Web Service free + GitHub Actions cron, ver
  README), este loop não é usado: o GitHub Actions chama
  `worker.py --run-now` uma vez por dia diretamente, porque o Render free
  não tem Background Worker pra manter isso rodando 24/7.
- `build_background_scheduler`: usado pelo app desktop (.exe,
  desktop_app.py) — roda numa thread própria sem bloquear o processo
  principal, que também precisa servir o painel web e o ícone da bandeja.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.scheduler.jobs import run_daily_search_job

# Uma vez por dia de manhã cedo — evita concorrer com horário de pico das
# lojas e dá tempo de notificar antes do usuário acordar.
_DAILY_TRIGGER_KWARGS = dict(hour=7, minute=0)


def build_blocking_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        run_daily_search_job,
        trigger=CronTrigger(**_DAILY_TRIGGER_KWARGS),
        id="daily_search",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    return scheduler


def build_background_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        run_daily_search_job,
        trigger=CronTrigger(**_DAILY_TRIGGER_KWARGS),
        id="daily_search",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    return scheduler
