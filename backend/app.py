from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from io import BytesIO
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config
from .processor import ScanError
from .scanner import ScannerService
from .storage import current_background_path, lantern_count, list_lanterns, recent_lanterns

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("lantern.app")

scanner = ScannerService()
scan_lock = asyncio.Lock()


class Manager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.discard(websocket)

    async def broadcast(self, payload):
        dead = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


manager = Manager()


@asynccontextmanager
async def lifespan(app):
    config.initialize_runtime_dirs()
    if not config.DISABLE_CAMERA:
        scanner.start()
    try:
        yield
    finally:
        if not config.DISABLE_CAMERA:
            scanner.stop()


app = FastAPI(title="Lantern Sky", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")
app.mount("/templates", StaticFiles(directory=str(config.PRINT_DIR)), name="templates")
app.mount(
    "/generated/lanterns",
    StaticFiles(directory=str(config.LANTERNS_DIR), check_dir=False),
    name="lanterns",
)


def _background_url() -> str | None:
    path = current_background_path()
    if path is None:
        return None
    return f"/api/background/current?v={int(path.stat().st_mtime_ns)}"


@app.get("/")
def home():
    return FileResponse(config.FRONTEND_DIR / "control.html")


@app.get("/control")
def control():
    return FileResponse(config.FRONTEND_DIR / "control.html")


@app.get("/display")
def display():
    return FileResponse(config.FRONTEND_DIR / "display.html")


@app.get("/api/status")
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


@app.get("/api/camera/stream")
def stream():
    return StreamingResponse(
        scanner.mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/scan")
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

        url = f"/generated/lanterns/{result.lantern_path.name}"
        total_count = lantern_count()
        payload = {
            "type": "lantern_created",
            "id": result.id,
            "url": url,
            "variant": result.variant_key,
            "variantLabel": result.variant_label,
            "totalCount": total_count,
        }
        await manager.broadcast(payload)
        return {
            "ok": True,
            "id": result.id,
            "lanternUrl": url,
            "markerIds": result.marker_ids,
            "canonicalSize": list(result.canonical_size),
            "variant": result.variant_key,
            "variantLabel": result.variant_label,
            "quality": result.quality,
            "totalCount": total_count,
        }


@app.post("/api/demo")
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


@app.post("/api/background")
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
    await manager.broadcast({"type": "background_changed", "url": url})
    return {"ok": True, "url": url}


@app.get("/api/recent")
def recent(limit: int = 12):
    return recent_lanterns(limit)


@app.get("/api/lanterns")
def lanterns():
    return {"totalCount": lantern_count(), "lanterns": list_lanterns()}


@app.get("/api/display-state")
def display_state():
    lanterns = list_lanterns()
    return {
        "backgroundUrl": _background_url(),
        "lanterns": lanterns,
        "totalCount": len(lanterns),
    }


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
