"""Image file loader using Pillow.

Owned by: pipeline/ingestion/loader_image.py
"""

from pathlib import Path
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 25_000_000
MAX_SAFE_IMAGE_PIXELS = 25_000_000


class ImageWrapper:
    """Wrapper around PIL Image to keep file opening encapsulated in ingestion/."""

    def __init__(self, image: Image.Image, file_path: Path):
        self.image = image
        self.file_path = file_path

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


def load_image(file_path: Path) -> ImageWrapper:
    """Open image file, transpose EXIF orientation, and ensure RGB mode."""
    with Image.open(file_path) as raw_img:
        img = ImageOps.exif_transpose(raw_img)
        if img.mode not in {"RGB", "L"}:
            img = img.convert("RGB")
        # Load pixels into memory so stream stays open after closing raw_img
        img.load()
        return ImageWrapper(img, file_path)
