from types import SimpleNamespace

from backend.app.services import llm as llm_module
from backend.app.services.llm import EXTRACTION_CHUNK_CHARS, ModelProviderConfig, OpenRouterClient, TokenLimitReachedError


def test_salvages_items_from_malformed_openrouter_json() -> None:
    client = object.__new__(OpenRouterClient)
    content = """
    {
      "items": [
        {"ingredient_name": "Citric Acid", "price_per_unit": 10.5},
        {"ingredient_name": "Nicotinamide", "price_per_unit": 99.02},
    """

    payload = client._parse_json_response(content)

    assert len(payload["items"]) == 2
    assert payload["items"][1]["ingredient_name"] == "Nicotinamide"


def test_repairs_trailing_commas_in_openrouter_json() -> None:
    client = object.__new__(OpenRouterClient)
    content = '{"items":[{"ingredient_name":"Glycine","price_per_unit":3.88,},],}'

    payload = client._parse_json_response(content)

    assert payload["items"][0]["price_per_unit"] == 3.88


def test_model_router_uses_groq_before_openrouter() -> None:
    client = object.__new__(OpenRouterClient)
    client.providers = [
        ModelProviderConfig("groq", "groq-key", "groq-model", "https://groq.test"),
        ModelProviderConfig("openrouter", "openrouter-key", "openrouter-model", "https://openrouter.test"),
    ]
    called = []

    def fake_chat_with_provider(provider, messages, *, temperature=0, json_mode=False):
        called.append(provider.name)
        return "primary response"

    client._chat_with_provider = fake_chat_with_provider

    assert client._chat([{"role": "user", "content": "hello"}]) == "primary response"
    assert called == ["groq"]


def test_tenant_llm_routing_uses_tenant_openrouter_without_env_openrouter_fallback(monkeypatch) -> None:
    client = object.__new__(OpenRouterClient)
    client.db = object()
    client.cerebras_provider = ModelProviderConfig("cerebras", "cerebras-key", "cerebras-model", "https://cerebras.test")
    client.openrouter_fallback_provider = ModelProviderConfig("openrouter", "env-openrouter-key", "env-openrouter-model", "https://openrouter.test")

    monkeypatch.setattr(llm_module, "get_tenant_openrouter_config", lambda db, tenant_id: None)
    providers_without_settings = client._available_providers(tenant_id="00000000-0000-0000-0000-000000000001")

    monkeypatch.setattr(
        llm_module,
        "get_tenant_openrouter_config",
        lambda db, tenant_id: SimpleNamespace(api_key="tenant-key", text_model="tenant/text-model"),
    )
    providers_with_settings = client._available_providers(tenant_id="00000000-0000-0000-0000-000000000001")

    assert [provider.name for provider in providers_without_settings] == ["cerebras"]
    assert providers_with_settings[0].name == "openrouter"
    assert providers_with_settings[0].api_key == "tenant-key"
    assert providers_with_settings[0].model == "tenant/text-model"


def test_model_router_falls_back_to_openrouter_after_groq_failure() -> None:
    client = object.__new__(OpenRouterClient)
    client.providers = [
        ModelProviderConfig("groq", "groq-key", "groq-model", "https://groq.test"),
        ModelProviderConfig("openrouter", "openrouter-key", "openrouter-model", "https://openrouter.test"),
    ]
    called = []

    def fake_chat_with_provider(provider, messages, *, temperature=0, json_mode=False):
        called.append(provider.name)
        if provider.name == "groq":
            raise RuntimeError("primary unavailable")
        return "secondary response"

    client._chat_with_provider = fake_chat_with_provider

    assert client._chat([{"role": "user", "content": "hello"}]) == "secondary response"
    assert called == ["groq", "openrouter"]


def test_extraction_chunks_are_sized_for_primary_groq_route() -> None:
    client = object.__new__(OpenRouterClient)
    text = "\n".join(f"Vitamin C row {index} USD 5/kg" for index in range(5000))

    chunks = client._chunk_text(text)

    assert EXTRACTION_CHUNK_CHARS == 40000
    assert len(chunks) > 1
    assert all(len(chunk) <= EXTRACTION_CHUNK_CHARS + 1000 for chunk in chunks)


def test_catalogue_extraction_prompt_stays_compact() -> None:
    client = object.__new__(OpenRouterClient)
    prompt = client._catalogue_extraction_system_prompt()

    assert len(prompt) < 1600
    assert "price_per_unit" in prompt
    assert "available_qty" in prompt


def test_model_router_raises_token_limit_for_rate_limit_exhaustion() -> None:
    client = object.__new__(OpenRouterClient)
    client.providers = [
        ModelProviderConfig("groq", "groq-key", "groq-model", "https://groq.test"),
        ModelProviderConfig("openrouter", "openrouter-key", "openrouter-model", "https://openrouter.test"),
    ]

    def fake_chat_with_provider(provider, messages, *, temperature=0, json_mode=False):
        raise RuntimeError("429 rate limit quota exhausted")

    client._chat_with_provider = fake_chat_with_provider

    try:
        client._chat([{"role": "user", "content": "hello"}])
    except TokenLimitReachedError as exc:
        assert str(exc) == "Token Limit Reached"
    else:
        raise AssertionError("TokenLimitReachedError was not raised")


def test_json_chat_falls_back_when_primary_returns_invalid_json() -> None:
    client = object.__new__(OpenRouterClient)
    client.providers = [
        ModelProviderConfig("groq", "groq-key", "groq-model", "https://groq.test"),
        ModelProviderConfig("openrouter", "openrouter-key", "openrouter-model", "https://openrouter.test"),
    ]

    def fake_chat_with_provider(provider, messages, *, temperature=0, json_mode=False):
        if provider.name == "groq":
            return "not json"
        return '{"items":[{"ingredient_name":"Citric Acid"}]}'

    client._chat_with_provider = fake_chat_with_provider

    payload = client._json_chat("Return JSON", "catalogue text")

    assert payload["items"][0]["ingredient_name"] == "Citric Acid"


def test_catalogue_extraction_keeps_openrouter_fallback() -> None:
    client = object.__new__(OpenRouterClient)
    client.providers = [
        ModelProviderConfig("groq", "groq-key", "groq-model", "https://groq.test"),
        ModelProviderConfig("openrouter", "openrouter-key", "openrouter-model", "https://openrouter.test"),
    ]
    called = []

    def fake_chat_with_provider(provider, messages, *, temperature=0, json_mode=False):
        called.append(provider.name)
        if provider.name == "groq":
            raise RuntimeError("429 rate limit quota exhausted")
        return '{"items":[{"ingredient_name":"L-Carnitine","price_per_unit":22.7,"currency":"USD","unit":"kg"}]}'

    client._chat_with_provider = fake_chat_with_provider

    items = client.extract_catalog_items("Price: USD22.7/kg for L-Carnitine")
    assert called == ["groq", "openrouter"]
    assert len(items) == 1
    assert items[0].ingredient_name == "L-Carnitine"
