from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image

from backend.layout import LANTERN_VARIANTS, create_lantern_mask, lantern_roi, marker_boxes

PAGE_W, PAGE_H = 2480, 3508
OUTPUTS = {
    "classic": ROOT / "print" / "lantern_template.png",
    "balloon": ROOT / "print" / "lantern_template_balloon.png",
    "round": ROOT / "print" / "lantern_template_round.png",
    "rectangle": ROOT / "print" / "lantern_template_rectangle.png",
}


def build_template(variant_key: str):
    variant = LANTERN_VARIANTS[variant_key]
    page = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    for marker_id, (x, y, side) in marker_boxes(PAGE_W, PAGE_H, variant.marker_ids).items():
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        page[y:y + side, x:x + side] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)

    title = f"LANTERN SKY - {variant.label.upper()} TEMPLATE"
    subtitle = f"Draw inside the lantern. Keep markers {', '.join(map(str, variant.marker_ids))} visible."
    cv2.putText(
        page,
        title,
        (round(PAGE_W * .20), round(PAGE_H * .16)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.55,
        (45, 45, 45),
        4,
        cv2.LINE_AA,
    )
    cv2.putText(
        page,
        subtitle,
        (round(PAGE_W * .205), round(PAGE_H * .19)),
        cv2.FONT_HERSHEY_SIMPLEX,
        .78,
        (110, 110, 110),
        2,
        cv2.LINE_AA,
    )

    x1, y1, x2, y2 = lantern_roi(PAGE_W, PAGE_H, variant_key)
    mask = create_lantern_mask(x2 - x1, y2 - y1, variant_key, 1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    shifted = []
    for contour in contours:
        contour = contour.copy()
        contour[:, :, 0] += x1
        contour[:, :, 1] += y1
        shifted.append(contour)
    cv2.drawContours(page, shifted, -1, (190, 190, 190), 6, cv2.LINE_AA)

    output = OUTPUTS[variant_key]
    output.parent.mkdir(parents=True, exist_ok=True)
    rgb = cv2.cvtColor(page, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(output, dpi=(300, 300), optimize=True)
    return output


def main():
    for variant_key in LANTERN_VARIANTS:
        output = build_template(variant_key)
        print(f"Created {variant_key}: {output}")


if __name__ == "__main__":
    main()
