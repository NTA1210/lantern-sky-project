from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class LanternVariant:
    key: str
    label: str
    marker_ids: tuple[int, int, int, int]
    roi: tuple[float, float, float, float]


# The original template keeps marker IDs 0-3 for backward compatibility.
# Each new printable template gets its own four-marker signature, allowing the
# scanner to infer the lantern silhouette without asking the operator to choose it.
LANTERN_VARIANTS: dict[str, LanternVariant] = {
    "classic": LanternVariant("classic", "Classic", (0, 1, 2, 3), (.245, .225, .755, .805)),
    "balloon": LanternVariant("balloon", "Balloon", (4, 5, 6, 7), (.225, .215, .775, .825)),
    "round": LanternVariant("round", "Round", (8, 9, 10, 11), (.205, .285, .795, .705)),
    "rectangle": LanternVariant("rectangle", "Rectangle", (12, 13, 14, 15), (.275, .22, .725, .82)),
}


def get_variant(key: str) -> LanternVariant:
    try:
        return LANTERN_VARIANTS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown lantern variant: {key}") from exc


def identify_variant(marker_ids, require_complete: bool = True) -> LanternVariant | None:
    found = set(int(marker_id) for marker_id in marker_ids)
    matches = []
    for variant in LANTERN_VARIANTS.values():
        score = len(found.intersection(variant.marker_ids))
        if require_complete and score != len(variant.marker_ids):
            continue
        matches.append((score, variant))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    if matches[0][0] == 0:
        return None
    return matches[0][1]


def marker_boxes(width: int, height: int, marker_ids: tuple[int, int, int, int] = (0, 1, 2, 3)):
    side = max(64, round(width * .12))
    mx = round(width * .055)
    my = round(height * .045)
    boxes = (
        (mx, my, side),
        (width - mx - side, my, side),
        (width - mx - side, height - my - side, side),
        (mx, height - my - side, side),
    )
    return {mid: box for mid, box in zip(marker_ids, boxes)}


def expected_marker_corners(width: int, height: int, marker_ids: tuple[int, int, int, int] = (0, 1, 2, 3)):
    out = {}
    for mid, (x, y, side) in marker_boxes(width, height, marker_ids).items():
        out[mid] = np.array(
            [[x, y], [x + side - 1, y], [x + side - 1, y + side - 1], [x, y + side - 1]],
            dtype=np.float32,
        )
    return out


def lantern_roi(width: int, height: int, variant_key: str = "classic"):
    x1, y1, x2, y2 = get_variant(variant_key).roi
    return round(width * x1), round(height * y1), round(width * x2), round(height * y2)


def _scaled_poly(points, width: int, height: int):
    poly = np.asarray(points, dtype=np.float32).copy()
    poly[:, 0] *= width - 1
    poly[:, 1] *= height - 1
    return np.round(poly).astype(np.int32)


def _classic_poly(width: int, height: int):
    return _scaled_poly(
        [
            [.22, .02], [.78, .02], [.90, .08], [.965, .22], [.99, .45], [.97, .70], [.90, .88],
            [.78, .98], [.22, .98], [.10, .88], [.03, .70], [.01, .45], [.035, .22], [.10, .08],
        ],
        width,
        height,
    )


def _balloon_poly(width: int, height: int):
    return _scaled_poly(
        [
            [.38, .015], [.62, .015], [.74, .06], [.84, .14], [.93, .29], [.975, .46], [.95, .63],
            [.87, .77], [.74, .89], [.60, .98], [.40, .98], [.26, .89], [.13, .77], [.05, .63],
            [.025, .46], [.07, .29], [.16, .14], [.26, .06],
        ],
        width,
        height,
    )


def _rectangle_poly(width: int, height: int):
    return _scaled_poly(
        [[.08, .015], [.92, .015], [.985, .07], [.985, .93], [.92, .985], [.08, .985], [.015, .93], [.015, .07]],
        width,
        height,
    )


def create_lantern_mask(width: int, height: int, variant_key: str = "classic", antialias: int = 4):
    aa = max(1, antialias)
    scaled_width = width * aa
    scaled_height = height * aa
    mask = np.zeros((scaled_height, scaled_width), dtype=np.uint8)

    if variant_key == "round":
        center = (scaled_width // 2, scaled_height // 2)
        axes = (round(scaled_width * .485), round(scaled_height * .47))
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, thickness=-1, lineType=cv2.LINE_AA)
    else:
        if variant_key == "classic":
            poly = _classic_poly(scaled_width, scaled_height)
        elif variant_key == "balloon":
            poly = _balloon_poly(scaled_width, scaled_height)
        elif variant_key == "rectangle":
            poly = _rectangle_poly(scaled_width, scaled_height)
        else:
            raise ValueError(f"Unknown lantern variant: {variant_key}")
        cv2.fillPoly(mask, [poly], 255, lineType=cv2.LINE_AA)

    if aa > 1:
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_AREA)
    return mask
