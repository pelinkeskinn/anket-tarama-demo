from __future__ import annotations

from app.config import _database_url


def test_postgres_url_uses_installed_psycopg_driver(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.test/database")
    assert _database_url() == "postgresql+psycopg://user:password@example.test/database"
