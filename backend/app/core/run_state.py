"""Estado da execução da busca (rodando/pausado/cancelado), em memória.

Usado pelos botões Pausar/Retomar/Cancelar no painel. Assim como o
live_log, não é persistido — reinicia zerado a cada vez que o processo sobe,
o que é o comportamento esperado (é controle da sessão atual, não histórico).
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_state = {"running": False, "paused": False, "cancel_requested": False}


def start_run() -> bool:
    """Marca início de uma busca. Retorna False se já tem uma rodando (pra
    não deixar duas buscas concorrentes brigando pelo mesmo estado/cota)."""
    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True
        _state["paused"] = False
        _state["cancel_requested"] = False
        return True


def finish_run() -> None:
    with _lock:
        _state["running"] = False
        _state["paused"] = False
        _state["cancel_requested"] = False


def request_pause() -> None:
    with _lock:
        if _state["running"]:
            _state["paused"] = True


def request_resume() -> None:
    with _lock:
        _state["paused"] = False


def request_cancel() -> None:
    with _lock:
        _state["cancel_requested"] = True
        _state["paused"] = False  # cancelar também destrava uma pausa


def is_paused() -> bool:
    with _lock:
        return _state["paused"]


def is_cancelled() -> bool:
    with _lock:
        return _state["cancel_requested"]


def get_status() -> dict:
    with _lock:
        return dict(_state)
