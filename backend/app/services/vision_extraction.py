"""OpenRouter vision extraction for scanned catalogue pages and images."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

MAX_VISION_IMAGE_SIDE = 2200
VISION_JPEG_QUALITY = 85
VISION_MAX_OUTPUT_TOKENS = 4000


def extract_image_text_with_openrouter_vision(image_or_path: Image.Image | Path, source_name: str = "image") -> str:
    """Extract visible catalogue text/table content using the configured OpenRouter vision model."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        return ""

    model = settings.openrouter_vision_model or settings.openrouter_model
    if not model:
        return ""

    try:
        image_bytes = _image_to_jpeg_bytes(image_or_path)
        data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract supplier catalogue data from document images. "
                        "Return only the transcribed visible content. Preserve item names, pack sizes, "
                        "prices, quantities, units, tables, and row order. Do not summarize or add commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Transcribe all readable catalogue text and tables from this image. "
                                "Use markdown tables where rows and columns are visible. "
                                "If no readable catalogue data is visible, return an empty response."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": VISION_MAX_OUTPUT_TOKENS,
        }

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "Connection": "close",
        }
        site_url = settings.openrouter_site_url or settings.frontend_origin
        app_name = settings.openrouter_app_name or settings.app_name
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name

        timeout = httpx.Timeout(90.0, connect=20.0, read=60.0, write=30.0, pool=10.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        text = str(content).strip()
        if text:
            logger.info("OpenRouter vision extracted %s characters from %s", len(text), source_name)
        return text
    except Exception as err:
        logger.warning("OpenRouter vision extraction failed for %s: %s", source_name, err)
        return ""


def _image_to_jpeg_bytes(image_or_path: Image.Image | Path) -> bytes:
    if isinstance(image_or_path, Path):
        with Image.open(image_or_path) as image:
            return _pil_image_to_jpeg_bytes(image)
    return _pil_image_to_jpeg_bytes(image_or_path)


def _pil_image_to_jpeg_bytes(image: Image.Image) -> bytes:
    prepared = ImageOps.exif_transpose(image).copy()
    if prepared.mode not in {"RGB", "L"}:
        prepared = prepared.convert("RGB")
    if prepared.mode == "L":
        prepared = prepared.convert("RGB")
    prepared.thumbnail((MAX_VISION_IMAGE_SIDE, MAX_VISION_IMAGE_SIDE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    prepared.save(output, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
    return output.getvalue()
