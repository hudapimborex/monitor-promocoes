"""Buffer de log em memória usado pelo painel pra mostrar a busca "ao vivo".

Não é persistido em banco de propósito — é só um espelho recente (últimas
~500 linhas) do que os loggers de app.* emitem, pra alimentar a caixa estilo
terminal no painel via polling (GET /run-log). Reinicia zerado a cada vez
que o processo sobe, o que é o comportamento esperado (é log de sessão, não
histórico permanente — isso já vive em search_runs/price_history).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import deque
from dataclasses import dataclass
from itertools import count
from typing import List

_lock = threading.Lock()
_buffer: deque["LogEntry"] = deque(maxlen=500)
_counter = count(1)
_installed = False


@dataclass
class LogEntry:
    id: int
    time: str
    level: str
    message: str


class _LiveLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record) if self.formatter else record.getMessage()
        except Exception:  # nunca deixa um log quebrar a aplicação
            message = record.getMessage()
        entry = LogEntry(
            id=next(_counter),
            time=dt.datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            level=record.levelname,
            message=message,
        )
        with _lock:
            _buffer.append(entry)


def install_live_log_handler() -> None:
    """Chamar uma vez no startup (main.py / desktop_app.py). Idempotente."""
    global _installed
    if _installed:
        return
    handler = _LiveLogHandler()
    handler.setLevel(logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    _installed = True


def get_entries_since(last_id: int = 0) -> List[LogEntry]:
    with _lock:
        return [e for e in _buffer if e.id > last_id]
