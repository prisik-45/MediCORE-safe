"""OpenRouter vision extraction for scanned catalogue pages and images."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from backend.app.config import get_settings
from backend.app.schemas import ExtractedCatalogItem
from backend.app.services.tenant_ai_settings import get_tenant_openrouter_config

logger = logging.getLogger(__name__)

MAX_VISION_IMAGE_SIDE = 2200
VISION_JPEG_QUALITY = 85
VISION_MAX_OUTPUT_TOKENS = 4000


def extract_image_text_with_openrouter_vision(
    image_or_path: Image.Image | Path,
    source_name: str = "image",
    db: Any | None = None,
    tenant_id: Any | None = None,
) -> str:
    """Extract visible catalogue text/table content using the configured OpenRouter vision model."""
    try:
        payload = {
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
                        {"type": "image_url", "image_url": {"url": "__IMAGE_URL__"}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": VISION_MAX_OUTPUT_TOKENS,
        }
        text = _openrouter_vision_chat(image_or_path, payload, source_name, db=db, tenant_id=tenant_id)
        if text:
            logger.info("OpenRouter vision extracted %s characters from %s", len(text), source_name)
        return text
    except Exception as err:
        logger.warning("OpenRouter vision extraction failed for %s: %s", source_name, err)
        return ""


def extract_catalog_items_from_image_with_openrouter_vision(
    image_or_path: Image.Image | Path,
    source_name: str = "image",
    db: Any | None = None,
    tenant_id: Any | None = None,
) -> list[ExtractedCatalogItem]:
    """Extract catalogue item JSON directly from a direct image attachment."""
    try:
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract supplier catalogue rows from the image. Output only minified JSON shaped as "
                        "{\"items\":[{ingredient_name,specification,price_per_unit,currency,available_qty,unit,valid_until,lead_time_days,lead_time_text,moq,notes}]}. "
                        "Use null for missing fields. Do not invent, convert, or round values. Obey table headers: Qty/Quantity is stock, Price/Rate is price. "
                        "Put concise source evidence and terms in notes using source='visible row text'. No markdown or explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Return every visible product row and every price tier as JSON items."},
                        {"type": "image_url", "image_url": {"url": "__IMAGE_URL__"}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": VISION_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }
        content = _openrouter_vision_chat(image_or_path, payload, source_name, db=db, tenant_id=tenant_id)
        if not content:
            return []
        data = _parse_json_response(content)
        items = []
        for raw_item in data.get("items", []):
            try:
                items.append(ExtractedCatalogItem.model_validate(raw_item))
            except Exception as err:
                logger.warning("Skipping invalid OpenRouter vision item from %s: %s", source_name, err)
        if items:
            logger.info("OpenRouter vision extracted %s catalogue item(s) from %s", len(items), source_name)
        return items
    except Exception as err:
        logger.warning("OpenRouter vision JSON extraction failed for %s: %s", source_name, err)
        return []


def _openrouter_vision_chat(
    image_or_path: Image.Image | Path,
    payload: dict,
    source_name: str,
    db: Any | None = None,
    tenant_id: Any | None = None,
) -> str:
    settings = get_settings()
    tenant_config = get_tenant_openrouter_config(db, tenant_id)
    if tenant_config is None:
        logger.warning("OpenRouter vision skipped for %s: tenant OpenRouter settings are not configured", source_name)
        return ""

    image_bytes = _image_to_jpeg_bytes(image_or_path)
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
    payload = dict(payload)
    payload["model"] = tenant_config.vision_model
    payload["messages"] = _inject_image_url(payload["messages"], data_url)

    headers = {
        "Authorization": f"Bearer {tenant_config.api_key}",
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
    return str(content).strip()


def _inject_image_url(messages: list[dict], data_url: str) -> list[dict]:
    injected = []
    for message in messages:
        message_copy = dict(message)
        content = message_copy.get("content")
        if isinstance(content, list):
            patched_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    patched = dict(part)
                    patched["image_url"] = {"url": data_url}
                    patched_content.append(patched)
                else:
                    patched_content.append(part)
            message_copy["content"] = patched_content
        injected.append(message_copy)
    return injected


def _parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first != -1 and last > first:
        cleaned = cleaned[first : last + 1]
    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, dict) else {}

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
