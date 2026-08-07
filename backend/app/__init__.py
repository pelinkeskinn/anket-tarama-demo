from __future__ import annotations

import os

import cv2
import numpy as np


def _imread_unicode(path: str, flags: int = cv2.IMREAD_COLOR):
	data = np.fromfile(path, dtype=np.uint8)
	if data.size == 0:
		return None
	return cv2.imdecode(data, flags)


if os.name == "nt":
	cv2.imread = _imread_unicode

