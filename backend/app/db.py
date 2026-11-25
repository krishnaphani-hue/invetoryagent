from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def configure(url: str) -> None:
    """Point the app at a different database (used by tests)."""
    global engine
    engine.dispose()
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal.configure(bind=engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
