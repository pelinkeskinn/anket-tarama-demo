from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backup_db import backup_sqlite


def test_sqlite_backup_copies_rows(tmp_path: Path) -> None:
    source = tmp_path / "demo.db"
    destination = tmp_path / "demo-copy.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE demo_forms (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO demo_forms (name) VALUES ('row-1')")
        connection.commit()
    backup_sqlite(source, destination)
    with sqlite3.connect(destination) as connection:
        count = connection.execute("SELECT COUNT(*) FROM demo_forms").fetchone()[0]
    assert count == 1
    assert destination.exists()
