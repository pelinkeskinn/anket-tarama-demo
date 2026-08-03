from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import TEMPLATE_PATH
from app.errors import OmrError


@lru_cache
def load_template() -> dict[str, Any]:
    try:
        with TEMPLATE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise OmrError("INVALID_TEMPLATE") from exc

