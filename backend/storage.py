from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from PIL import Image, UnidentifiedImageError

from . import config, db
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


def _is_primary_storage() -> bool:
    try:
        return config.LANTERNS_DIR.resolve() == (config.RUNTIME_DIR / "lanterns").resolve()
    except OSError:
        return False


def _thumb_filename_for(lantern_path: Path) -> str:
    return f"{lantern_path.stem}.webp"


def ensure_thumbnail(lantern_path: Path) -> str | None:
    """Create a lightweight RGBA WebP thumbnail for fast /display loading."""
    if not lantern_path.is_file():
        return None
    thumb_name = _thumb_filename_for(lantern_path)
    thumb_path = config.THUMBS_DIR / thumb_name
    if thumb_path.is_file():
        return thumb_name

    config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    temp = _temp_path(thumb_path)
    try:
        with Image.open(lantern_path) as img:
            rgba = img.convert("RGBA")
            max_h = max(120, config.THUMB_MAX_HEIGHT)
            if rgba.height > max_h:
                ratio = max_h / float(rgba.height)
                new_size = (max(1, round(rgba.width * ratio)), max_h)
                rgba = rgba.resize(new_size, Image.Resampling.LANCZOS)
            rgba.save(temp, format="WEBP", quality=82, method=4)
        os.replace(temp, thumb_path)
        return thumb_name
    except Exception:
        temp.unlink(missing_ok=True)
        return None


def _row_to_record(row: dict) -> dict:
    filename = row["filename"]
    thumb_filename = row.get("thumb_filename")
    full_url = f"/generated/lanterns/{filename}"
    display_url = f"/generated/thumbs/{thumb_filename}" if thumb_filename and (config.THUMBS_DIR / thumb_filename).is_file() else full_url
    return {
        "id": row["id"],
        "url": display_url,
        "fullUrl": full_url,
        "variant": row["variant"],
        "createdAt": row["created_at"],
    }


def _unlink_lantern_artifacts(scan_id: str, filename: str | None = None, thumb_filename: str | None = None) -> None:
    if filename:
        (config.LANTERNS_DIR / filename).unlink(missing_ok=True)
    if thumb_filename:
        (config.THUMBS_DIR / thumb_filename).unlink(missing_ok=True)
    (config.ORIGINAL_DIR / f"{scan_id}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{scan_id}.png").unlink(missing_ok=True)


def sync_storage_with_db() -> None:
    """Reconcile existing PNG files on disk with SQLite and missing thumbnails."""
    if not _is_primary_storage():
        return
    db.ensure_schema()
    disk_files = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    disk_by_id: dict[str, tuple[Path, dict]] = {}
    for item in disk_files:
        parsed = _parse_lantern_path(item)
        disk_by_id[parsed["id"]] = (item, parsed)

    existing_rows = {row["id"]: row for row in db.get_lantern_rows()}

    # Insert new/unindexed disk files into DB
    for scan_id, (path, parsed) in disk_by_id.items():
        row = existing_rows.get(scan_id)
        thumb_name = row.get("thumb_filename") if row else None
        if not thumb_name or not (config.THUMBS_DIR / thumb_name).is_file():
            thumb_name = ensure_thumbnail(path)
        if row is None or row.get("thumb_filename") != thumb_name:
            db.upsert_lantern(
                scan_id=scan_id,
                variant=parsed["variant"],
                filename=path.name,
                thumb_filename=thumb_name,
                quality_score=row.get("quality_score") if row else None,
                created_at=parsed["createdAt"],
                created_ts=path.stat().st_mtime,
            )

    # Remove DB rows whose files were deleted manually outside the app
    for scan_id, row in existing_rows.items():
        if scan_id not in disk_by_id:
            db.delete_lantern_row(scan_id)
            if row.get("thumb_filename"):
                (config.THUMBS_DIR / row["thumb_filename"]).unlink(missing_ok=True)


def record_new_lantern(
    scan_id: str,
    variant_key: str,
    lantern_path: Path,
    quality_score: float | None = None,
) -> dict:
    """Generate display thumbnail and persist lantern metadata to SQLite."""
    modified = lantern_path.stat().st_mtime
    created_at = datetime.fromtimestamp(modified, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    thumb_name = ensure_thumbnail(lantern_path) if _is_primary_storage() else None
    if _is_primary_storage():
        db.upsert_lantern(
            scan_id=scan_id,
            variant=variant_key,
            filename=lantern_path.name,
            thumb_filename=thumb_name,
            quality_score=quality_score,
            created_at=created_at,
            created_ts=modified,
        )
    full_url = f"/generated/lanterns/{lantern_path.name}"
    display_url = f"/generated/thumbs/{thumb_name}" if thumb_name else full_url
    return {
        "id": scan_id,
        "url": display_url,
        "fullUrl": full_url,
        "variant": variant_key,
        "createdAt": created_at,
    }


def list_lanterns(limit: int | None = None) -> list[dict]:
    """List persisted lanterns oldest-first.

    The event display intentionally keeps the full history. A bounded limit is
    only used by compatibility endpoints such as /api/recent.
    """
    if _is_primary_storage():
        return [_row_to_record(row) for row in db.get_lantern_rows(limit=limit)]

    files = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    if limit is not None:
        limit = max(0, limit)
        files = files[-limit:] if limit else []
    return [_parse_lantern_path(item) for item in files]


def lantern_count() -> int:
    if _is_primary_storage():
        return db.count_lantern_rows()
    return sum(1 for _ in config.LANTERNS_DIR.glob("*.png"))


def delete_lantern(scan_id: str) -> bool:
    """Delete a single lantern and its diagnostic files by ID."""
    found = False
    if _is_primary_storage():
        row = db.delete_lantern_row(scan_id)
        if row is not None:
            _unlink_lantern_artifacts(scan_id, row.get("filename"), row.get("thumb_filename"))
            found = True

    for lantern in config.LANTERNS_DIR.glob("*.png"):
        record = _parse_lantern_path(lantern)
        if (
            record["id"] == scan_id
            or lantern.stem == scan_id
            or lantern.name.startswith(f"{scan_id}_")
            or lantern.name.startswith(f"{scan_id}.")
        ):
            lantern.unlink(missing_ok=True)
            (config.THUMBS_DIR / _thumb_filename_for(lantern)).unlink(missing_ok=True)
            found = True
    (config.ORIGINAL_DIR / f"{scan_id}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{scan_id}.png").unlink(missing_ok=True)
    return found


def delete_oldest_lantern() -> dict | None:
    """Delete the oldest created lantern (FIFO)."""
    if _is_primary_storage():
        rows = db.pop_oldest_lantern_rows(1)
        if not rows:
            return None
        row = rows[0]
        _unlink_lantern_artifacts(row["id"], row.get("filename"), row.get("thumb_filename"))
        return _row_to_record(row)

    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    if not lanterns:
        return None
    oldest = lanterns[0]
    record = _parse_lantern_path(oldest)
    oldest.unlink(missing_ok=True)
    (config.ORIGINAL_DIR / f"{record['id']}.jpg").unlink(missing_ok=True)
    (config.CORRECTED_DIR / f"{record['id']}.png").unlink(missing_ok=True)
    return record


def delete_oldest_lanterns(count: int) -> list[dict]:
    """Delete the N oldest created lanterns (FIFO)."""
    if count <= 0:
        return []
    if _is_primary_storage():
        rows = db.pop_oldest_lantern_rows(count)
        for row in rows:
            _unlink_lantern_artifacts(row["id"], row.get("filename"), row.get("thumb_filename"))
        return [_row_to_record(row) for row in rows]

    lanterns = sorted(config.LANTERNS_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime)
    to_delete = lanterns[:count]
    deleted_records = []
    for item in to_delete:
        record = _parse_lantern_path(item)
        item.unlink(missing_ok=True)
        (config.ORIGINAL_DIR / f"{record['id']}.jpg").unlink(missing_ok=True)
        (config.CORRECTED_DIR / f"{record['id']}.png").unlink(missing_ok=True)
        deleted_records.append(record)
    return deleted_records


def delete_latest_lantern() -> dict | None:
    """Delete the most recently created lantern."""
    if _is_primary_storage():
        row = db.pop_latest_lantern_row()
        if row is None:
            return None
        _unlink_lantern_artifacts(row["id"], row.get("filename"), row.get("thumb_filename"))
        return _row_to_record(row)

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
    if _is_primary_storage():
        rows = db.clear_lantern_rows()
        count = len(rows)
        for row in rows:
            _unlink_lantern_artifacts(row["id"], row.get("filename"), row.get("thumb_filename"))

    for lantern in config.LANTERNS_DIR.glob("*.png"):
        lantern.unlink(missing_ok=True)
        if not _is_primary_storage():
            count += 1
    for thumb in config.THUMBS_DIR.glob("*.webp"):
        thumb.unlink(missing_ok=True)
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
    if _is_primary_storage():
        rows = db.prune_except_latest(max_items)
        for row in rows:
            _unlink_lantern_artifacts(row["id"], row.get("filename"), row.get("thumb_filename"))
        return

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

