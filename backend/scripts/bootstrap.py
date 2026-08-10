"""Cria as tabelas (via Alembic, se ainda não aplicado) e semeia dados iniciais.

Uso:
    python scripts/bootstrap.py

Rode `alembic upgrade head` antes (ou deixe o worker/main fazer isso) — este
script só cuida do seed de planos/usuário/categorias.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.seed import run_seed  # noqa: E402
from app.db.session import session_scope  # noqa: E402


def main() -> None:
    db = session_scope()
    try:
        run_seed(db)
        print("Seed concluído: planos, usuário e categorias prontos.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
