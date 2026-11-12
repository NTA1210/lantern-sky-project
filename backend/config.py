from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional fallback if dotenv is absent
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


FRONTEND_DIR = BASE_DIR / "frontend"
PRINT_DIR = BASE_DIR / "print"
RUNTIME_DIR = Path(os.environ.get("LANTERN_RUNTIME_DIR", BASE_DIR / "runtime"))
LANTERNS_DIR = RUNTIME_DIR / "lanterns"
THUMBS_DIR = RUNTIME_DIR / "thumbs"
DIAGNOSTICS_DIR = RUNTIME_DIR / "diagnostics"
ORIGINAL_DIR = DIAGNOSTICS_DIR / "original"
CORRECTED_DIR = DIAGNOSTICS_DIR / "corrected"
BACKGROUND_DIR = RUNTIME_DIR / "backgrounds"
AUTH_FILE = RUNTIME_DIR / "control_auth.json"
AUTH_SECRET_FILE = RUNTIME_DIR / ".auth_secret"
DB_PATH = Path(os.environ.get("LANTERN_DB_PATH", RUNTIME_DIR / "lantern_sky.db"))


def initialize_runtime_dirs() -> None:
    """Create mutable runtime directories explicitly during application startup."""
    for directory in (
        RUNTIME_DIR,
        LANTERNS_DIR,
        THUMBS_DIR,
        DIAGNOSTICS_DIR,
        ORIGINAL_DIR,
        CORRECTED_DIR,
        BACKGROUND_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


# Control and Display run on the same laptop, so localhost is the safe default.
HOST = os.environ.get("LANTERN_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# Browser E2E does not need physical video hardware. This is intentionally
# opt-in so production/event startup behavior remains unchanged.
DISABLE_CAMERA = _env_bool("LANTERN_DISABLE_CAMERA", False)

CAMERA_INDEX = int(os.environ.get("LANTERN_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.environ.get("LANTERN_CAMERA_WIDTH", "3840"))
CAMERA_HEIGHT = int(os.environ.get("LANTERN_CAMERA_HEIGHT", "2160"))
CAMERA_FPS = int(os.environ.get("LANTERN_CAMERA_FPS", "30"))
CAMERA_USE_MJPG = _env_bool("LANTERN_CAMERA_MJPG", True)
CAMERA_RECONNECT_SECONDS = float(os.environ.get("LANTERN_CAMERA_RECONNECT_SECONDS", "1.5"))
CAMERA_READ_FAILURE_LIMIT = int(os.environ.get("LANTERN_CAMERA_READ_FAILURE_LIMIT", "8"))
CAMERA_PROBE_MAX = int(os.environ.get("LANTERN_CAMERA_PROBE_MAX", "6"))
PREVIEW_MAX_WIDTH = int(os.environ.get("LANTERN_PREVIEW_MAX_WIDTH", "1280"))
PREVIEW_FPS = float(os.environ.get("LANTERN_PREVIEW_FPS", "25"))

CANONICAL_WIDTH = int(os.environ.get("LANTERN_CANONICAL_WIDTH", "1600"))
CANONICAL_HEIGHT = round(CANONICAL_WIDTH * 297 / 210)
JPEG_PREVIEW_QUALITY = 82
JPEG_MASTER_QUALITY = 97
PNG_COMPRESSION = 3

# /api/recent remains bounded for Control/diagnostics only. This is not a
# storage/display retention limit: /api/display-state loads the full history.
MAX_RECENT_API_ITEMS = 40
KEEP_DIAGNOSTICS = _env_bool("LANTERN_KEEP_DIAGNOSTICS", False)

MAX_BACKGROUND_BYTES = int(os.environ.get("LANTERN_MAX_BACKGROUND_BYTES", str(20 * 1024 * 1024)))
MAX_BACKGROUND_PIXELS = int(os.environ.get("LANTERN_MAX_BACKGROUND_PIXELS", "40000000"))
MAX_SCAN_UPLOAD_BYTES = int(os.environ.get("LANTERN_MAX_SCAN_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_SCAN_PIXELS = int(os.environ.get("LANTERN_MAX_SCAN_PIXELS", "40000000"))
THUMB_MAX_HEIGHT = int(os.environ.get("LANTERN_THUMB_MAX_HEIGHT", "400"))
MAX_WS_CONNECTIONS = int(os.environ.get("LANTERN_MAX_WS_CONNECTIONS", "1000"))

SETTINGS_FILE = RUNTIME_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "conveyor_speed": 1.0,
    "sway_amplitude": 1.0,
    "sway_speed": 1.0,
    "auto_scan_seconds": 2.0,
    "camera_flip_horizontal": False,
    "scan_quality_threshold": 50,
}


def load_settings() -> dict:
    if SETTINGS_FILE.is_file():
        try:
            import json
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(new_settings: dict) -> dict:
    import json
    current = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in new_settings:
            if isinstance(DEFAULT_SETTINGS[k], bool):
                current[k] = bool(new_settings[k])
            else:
                try:
                    current[k] = float(new_settings[k])
                except (ValueError, TypeError):
                    pass
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


AUTH_DISABLED = _env_bool("LANTERN_AUTH_DISABLED", False)
CONTROL_USER = os.environ.get("LANTERN_CONTROL_USER", "admin").strip() or "admin"
CONTROL_PASSWORD = os.environ.get("LANTERN_CONTROL_PASSWORD", "")
CONTROL_PASSWORD_HASH = os.environ.get("LANTERN_CONTROL_PASSWORD_HASH", "")
AUTH_SECRET = os.environ.get("LANTERN_AUTH_SECRET", "")
SESSION_TTL_SECONDS = max(300, int(float(os.environ.get("LANTERN_SESSION_HOURS", "12")) * 3600))
COOKIE_SECURE_MODE = os.environ.get("LANTERN_COOKIE_SECURE", "auto").strip().lower()

