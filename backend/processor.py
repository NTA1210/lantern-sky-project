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
from .storage import atomic_imwrite, lantern_filename

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


# The system only uses markers 0..15 across the 4 templates
VALID_TEMPLATE_MARKER_IDS = set(range(16))


class LanternProcessor:
    def __init__(self):
        self.dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        params.adaptiveThreshWinSizeMin = 3
        params.adaptiveThreshWinSizeMax = 23
        params.adaptiveThreshWinSizeStep = 10
        params.adaptiveThreshConstant = 7.0
        params.minMarkerPerimeterRate = 0.025
        params.maxMarkerPerimeterRate = 4.0
        params.polygonalApproxAccuracyRate = 0.03
        params.minCornerDistanceRate = 0.05
        params.minDistanceToBorder = 3
        params.perspectiveRemovePixelPerCell = 4
        params.perspectiveRemoveIgnoredMarginPerCell = 0.13
        params.maxErroneousBitsInBorderRate = 0.25
        params.errorCorrectionRate = 0.5
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, params)

    def detect(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        found = {}
        if ids is not None:
            for corner, marker_id in zip(corners, ids.flatten().tolist()):
                mid = int(marker_id)
                if mid in VALID_TEMPLATE_MARKER_IDS:
                    pts = corner.reshape(4, 2).astype(np.float32)
                    if cv2.isContourConvex(pts.astype(np.int32)) and cv2.contourArea(pts) > 100:
                        found[mid] = pts

        complete = self.identify_variant(found, require_complete=True)
        if complete is not None:
            return found

        # Fallback for mirrored/flipped camera feeds (ArUco bit matrices are non-symmetric)
        gray_flipped = cv2.flip(gray, 1)
        corners_f, ids_f, _ = self.detector.detectMarkers(gray_flipped)
        if ids_f is not None:
            width = frame.shape[1]
            for corner, marker_id in zip(corners_f, ids_f.flatten().tolist()):
                mid = int(marker_id)
                if mid in VALID_TEMPLATE_MARKER_IDS and mid not in found:
                    pts = corner.reshape(4, 2).astype(np.float32)
                    if cv2.isContourConvex(pts.astype(np.int32)) and cv2.contourArea(pts) > 100:
                        pts[:, 0] = (width - 1) - pts[:, 0]
                        # In mirrored frame, swap TL<->TR (0<->1) and BL<->BR (3<->2)
                        reordered = np.array([pts[1], pts[0], pts[3], pts[2]], dtype=np.float32)
                        found[mid] = reordered
        return found

    @staticmethod
    def identify_variant(detected, require_complete: bool = True) -> LanternVariant | None:
        marker_ids = detected.keys() if hasattr(detected, "keys") else detected
        return identify_variant(marker_ids, require_complete=require_complete)

    def rectify_extended(self, frame, detected, variant: LanternVariant):
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
        homography, inlier_mask = cv2.findHomography(src_array, dst_array, cv2.RANSAC, 6.0)
        if homography is None:
            raise ScanError("Không tính được perspective transform.")
        inlier_count = int(inlier_mask.sum()) if inlier_mask is not None else 16
        if inlier_count < 8:
            raise ScanError("Góc chụp quá méo hoặc marker không ổn định. Hãy đặt giấy phẳng và thử lại.")

        rectified = cv2.warpPerspective(
            frame,
            homography,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        return rectified, inlier_count

    def rectify(self, frame, detected, variant: LanternVariant):
        rectified, _ = self.rectify_extended(frame, detected, variant)
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
    def assess_quality(frame, detected, variant: LanternVariant, inlier_count: int = 16) -> dict:
        height, width = frame.shape[:2]
        scale = min(1.0, 720.0 / max(width, 1))
        sample = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        focus_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        frame_area = max(1.0, float(width * height))
        marker_areas = [abs(float(cv2.contourArea(detected[mid]))) / frame_area for mid in variant.marker_ids if mid in detected]
        marker_area = float(np.mean(marker_areas)) if marker_areas else 0.0

        # Sub-score calculations calibrated for standard webcams and USB cameras (0.0 to 1.0)
        focus_norm = min(1.0, max(0.0, focus_score / 15.0))
        if 35 <= brightness <= 225:
            bright_norm = 1.0
        elif brightness < 35:
            bright_norm = max(0.0, brightness / 35.0)
        else:
            bright_norm = max(0.0, (255 - brightness) / 30.0)
        inlier_norm = min(1.0, max(0.0, inlier_count / 16.0))
        distance_norm = min(1.0, max(0.0, marker_area / 0.0002))

        overall_score = round(
            (focus_norm * 0.35 + bright_norm * 0.20 + inlier_norm * 0.35 + distance_norm * 0.10) * 100.0,
            1,
        )

        warnings = []
        if focus_score < 12:
            warnings.append("Ảnh hơi mờ; giữ yên giấy hoặc tăng ánh sáng.")
        if brightness < 30:
            warnings.append("Khung hình tối; nên bổ sung ánh sáng.")
        elif brightness > 235:
            warnings.append("Khung hình quá sáng; tránh lóa flash trên giấy.")
        if marker_area < .00025:
            warnings.append("Template đang khá xa camera; đưa lại gần hơn.")
        return {
            "overallScore": overall_score,
            "focusScore": round(focus_score, 1),
            "brightness": round(brightness, 1),
            "markerAreaRatio": round(marker_area, 6),
            "inliers": inlier_count,
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

    def process(self, frame, precomputed_detected=None, precomputed_variant=None, min_quality_score=None):
        started = time.perf_counter()
        detected = precomputed_detected if precomputed_detected is not None else self.detect(frame)
        variant = precomputed_variant if precomputed_variant is not None else self.identify_variant(detected, require_complete=True)
        if variant is None:
            partial = self.identify_variant(detected, require_complete=False)
            if partial:
                missing = [mid for mid in partial.marker_ids if mid not in detected]
                raise ScanError(f"Template {partial.label}: thiếu marker {', '.join(map(str, missing))}.")
            raise ScanError("Không nhận diện được template lồng đèn. Hãy đảm bảo đủ 4 marker nằm trong khung hình.")

        rectified, inlier_count = self.rectify_extended(frame, detected, variant)
        rectified = self.gentle_white_balance(rectified)
        quality = self.assess_quality(frame, detected, variant, inlier_count=inlier_count)

        if min_quality_score is None:
            min_quality_score = float(config.load_settings().get("scan_quality_threshold", 65))

        if quality["overallScore"] < min_quality_score:
            warn_detail = f" ({quality['warnings'][0]})" if quality.get("warnings") else ""
            raise ScanError(
                f"Chất lượng quét chưa đạt chuẩn ({quality['overallScore']:.0f}% < ngưỡng {min_quality_score:.0f}%).{warn_detail} "
                "Hãy giữ phẳng giấy và đưa lại gần camera hơn."
            )

        lantern = self.extract_lantern(rectified, variant.key)

        scan_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        lantern_path = config.LANTERNS_DIR / lantern_filename(scan_id, variant.key)
        atomic_imwrite(lantern_path, lantern, [cv2.IMWRITE_PNG_COMPRESSION, config.PNG_COMPRESSION])

        original_path = None
        corrected_path = None
        if config.KEEP_DIAGNOSTICS:
            original_path = config.ORIGINAL_DIR / f"{scan_id}.jpg"
            corrected_path = config.CORRECTED_DIR / f"{scan_id}.png"
            atomic_imwrite(original_path, frame, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_MASTER_QUALITY])
            atomic_imwrite(corrected_path, rectified, [cv2.IMWRITE_PNG_COMPRESSION, config.PNG_COMPRESSION])

        # Event history is append-only: successfully scanned lantern PNGs are
        # never deleted automatically. Cleanup, if desired, is an explicit
        # between-event maintenance action.
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "scan_completed id=%s variant=%s duration_ms=%s quality=%s focus=%s",
            scan_id,
            variant.key,
            duration_ms,
            quality["overallScore"],
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
