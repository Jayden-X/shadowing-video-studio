import asyncio
import json

import httpx
import pytest

from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.providers.deepseek import DEEPSEEK_ENDPOINT, DeepSeekTextProvider
from shadowing_video_studio.text_processing import MAX_OUTPUT_BYTES, PreparationError


def completion(content='{"sentences":["First.","Second."]}', finish="stop", **extra):
    return {"choices": [{"finish_reason": finish, "message": {"content": content, **extra}}]}


def provider(handler):
    return DeepSeekTextProvider(
        ProviderSettings(deepseek_api_key="synthetic-test-key"), httpx.MockTransport(handler)
    )


def test_official_request_has_json_contract_and_no_tools():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    source = "  First.\nSecond.  "
    assert asyncio.run(provider(respond).prepare(source)) == ["First.", "Second."]
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == DEEPSEEK_ENDPOINT
    assert request.headers["Authorization"] == "Bearer synthetic-test-key"
    payload = json.loads(request.content)
    assert payload["messages"][1] == {"role": "user", "content": source}
    assert "json" in payload["messages"][0]["content"].lower()
    assert payload["model"] == "deepseek-flash"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tool_choice"] == "none" and "tools" not in payload
    assert payload["stream"] is False


def test_missing_configuration_is_unavailable_without_network():
    item = DeepSeekTextProvider(ProviderSettings())
    assert not asyncio.run(item.availability()).available
    with pytest.raises(PreparationError) as failure:
        asyncio.run(item.prepare("Source"))
    assert failure.value.status_code == 503


@pytest.mark.parametrize(
    "body",
    [
        completion(finish="length"),
        completion(finish="content_filter"),
        completion(finish="aborted"),
        completion(content=""),
        completion(content=None),
        completion(content='{"sentences":["A"],"extra":true}'),
        completion(tool_calls=[{"function": {"name": "execute"}}]),
        {"choices": []},
        {"choices": [None]},
        {},
        [],
    ],
)
def test_invalid_completion_is_rejected(body):
    with pytest.raises(PreparationError) as failure:
        asyncio.run(provider(lambda _: httpx.Response(200, json=body)).prepare("Source"))
    assert failure.value.status_code == 502


@pytest.mark.parametrize(
    "status,expected", [(401, 503), (403, 503), (402, 503), (429, 503), (500, 502)]
)
def test_http_failures_are_safe_and_not_retried(status, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="private token and dialogue")

    with pytest.raises(PreparationError) as failure:
        asyncio.run(provider(respond).prepare("Source"))
    assert failure.value.status_code == expected
    assert "private" not in failure.value.detail
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body", [b"not-json", b"x" * (MAX_OUTPUT_BYTES + 1)], ids=["malformed", "oversized"]
)
def test_malformed_or_large_transport_output(body):
    with pytest.raises(PreparationError):
        asyncio.run(provider(lambda _: httpx.Response(200, content=body)).prepare("Source"))


def test_provider_timeout_is_safe():
    def timeout(_request):
        raise httpx.ReadTimeout("private diagnostic")

    with pytest.raises(PreparationError) as failure:
        asyncio.run(provider(timeout).prepare("Source"))
    assert failure.value.status_code == 504
    assert "private" not in failure.value.detail


def test_redirect_is_not_followed():
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://untrusted.invalid"})

    with pytest.raises(PreparationError):
        asyncio.run(provider(redirect).prepare("Source"))
    assert len(calls) == 1
