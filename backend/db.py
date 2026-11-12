from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

logger = logging.getLogger("lantern.db")

_DB_LOCK = threading.RLock()
_INITIALIZED_DBS: set[Path] = set()


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _connect() -> sqlite3.Connection:
    db_path = config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def ensure_schema() -> None:
    db_path = config.DB_PATH
    if db_path in _INITIALIZED_DBS and db_path.is_file():
        return
    with _DB_LOCK:
        if db_path in _INITIALIZED_DBS and db_path.is_file():
            return
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS lanterns (
                    id TEXT PRIMARY KEY,
                    variant TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    thumb_filename TEXT,
                    quality_score REAL,
                    created_at TEXT NOT NULL,
                    created_ts REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lanterns_created_ts ON lanterns(created_ts ASC);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            _migrate_legacy_settings_if_empty(conn)
        _INITIALIZED_DBS.add(db_path)


def _migrate_legacy_settings_if_empty(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM settings").fetchone()
    if row and row["cnt"] > 0:
        return
    initial = config.load_settings()
    now = _utc_now_iso()
    for key, val in initial.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(val), now),
        )


def ping() -> bool:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute("SELECT 1").fetchone()
            return bool(row and row[0] == 1)


def upsert_lantern(
    scan_id: str,
    variant: str,
    filename: str,
    thumb_filename: str | None,
    quality_score: float | None,
    created_at: str,
    created_ts: float,
) -> None:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO lanterns (id, variant, filename, thumb_filename, quality_score, created_at, created_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    variant = excluded.variant,
                    filename = excluded.filename,
                    thumb_filename = COALESCE(excluded.thumb_filename, lanterns.thumb_filename),
                    quality_score = COALESCE(excluded.quality_score, lanterns.quality_score),
                    created_at = excluded.created_at,
                    created_ts = excluded.created_ts
                """,
                (scan_id, variant, filename, thumb_filename, quality_score, created_at, created_ts),
            )


def get_lantern_rows(limit: int | None = None) -> list[dict]:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            if limit is not None:
                bounded = max(0, int(limit))
                if bounded == 0:
                    return []
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT id, variant, filename, thumb_filename, quality_score, created_at, created_ts
                        FROM lanterns
                        ORDER BY created_ts DESC, rowid DESC
                        LIMIT ?
                    ) sub
                    ORDER BY created_ts ASC
                    """,
                    (bounded,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, variant, filename, thumb_filename, quality_score, created_at, created_ts
                    FROM lanterns
                    ORDER BY created_ts ASC, rowid ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]


def count_lantern_rows() -> int:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM lanterns").fetchone()
            return int(row["cnt"]) if row else 0


def delete_lantern_row(scan_id: str) -> dict | None:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                "SELECT id, variant, filename, thumb_filename, created_at, created_ts FROM lanterns WHERE id = ?",
                (scan_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM lanterns WHERE id = ?", (scan_id,))
            return dict(row)


def pop_oldest_lantern_rows(count: int) -> list[dict]:
    if count <= 0:
        return []
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, variant, filename, thumb_filename, created_at, created_ts
                FROM lanterns
                ORDER BY created_ts ASC, rowid ASC
                LIMIT ?
                """,
                (int(count),),
            ).fetchall()
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM lanterns WHERE id IN ({placeholders})", ids)
            return [dict(row) for row in rows]


def pop_latest_lantern_row() -> dict | None:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT id, variant, filename, thumb_filename, created_at, created_ts
                FROM lanterns
                ORDER BY created_ts DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM lanterns WHERE id = ?", (row["id"],))
            return dict(row)


def clear_lantern_rows() -> list[dict]:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, variant, filename, thumb_filename, created_at, created_ts FROM lanterns"
            ).fetchall()
            conn.execute("DELETE FROM lanterns")
            return [dict(row) for row in rows]


def prune_except_latest(max_items: int) -> list[dict]:
    max_items = max(0, int(max_items))
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, variant, filename, thumb_filename, created_at, created_ts
                FROM lanterns
                ORDER BY created_ts DESC, rowid DESC
                LIMIT -1 OFFSET ?
                """,
                (max_items,),
            ).fetchall()
            if not rows:
                return []
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM lanterns WHERE id IN ({placeholders})", ids)
            return [dict(row) for row in rows]


def load_settings_db() -> dict:
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
            merged = dict(config.DEFAULT_SETTINGS)
            for row in rows:
                key = row["key"]
                if key in merged:
                    try:
                        merged[key] = json.loads(row["value_json"])
                    except Exception:
                        pass
            return merged


def save_settings_db(new_settings: dict) -> dict:
    ensure_schema()
    current = load_settings_db()
    for k in config.DEFAULT_SETTINGS:
        if k in new_settings:
            if isinstance(config.DEFAULT_SETTINGS[k], bool):
                current[k] = bool(new_settings[k])
            else:
                try:
                    current[k] = float(new_settings[k])
                except (ValueError, TypeError):
                    pass

    now = _utc_now_iso()
    with _DB_LOCK:
        with _connect() as conn:
            for k, val in current.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (k, json.dumps(val), now),
                )
    # Keep JSON file mirror updated for tools/backward compatibility
    try:
        config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception:
        pass
    return current


def set_app_state(key: str, value: str) -> None:
    ensure_schema()
    now = _utc_now_iso()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

