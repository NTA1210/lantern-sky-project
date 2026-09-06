from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from . import config
from .layout import LanternVariant, create_lantern_mask, expected_marker_corners, identify_variant, lantern_roi
from .storage import atomic_imwrite, prune_scan_storage

logger = logging.getLogger("lantern.processor")


class ScanError(RuntimeError):
    pass


@dataclass
class ProcessResult:
    id: str
    lantern_path: Path
    marker_ids: list[int]
    canonical_size: tuple[int, int]
    variant_key: str
    variant_label: str
    quality: dict
    original_path: Path | None = None
    corrected_path: Path | None = None


class LanternProcessor:
    def __init__(self):
        self.dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, params)

    def detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        found = {}
        if ids is not None:
            for corner, marker_id in zip(corners, ids.flatten().tolist()):
                found[int(marker_id)] = corner.reshape(4, 2).astype(np.float32)
        return found

    @staticmethod
    def identify_variant(detected, require_complete: bool = True) -> LanternVariant | None:
        marker_ids = detected.keys() if hasattr(detected, "keys") else detected
        return identify_variant(marker_ids, require_complete=require_complete)

    def rectify(self, frame, detected, variant: LanternVariant):
        missing = [marker_id for marker_id in variant.marker_ids if marker_id not in detected]
        if missing:
            raise ScanError("Không thấy đủ 4 marker. Thiếu: " + ",".join(map(str, missing)))

        width, height = config.CANONICAL_WIDTH, config.CANONICAL_HEIGHT
        expected = expected_marker_corners(width, height, variant.marker_ids)
        src = []
        dst = []
        for marker_id in variant.marker_ids:
            src += detected[marker_id].tolist()
            dst += expected[marker_id].tolist()

        src_array = np.asarray(src, np.float32)
        dst_array = np.asarray(dst, np.float32)
        homography, inlier_mask = cv2.findHomography(src_array, dst_array, cv2.RANSAC, 3.0)
        if homography is None:
            raise ScanError("Không tính được perspective transform.")
        if inlier_mask is not None and int(inlier_mask.sum()) < 10:
            raise ScanError("Góc chụp quá méo hoặc marker không ổn định. Hãy đặt giấy phẳng và thử lại.")

        rectified = cv2.warpPerspective(
            frame,
            homography,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        return rectified

    @staticmethod
    def gentle_white_balance(img):
        height, width = img.shape[:2]
        patch = img[round(height * .055):round(height * .115), round(width * .34):round(width * .66)]
        if not patch.size:
            return img
        bright = np.min(patch, axis=2) > 150
        if np.count_nonzero(bright) < 100:
            return img
        means = patch[bright].astype(np.float32).mean(axis=0)
        gains = np.clip(242.0 / np.maximum(means, 1), .86, 1.18)
        return np.clip(img.astype(np.float32) * gains.reshape(1, 1, 3), 0, 255).astype(np.uint8)

    @staticmethod
    def assess_quality(frame, detected, variant: LanternVariant) -> dict:
        height, width = frame.shape[:2]
        scale = min(1.0, 720.0 / max(width, 1))
        sample = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        focus_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        frame_area = max(1.0, float(width * height))
        marker_areas = [abs(float(cv2.contourArea(detected[mid]))) / frame_area for mid in variant.marker_ids if mid in detected]
        marker_area = float(np.mean(marker_areas)) if marker_areas else 0.0
        warnings = []
        if focus_score < 35:
            warnings.append("Ảnh hơi mờ; giữ giấy/camera ổn định hoặc tăng ánh sáng.")
        if brightness < 45:
            warnings.append("Khung hình khá tối; nên tăng ánh sáng mềm.")
        elif brightness > 225:
            warnings.append("Khung hình quá sáng; tránh cháy sáng trên giấy.")
        if marker_area < .00045:
            warnings.append("Template đang khá xa camera; đưa giấy gần hơn để tăng độ chi tiết.")
        return {
            "focusScore": round(focus_score, 1),
            "brightness": round(brightness, 1),
            "markerAreaRatio": round(marker_area, 6),
            "warnings": warnings,
        }

    @staticmethod
    def extract_lantern(rectified, variant_key: str):
        height, width = rectified.shape[:2]
        x1, y1, x2, y2 = lantern_roi(width, height, variant_key)
        crop = rectified[y1:y2, x1:x2].copy()
        alpha = create_lantern_mask(crop.shape[1], crop.shape[0], variant_key, 4)
        out = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        out[:, :, 3] = alpha
        out[alpha == 0, 0:3] = 255
        return out

    def process(self, frame):
        started = time.perf_counter()
        detected = self.detect(frame)
        variant = self.identify_variant(detected, require_complete=True)
        if variant is None:
            partial = self.identify_variant(detected, require_complete=False)
            if partial:
                missing = [mid for mid in partial.marker_ids if mid not in detected]
                raise ScanError(f"Template {partial.label}: thiếu marker {', '.join(map(str, missing))}.")
            raise ScanError("Không nhận diện được template lồng đèn. Hãy đảm bảo đủ 4 marker nằm trong khung hình.")

        quality = self.assess_quality(frame, detected, variant)
        rectified = self.gentle_white_balance(self.rectify(frame, detected, variant))
        lantern = self.extract_lantern(rectified, variant.key)

        scan_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        lantern_path = config.LANTERNS_DIR / f"{scan_id}.png"
        atomic_imwrite(lantern_path, lantern, [cv2.IMWRITE_PNG_COMPRESSION, config.PNG_COMPRESSION])

        original_path = None
        corrected_path = None
        if config.KEEP_DIAGNOSTICS:
            original_path = config.ORIGINAL_DIR / f"{scan_id}.jpg"
            corrected_path = config.CORRECTED_DIR / f"{scan_id}.png"
            atomic_imwrite(original_path, frame, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_MASTER_QUALITY])
            atomic_imwrite(corrected_path, rectified, [cv2.IMWRITE_PNG_COMPRESSION, config.PNG_COMPRESSION])

        prune_scan_storage()
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "scan_completed id=%s variant=%s duration_ms=%s focus=%s",
            scan_id,
            variant.key,
            duration_ms,
            quality["focusScore"],
        )
        quality["processingMs"] = duration_ms
        return ProcessResult(
            id=scan_id,
            lantern_path=lantern_path,
            marker_ids=sorted(detected),
            canonical_size=(rectified.shape[1], rectified.shape[0]),
            variant_key=variant.key,
            variant_label=variant.label,
            quality=quality,
            original_path=original_path,
            corrected_path=corrected_path,
        )
