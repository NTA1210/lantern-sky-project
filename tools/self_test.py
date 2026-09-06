from __future__ import annotations

from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from backend import config
from backend.layout import LANTERN_VARIANTS, lantern_roi, marker_boxes
from backend.processor import LanternProcessor, ScanError
from backend.scanner import ScannerService
from backend.storage import lantern_count, list_lanterns, prune_scan_storage

OUT = ROOT / "self_test_output"
OUT.mkdir(exist_ok=True)


def canonical(variant_key: str):
    variant = LANTERN_VARIANTS[variant_key]
    width, height = config.CANONICAL_WIDTH, config.CANONICAL_HEIGHT
    page = np.full((height, width, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    for marker_id, (x, y, side) in marker_boxes(width, height, variant.marker_ids).items():
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        page[y:y + side, x:x + side] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)

    x1, y1, x2, y2 = lantern_roi(width, height, variant_key)
    roi_w, roi_h = x2 - x1, y2 - y1
    artwork = np.full((roi_h, roi_w, 3), 248, np.uint8)
    for index in range(12):
        cv2.circle(
            artwork,
            (int(roi_w * (.12 + (index % 4) * .25)), int(roi_h * (.14 + (index // 4) * .28))),
            max(12, roi_w // 16),
            (40 + (index * 47) % 190, 50 + (index * 71) % 190, 60 + (index * 91) % 190),
            -1,
            cv2.LINE_AA,
        )
    cv2.putText(
        artwork,
        variant.label.upper(),
        (max(20, roi_w // 8), roi_h // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (20, 20, 20),
        3,
        cv2.LINE_AA,
    )
    page[y1:y2, x1:x2] = artwork
    return page


def fake_camera(page):
    height, width = page.shape[:2]
    camera_w, camera_h = 1920, 1080
    output = np.full((camera_h, camera_w, 3), 60, np.uint8)
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    destination = np.float32([[610, 70], [1370, 110], [1450, 1010], [500, 960]])
    homography = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(page, homography, (camera_w, camera_h), borderValue=(60, 60, 60))
    mask = cv2.warpPerspective(np.full((height, width), 255, np.uint8), homography, (camera_w, camera_h))
    output[mask > 0] = warped[mask > 0]
    return output


def verify_negative_cases(processor: LanternProcessor, frame, detected, variant_key: str) -> None:
    variant = LANTERN_VARIANTS[variant_key]
    partial_detected = dict(detected)
    partial_detected.pop(variant.marker_ids[-1])

    if processor.identify_variant(partial_detected, require_complete=True) is not None:
        raise RuntimeError(f"Incomplete template incorrectly marked complete: {variant_key}")

    partial = processor.identify_variant(partial_detected, require_complete=False)
    if partial is None or partial.key != variant_key:
        raise RuntimeError(f"Partial variant detection failed for {variant_key}")

    try:
        processor.rectify(frame, partial_detected, variant)
    except ScanError:
        pass
    else:
        raise RuntimeError(f"Missing marker did not reject rectify for {variant_key}")


def verify_scanner_preview_path() -> None:
    scanner = ScannerService()
    if scanner.preview_processor is scanner.scan_processor:
        raise RuntimeError("Preview and final scan unexpectedly share one OpenCV detector")

    source_width = max(config.PREVIEW_MAX_WIDTH * 3, 1920)
    source_height = round(source_width * 9 / 16)
    master = np.zeros((source_height, source_width, 3), np.uint8)
    preview = scanner._preview_frame(master)
    expected_width = min(source_width, max(320, config.PREVIEW_MAX_WIDTH))
    if preview.shape[1] != expected_width:
        raise RuntimeError(f"Preview downscale failed: expected width {expected_width}, got {preview.shape[1]}")
    if master.shape[1] != source_width:
        raise RuntimeError("Preview processing mutated the master scan frame")


def verify_processing_and_storage(processor: LanternProcessor, frames: dict[str, np.ndarray]) -> None:
    original_config = (
        config.LANTERNS_DIR,
        config.ORIGINAL_DIR,
        config.CORRECTED_DIR,
        config.KEEP_DIAGNOSTICS,
    )

    with TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        config.LANTERNS_DIR = temp / "lanterns"
        config.ORIGINAL_DIR = temp / "original"
        config.CORRECTED_DIR = temp / "corrected"
        config.KEEP_DIAGNOSTICS = False

        try:
            results = {}
            for variant_key in LANTERN_VARIANTS:
                result = processor.process(frames[variant_key])
                results[variant_key] = result
                if not result.lantern_path.is_file():
                    raise RuntimeError(f"Final PNG was not stored for {variant_key}")
                if f"__{variant_key}.png" not in result.lantern_path.name:
                    raise RuntimeError(f"Variant was not persisted in filename for {variant_key}")
                if result.original_path is not None or result.corrected_path is not None:
                    raise RuntimeError("Diagnostics were stored while disabled")

            # Simulate a PNG created by the previous four-template build before
            # variant suffixes were introduced. The storage layer should infer
            # its lane from the exported image dimensions.
            shutil.copyfile(results["round"].lantern_path, config.LANTERNS_DIR / "legacy-round.png")
            expected_count = len(LANTERN_VARIANTS) + 1
            stored = list(config.LANTERNS_DIR.glob("*.png"))
            if len(stored) != expected_count:
                raise RuntimeError(
                    f"Event history was unexpectedly pruned: expected {expected_count}, got {len(stored)}"
                )
            if lantern_count() != expected_count:
                raise RuntimeError("Persisted lantern count is incorrect")

            records = list_lanterns()
            if not set(LANTERN_VARIANTS).issubset({item["variant"] for item in records}):
                raise RuntimeError(f"Persisted variant metadata is incorrect: {records}")
            legacy = next((item for item in records if item["id"] == "legacy-round"), None)
            if legacy is None or legacy["variant"] != "round":
                raise RuntimeError(f"Legacy variant inference failed: {legacy}")
            if any(not item["createdAt"] for item in records):
                raise RuntimeError("Persisted display records are missing createdAt")

            # Cleanup remains available only as an explicit maintenance action.
            prune_scan_storage(2)
            if lantern_count() != 2:
                raise RuntimeError("Explicit storage pruning helper failed")
        finally:
            (
                config.LANTERNS_DIR,
                config.ORIGINAL_DIR,
                config.CORRECTED_DIR,
                config.KEEP_DIAGNOSTICS,
            ) = original_config


def main():
    processor = LanternProcessor()
    frames = {}

    verify_scanner_preview_path()
    print("SCANNER PREVIEW TEST PASSED")

    for variant_key, variant in LANTERN_VARIANTS.items():
        page = canonical(variant_key)
        frame = fake_camera(page)
        detected = processor.detect(frame)
        identified = processor.identify_variant(detected, require_complete=True)
        if identified is None or identified.key != variant_key:
            raise RuntimeError(f"Variant detection failed for {variant_key}: {sorted(detected)}")

        verify_negative_cases(processor, frame, detected, variant_key)

        rectified = processor.rectify(frame, detected, identified)
        lantern = processor.extract_lantern(rectified, variant_key)
        cv2.imwrite(str(OUT / f"{variant_key}_canonical.png"), page)
        cv2.imwrite(str(OUT / f"{variant_key}_camera.png"), frame)
        cv2.imwrite(str(OUT / f"{variant_key}_rectified.png"), rectified)
        cv2.imwrite(str(OUT / f"{variant_key}_lantern.png"), lantern)
        frames[variant_key] = frame
        print(f"SELF TEST PASSED: {variant_key} markers={sorted(detected)}")

    verify_processing_and_storage(processor, frames)
    print("PROCESSING/STORAGE TEST PASSED")
    print("Outputs:", OUT)


if __name__ == "__main__":
    main()
