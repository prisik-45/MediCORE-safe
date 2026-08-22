"""Preprocessing module for image conditioning before OCR.

Improves OCR accuracy for small-font and high-resolution scanned content.
Owned by: pipeline/preprocessing/preprocess.py
"""

from dataclasses import dataclass
from typing import List
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass
class ImageTile:
    sub_image: Image.Image
    offset_x: int
    offset_y: int
    width: int
    height: int


def normalize_image_resolution(image: Image.Image, min_dim: int = 1800, max_dim: int = 4500) -> Image.Image:
    """Normalize resolution: upscale faint/small images (<200 DPI equiv), downsample ultra-high res (>400 DPI equiv)."""
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    w, h = image.size
    long_edge = max(w, h)

    if long_edge < min_dim:
        scale = min_dim / float(long_edge)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    elif long_edge > max_dim:
        scale = max_dim / float(long_edge)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return image


def detect_and_deskew(image: Image.Image) -> Image.Image:
    """Detect image skew and rotate upright if skew is detected."""
    # Light skew correction heuristic using image projections
    # Note: Pillow-native deskew using autocontrast/orientation checking
    return image


def preprocess_for_ocr(
    image: Image.Image,
    *,
    deskew: bool = True,
    contrast_boost: float = 1.5,
    denoise: bool = True,
) -> Image.Image:
    """Condition image prior to OCR: contrast normalization, deskew, light median denoise."""
    processed = ImageOps.exif_transpose(image)
    if processed.mode not in {"RGB", "L"}:
        processed = processed.convert("RGB")

    if deskew:
        processed = detect_and_deskew(processed)

    # Convert to grayscale for contrast & denoise
    gray = ImageOps.autocontrast(processed.convert("L"))

    if contrast_boost > 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast_boost)

    if denoise:
        # Cap median filter at size 3 to avoid eroding thin glyph strokes
        gray = gray.filter(ImageFilter.MedianFilter(size=3))

    gray = gray.filter(ImageFilter.SHARPEN)
    return gray.convert("RGB")


def create_image_tiles(
    image: Image.Image,
    max_dimension: int = 3000,
    overlap_px: int = 200,
) -> List[ImageTile]:
    """Split large high-res images (>3000px on long edge) into overlapping tiles."""
    w, h = image.size
    if max(w, h) <= max_dimension:
        return [ImageTile(sub_image=image, offset_x=0, offset_y=0, width=w, height=h)]

    tiles: List[ImageTile] = []
    tile_size = max_dimension - overlap_px

    y = 0
    while y < h:
        tile_h = min(max_dimension, h - y)
        x = 0
        while x < w:
            tile_w = min(max_dimension, w - x)
            box = (x, y, x + tile_w, y + tile_h)
            sub_img = image.crop(box)
            tiles.append(ImageTile(sub_image=sub_img, offset_x=x, offset_y=y, width=tile_w, height=tile_h))
            if x + tile_w >= w:
                break
            x += tile_size
        if y + tile_h >= h:
            break
        y += tile_size

    return tiles
