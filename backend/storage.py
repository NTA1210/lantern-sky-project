from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import cv2

from . import config


class StorageError(RuntimeError):
    pass


def _temp_path(path: Path) -> Path:
    return path.with_name(f".{path.stem}.{uuid4().hex}.tmp{path.suffix}")


def atomic_imwrite(path: Path, image, params: list[int] | None = None) -> None:
    """Write an OpenCV image atomically and fail loudly if encoding/storage fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = _temp_path(path)
    try:
        ok = cv2.imwrite(str(temp), image, params or [])
        if not ok:
            raise StorageError(f"Không thể ghi ảnh: {path.name}")
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def prune_scan_storage(max_items: int | None = None) -> None:
    max_items = config.MAX_STORED_LANTERNS if max_items is None else max(0, max_items)
    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    for lantern in lanterns[max_items:]:
        scan_id = lantern.stem
        lantern.unlink(missing_ok=True)
        (config.ORIGINAL_DIR / f"{scan_id}.jpg").unlink(missing_ok=True)
        (config.CORRECTED_DIR / f"{scan_id}.png").unlink(missing_ok=True)


def recent_lanterns(limit: int = 12):
    limit = max(0, min(limit, config.MAX_RECENT_LANTERNS))
    files = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    files.reverse()
    return [{"id": item.stem, "url": f"/generated/lanterns/{item.name}"} for item in files]


def current_background_path() -> Path | None:
    candidates = sorted(
        (path for path in config.BACKGROUND_DIR.glob("current.*") if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None
