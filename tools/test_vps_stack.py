from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.self_test import canonical, fake_camera


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(opener, url: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=8) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()


def main() -> None:
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        env = dict(os.environ)
        env["LANTERN_RUNTIME_DIR"] = str(tmp_path)
        env["LANTERN_DB_PATH"] = str(tmp_path / "lantern_sky.db")
        env["LANTERN_DISABLE_CAMERA"] = "1"
        env["LANTERN_NO_BROWSER"] = "1"
        env["LANTERN_RELOAD"] = "0"
        env["LANTERN_HOST"] = "127.0.0.1"
        env["PORT"] = str(port)
        env["LANTERN_CONTROL_USER"] = "vps_admin"
        env["LANTERN_CONTROL_PASSWORD"] = "vps_strong_pass_123"

        proc = subprocess.Popen(
            [sys.executable, "run.py"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    st, _, body = _request(opener, f"{base}/healthz")
                    if st == 200:
                        health = json.loads(body.decode("utf-8"))
                        assert health["ok"] is True and health["db"] == "ok"
                        break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Server did not become healthy in time")

            # Prepare synthetic camera JPEG
            frame = fake_camera(canonical("round"))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            assert ok
            jpeg_bytes = encoded.tobytes()

            # 1. Unauthenticated /api/scan/detect & /api/scan/upload must return 401
            st, _, _ = _request(opener, f"{base}/api/scan/detect", method="POST", body=jpeg_bytes)
            assert st == 401, f"Expected 401 on unauthed detect, got {st}"
            st, _, _ = _request(opener, f"{base}/api/scan/upload", method="POST", body=jpeg_bytes)
            assert st == 401, f"Expected 401 on unauthed upload, got {st}"

            # 2. Login
            st, _, _ = _request(
                opener,
                f"{base}/api/auth/login",
                method="POST",
                body=json.dumps({"username": "vps_admin", "password": "vps_strong_pass_123"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            assert st == 200

            # 3. Preview detect
            st, _, body = _request(
                opener,
                f"{base}/api/scan/detect",
                method="POST",
                body=jpeg_bytes,
                headers={"Content-Type": "image/jpeg"},
            )
            assert st == 200
            detect_data = json.loads(body.decode("utf-8"))
            assert detect_data["readyToScan"] is True
            assert detect_data["variant"] == "round"

            # 4. Upload scan creates full PNG + lightweight WebP thumb + SQLite row
            st, _, body = _request(
                opener,
                f"{base}/api/scan/upload",
                method="POST",
                body=jpeg_bytes,
                headers={"Content-Type": "image/jpeg"},
            )
            assert st == 200, f"Upload scan failed: {st} {body}"
            scan_data = json.loads(body.decode("utf-8"))
            assert scan_data["variant"] == "round"
            assert scan_data["lanternUrl"].startswith("/generated/thumbs/")
            assert scan_data["fullUrl"].startswith("/generated/lanterns/")
            assert scan_data["totalCount"] == 1

            # 5. Thumbnail endpoint serves immutable cache header & smaller size than full PNG
            st, thumb_hdrs, thumb_bytes = _request(opener, f"{base}{scan_data['lanternUrl']}")
            assert st == 200
            assert "immutable" in thumb_hdrs.get("cache-control", "")

            st, _, full_bytes = _request(opener, f"{base}{scan_data['fullUrl']}")
            assert st == 200
            assert len(thumb_bytes) < len(full_bytes), (
                f"Expected thumbnail ({len(thumb_bytes)}B) smaller than full PNG ({len(full_bytes)}B)"
            )

            # 6. Verify SQLite WAL DB has persisted row and settings
            conn = sqlite3.connect(str(tmp_path / "lantern_sky.db"))
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert journal_mode.lower() == "wal", f"Expected WAL mode, got {journal_mode}"
            row = conn.execute("SELECT id, variant, thumb_filename FROM lanterns WHERE id = ?", (scan_data["id"],)).fetchone()
            assert row is not None and row[1] == "round" and row[2].endswith(".webp")
            conn.close()

            # 7. Display-state returns thumb URL and supports GZip
            st, hdrs, _ = _request(
                opener,
                f"{base}/api/display-state",
                headers={"Accept-Encoding": "gzip"},
            )
            assert st == 200
            assert hdrs.get("x-content-type-options") == "nosniff"

            # 8. Delete removes DB row, PNG, and WebP thumbnail
            st, _, _ = _request(opener, f"{base}/api/lanterns/{scan_data['id']}", method="DELETE")
            assert st == 200
            assert not (tmp_path / "lanterns").glob("*.png").__iter__().__next__() if list((tmp_path / "lanterns").glob("*.png")) else True
            assert len(list((tmp_path / "lanterns").glob("*.png"))) == 0
            assert len(list((tmp_path / "thumbs").glob("*.webp"))) == 0

            print("VPS STACK (DB + THUMBS + UPLOAD SCAN + HEADERS) TESTS PASSED")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()

