"""Draw a scan result on the photo: one coloured box per pill, its name and its score.

Used by `POST /api/predict/visualize`. The colour of a box is derived from the class id, so
the same product is always drawn in the same colour and two pills of different products in
one photo never share one. Drawing is pure OpenCV, like the rest of `scanner.py`.
"""

from __future__ import annotations

import colorsys
import unicodedata

import cv2
import numpy as np

from app.schemas import ScanResult

FONT = cv2.FONT_HERSHEY_SIMPLEX
GOLDEN_ANGLE = 0.61803398875  # spreads consecutive class ids far apart on the hue circle
UNKNOWN_COLOR = (120, 120, 120)  # BGR, for a box with no identification


def class_color(class_id: int) -> tuple[int, int, int]:
    """A stable, well-separated BGR colour for a class id."""
    hue = (class_id * GOLDEN_ANGLE) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.78, 1.0)
    return round(blue * 255), round(green * 255), round(red * 255)


def _ascii(text: str) -> str:
    """OpenCV's Hershey fonts have no accents: "Paracétamol" -> "Paracetamol"."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return stripped or "?"


def _text_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Black on a light box, white on a dark one (ITU-R BT.601 luma)."""
    blue, green, red = background
    luma = 0.299 * red + 0.587 * green + 0.114 * blue
    return (0, 0, 0) if luma > 140 else (255, 255, 255)


def _label(
    canvas: np.ndarray,
    text: str,
    corner: tuple[int, int],
    color: tuple[int, int, int],
    scale: float,
    thickness: int,
) -> None:
    """A filled caption above the box, pushed inside the image when there is no room."""
    pen = max(1, thickness // 2)
    (width, height), baseline = cv2.getTextSize(text, FONT, scale, pen)
    x, y = corner
    x = max(0, min(x, canvas.shape[1] - width - 2 * pen))
    top = y - height - 2 * baseline
    if top < 0:  # the box touches the top edge: caption goes just below its corner
        top = y
    cv2.rectangle(
        canvas, (x, top), (x + width + 2 * pen, top + height + 2 * baseline), color, cv2.FILLED
    )
    cv2.putText(
        canvas,
        text,
        (x + pen, top + height + baseline // 2),
        FONT,
        scale,
        _text_color(color),
        pen,
        cv2.LINE_AA,
    )


def annotate(image: np.ndarray, result: ScanResult, *, banner: bool = True) -> np.ndarray:
    """A copy of `image` with a box, a name and a probability for every detected pill."""
    canvas = image.copy()
    # Everything scales with the photo, so a 4000 px and a 640 px photo look the same.
    scale = max(canvas.shape[:2]) / 1200
    thickness = max(2, round(3 * scale))
    font_scale = max(0.45, 0.75 * scale)

    for pill in result.pills:
        best = pill.candidates[0] if pill.candidates else None
        color = class_color(best.class_id) if best else UNKNOWN_COLOR
        x1, y1 = round(pill.box.x1), round(pill.box.y1)
        x2, y2 = round(pill.box.x2), round(pill.box.y2)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        if best is None:
            caption = "unidentified"
        else:
            caption = f"{_ascii(best.name)} {best.probability:.0%}"
            if pill.needs_confirmation:
                caption += " (to confirm)"
        _label(canvas, caption, (x1, y1), color, font_scale, thickness)

    if banner:
        found = len(result.pills)
        text = f"{found} pill{'s' if found != 1 else ''} - {result.timings.total_ms:.0f} ms"
        _label(canvas, text, (0, round(26 * scale) + 6), (28, 28, 28), font_scale, thickness)
    return canvas


def to_png(image: np.ndarray) -> bytes:
    """PNG bytes, so the boxes and the text stay sharp."""
    ok, buffer = cv2.imencode(".png", image)
    if not ok:  # pragma: no cover - OpenCV only fails here on an unsupported array
        raise RuntimeError("The annotated image could not be encoded as PNG.")
    return buffer.tobytes()
