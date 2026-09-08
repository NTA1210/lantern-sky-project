from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from PIL import Image, UnidentifiedImageError

from . import config
from .layout import LANTERN_VARIANTS, lantern_roi


class StorageError(RuntimeError):
    pass


_VARIANT_SEPARATOR = "__"


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


def lantern_filename(scan_id: str, variant_key: str) -> str:
    if variant_key not in LANTERN_VARIANTS:
        raise StorageError(f"Unknown lantern variant: {variant_key}")
    return f"{scan_id}{_VARIANT_SEPARATOR}{variant_key}.png"


def _infer_legacy_variant(path: Path) -> str:
    """Infer pre-suffix variant from the exported PNG aspect ratio."""
    try:
        with Image.open(path) as image:
            aspect = image.width / max(1, image.height)
    except (OSError, UnidentifiedImageError):
        return "classic"

    expected = {}
    for key in LANTERN_VARIANTS:
        x1, y1, x2, y2 = lantern_roi(config.CANONICAL_WIDTH, config.CANONICAL_HEIGHT, key)
        expected[key] = (x2 - x1) / max(1, y2 - y1)
    return min(expected, key=lambda key: abs(expected[key] - aspect))


def _parse_lantern_path(path: Path) -> dict:
    """Return durable display metadata encoded by the generated PNG filename.

    Files created before multi-template persistence did not contain a variant
    suffix. Their exported dimensions are used to infer the closest template.
    """
    stem = path.stem
    variant_key = None
    scan_id = stem
    for key in LANTERN_VARIANTS:
        suffix = f"{_VARIANT_SEPARATOR}{key}"
        if stem.endswith(suffix):
            variant_key = key
            scan_id = stem[:-len(suffix)]
            break
    if variant_key is None:
        variant_key = _infer_legacy_variant(path)

    modified = path.stat().st_mtime
    created_at = datetime.fromtimestamp(modified, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": scan_id,
        "url": f"/generated/lanterns/{path.name}",
        "variant": variant_key,
        "createdAt": created_at,
    }


def list_lanterns(limit: int | None = None) -> list[dict]:
    """List persisted lanterns oldest-first.

    The event display intentionally keeps the full history. A bounded limit is
    only used by compatibility endpoints such as /api/recent.
    """
    files = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    if limit is not None:
        limit = max(0, limit)
        files = files[-limit:] if limit else []
    return [_parse_lantern_path(item) for item in files]


def lantern_count() -> int:
    return sum(1 for _ in config.LANTERNS_DIR.glob("*.png"))


def delete_lantern(scan_id: str) -> bool:
    """Delete a single lantern and its diagnostic files by ID."""
    found = False
    for lantern in config.LANTERNS_DIR.glob("*.png"):
        record = _parse_lantern_path(lantern)
        if (
            record["id"] == scan_id
            or lantern.stem == scan_id
            or lantern.name.startswith(f"{scan_id}_")
            or lantern.name.startswith(f"{scan_id}.")
        ):
            lantern.unlink(missing_ok=True)
            found = True
    (config.ORIGINAL_DIR / f"{scan_id}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{scan_id}.png").unlink(missing_ok=True)
    return found


def delete_oldest_lantern() -> dict | None:
    """Delete the oldest created lantern (FIFO)."""
    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    if not lanterns:
        return None
    oldest = lanterns[0]
    record = _parse_lantern_path(oldest)
    oldest.unlink(missing_ok=True)
    (config.ORIGINAL_DIR / f"{record['id']}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{record['id']}.png").unlink(missing_ok=True)
    return record


def delete_latest_lantern() -> dict | None:
    """Delete the most recently created lantern."""
    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    if not lanterns:
        return None
    latest = lanterns[-1]
    record = _parse_lantern_path(latest)
    latest.unlink(missing_ok=True)
    (config.ORIGINAL_DIR / f"{record['id']}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{record['id']}.png").unlink(missing_ok=True)
    return record


def delete_all_lanterns() -> int:
    """Delete all scanned lanterns and diagnostics."""
    count = 0
    for lantern in config.LANTERNS_DIR.glob("*.png"):
        lantern.unlink(missing_ok=True)
        count += 1
    for item in config.ORIGINAL_DIR.glob("*.jpg"):
        item.unlink(missing_ok=True)
    for item in config.CORRECTED_DIR.glob("*.png"):
        item.unlink(missing_ok=True)
    return count


def prune_scan_storage(max_items: int) -> None:
    """Explicit maintenance helper; normal event scans never call this.

    Keeping this helper makes manual cleanup possible between events without
    introducing automatic deletion during an active event.
    """
    max_items = max(0, max_items)
    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)
    for lantern in lanterns[max_items:]:
        record = _parse_lantern_path(lantern)
        scan_id = record["id"]
        lantern.unlink(missing_ok=True)
        (config.ORIGINAL_DIR / f"{scan_id}.jpg").unlink(missing_ok=True)
        (config.CORRECTED_DIR / f"{scan_id}.png").unlink(missing_ok=True)


def recent_lanterns(limit: int = 12) -> list[dict]:
    limit = max(0, min(limit, config.MAX_RECENT_API_ITEMS))
    return list_lanterns(limit)


def current_background_path() -> Path | None:
    candidates = sorted(
        (path for path in config.BACKGROUND_DIR.glob("current.*") if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None

