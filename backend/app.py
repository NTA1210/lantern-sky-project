from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from io import BytesIO
from urllib.parse import parse_qs, quote
from uuid import uuid4

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from . import auth, config, db
from .processor import ScanError
from .scanner import ScannerService
from .storage import (
    current_background_path,
    delete_all_lanterns,
    delete_lantern,
    delete_latest_lantern,
    delete_oldest_lantern,
    delete_oldest_lanterns,
    lantern_count,
    list_lanterns,
    recent_lanterns,
    sync_storage_with_db,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("lantern.app")

scanner = ScannerService()
scan_lock = asyncio.Lock()
sequential_delete_task: asyncio.Task | None = None
sequential_delete_active = False
_display_state_cache: dict | None = None


def invalidate_display_state_cache() -> None:
    global _display_state_cache
    _display_state_cache = None


class ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


async def _sequential_delete_worker(max_count: int | None = None):
    global sequential_delete_active, sequential_delete_task
    deleted_so_far = 0
    try:
        while sequential_delete_active:
            if max_count is not None and deleted_so_far >= max_count:
                break

            total_before = lantern_count()
            if total_before == 0:
                # No files on disk, tell Display to pop any in-memory/demo lantern
                await manager.broadcast({
                    "type": "pop_oldest_lantern",
                    "duration": 1.0,
                    "totalCount": 0,
                })
                await asyncio.sleep(1.0)
                break

            oldest = delete_oldest_lantern()
            invalidate_display_state_cache()
            total_after = lantern_count()
            if oldest is not None:
                deleted_so_far += 1
                await manager.broadcast({
                    "type": "lantern_fading_out",
                    "id": oldest["id"],
                    "duration": 1.0,
                    "totalCount": total_after,
                })
                # If this was the last lantern on disk or reached max_count, sleep 1.0s for the fade-out animation to complete, then exit loop
                if total_after == 0 or (max_count is not None and deleted_so_far >= max_count):
                    await asyncio.sleep(1.0)
                    break
                await asyncio.sleep(1.0)
            else:
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("sequential_delete_error")
    finally:
        sequential_delete_active = False
        sequential_delete_task = None
        await manager.broadcast({
            "type": "sequential_delete_completed",
            "totalCount": lantern_count(),
        })


class Manager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> bool:
        if len(self.connections) >= config.MAX_WS_CONNECTIONS:
            await websocket.close(code=1013, reason="Server busy")
            return False
        await websocket.accept()
        self.connections.add(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def broadcast(self, payload):
        targets = list(self.connections)
        if not targets:
            return

        async def _send_one(ws: WebSocket):
            try:
                await asyncio.wait_for(ws.send_json(payload), timeout=2.5)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*(_send_one(ws) for ws in targets), return_exceptions=True)
        for item in results:
            if isinstance(item, WebSocket):
                self.disconnect(item)


manager = Manager()


@asynccontextmanager
async def lifespan(app):
    config.initialize_runtime_dirs()
    db.ensure_schema()
    sync_storage_with_db()
    auth.ensure_credentials_initialized()
    if not config.DISABLE_CAMERA:
        scanner.start()
    try:
        yield
    finally:
        if not config.DISABLE_CAMERA:
            scanner.stop()


app = FastAPI(title="Lantern Sky", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self)")
    return response


app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")
app.mount("/templates", StaticFiles(directory=str(config.PRINT_DIR)), name="templates")
app.mount(
    "/generated/lanterns",
    ImmutableStaticFiles(directory=str(config.LANTERNS_DIR), check_dir=False),
    name="lanterns",
)
app.mount(
    "/generated/thumbs",
    ImmutableStaticFiles(directory=str(config.THUMBS_DIR), check_dir=False),
    name="thumbs",
)


def _background_url() -> str | None:
    path = current_background_path()
    if path is None:
        return None
    return f"/api/background/current?v={int(path.stat().st_mtime_ns)}"


_NO_STORE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "X-Frame-Options": "SAMEORIGIN",
}


def _serve_control_or_login(request: Request):
    if auth.get_authenticated_user(request) is None:
        return RedirectResponse(url="/login?next=/control", status_code=303, headers=_NO_STORE_HEADERS)
    return FileResponse(config.FRONTEND_DIR / "control.html", headers=_NO_STORE_HEADERS)


@app.get("/")
def home(request: Request):
    return _serve_control_or_login(request)


@app.get("/control")
def control(request: Request):
    return _serve_control_or_login(request)


@app.get("/login")
def login_page(request: Request, next: str | None = None):
    safe_next = auth.sanitize_next_url(next)
    if auth.get_authenticated_user(request) is not None:
        return RedirectResponse(url=safe_next, status_code=303, headers=_NO_STORE_HEADERS)
    return FileResponse(config.FRONTEND_DIR / "login.html", headers=_NO_STORE_HEADERS)


@app.get("/display")
def display():
    return FileResponse(config.FRONTEND_DIR / "display.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/favicon.ico")
def favicon():
    icon_path = config.FRONTEND_DIR / "favicon.ico"
    if icon_path.exists():
        return FileResponse(icon_path, media_type="image/x-icon")
    return FileResponse(config.FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")


from pydantic import BaseModel


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CameraSelectRequest(BaseModel):
    index: int


class SettingsUpdateRequest(BaseModel):
    conveyor_speed: float | None = None
    sway_amplitude: float | None = None
    sway_speed: float | None = None
    auto_scan_seconds: float | None = None
    camera_flip_horizontal: bool | None = None
    scan_quality_threshold: float | None = None


@app.get("/api/auth/status")
def auth_status(request: Request):
    user = auth.get_authenticated_user(request)
    return JSONResponse(
        {
            "authenticated": user is not None,
            "username": user,
            "envManaged": auth.is_env_managed(),
            "authDisabled": config.AUTH_DISABLED,
        },
        headers=_NO_STORE_HEADERS,
    )


@app.post("/api/auth/login")
async def auth_login(request: Request):
    client_ip = auth.get_client_ip(request)
    retry_after = auth.login_rate_limiter.check_allowed(client_ip)

    content_type = request.headers.get("content-type", "").lower()
    is_json = "application/json" in content_type
    raw_body = await request.body()

    username = ""
    password = ""
    next_url = None
    if is_json:
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:
            raise HTTPException(400, detail="Dữ liệu đăng nhập không hợp lệ.") from exc
        if isinstance(payload, dict):
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
            next_url = payload.get("next")
    else:
        parsed = parse_qs(raw_body.decode("utf-8", errors="ignore"), keep_blank_values=True)
        username = (parsed.get("username") or [""])[0]
        password = (parsed.get("password") or [""])[0]
        next_url = (parsed.get("next") or [None])[0]

    safe_next = auth.sanitize_next_url(next_url)

    if retry_after > 0:
        if is_json:
            return JSONResponse(
                {"detail": f"Bạn đã thử sai quá nhiều lần. Vui lòng đợi {retry_after} giây."},
                status_code=429,
                headers={**_NO_STORE_HEADERS, "Retry-After": str(retry_after)},
            )
        return RedirectResponse(
            url=f"/login?error=ratelimit&retry={retry_after}&next={quote(safe_next)}",
            status_code=303,
            headers=_NO_STORE_HEADERS,
        )

    if config.AUTH_DISABLED or auth.verify_credentials(username, password):
        auth.login_rate_limiter.reset(client_ip)
        effective_user = config.CONTROL_USER if config.AUTH_DISABLED else username.strip()
        if is_json:
            resp = JSONResponse(
                {"ok": True, "username": effective_user, "redirectTo": safe_next},
                headers=_NO_STORE_HEADERS,
            )
        else:
            resp = RedirectResponse(url=safe_next, status_code=303, headers=_NO_STORE_HEADERS)
        auth.set_session_cookie(resp, request, effective_user)
        return resp

    auth.login_rate_limiter.record_failure(client_ip)
    if is_json:
        return JSONResponse(
            {"detail": "Sai tên đăng nhập hoặc mật khẩu."},
            status_code=401,
            headers=_NO_STORE_HEADERS,
        )
    return RedirectResponse(
        url=f"/login?error=invalid&next={quote(safe_next)}",
        status_code=303,
        headers=_NO_STORE_HEADERS,
    )


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    accepts_html = "text/html" in request.headers.get("accept", "").lower() and "application/json" not in request.headers.get("accept", "").lower()
    if accepts_html and "application/json" not in request.headers.get("content-type", "").lower():
        resp: JSONResponse | RedirectResponse = RedirectResponse(url="/login", status_code=303, headers=_NO_STORE_HEADERS)
    else:
        resp = JSONResponse({"ok": True}, headers=_NO_STORE_HEADERS)
    auth.clear_session_cookie(resp, request)
    return resp


@app.post("/api/auth/change-password")
def auth_change_password(
    payload: ChangePasswordRequest,
    request: Request,
    _user: str = Depends(auth.require_control_api),
):
    username = auth.change_stored_password(payload.current_password, payload.new_password)
    resp = JSONResponse({"ok": True, "message": "Đã cập nhật mật khẩu thành công."}, headers=_NO_STORE_HEADERS)
    auth.set_session_cookie(resp, request, username)
    return resp


@app.get("/healthz")
def healthz():
    try:
        db_ok = db.ping()
    except Exception:
        db_ok = False
    return JSONResponse(
        {
            "ok": db_ok,
            "db": "ok" if db_ok else "error",
            "lanternCount": lantern_count() if db_ok else 0,
            "wsConnections": len(manager.connections),
        },
        status_code=200 if db_ok else 503,
        headers=_NO_STORE_HEADERS,
    )


@app.get("/api/settings", dependencies=[Depends(auth.require_control_api)])
def get_settings():
    return db.load_settings_db()


@app.post("/api/settings", dependencies=[Depends(auth.require_control_api)])
async def update_settings(payload: SettingsUpdateRequest):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    saved = db.save_settings_db(updates)
    invalidate_display_state_cache()
    if "camera_flip_horizontal" in updates:
        scanner.set_flip_horizontal(updates["camera_flip_horizontal"])
    await manager.broadcast({"type": "settings_updated", "settings": saved})
    return {"ok": True, "settings": saved}


@app.post("/api/settings/reset", dependencies=[Depends(auth.require_control_api)])
async def reset_settings():
    saved = db.save_settings_db(config.DEFAULT_SETTINGS)
    invalidate_display_state_cache()
    scanner.set_flip_horizontal(config.DEFAULT_SETTINGS.get("camera_flip_horizontal", False))
    await manager.broadcast({"type": "settings_updated", "settings": saved})
    return {"ok": True, "settings": saved}


@app.get("/api/cameras", dependencies=[Depends(auth.require_control_api)])
def list_cameras():
    return {
        "current": config.CAMERA_INDEX,
        "cameras": scanner.get_available_cameras(),
    }


@app.post("/api/cameras/select", dependencies=[Depends(auth.require_control_api)])
def select_camera(payload: CameraSelectRequest):
    scanner.switch_camera(payload.index)
    return {"ok": True, "current": config.CAMERA_INDEX}


@app.get("/api/status", dependencies=[Depends(auth.require_control_api)])
def status():
    current = scanner.get_status()
    return {
        "cameraOpen": current.camera_open,
        "cameraIndex": current.camera_index,
        "resolution": [current.width, current.height],
        "requestedResolution": [config.CAMERA_WIDTH, config.CAMERA_HEIGHT],
        "fps": current.fps,
        "markerIds": current.marker_ids,
        "requiredMarkerIds": current.required_marker_ids,
        "readyToScan": current.ready_to_scan,
        "variant": current.variant_key,
        "variantLabel": current.variant_label,
        "error": current.error,
    }


@app.get("/api/camera/stream", dependencies=[Depends(auth.require_control_api)])
def stream():
    return StreamingResponse(
        scanner.mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


async def _read_bounded_bytes(request: Request, max_bytes: int, empty_msg: str, too_large_msg: str) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, detail=too_large_msg)
        except ValueError:
            pass

    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > max_bytes:
            raise HTTPException(413, detail=too_large_msg)
        data.extend(chunk)
    if not data:
        raise HTTPException(400, detail=empty_msg)
    return bytes(data)


def _decode_image_to_bgr(data: bytes, max_pixels: int) -> np.ndarray:
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > max_pixels:
                raise HTTPException(413, detail="Độ phân giải ảnh quá lớn.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            rgb = np.asarray(image)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, detail="File này không phải ảnh hợp lệ.") from exc


async def _finalize_scan_result(result):
    invalidate_display_state_cache()
    full_url = f"/generated/lanterns/{result.lantern_path.name}"
    display_url = result.display_url or full_url
    total_count = lantern_count()
    payload = {
        "type": "lantern_created",
        "id": result.id,
        "url": display_url,
        "fullUrl": full_url,
        "variant": result.variant_key,
        "variantLabel": result.variant_label,
        "totalCount": total_count,
    }
    await manager.broadcast(payload)
    return {
        "ok": True,
        "id": result.id,
        "lanternUrl": display_url,
        "fullUrl": full_url,
        "markerIds": result.marker_ids,
        "canonicalSize": list(result.canonical_size),
        "variant": result.variant_key,
        "variantLabel": result.variant_label,
        "quality": result.quality,
        "totalCount": total_count,
    }


@app.post("/api/scan", dependencies=[Depends(auth.require_control_api)])
async def scan():
    if scan_lock.locked():
        raise HTTPException(409, detail="Scanner đang xử lý một lồng đèn khác. Vui lòng đợi vài giây.")

    async with scan_lock:
        try:
            result = await asyncio.to_thread(scanner.capture_and_process)
        except ScanError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("scan_failed")
            raise HTTPException(500, detail="Scan failed. Xem log trên máy Control để biết chi tiết.") from exc

        return await _finalize_scan_result(result)


@app.post("/api/scan/detect", dependencies=[Depends(auth.require_control_api)])
async def scan_detect(request: Request):
    raw = await _read_bounded_bytes(
        request,
        max_bytes=5 * 1024 * 1024,
        empty_msg="Chưa có dữ liệu khung hình.",
        too_large_msg="Khung hình preview quá lớn.",
    )
    frame = await asyncio.to_thread(_decode_image_to_bgr, raw, config.MAX_SCAN_PIXELS)
    detected = await asyncio.to_thread(scanner.preview_processor.detect, frame)
    marker_ids = sorted(detected)
    complete = scanner.preview_processor.identify_variant(marker_ids, require_complete=True)
    partial = complete or scanner.preview_processor.identify_variant(marker_ids, require_complete=False)
    return {
        "markerIds": marker_ids,
        "requiredMarkerIds": list(partial.marker_ids) if partial else [],
        "readyToScan": complete is not None,
        "variant": partial.key if partial else None,
        "variantLabel": partial.label if partial else None,
    }


@app.post("/api/scan/upload", dependencies=[Depends(auth.require_control_api)])
async def scan_upload(request: Request):
    if scan_lock.locked():
        raise HTTPException(409, detail="Scanner đang xử lý một lồng đèn khác. Vui lòng đợi vài giây.")

    raw = await _read_bounded_bytes(
        request,
        max_bytes=config.MAX_SCAN_UPLOAD_BYTES,
        empty_msg="Chưa có dữ liệu ảnh để scan.",
        too_large_msg="Ảnh quá lớn. Vui lòng chọn ảnh dưới 20MB.",
    )
    frame = await asyncio.to_thread(_decode_image_to_bgr, raw, config.MAX_SCAN_PIXELS)

    async with scan_lock:
        try:
            min_quality = float(db.load_settings_db().get("scan_quality_threshold", 65))
            result = await asyncio.to_thread(
                scanner.scan_processor.process,
                frame,
                None,
                None,
                min_quality,
            )
        except ScanError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("scan_upload_failed")
            raise HTTPException(500, detail="Scan failed. Xem log trên máy chủ để biết chi tiết.") from exc

        return await _finalize_scan_result(result)


@app.post("/api/demo", dependencies=[Depends(auth.require_control_api)])
async def demo():
    demo_id = f"demo-{uuid4().hex[:8]}"
    await manager.broadcast(
        {
            "type": "lantern_created",
            "id": demo_id,
            "url": "/static/sample_lantern.png",
            "variant": "classic",
            "variantLabel": "Classic",
            "demo": True,
            "totalCount": lantern_count(),
        }
    )
    return {"ok": True, "id": demo_id}


@app.get("/api/background/current")
def background_current():
    path = current_background_path()
    if path is None:
        raise HTTPException(404, detail="Chưa có background tùy chỉnh.")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@app.post("/api/background", dependencies=[Depends(auth.require_control_api)])
async def background(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > config.MAX_BACKGROUND_BYTES:
                raise HTTPException(413, detail="Ảnh quá lớn. Vui lòng chọn ảnh dưới 20MB.")
        except ValueError:
            pass

    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > config.MAX_BACKGROUND_BYTES:
            raise HTTPException(413, detail="Ảnh quá lớn. Vui lòng chọn ảnh dưới 20MB.")
        data.extend(chunk)
    if not data:
        raise HTTPException(400, detail="Chưa chọn file ảnh.")

    try:
        with Image.open(BytesIO(data)) as source:
            fmt = (source.format or "").lower()
            if source.width * source.height > config.MAX_BACKGROUND_PIXELS:
                raise HTTPException(413, detail="Độ phân giải ảnh nền quá lớn.")
            image = ImageOps.exif_transpose(source)
            image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, detail="File này không phải ảnh hợp lệ.") from exc

    ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}.get(fmt)
    if ext is None:
        raise HTTPException(400, detail="Chỉ hỗ trợ JPG, PNG hoặc WEBP.")

    config.BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    temp = config.BACKGROUND_DIR / f".upload-{uuid4().hex}.{ext}"
    final = config.BACKGROUND_DIR / f"current.{ext}"
    try:
        if ext == "jpg":
            image.convert("RGB").save(temp, format="JPEG", quality=92, optimize=True)
        elif ext == "png":
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            image.convert(mode).save(temp, format="PNG", optimize=True)
        else:
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            image.convert(mode).save(temp, format="WEBP", quality=92, method=4)
        os.replace(temp, final)
    except Exception as exc:
        temp.unlink(missing_ok=True)
        logger.exception("background_write_failed")
        raise HTTPException(500, detail="Không thể lưu ảnh nền.") from exc

    for old in config.BACKGROUND_DIR.glob("current.*"):
        if old != final and old.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            old.unlink(missing_ok=True)

    url = _background_url()
    invalidate_display_state_cache()
    await manager.broadcast({"type": "background_changed", "url": url})
    return {"ok": True, "url": url}


@app.delete("/api/background", dependencies=[Depends(auth.require_control_api)])
async def reset_background():
    for old in config.BACKGROUND_DIR.glob("current.*"):
        old.unlink(missing_ok=True)
    invalidate_display_state_cache()
    await manager.broadcast({"type": "background_changed", "url": None})
    return {"ok": True, "url": None}


@app.get("/api/recent", dependencies=[Depends(auth.require_control_api)])
def recent(limit: int = 12):
    return recent_lanterns(limit)


@app.get("/api/lanterns", dependencies=[Depends(auth.require_control_api)])
def lanterns():
    return {"totalCount": lantern_count(), "lanterns": list_lanterns()}


class SequentialDeleteRequest(BaseModel):
    count: int | None = None


@app.post("/api/lanterns/sequential-delete/start", dependencies=[Depends(auth.require_control_api)])
async def start_sequential_delete(payload: SequentialDeleteRequest | None = None):
    global sequential_delete_active, sequential_delete_task
    max_count = payload.count if (payload and payload.count and payload.count > 0) else None
    if sequential_delete_active and sequential_delete_task and not sequential_delete_task.done():
        return {"ok": True, "active": True, "message": "Đang chạy xóa lần lượt.", "maxCount": max_count}
    sequential_delete_active = True
    sequential_delete_task = asyncio.create_task(_sequential_delete_worker(max_count=max_count))
    await manager.broadcast({
        "type": "sequential_delete_started",
        "totalCount": lantern_count(),
        "maxCount": max_count,
    })
    return {"ok": True, "active": True, "totalCount": lantern_count(), "maxCount": max_count}


@app.post("/api/lanterns/sequential-delete/stop", dependencies=[Depends(auth.require_control_api)])
async def stop_sequential_delete():
    global sequential_delete_active, sequential_delete_task
    sequential_delete_active = False
    if sequential_delete_task and not sequential_delete_task.done():
        sequential_delete_task.cancel()
    sequential_delete_task = None
    await manager.broadcast({"type": "sequential_delete_stopped", "totalCount": lantern_count()})
    return {"ok": True, "active": False, "totalCount": lantern_count()}


@app.get("/api/lanterns/sequential-delete/status", dependencies=[Depends(auth.require_control_api)])
def sequential_delete_status():
    return {"active": sequential_delete_active, "totalCount": lantern_count()}


@app.delete("/api/lanterns", dependencies=[Depends(auth.require_control_api)])
async def clear_all_lanterns(count: int | None = None):
    global sequential_delete_active, sequential_delete_task
    sequential_delete_active = False
    if sequential_delete_task and not sequential_delete_task.done():
        sequential_delete_task.cancel()
    
    total = lantern_count()
    if count is None or count <= 0 or count >= total:
        deleted_count = delete_all_lanterns()
        invalidate_display_state_cache()
        await manager.broadcast({"type": "all_lanterns_fading_out", "duration": 1.0, "totalCount": 0})
        return {"ok": True, "deletedCount": deleted_count, "totalCount": 0}
    else:
        deleted_records = delete_oldest_lanterns(count)
        invalidate_display_state_cache()
        remaining = lantern_count()
        deleted_ids = [r["id"] for r in deleted_records]
        await manager.broadcast({
            "type": "batch_lanterns_fading_out",
            "ids": deleted_ids,
            "duration": 1.0,
            "totalCount": remaining,
        })
        return {"ok": True, "deletedCount": len(deleted_records), "totalCount": remaining}


@app.post("/api/lanterns/delete-latest", dependencies=[Depends(auth.require_control_api)])
async def remove_latest_lantern():
    record = delete_latest_lantern()
    if record is None:
        raise HTTPException(404, detail="Không có lồng đèn nào để xóa.")
    invalidate_display_state_cache()
    total = lantern_count()
    await manager.broadcast({
        "type": "lantern_fading_out",
        "id": record["id"],
        "duration": 1.0,
        "totalCount": total,
    })
    return {"ok": True, "deletedId": record["id"], "totalCount": total}


@app.delete("/api/lanterns/{scan_id}", dependencies=[Depends(auth.require_control_api)])
async def remove_single_lantern(scan_id: str):
    ok = delete_lantern(scan_id)
    if not ok:
        raise HTTPException(404, detail=f"Không tìm thấy lồng đèn: {scan_id}")
    invalidate_display_state_cache()
    total = lantern_count()
    await manager.broadcast({
        "type": "lantern_fading_out",
        "id": scan_id,
        "duration": 1.0,
        "totalCount": total,
    })
    return {"ok": True, "deletedId": scan_id, "totalCount": total}


@app.get("/api/display-state")
def display_state():
    global _display_state_cache
    if _display_state_cache is None:
        lanterns = list_lanterns()
        _display_state_cache = {
            "backgroundUrl": _background_url(),
            "lanterns": lanterns,
            "totalCount": len(lanterns),
            "settings": db.load_settings_db(),
        }
    return JSONResponse(_display_state_cache, headers={"Cache-Control": "no-cache"})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    accepted = await manager.connect(websocket)
    if not accepted:
        return
    try:
        while True:
            text = await asyncio.wait_for(websocket.receive_text(), timeout=90.0)
            if text == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
