#!/usr/bin/env python3
"""Copy a SQLite database using the online backup API (safe with WAL mode)."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "backend" / "data" / "demo.db"
DEFAULT_BACKUP_DIR = ROOT / "backend" / "data" / "backups"


def backup_sqlite(source: Path, destination: Path) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dest:
        src.backup(dest)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WAL-safe SQLite backup")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_dir / f"demo-{stamp}.db"
    backup_sqlite(args.source, destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
