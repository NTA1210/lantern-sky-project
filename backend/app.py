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
from .storage import (
    current_background_path,
    delete_all_lanterns,
    delete_lantern,
    delete_latest_lantern,
    delete_oldest_lantern,
    lantern_count,
    list_lanterns,
    recent_lanterns,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("lantern.app")

scanner = ScannerService()
scan_lock = asyncio.Lock()
sequential_delete_task: asyncio.Task | None = None
sequential_delete_active = False


async def _sequential_delete_worker():
    global sequential_delete_active, sequential_delete_task
    try:
        while sequential_delete_active:
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
            total_after = lantern_count()
            if oldest is not None:
                await manager.broadcast({
                    "type": "lantern_fading_out",
                    "id": oldest["id"],
                    "duration": 1.0,
                    "totalCount": total_after,
                })
                # If this was the last lantern on disk, sleep 1.0s for the fade-out animation to complete, then exit loop
                if total_after == 0:
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
    return FileResponse(config.FRONTEND_DIR / "control.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/control")
def control():
    return FileResponse(config.FRONTEND_DIR / "control.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/display")
def display():
    return FileResponse(config.FRONTEND_DIR / "display.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


from pydantic import BaseModel


class CameraSelectRequest(BaseModel):
    index: int


@app.get("/api/cameras")
def list_cameras():
    return {
        "current": config.CAMERA_INDEX,
        "cameras": scanner.get_available_cameras(),
    }


@app.post("/api/cameras/select")
def select_camera(payload: CameraSelectRequest):
    scanner.switch_camera(payload.index)
    return {"ok": True, "current": config.CAMERA_INDEX}


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


@app.post("/api/lanterns/sequential-delete/start")
async def start_sequential_delete():
    global sequential_delete_active, sequential_delete_task
    if sequential_delete_active and sequential_delete_task and not sequential_delete_task.done():
        return {"ok": True, "active": True, "message": "Đang chạy xóa lần lượt."}
    sequential_delete_active = True
    sequential_delete_task = asyncio.create_task(_sequential_delete_worker())
    await manager.broadcast({"type": "sequential_delete_started", "totalCount": lantern_count()})
    return {"ok": True, "active": True, "totalCount": lantern_count()}


@app.post("/api/lanterns/sequential-delete/stop")
async def stop_sequential_delete():
    global sequential_delete_active, sequential_delete_task
    sequential_delete_active = False
    if sequential_delete_task and not sequential_delete_task.done():
        sequential_delete_task.cancel()
    sequential_delete_task = None
    await manager.broadcast({"type": "sequential_delete_stopped", "totalCount": lantern_count()})
    return {"ok": True, "active": False, "totalCount": lantern_count()}


@app.get("/api/lanterns/sequential-delete/status")
def sequential_delete_status():
    return {"active": sequential_delete_active, "totalCount": lantern_count()}


@app.delete("/api/lanterns")
async def clear_all_lanterns():
    global sequential_delete_active, sequential_delete_task
    sequential_delete_active = False
    if sequential_delete_task and not sequential_delete_task.done():
        sequential_delete_task.cancel()
    deleted_count = delete_all_lanterns()
    await manager.broadcast({"type": "all_lanterns_fading_out", "duration": 1.0, "totalCount": 0})
    return {"ok": True, "deletedCount": deleted_count, "totalCount": 0}


@app.post("/api/lanterns/delete-latest")
async def remove_latest_lantern():
    record = delete_latest_lantern()
    if record is None:
        raise HTTPException(404, detail="Không có lồng đèn nào để xóa.")
    total = lantern_count()
    await manager.broadcast({
        "type": "lantern_fading_out",
        "id": record["id"],
        "duration": 1.0,
        "totalCount": total,
    })
    return {"ok": True, "deletedId": record["id"], "totalCount": total}


@app.delete("/api/lanterns/{scan_id}")
async def remove_single_lantern(scan_id: str):
    ok = delete_lantern(scan_id)
    if not ok:
        raise HTTPException(404, detail=f"Không tìm thấy lồng đèn: {scan_id}")
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
