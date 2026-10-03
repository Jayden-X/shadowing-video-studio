"""Provider-neutral proposals; canonical IDs and acceptance belong to the editor."""

import asyncio
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

MAX_SOURCE_CHARACTERS = 20_000
MAX_OUTPUT_BYTES = 128 * 1024
MAX_SENTENCES = 500
MAX_SENTENCE_CHARACTERS = 4_000
ProviderId = Literal["deepseek", "codex"]


def text_length(value: str) -> int:
    """Match browser textarea/JavaScript UTF-16 limits; reject isolated surrogates."""
    return len(value.encode("utf-16-le")) // 2


class PreparationError(Exception):
    """A deliberately safe message/status, never a raw provider exception."""

    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class SentenceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sentences: list[StrictStr] = Field(min_length=1, max_length=MAX_SENTENCES)

    @field_validator("sentences")
    @classmethod
    def validate_sentences(cls, values: list[str]) -> list[str]:
        if any(text_length(value) > MAX_SENTENCE_CHARACTERS for value in values):
            raise ValueError("Invalid sentence length")
        result = [value.strip() for value in values]
        if any(not value for value in result):
            raise ValueError("Invalid sentence length")
        return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def parse_proposal(content: str | bytes) -> list[str]:
    """Validate even when a provider promises JSON/schema-constrained output."""
    try:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        if len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("Oversized output")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        return SentenceProposal.model_validate(payload).sentences
    except (ValueError, TypeError, UnicodeError, RecursionError, ValidationError) as exc:
        raise PreparationError("The provider returned an invalid sentence proposal.") from exc


def validate_proposal(sentences: list[str]) -> list[str]:
    return parse_proposal(json.dumps({"sentences": sentences}, ensure_ascii=False))


def segmentation_prompt() -> str:
    return (
        files("shadowing_video_studio")
        .joinpath("prompts", "segmentation-v1.txt")
        .read_text(encoding="utf-8")
    )


def segmentation_schema() -> str:
    return (
        files("shadowing_video_studio")
        .joinpath("prompts", "segmentation-v1.schema.json")
        .read_text(encoding="utf-8")
    )


@dataclass(frozen=True)
class ProviderAvailability:
    id: ProviderId
    label: str
    available: bool
    reason: str | None = None


class TextProcessingProvider(Protocol):
    async def availability(self) -> ProviderAvailability: ...

    async def prepare(self, source: str) -> list[str]: ...


class TextPreparationService:
    def __init__(self, providers: dict[ProviderId, TextProcessingProvider]) -> None:
        self._providers = providers

    async def availability(self) -> list[ProviderAvailability]:
        return list(
            await asyncio.gather(*(item.availability() for item in self._providers.values()))
        )

    async def prepare(self, provider: ProviderId, source: str) -> list[str]:
        if provider not in self._providers:
            raise PreparationError("Select an available text provider.", 400)
        try:
            valid = bool(source.strip()) and text_length(source) <= MAX_SOURCE_CHARACTERS
        except UnicodeError:
            valid = False
        if not valid:
            raise PreparationError("Enter between 1 and 20,000 characters of source text.", 400)
        # Application validation protects the boundary even if an adapter is replaced.
        return validate_proposal(await self._providers[provider].prepare(source))
