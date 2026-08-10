"""Resolve caminhos tanto rodando a partir do código-fonte (dev/cloud)
quanto empacotado como .exe (PyInstaller).

A diferença principal: dentro de um .exe empacotado, o bundle é somente
leitura (fica num diretório temporário que pode até ser apagado entre
execuções), então dados graváveis (banco SQLite, `.env`) precisam morar em
outro lugar — usamos `%APPDATA%\\PromoMonitor` no Windows, igual a maioria
dos programas desktop faz.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
PROJECT_ROOT = BACKEND_DIR.parent

IS_FROZEN = bool(getattr(sys, "frozen", False))


def _appdata_dir() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home()))) / "PromoMonitor"
    base.mkdir(parents=True, exist_ok=True)
    return base


def resource_dir(*parts: str) -> Path:
    """Recursos empacotados junto com o app (templates Jinja2,
    config/categories.yml) — somente leitura, tanto no .exe quanto rodando
    do código-fonte. `config/categories.yml` vive na raiz do repo (um nível
    acima de backend/), então o caso não-empacotado usa PROJECT_ROOT."""
    base = Path(getattr(sys, "_MEIPASS", str(PROJECT_ROOT))) if IS_FROZEN else PROJECT_ROOT
    return base.joinpath(*parts)


def env_file_dir() -> Path:
    """Onde procurar o `.env`. Empacotado: %APPDATA%\\PromoMonitor. Rodando
    do código-fonte: raiz do repositório (comportamento de sempre)."""
    return _appdata_dir() if IS_FROZEN else PROJECT_ROOT


def sqlite_dir() -> Path:
    """Onde grava o arquivo SQLite local. Empacotado: %APPDATA%\\PromoMonitor.
    Rodando do código-fonte: dentro de backend/ (comportamento de sempre —
    absoluto de propósito, pra não depender do diretório de onde o processo
    foi iniciado)."""
    return _appdata_dir() if IS_FROZEN else BACKEND_DIR
