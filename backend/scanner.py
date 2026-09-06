from __future__ import annotations

import logging
import platform
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
        self.processor = LanternProcessor()
        self.cap = None
        self.thread = None
        self.running = False
        self.lock = threading.Lock()
        self.frame = None
        self.preview = None
        self.detected = {}
        self.error = None
        self.w = 0
        self.h = 0
        self.fps = 0.0
        self.camera_open = False

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

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="lantern-camera")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.5)
        self._close_camera()

    def _loop(self):
        read_failures = 0
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
            try:
                detected = self.processor.detect(frame)
                preview = self._decorate(frame.copy(), detected)
                ok_jpeg, jpeg = cv2.imencode(
                    ".jpg",
                    preview,
                    [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_PREVIEW_QUALITY],
                )
                with self.lock:
                    self.frame = frame
                    self.detected = detected
                    self.preview = jpeg.tobytes() if ok_jpeg else None
                    self.error = None
                    self.camera_open = True
            except Exception as exc:
                logger.exception("camera_processing_error")
                with self.lock:
                    self.error = f"Camera processing error: {exc}"

    def _decorate(self, frame, detected):
        partial = self.processor.identify_variant(detected, require_complete=False)
        complete = self.processor.identify_variant(detected, require_complete=True)
        ready = complete is not None
        expected = partial.marker_ids if partial else ()
        color = (80, 220, 100) if ready else (40, 170, 255)

        for marker_id, points in detected.items():
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
        complete = self.processor.identify_variant(marker_ids, require_complete=True)
        partial = complete or self.processor.identify_variant(marker_ids, require_complete=False)
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
        with self.lock:
            if self.frame is None:
                raise ScanError("Chưa có frame từ camera.")
            frame = self.frame.copy()
        return self.processor.process(frame)

    def mjpeg_generator(self):
        while self.running:
            with self.lock:
                preview = self.preview
            if preview:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + preview + b"\r\n"
            time.sleep(1 / 24)
