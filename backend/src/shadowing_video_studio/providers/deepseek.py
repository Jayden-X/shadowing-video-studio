import asyncio
import json

import httpx

from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.text_processing import (
    MAX_OUTPUT_BYTES,
    PreparationError,
    ProviderAvailability,
    parse_proposal,
    segmentation_prompt,
)

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"


class DeepSeekTextProvider:
    def __init__(
        self, settings: ProviderSettings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def availability(self) -> ProviderAvailability:
        reason = self._settings.error or self._settings.deepseek_error
        if not reason and not self._settings.deepseek_api_key:
            reason = "Configure DEEPSEEK_API_KEY on the backend to enable DeepSeek."
        return ProviderAvailability("deepseek", "DeepSeek", reason is None, reason)

    async def prepare(self, source: str) -> list[str]:
        status = await self.availability()
        if not status.available:
            raise PreparationError(status.reason or "DeepSeek is unavailable.", 503)
        payload = {
            "model": self._settings.deepseek_model,
            "messages": [
                {"role": "system", "content": segmentation_prompt()},
                {"role": "user", "content": source},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": 8192,
            "tool_choice": "none",
        }
        try:
            # A total deadline also bounds keep-alive whitespace from an overloaded server.
            async with asyncio.timeout(self._settings.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(self._settings.timeout_seconds, connect=10),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        DEEPSEEK_ENDPOINT,
                        headers={"Authorization": f"Bearer {self._settings.deepseek_api_key}"},
                        json=payload,
                    ) as response:
                        if response.status_code != 200:
                            self._reject_status(response.status_code)
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_OUTPUT_BYTES:
                                raise PreparationError("DeepSeek returned too much output.")
            result = json.loads(body)
            choices = result.get("choices") if isinstance(result, dict) else None
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("Invalid choices")
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                raise ValueError("Incomplete completion")
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("tool_calls"):
                raise ValueError("Unexpected tool output")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty completion")
            return parse_proposal(content)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise PreparationError("DeepSeek timed out. You can try preparing again.", 504) from exc
        except httpx.HTTPError as exc:
            raise PreparationError("Could not reach DeepSeek. Check your connection.", 502) from exc
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise PreparationError("DeepSeek returned an incomplete or invalid response.") from exc

    @staticmethod
    def _reject_status(status: int) -> None:
        if status in (401, 403):
            raise PreparationError(
                "DeepSeek authentication failed. Check the backend API key.", 503
            )
        if status == 402:
            raise PreparationError(
                "DeepSeek has insufficient balance. Check your provider account.", 503
            )
        if status == 429:
            raise PreparationError("DeepSeek is rate limited. Try again later.", 503)
        raise PreparationError("DeepSeek could not prepare the text. Try again later.", 502)
