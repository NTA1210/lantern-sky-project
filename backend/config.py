from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
PRINT_DIR = BASE_DIR / "print"
RUNTIME_DIR = Path(os.environ.get("LANTERN_RUNTIME_DIR", BASE_DIR / "runtime"))
LANTERNS_DIR = RUNTIME_DIR / "lanterns"
DIAGNOSTICS_DIR = RUNTIME_DIR / "diagnostics"
ORIGINAL_DIR = DIAGNOSTICS_DIR / "original"
CORRECTED_DIR = DIAGNOSTICS_DIR / "corrected"
BACKGROUND_DIR = RUNTIME_DIR / "backgrounds"

for directory in (
    RUNTIME_DIR,
    LANTERNS_DIR,
    DIAGNOSTICS_DIR,
    ORIGINAL_DIR,
    CORRECTED_DIR,
    BACKGROUND_DIR,
    PRINT_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)

# Control and Display run on the same laptop, so localhost is the safe default.
HOST = os.environ.get("LANTERN_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

CAMERA_INDEX = int(os.environ.get("LANTERN_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LANTERN_CAMERA_WIDTH", "3840"))
CAMERA_HEIGHT = int(os.environ.get("LANTERN_CAMERA_HEIGHT", "2160"))
CAMERA_FPS = int(os.environ.get("LANTERN_CAMERA_FPS", "30"))
CAMERA_USE_MJPG = _env_bool("LANTERN_CAMERA_MJPG", True)
CAMERA_RECONNECT_SECONDS = float(os.environ.get("LANTERN_CAMERA_RECONNECT_SECONDS", "1.5"))
CAMERA_READ_FAILURE_LIMIT = int(os.environ.get("LANTERN_CAMERA_READ_FAILURE_LIMIT", "8"))
CAMERA_PROBE_MAX = int(os.environ.get("LANTERN_CAMERA_PROBE_MAX", "6"))

CANONICAL_WIDTH = int(os.environ.get("LANTERN_CANONICAL_WIDTH", "1600"))
CANONICAL_HEIGHT = round(CANONICAL_WIDTH * 297 / 210)
JPEG_PREVIEW_QUALITY = 82
JPEG_MASTER_QUALITY = 97
PNG_COMPRESSION = 3

MAX_RECENT_LANTERNS = 40
MAX_STORED_LANTERNS = int(os.environ.get("LANTERN_MAX_STORED", "240"))
KEEP_DIAGNOSTICS = _env_bool("LANTERN_KEEP_DIAGNOSTICS", False)

MAX_BACKGROUND_BYTES = int(os.environ.get("LANTERN_MAX_BACKGROUND_BYTES", str(20 * 1024 * 1024)))
MAX_BACKGROUND_PIXELS = int(os.environ.get("LANTERN_MAX_BACKGROUND_PIXELS", "40000000"))
