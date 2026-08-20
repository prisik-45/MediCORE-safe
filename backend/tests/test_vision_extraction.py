from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from backend.app.services import vision_extraction


def _settings(api_key: str = "openrouter-key") -> SimpleNamespace:
    return SimpleNamespace(
        openrouter_base_url="https://openrouter.test/api/v1",
        openrouter_site_url="",
        frontend_origin="http://localhost:3000",
        openrouter_app_name="MediCORE",
        app_name="MediCORE",
    )


def test_vision_extraction_uses_configured_openrouter_vision_model(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "catalogue.png"
    Image.new("RGB", (16, 16), "white").save(image_path)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "Vitamin C | USD 5/kg"}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(vision_extraction, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        vision_extraction,
        "get_tenant_openrouter_config",
        lambda db, tenant_id: SimpleNamespace(
            api_key="tenant-openrouter-key",
            vision_model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        ),
    )
    monkeypatch.setattr(vision_extraction.httpx, "Client", FakeClient)

    text = vision_extraction.extract_image_text_with_openrouter_vision(
        image_path,
        "catalogue.png",
        db=object(),
        tenant_id="00000000-0000-0000-0000-000000000001",
    )

    assert text == "Vitamin C | USD 5/kg"
    assert captured["url"] == "https://openrouter.test/api/v1/chat/completions"
    assert captured["json"]["model"] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    assert captured["headers"]["Authorization"] == "Bearer tenant-openrouter-key"
    assert captured["json"]["messages"][1]["content"][1]["type"] == "image_url"


def test_vision_extraction_returns_empty_without_tenant_config(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "catalogue.png"
    Image.new("RGB", (16, 16), "white").save(image_path)
    monkeypatch.setattr(vision_extraction, "get_settings", lambda: _settings())
    monkeypatch.setattr(vision_extraction, "get_tenant_openrouter_config", lambda db, tenant_id: None)

    assert vision_extraction.extract_image_text_with_openrouter_vision(
        image_path,
        "catalogue.png",
        db=object(),
        tenant_id="00000000-0000-0000-0000-000000000001",
    ) == ""
