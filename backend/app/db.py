from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _create_engine() -> Engine:
    database_url = get_settings().database_url
    connect_args = {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _configure_sqlite(connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    if engine.dialect.name != "sqlite":
        return
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
