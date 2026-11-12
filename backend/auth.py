from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response

from . import config

logger = logging.getLogger("lantern.auth")

SESSION_COOKIE_NAME = "lantern_control_session"
PBKDF2_ITERATIONS = 240_000
MIN_PASSWORD_LENGTH = 8
MAX_LOGIN_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sha256_digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def _constant_time_str_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(_sha256_digest(a), _sha256_digest(b))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64u_encode(salt)}${_b64u_encode(derived)}"


def verify_password_hash(password: str, stored_hash: str) -> bool:
    try:
        scheme, iter_text, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        if iterations < 10_000:
            return False
        salt = _b64u_decode(salt_b64)
        expected = _b64u_decode(digest_b64)
    except Exception:
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def _write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def is_env_managed() -> bool:
    return False


def _env_fingerprint() -> str | None:
    if not (config.CONTROL_PASSWORD or config.CONTROL_PASSWORD_HASH):
        return None
    raw = f"{config.CONTROL_USER}:{config.CONTROL_PASSWORD}:{config.CONTROL_PASSWORD_HASH}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _load_stored_credentials() -> dict | None:
    if not config.AUTH_FILE.is_file():
        return None
    try:
        data = json.loads(config.AUTH_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("username") and data.get("password_hash"):
            return data
    except Exception:
        logger.warning("Failed to parse %s", config.AUTH_FILE)
    return None


def _active_credentials() -> tuple[str, str, str]:
    """Return (username, mode, material) backed by control_auth.json."""
    stored = _load_stored_credentials()
    if stored is None:
        ensure_credentials_initialized()
        stored = _load_stored_credentials()
    if stored is None:
        raise RuntimeError("Control auth credentials could not be initialized")
    return str(stored["username"]), "hash", str(stored["password_hash"])


def _credential_version() -> str:
    username, mode, material = _active_credentials()
    digest = hashlib.sha256(f"{username}:{mode}:{material}".encode("utf-8")).hexdigest()
    return digest[:16]


def ensure_credentials_initialized() -> None:
    """Seed control_auth.json from env on first boot (or when env credentials change), or generate random password."""
    if config.AUTH_DISABLED:
        return

    stored = _load_stored_credentials()
    env_fp = _env_fingerprint()

    if env_fp is not None:
        if stored is not None and stored.get("env_fingerprint") == env_fp:
            return
        password_hash = config.CONTROL_PASSWORD_HASH or hash_password(config.CONTROL_PASSWORD)
        payload = {
            "username": config.CONTROL_USER,
            "password_hash": password_hash,
            "env_fingerprint": env_fp,
        }
        _write_private_file(config.AUTH_FILE, json.dumps(payload, indent=2))
        return

    if stored is not None:
        return

    initial_password = secrets.token_urlsafe(12)
    payload = {
        "username": config.CONTROL_USER,
        "password_hash": hash_password(initial_password),
    }
    _write_private_file(config.AUTH_FILE, json.dumps(payload, indent=2))
    banner = (
        "\n==================================================================\n"
        "[Lantern Sky Security] Da tao tai khoan Control mac dinh:\n"
        f"  Username: {config.CONTROL_USER}\n"
        f"  Password: {initial_password}\n"
        "Ban co the dang nhap va doi mat khau ngay trong giao dien Control\n"
        "(nut Doi mat khau) ma khong can sua file .env.\n"
        "=================================================================="
    )
    logger.warning(banner)
    print(banner, flush=True)


def _signing_secret() -> bytes:
    if config.AUTH_SECRET:
        return _sha256_digest(config.AUTH_SECRET)

    if config.AUTH_SECRET_FILE.is_file():
        existing = config.AUTH_SECRET_FILE.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return _sha256_digest(existing)

    generated = secrets.token_hex(32)
    _write_private_file(config.AUTH_SECRET_FILE, generated)
    return _sha256_digest(generated)


def verify_credentials(username: str, password: str) -> bool:
    if not username or not password:
        return False
    expected_user, mode, material = _active_credentials()
    user_ok = _constant_time_str_eq(username.strip(), expected_user)
    if mode == "hash":
        pass_ok = verify_password_hash(password, material)
    else:
        pass_ok = _constant_time_str_eq(password, material)
    return user_ok and pass_ok


def change_stored_password(current_password: str, new_password: str) -> str:
    username, _, _ = _active_credentials()
    if not verify_credentials(username, current_password):
        raise HTTPException(400, detail="Mật khẩu hiện tại không đúng.")

    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, detail=f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")

    payload: dict[str, str] = {
        "username": username,
        "password_hash": hash_password(new_password),
    }
    env_fp = _env_fingerprint()
    if env_fp is not None:
        payload["env_fingerprint"] = env_fp
    _write_private_file(config.AUTH_FILE, json.dumps(payload, indent=2))
    return username


def create_session_token(username: str) -> str:
    now = int(time.time())
    payload = {
        "u": username,
        "iat": now,
        "exp": now + config.SESSION_TTL_SECONDS,
        "v": _credential_version(),
    }
    payload_b64 = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_signing_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64u_encode(signature)}"


def verify_session_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(_signing_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        provided_sig = _b64u_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(_b64u_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None

    exp = payload.get("exp")
    username = payload.get("u")
    version = payload.get("v")
    if not isinstance(exp, int) or exp <= int(time.time()):
        return None
    expected_user, _, _ = _active_credentials()
    if not isinstance(username, str) or not _constant_time_str_eq(username, expected_user):
        return None
    if not isinstance(version, str) or not hmac.compare_digest(version, _credential_version()):
        return None
    return expected_user


def should_use_secure_cookie(request: Request) -> bool:
    mode = config.COOKIE_SECURE_MODE
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def set_session_cookie(response: Response, request: Request, username: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(username),
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=should_use_secure_cookie(request),
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=should_use_secure_cookie(request),
        path="/",
    )


def sanitize_next_url(next_url: str | None) -> str:
    if not next_url:
        return "/control"
    candidate = next_url.strip()
    if not candidate.startswith("/") or candidate.startswith("//") or candidate.startswith("/\\"):
        return "/control"
    if any(ch in candidate for ch in ("\r", "\n", "\x00")):
        return "/control"
    if candidate.startswith("/login") or candidate.startswith("/api/auth/"):
        return "/control"
    return candidate


def _is_trusted_proxy_ip(ip_text: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_text)
        return addr.is_loopback or addr.is_private
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for and _is_trusted_proxy_ip(direct_ip):
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    return direct_ip


class LoginRateLimiter:
    def __init__(self, max_attempts: int = MAX_LOGIN_ATTEMPTS, window_seconds: float = RATE_LIMIT_WINDOW_SECONDS):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._failures.get(key)
        if bucket is None:
            return deque()
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
        return bucket

    def check_allowed(self, key: str) -> int:
        now = time.monotonic()
        bucket = self._prune(key, now)
        if len(bucket) >= self.max_attempts:
            retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
            return retry_after
        return 0

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._prune(key, now)
        bucket.append(now)
        self._failures[key] = bucket
        if len(self._failures) > 2048:
            for existing_key in list(self._failures):
                self._prune(existing_key, now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()


def _verify_same_origin(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_host = urlparse(origin).netloc.lower()
    if not origin_host:
        raise HTTPException(403, detail="Origin không hợp lệ.")
    allowed_hosts = set()
    for header_name in ("host", "x-forwarded-host"):
        raw = request.headers.get(header_name, "")
        for item in raw.split(","):
            cleaned = item.strip().lower()
            if cleaned:
                allowed_hosts.add(cleaned)
    if allowed_hosts and origin_host not in allowed_hosts:
        raise HTTPException(403, detail="Cross-origin request bị từ chối.")


def get_authenticated_user(request: Request) -> str | None:
    if config.AUTH_DISABLED:
        return config.CONTROL_USER
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_token(token)


def require_control_api(request: Request) -> str:
    user = get_authenticated_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Vui lòng đăng nhập để truy cập trang Control.",
        )
    _verify_same_origin(request)
    return user

