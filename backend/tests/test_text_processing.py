import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from shadowing_video_studio.main import app
from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.text_api import get_text_service
from shadowing_video_studio.text_processing import (
    MAX_OUTPUT_BYTES,
    PreparationError,
    ProviderAvailability,
    TextPreparationService,
    parse_proposal,
    segmentation_prompt,
    segmentation_schema,
)


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = [" First sentence. ", "Second sentence."] if result is None else result
        self.error = error
        self.sources = []

    async def availability(self):
        return ProviderAvailability("deepseek", "DeepSeek", True)

    async def prepare(self, source):
        self.sources.append(source)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def api():
    provider = FakeProvider()
    service = TextPreparationService({"deepseek": provider})
    app.dependency_overrides[get_text_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, provider
    finally:
        app.dependency_overrides.clear()


def test_prepare_api_preserves_exact_source_and_returns_only_proposal(api):
    client, provider = api
    source = "  First sentence.\nSecond sentence.  "
    response = client.post("/api/text/prepare", json={"provider": "deepseek", "sourceText": source})
    assert response.status_code == 200
    assert response.json() == {
        "provider": "deepseek",
        "sourceText": source,
        "sentences": ["First sentence.", "Second sentence."],
    }
    assert provider.sources == [source]


def test_provider_api_does_not_expose_configuration(api):
    client, _ = api
    response = client.get("/api/text/providers")
    assert response.json() == {
        "providers": [{"id": "deepseek", "label": "DeepSeek", "available": True, "reason": None}]
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "invalid", "sourceText": "Secret source"},
        {"provider": "deepseek", "sourceText": "  "},
        {"provider": "deepseek", "sourceText": True},
        {"provider": "deepseek", "sourceText": "x" * 20001},
        {"provider": "deepseek", "sourceText": "😀" * 10001},
        {"provider": "deepseek", "source_text": "Secret source"},
        {"provider": "deepseek", "sourceText": "Secret source", "key": "private key"},
    ],
    ids=["provider", "blank", "type", "long", "utf16-long", "snake-case", "extra"],
)
def test_api_rejects_invalid_input_without_echoing_content(api, payload):
    client, provider = api
    response = client.post("/api/text/prepare", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid text preparation request."}
    assert provider.sources == []


def test_api_rejects_isolated_surrogate(api):
    client, provider = api
    response = client.post(
        "/api/text/prepare",
        content=b'{"provider":"deepseek","sourceText":"\\ud800"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert provider.sources == []


def test_safe_provider_failure_status_is_preserved(api):
    client, provider = api
    provider.error = PreparationError("Provider timed out.", 504)
    response = client.post(
        "/api/text/prepare", json={"provider": "deepseek", "sourceText": "Input"}
    )
    assert response.status_code == 504
    assert response.json() == {"detail": "Provider timed out."}
    assert provider.sources == ["Input"]


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        '```json\n{"sentences":["A."]}\n```',
        '{"sentences":[]}',
        '{"sentences":["  "]}',
        '{"sentences":[1]}',
        '{"sentences":"A."}',
        '{"sentences":["A."],"id":"provider-id"}',
        '{"sentences":["A."],"sentences":["B."]}',
        '{"sentences":["\\ud800"]}',
        json.dumps({"sentences": ["A."] * 501}),
        json.dumps({"sentences": ["x" * 4001]}),
        json.dumps({"sentences": [" " * 4000 + "x"]}),
        json.dumps({"sentences": ["😀" * 2001]}),
        b"x" * (MAX_OUTPUT_BYTES + 1),
    ],
    ids=[
        "malformed",
        "markdown",
        "empty",
        "blank",
        "number",
        "string",
        "extra",
        "duplicate",
        "surrogate",
        "count",
        "long",
        "raw-long",
        "utf16-long",
        "oversized",
    ],
)
def test_strict_proposal_parser_rejects_invalid_or_unbounded_output(content):
    with pytest.raises(PreparationError) as failure:
        parse_proposal(content)
    assert failure.value.status_code == 502


def test_service_revalidates_replacement_adapter_output():
    provider = FakeProvider(result=[" "])
    with pytest.raises(PreparationError):
        asyncio.run(TextPreparationService({"deepseek": provider}).prepare("deepseek", "Source"))
    assert provider.sources == ["Source"]


def test_service_rejects_invalid_source_before_provider():
    provider = FakeProvider()
    for source in ["", " ", "x" * 20001, "😀" * 10001, "\ud800"]:
        with pytest.raises(PreparationError) as failure:
            asyncio.run(TextPreparationService({"deepseek": provider}).prepare("deepseek", source))
        assert failure.value.status_code == 400
    assert provider.sources == []


def test_prompt_and_schema_are_installed_package_resources():
    schema = json.loads(segmentation_schema())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["sentences"]["maxItems"] == 500
    assert schema["properties"]["sentences"]["items"]["maxLength"] == 4000
    assert "untrusted content" in segmentation_prompt()
    assert "human review" in segmentation_prompt()


@pytest.mark.parametrize("timeout", ["0", "111", "nan", "inf", "invalid"])
def test_invalid_timeout_configuration_is_actionable(timeout):
    assert ProviderSettings.from_environment({"TEXT_PROVIDER_TIMEOUT_SECONDS": timeout}).error


def test_blank_codex_executable_uses_path_default():
    assert ProviderSettings.from_environment({"CODEX_EXECUTABLE": "  "}).codex_executable == "codex"
