import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.run_state import finish_run
from app.db.base import Base
from app.db import models  # noqa: F401 garante que todos os models registrem no Base.metadata


@pytest.fixture(autouse=True)
def _reset_run_state():
    """run_state é um singleton global (em memória, de propósito) — sem
    isso, um teste que chama start_run()/request_pause() vaza estado pros
    testes seguintes, não importa a ordem em que os arquivos rodam."""
    finish_run()
    yield
    finish_run()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
