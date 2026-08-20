from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = ROOT / ".pytest-tmp-local"


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    TMP_ROOT.mkdir(exist_ok=True)
    path = TMP_ROOT / os.urandom(4).hex()
    path.mkdir()
    yield path
