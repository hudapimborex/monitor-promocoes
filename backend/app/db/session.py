from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# SQLite precisa de check_same_thread=False porque o APScheduler roda jobs
# em threads diferentes da que abriu a conexão. Postgres não precisa disso.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """Dependency do FastAPI: uma sessão por request, sempre fechada no final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Uso fora do FastAPI (jobs do scheduler, scripts). Chamador deve fechar."""
    return SessionLocal()
