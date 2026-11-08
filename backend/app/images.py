"""Profile photos and signatures: decoded, checked and re-encoded by the server.

Whatever was uploaded, the stored file is a plain JPEG or PNG written here. That drops any
hidden metadata (a phone photo's GPS position) and anything that is not pixels.
"""

from __future__ import annotations

import cv2
import numpy as np

PHOTO_MAX_BYTES = 5 * 1024 * 1024
PHOTO_SIZE = 256  # stored square, in pixels; shown at 84 px at most (x2 for sharp screens)
PHOTO_MIN_SIZE = 32
SIGNATURE_MAX_BYTES = 2 * 1024 * 1024
SIGNATURE_MAX_WIDTH = 1200
SIGNATURE_MAX_HEIGHT = 400
SIGNATURE_MIN_SIZE = 16


class InvalidImage(ValueError):
    """The upload is not an image that can be used here."""


def _decode(data: bytes, flags: int) -> np.ndarray:
    if not data:
        raise InvalidImage("The file is empty.")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flags)
    if image is None or image.size == 0:
        raise InvalidImage("The file is not an image that can be read (JPEG, PNG or WebP).")
    return image


def _encode(extension: str, image: np.ndarray, params: list[int]) -> bytes:
    ok, encoded = cv2.imencode(extension, image, params)
    if not ok:
        raise InvalidImage("The image could not be saved.")
    return encoded.tobytes()


def make_photo(data: bytes) -> bytes:
    """Centre square of the image, at most PHOTO_SIZE pixels wide, as a JPEG."""
    image = _decode(data, cv2.IMREAD_COLOR)  # 8-bit colour, turned upright from EXIF
    height, width = image.shape[:2]
    side = min(height, width)
    if side < PHOTO_MIN_SIZE:
        raise InvalidImage(f"The photo is too small (at least {PHOTO_MIN_SIZE} pixels wide).")
    top, left = (height - side) // 2, (width - side) // 2
    square = image[top : top + side, left : left + side]
    if side > PHOTO_SIZE:
        square = cv2.resize(square, (PHOTO_SIZE, PHOTO_SIZE), interpolation=cv2.INTER_AREA)
    return _encode(".jpg", square, [cv2.IMWRITE_JPEG_QUALITY, 88])


def make_signature(data: bytes) -> bytes:
    """The image as a PNG that keeps its transparency, shrunk to fit SIGNATURE_MAX_*."""
    image = _decode(data, cv2.IMREAD_UNCHANGED)
    if image.dtype == np.uint16:
        image = (image >> 8).astype(np.uint8)
    elif image.dtype != np.uint8:
        raise InvalidImage("Send a JPEG, PNG or WebP image.")
    height, width = image.shape[:2]
    if min(height, width) < SIGNATURE_MIN_SIZE:
        raise InvalidImage("The signature image is too small.")
    scale = min(1.0, SIGNATURE_MAX_WIDTH / width, SIGNATURE_MAX_HEIGHT / height)
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return _encode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
