from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from backend import config
from backend.layout import LANTERN_VARIANTS, lantern_roi, marker_boxes
from backend.processor import LanternProcessor

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
    cv2.putText(artwork, variant.label.upper(), (max(20, roi_w // 8), roi_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1, (20, 20, 20), 3, cv2.LINE_AA)
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


def main():
    processor = LanternProcessor()
    for variant_key, variant in LANTERN_VARIANTS.items():
        page = canonical(variant_key)
        frame = fake_camera(page)
        detected = processor.detect(frame)
        identified = processor.identify_variant(detected, require_complete=True)
        if identified is None or identified.key != variant_key:
            raise RuntimeError(f"Variant detection failed for {variant_key}: {sorted(detected)}")

        rectified = processor.rectify(frame, detected, identified)
        lantern = processor.extract_lantern(rectified, variant_key)
        cv2.imwrite(str(OUT / f"{variant_key}_canonical.png"), page)
        cv2.imwrite(str(OUT / f"{variant_key}_camera.png"), frame)
        cv2.imwrite(str(OUT / f"{variant_key}_rectified.png"), rectified)
        cv2.imwrite(str(OUT / f"{variant_key}_lantern.png"), lantern)
        print(f"SELF TEST PASSED: {variant_key} markers={sorted(detected)}")

    print("Outputs:", OUT)


if __name__ == "__main__":
    main()
