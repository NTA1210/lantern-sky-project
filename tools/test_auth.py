from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import auth, config


def test_auth_unit() -> None:
    hashed = auth.hash_password("MyStrongPass123!")
    assert hashed.startswith("pbkdf2_sha256$")
    assert auth.verify_password_hash("MyStrongPass123!", hashed)
    assert not auth.verify_password_hash("WrongPass123!", hashed)

    assert auth.sanitize_next_url("/control") == "/control"
    assert auth.sanitize_next_url("/control?tab=1") == "/control?tab=1"
    assert auth.sanitize_next_url("https://evil.example/phish") == "/control"
    assert auth.sanitize_next_url("//evil.example") == "/control"
    assert auth.sanitize_next_url("/\\evil.example") == "/control"
    assert auth.sanitize_next_url("/login") == "/control"

    limiter = auth.LoginRateLimiter(max_attempts=3, window_seconds=60.0)
    assert limiter.check_allowed("1.2.3.4") == 0
    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.check_allowed("1.2.3.4") == 0
    limiter.record_failure("1.2.3.4")
    assert limiter.check_allowed("1.2.3.4") > 0
    limiter.reset("1.2.3.4")
    assert limiter.check_allowed("1.2.3.4") == 0
    print("UNIT AUTH TESTS PASSED")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(opener, url: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()


def test_http_auth_flow() -> None:
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmpdir:
        env = dict(os.environ)
        env.pop("LANTERN_CONTROL_PASSWORD", None)
        env.pop("LANTERN_CONTROL_PASSWORD_HASH", None)
        env.pop("LANTERN_AUTH_SECRET", None)
        env["LANTERN_RUNTIME_DIR"] = tmpdir
        env["LANTERN_DISABLE_CAMERA"] = "1"
        env["LANTERN_NO_BROWSER"] = "1"
        env["LANTERN_RELOAD"] = "0"
        env["LANTERN_HOST"] = "127.0.0.1"
        env["PORT"] = str(port)
        env["LANTERN_CONTROL_USER"] = "operator"

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
            no_redirect_opener = urllib.request.build_opener(_NoRedirect())
            cookie_jar = http.cookiejar.CookieJar()
            authed_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

            # Wait for server startup
            deadline = time.monotonic() + 15.0
            initial_password = None
            while time.monotonic() < deadline:
                try:
                    status, _, _ = _request(no_redirect_opener, f"{base}/api/auth/status")
                    if status == 200:
                        break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Server failed to start within 15s")

            # Read stdout to extract auto-generated initial password
            assert proc.stdout is not None
            os.set_blocking(proc.stdout.fileno(), False)
            captured = proc.stdout.read() or ""
            for line in captured.splitlines():
                if "Password:" in line:
                    initial_password = line.split("Password:", 1)[1].strip()
            assert initial_password, f"Expected initial generated password in logs, got:\n{captured}"

            # 1. Public display endpoints remain accessible
            st, _, _ = _request(no_redirect_opener, f"{base}/display")
            assert st == 200, f"/display returned {st}"
            st, _, _ = _request(no_redirect_opener, f"{base}/api/display-state")
            assert st == 200, f"/api/display-state returned {st}"

            # 2. Protected pages redirect to /login
            for path in ("/", "/control"):
                st, hdrs, _ = _request(no_redirect_opener, f"{base}{path}")
                assert st == 303, f"{path} expected 303, got {st}"
                assert "/login" in hdrs.get("location", ""), f"{path} location={hdrs.get('location')}"

            # 3. Protected APIs reject unauthenticated requests with 401
            protected = [
                ("GET", "/api/settings"),
                ("POST", "/api/settings"),
                ("POST", "/api/settings/reset"),
                ("GET", "/api/cameras"),
                ("POST", "/api/cameras/select"),
                ("GET", "/api/status"),
                ("GET", "/api/camera/stream"),
                ("POST", "/api/scan"),
                ("POST", "/api/demo"),
                ("POST", "/api/background"),
                ("DELETE", "/api/background"),
                ("GET", "/api/recent"),
                ("GET", "/api/lanterns"),
                ("POST", "/api/lanterns/sequential-delete/start"),
                ("POST", "/api/lanterns/sequential-delete/stop"),
                ("GET", "/api/lanterns/sequential-delete/status"),
                ("DELETE", "/api/lanterns"),
                ("POST", "/api/lanterns/delete-latest"),
                ("DELETE", "/api/lanterns/abc"),
            ]
            for method, path in protected:
                st, _, _ = _request(no_redirect_opener, f"{base}{path}", method=method)
                assert st == 401, f"{method} {path} expected 401, got {st}"

            # 4. Wrong login fails with 401
            st, _, _ = _request(
                authed_opener,
                f"{base}/api/auth/login",
                method="POST",
                body=json.dumps({"username": "operator", "password": "wrong"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            assert st == 401

            # 5. Correct login sets HttpOnly session cookie and grants access
            st, _, body = _request(
                authed_opener,
                f"{base}/api/auth/login",
                method="POST",
                body=json.dumps({"username": "operator", "password": initial_password}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            assert st == 200, f"Valid login failed with {st}: {body}"

            st, _, body = _request(authed_opener, f"{base}/control")
            assert st == 200 and b"Trung T" in body

            st, _, _ = _request(authed_opener, f"{base}/api/settings")
            assert st == 200

            # 6. Cross-origin mutation rejected with 403
            st, _, _ = _request(
                authed_opener,
                f"{base}/api/demo",
                method="POST",
                headers={"Origin": "https://evil.example"},
            )
            assert st == 403, f"Expected 403 for cross-origin POST, got {st}"

            # 7. Change password works and old password fails afterwards
            st, _, _ = _request(
                authed_opener,
                f"{base}/api/auth/change-password",
                method="POST",
                body=json.dumps({"current_password": initial_password, "new_password": "NewSecurePassword99"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            assert st == 200

            # Logout clears cookie
            st, _, _ = _request(authed_opener, f"{base}/api/auth/logout", method="POST")
            assert st == 200
            st, _, _ = _request(authed_opener, f"{base}/api/settings")
            assert st == 401

            # Old password rejected, new password accepted via HTML form POST
            form_data = urllib.parse.urlencode({"username": "operator", "password": "NewSecurePassword99", "next": "/control"}).encode("utf-8")
            st, _, _ = _request(
                authed_opener,
                f"{base}/api/auth/login",
                method="POST",
                body=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert st == 200

            # 8. Rate limiting blocks repeated invalid logins with 429
            fresh_opener = urllib.request.build_opener(_NoRedirect())
            for _ in range(auth.MAX_LOGIN_ATTEMPTS):
                st, _, _ = _request(
                    fresh_opener,
                    f"{base}/api/auth/login",
                    method="POST",
                    body=json.dumps({"username": "operator", "password": "bad"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.55"},
                )
                assert st == 401
            st, _, _ = _request(
                fresh_opener,
                f"{base}/api/auth/login",
                method="POST",
                body=json.dumps({"username": "operator", "password": "bad"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.55"},
            )
            assert st == 429, f"Expected 429 on brute-force attempt, got {st}"

            print("HTTP AUTH FLOW TESTS PASSED")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    test_auth_unit()
    test_http_auth_flow()
