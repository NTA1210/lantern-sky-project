from __future__ import annotations

from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2

from backend import config


def backends():
    system = platform.system()
    if system == "Darwin":
        return [("AVFoundation", cv2.CAP_AVFOUNDATION), ("Default", None)]
    if system == "Windows":
        values = [("DirectShow", cv2.CAP_DSHOW)]
        if hasattr(cv2, "CAP_MSMF"):
            values.append(("Media Foundation", cv2.CAP_MSMF))
        values.append(("Default", None))
        return values
    if system == "Linux":
        return [("V4L2", cv2.CAP_V4L2), ("Default", None)]
    return [("Default", None)]


def probe(index: int):
    for backend_name, backend in backends():
        camera = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
        try:
            if not camera.isOpened():
                continue
            ok, frame = camera.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            fps = float(camera.get(cv2.CAP_PROP_FPS) or 0)
            return backend_name, width, height, fps
        finally:
            camera.release()
    return None


def main():
    print("Lantern Sky camera probe")
    print("------------------------")
    found = 0
    for index in range(config.CAMERA_PROBE_MAX):
        result = probe(index)
        if result is None:
            continue
        backend_name, width, height, fps = result
        found += 1
        print(f"Camera #{index}: {width}x{height} @ {fps:.0f} FPS via {backend_name}")
    if found == 0:
        print("Không tìm thấy camera nào. Kiểm tra cáp, USB Streaming/capture card và quyền Camera.")
    else:
        print("\nChọn camera bằng biến LANTERN_CAMERA_INDEX. Ví dụ: LANTERN_CAMERA_INDEX=1 ./run_mac.sh")


if __name__ == "__main__":
    main()
