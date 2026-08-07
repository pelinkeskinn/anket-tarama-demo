from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT_DIR / "backend" / "templates" / "demo_form_v1.json"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "backend" / "data" / "demo.db"))
SAMPLE_FORMS_DIR = ROOT_DIR / "sample-forms"

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "12000000"))
MAX_MANUAL_REVIEW_QUESTIONS = int(os.getenv("MAX_MANUAL_REVIEW_QUESTIONS", "4"))

EMPTY_THRESHOLD = float(os.getenv("OMR_EMPTY_THRESHOLD", "0.23"))
MARK_THRESHOLD = float(os.getenv("OMR_MARK_THRESHOLD", "0.25"))
UNCERTAIN_MARGIN = float(os.getenv("OMR_UNCERTAIN_MARGIN", "0.07"))
DOUBLE_MARK_THRESHOLD = float(os.getenv("OMR_DOUBLE_MARK_THRESHOLD", "0.34"))

