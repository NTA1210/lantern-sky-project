from __future__ import annotations

from io import BytesIO
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageChops, UnidentifiedImageError


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = (
    ROOT / "print" / "lantern_template.png",
    ROOT / "print" / "lantern_template_balloon.png",
    ROOT / "print" / "lantern_template_round.png",
    ROOT / "print" / "lantern_template_rectangle.png",
)


def committed_bytes(path: Path) -> bytes:
    relative = path.relative_to(ROOT).as_posix()
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Không đọc được template đã commit {relative}: {message}")
    return result.stdout


def normalized_dpi(image: Image.Image) -> tuple[int, int] | None:
    dpi = image.info.get("dpi")
    if not dpi or len(dpi) < 2:
        return None
    return round(float(dpi[0])), round(float(dpi[1]))


def verify_template(path: Path) -> list[str]:
    relative = path.relative_to(ROOT).as_posix()
    errors: list[str] = []
    try:
        committed_source = BytesIO(committed_bytes(path))
        with Image.open(committed_source) as committed, Image.open(path) as generated:
            committed.load()
            generated.load()

            if committed.size != generated.size:
                errors.append(f"size {committed.size} != {generated.size}")

            committed_dpi = normalized_dpi(committed)
            generated_dpi = normalized_dpi(generated)
            if committed_dpi != generated_dpi:
                errors.append(f"dpi {committed_dpi} != {generated_dpi}")

            committed_pixels = committed.convert("RGBA")
            generated_pixels = generated.convert("RGBA")
            if committed_pixels.size == generated_pixels.size:
                diff = ImageChops.difference(committed_pixels, generated_pixels)
                if diff.getbbox() is not None:
                    errors.append("decoded pixels differ")
    except (OSError, RuntimeError, UnidentifiedImageError) as exc:
        errors.append(str(exc))

    if errors:
        return [f"{relative}: {error}" for error in errors]
    print(f"TEMPLATE OK: {relative}")
    return []


def main() -> int:
    errors: list[str] = []
    for path in TEMPLATES:
        if not path.is_file():
            errors.append(f"{path.relative_to(ROOT).as_posix()}: generated file is missing")
            continue
        errors.extend(verify_template(path))

    if errors:
        print("Printable template verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("PRINTABLE TEMPLATE VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
