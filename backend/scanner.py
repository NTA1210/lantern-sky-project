import atexit
import json
import logging
import platform
import subprocess
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from . import config
from .processor import LanternProcessor, ScanError

logger = logging.getLogger("lantern.scanner")


@dataclass
class ScannerStatus:
    camera_open: bool
    camera_index: int
    width: int
    height: int
    fps: float
    marker_ids: list[int]
    ready_to_scan: bool
    variant_key: str | None
    variant_label: str | None
    required_marker_ids: list[int]
    error: str | None


class ScannerService:
    def __init__(self):
        # OpenCV detector instances are owned by separate execution threads.
        # Preview detection runs on the camera thread; final scans run in a
        # FastAPI worker thread behind the API scan lock.
        self.preview_processor = LanternProcessor()
        self.scan_processor = LanternProcessor()
        self.cap = None
        self.thread = None
        self.running = False
        self.lock = threading.Lock()
        self.preview_condition = threading.Condition(self.lock)
        self.frame = None
        self.preview = None
        self.detected = {}
        self.error = None
        self.w = 0
        self.h = 0
        self.fps = 0.0
        self.camera_open = False
        self.flip_horizontal = config.load_settings().get("camera_flip_horizontal", False)
        atexit.register(self.stop)

    def __del__(self):
        self.stop()

    def set_flip_horizontal(self, value: bool) -> None:
        with self.lock:
            self.flip_horizontal = bool(value)

    @staticmethod
    def _backend_candidates():
        system = platform.system()
        if system == "Darwin":
            return [cv2.CAP_AVFOUNDATION, None]
        if system == "Windows":
            candidates = [cv2.CAP_DSHOW]
            if hasattr(cv2, "CAP_MSMF"):
                candidates.append(cv2.CAP_MSMF)
            candidates.append(None)
            return candidates
        if system == "Linux":
            return [cv2.CAP_V4L2, None]
        return [None]

    @staticmethod
    def _preview_frame(frame):
        height, width = frame.shape[:2]
        max_width = max(320, config.PREVIEW_MAX_WIDTH)
        if width <= max_width:
            return frame.copy()
        scale = max_width / width
        return cv2.resize(
            frame,
            (max_width, max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    def _open(self):
        for backend in self._backend_candidates():
            camera = (
                cv2.VideoCapture(config.CAMERA_INDEX)
                if backend is None
                else cv2.VideoCapture(config.CAMERA_INDEX, backend)
            )
            if not camera.isOpened():
                camera.release()
                continue

            if config.CAMERA_USE_MJPG:
                camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
            camera.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS)
            if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            valid_frame = False
            for _ in range(8):
                ok, frame = camera.read()
                if ok and frame is not None:
                    valid_frame = True
                    break
                time.sleep(.03)
            if not valid_frame:
                camera.release()
                continue

            logger.info("camera_opened index=%s backend=%s", config.CAMERA_INDEX, backend)
            return camera
        return None

    def _set_camera(self, camera) -> None:
        self.cap = camera
        with self.lock:
            self.camera_open = camera is not None and camera.isOpened()
            if self.camera_open:
                self.w = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                self.h = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                self.fps = float(camera.get(cv2.CAP_PROP_FPS) or 0)
            else:
                self.w = 0
                self.h = 0
                self.fps = 0.0
                self.frame = None
                self.preview = None
                self.detected = {}

    def _close_camera(self) -> None:
        camera = self.cap
        self.cap = None
        if camera is not None:
            camera.release()
        self._set_camera(None)

    def switch_camera(self, index: int) -> None:
        """Dynamically switch camera index and trigger reconnection."""
        logger.info("switching_camera to index=%s", index)
        with self.lock:
            config.CAMERA_INDEX = int(index)
            self.error = f"Đang chuyển sang Camera #{index}..."
            self.camera_open = False
        self._close_camera()

    @staticmethod
    def get_available_cameras(max_probe: int = 6) -> list[dict]:
        """Retrieve real camera device names from OS (macOS/Windows) or fallback."""
        cameras = []
        system = platform.system()

        if system == "Darwin":
            try:
                cmd = ["system_profiler", "-json", "SPCameraDataType"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    dev_list = data.get("SPCameraDataType", [])
                    for idx, dev in enumerate(dev_list):
                        name = dev.get("_name") or dev.get("spcamera_model-id") or f"Camera #{idx}"
                        is_active = (idx == config.CAMERA_INDEX)
                        cameras.append({
                            "index": idx,
                            "label": f"[{idx}] {name}{' — Đang dùng' if is_active else ''}",
                            "name": name,
                            "active": is_active,
                        })
            except Exception:
                logger.exception("system_profiler_camera_failed")

        elif system == "Windows":
            try:
                # Approach 1: Query Windows.Devices.Enumeration (VideoCapture device class)
                ps_cmd = (
                    "[Windows.Devices.Enumeration.DeviceInformation, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null; "
                    "[Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync([Windows.Devices.Enumeration.DeviceClass]::VideoCapture).GetAwaiter().GetResult() | "
                    "ForEach-Object { $_.Name }"
                )
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=3.5
                )
                lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]

                # Approach 2 fallback: PnP devices with class Camera or Image
                if not lines:
                    fallback_cmd = (
                        "Get-CimInstance Win32_PnPEntity | "
                        "Where-Object { $_.PNPClass -in @('Camera','Image') } | "
                        "ForEach-Object { $_.Caption }"
                    )
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", fallback_cmd],
                        capture_output=True, text=True, timeout=3.5
                    )
                    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]

                seen = set()
                unique_names = []
                for name in lines:
                    if name not in seen:
                        seen.add(name)
                        unique_names.append(name)

                for idx, name in enumerate(unique_names):
                    is_active = (idx == config.CAMERA_INDEX)
                    cameras.append({
                        "index": idx,
                        "label": f"[{idx}] {name}{' — Đang dùng' if is_active else ''}",
                        "name": name,
                        "active": is_active,
                    })
            except Exception:
                logger.exception("windows_camera_enum_failed")

        if not cameras:
            for idx in range(max_probe):
                is_active = (idx == config.CAMERA_INDEX)
                cameras.append({
                    "index": idx,
                    "label": f"Camera #{idx}{' — Đang dùng' if is_active else ''}",
                    "name": f"Camera #{idx}",
                    "active": is_active,
                })
        return cameras

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="lantern-camera")
        self.thread.start()

    def stop(self):
        self.running = False
        with self.lock:
            self.preview_condition.notify_all()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.5)
        self._close_camera()

    def _loop(self):
        read_failures = 0
        last_preview_at = 0.0
        preview_interval = 1.0 / max(1.0, config.PREVIEW_FPS)

        while self.running:
            if self.cap is None or not self.cap.isOpened():
                camera = self._open()
                if camera is None:
                    with self.lock:
                        self.error = (
                            f"Không mở được camera #{config.CAMERA_INDEX}. "
                            "Kiểm tra cáp/quyền Camera hoặc LANTERN_CAMERA_INDEX. Đang tự kết nối lại..."
                        )
                    self._set_camera(None)
                    time.sleep(config.CAMERA_RECONNECT_SECONDS)
                    continue
                self._set_camera(camera)
                with self.lock:
                    self.error = None
                read_failures = 0
                last_preview_at = 0.0

            ok, frame = self.cap.read()
            if not ok or frame is None:
                read_failures += 1
                with self.lock:
                    self.error = f"Camera không trả frame ({read_failures}/{config.CAMERA_READ_FAILURE_LIMIT})."
                if read_failures >= config.CAMERA_READ_FAILURE_LIMIT:
                    logger.warning("camera_read_failed index=%s; reopening", config.CAMERA_INDEX)
                    self._close_camera()
                    read_failures = 0
                    time.sleep(config.CAMERA_RECONNECT_SECONDS)
                else:
                    time.sleep(.08)
                continue

            read_failures = 0
            if self.flip_horizontal:
                frame = cv2.flip(frame, 1)

            with self.lock:
                # Keep the newest full-resolution frame for the final scan.
                self.frame = frame
                self.error = None
                self.camera_open = True

            now = time.monotonic()
            if now - last_preview_at < preview_interval:
                continue

            try:
                preview = self._preview_frame(frame)
                detected = self.preview_processor.detect(preview)
                preview = self._decorate(preview, detected)
                ok_jpeg, jpeg = cv2.imencode(
                    ".jpg",
                    preview,
                    [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_PREVIEW_QUALITY],
                )
                with self.lock:
                    self.detected = detected
                    self.preview = jpeg.tobytes() if ok_jpeg else None
                    self.error = None
                    self.camera_open = True
                    self.preview_condition.notify_all()
                last_preview_at = now
            except Exception as exc:
                logger.exception("camera_processing_error")
                with self.lock:
                    self.error = f"Camera processing error: {exc}"

    def _decorate(self, frame, detected):
        partial = self.preview_processor.identify_variant(detected, require_complete=False)
        complete = self.preview_processor.identify_variant(detected, require_complete=True)
        ready = complete is not None
        expected = partial.marker_ids if partial else ()
        color = (80, 220, 100) if ready else (40, 170, 255)

        for marker_id, points in detected.items():
            if marker_id not in range(16):
                continue
            poly = np.round(points).astype(np.int32).reshape((-1, 1, 2))
            marker_color = color if marker_id in expected else (160, 160, 160)
            cv2.polylines(frame, [poly], True, marker_color, 3, cv2.LINE_AA)
            x, y = np.round(points[0]).astype(int)
            cv2.putText(
                frame,
                f"ID {marker_id}",
                (x, max(30, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                .8,
                marker_color,
                2,
                cv2.LINE_AA,
            )

        if complete:
            text = f"READY - {complete.label} - press Scan"
        elif partial:
            found_count = len(set(detected).intersection(partial.marker_ids))
            text = f"{partial.label}: markers {found_count}/4 {list(partial.marker_ids)}"
        else:
            text = "Show all 4 template markers"
        cv2.putText(frame, text, (30, 50), cv2.FONT_HERSHEY_SIMPLEX, .9, color, 2, cv2.LINE_AA)
        return frame

    def get_status(self):
        with self.lock:
            marker_ids = sorted(self.detected)
            camera_open = self.camera_open
            width, height, fps = self.w, self.h, self.fps
            error = self.error
        complete = self.preview_processor.identify_variant(marker_ids, require_complete=True)
        partial = complete or self.preview_processor.identify_variant(marker_ids, require_complete=False)
        return ScannerStatus(
            camera_open=camera_open,
            camera_index=config.CAMERA_INDEX,
            width=width,
            height=height,
            fps=fps,
            marker_ids=marker_ids,
            ready_to_scan=complete is not None,
            variant_key=partial.key if partial else None,
            variant_label=partial.label if partial else None,
            required_marker_ids=list(partial.marker_ids) if partial else [],
            error=error,
        )

    def capture_and_process(self):
        best_candidate = None
        best_focus = -1.0

        # Sample up to 6 frames across ~250ms to ensure stability against single-frame shutter flutter
        for attempt in range(6):
            with self.lock:
                if self.frame is None:
                    raise ScanError("Chưa có frame từ camera.")
                frame = self.frame.copy()

            try:
                detected = self.scan_processor.detect(frame)
                variant = self.scan_processor.identify_variant(detected, require_complete=True)
                if variant is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    if focus > best_focus:
                        best_focus = focus
                        best_candidate = (frame, detected, variant)
                    # If we found a crisp frame on subsequent attempt, break early for fast responsiveness
                    if attempt >= 1 and best_candidate is not None:
                        break
            except Exception:
                pass

            time.sleep(0.04)

        if best_candidate is not None:
            frame, detected, variant = best_candidate
            return self.scan_processor.process(frame, precomputed_detected=detected, precomputed_variant=variant)

        # Fallback to single shot process on current frame (will raise specific ScanError)
        with self.lock:
            frame = self.frame.copy()
        return self.scan_processor.process(frame)

    def mjpeg_generator(self):
        last_frame = None
        while self.running:
            with self.preview_condition:
                self.preview_condition.wait_for(
                    lambda: not self.running or self.preview != last_frame,
                    timeout=0.2,
                )
                if not self.running:
                    break
                frame_bytes = self.preview
                last_frame = frame_bytes
            if frame_bytes:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
