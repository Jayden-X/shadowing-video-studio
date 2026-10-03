from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from shadowing_video_studio.provider_settings import ProviderSettings
from shadowing_video_studio.providers.codex import CodexTextProvider
from shadowing_video_studio.providers.deepseek import DeepSeekTextProvider
from shadowing_video_studio.text_processing import (
    MAX_SOURCE_CHARACTERS,
    PreparationError,
    ProviderId,
    TextPreparationService,
    text_length,
)

router = APIRouter(prefix="/api/text")


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: ProviderId
    source_text: StrictStr = Field(
        alias="sourceText", min_length=1, max_length=MAX_SOURCE_CHARACTERS
    )

    @field_validator("source_text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip() or text_length(value) > MAX_SOURCE_CHARACTERS:
            raise ValueError("Invalid source text")
        return value


class PrepareResponse(BaseModel):
    provider: ProviderId
    source_text: str = Field(alias="sourceText")
    sentences: list[str]


def get_text_service() -> TextPreparationService:
    settings = ProviderSettings.from_environment()
    return TextPreparationService(
        {"deepseek": DeepSeekTextProvider(settings), "codex": CodexTextProvider(settings)}
    )


@router.get("/providers")
async def providers(service: Annotated[TextPreparationService, Depends(get_text_service)]) -> dict:
    status = await service.availability()
    return {
        "providers": [
            {"id": item.id, "label": item.label, "available": item.available, "reason": item.reason}
            for item in status
        ]
    }


@router.post("/prepare", response_model=PrepareResponse)
async def prepare(
    request: PrepareRequest, service: Annotated[TextPreparationService, Depends(get_text_service)]
) -> PrepareResponse:
    try:
        sentences = await service.prepare(request.provider, request.source_text)
    except PreparationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return PrepareResponse(
        provider=request.provider, sourceText=request.source_text, sentences=sentences
    )
