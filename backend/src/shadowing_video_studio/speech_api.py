"""HTTP DTOs never accept filesystem paths or provider-specific model tensors."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from shadowing_video_studio.application_commands import speech_capabilities, submit_speech
from shadowing_video_studio.generation_requests import SpeechJobRequest
from shadowing_video_studio.providers.qwen import QwenSpeechProvider
from shadowing_video_studio.speech import (
    HeavyJobGate,
    SpeechError,
)
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.speech_settings import SpeechSettings


def verify_local_request(request: Request) -> None:
    """Loopback Host + browser Origin validation blocks DNS rebinding/drive-by POST."""
    loopback = {"127.0.0.1", "localhost", "::1"}
    try:
        if request.url.hostname not in loopback:
            raise ValueError
        if origin := request.headers.get("origin"):
            value = urlsplit(origin)
            if (
                value.hostname not in loopback
                or value.scheme not in {"http", "https"}
                or value.username
                or value.password
                or value.path
                or value.query
                or value.fragment
            ):
                raise ValueError
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="Use the local application to access speech."
        ) from exc


router = APIRouter(prefix="/api/speech", dependencies=[Depends(verify_local_request)])


def create_speech_service(assets: SpeechAssets | None = None) -> SpeechJobs:
    settings = SpeechSettings.from_environment()
    if assets is None:
        try:
            workspace, _ = settings.validated_paths()
            assets = SpeechAssets(workspace)
        except (SpeechError, OSError):
            assets = None
    return SpeechJobs(QwenSpeechProvider(settings, assets), assets, HeavyJobGate())


def get_speech_service(request: Request) -> SpeechJobs:
    # Also supports lightweight clients without a lifespan context; no heavy load.
    if not hasattr(request.app.state, "speech"):
        from shadowing_video_studio.project_api import get_project_service

        request.app.state.speech = create_speech_service(get_project_service(request).assets)
    return request.app.state.speech


@router.get("/status")
async def status(service: Annotated[SpeechJobs, Depends(get_speech_service)]) -> dict:
    item = await service.readiness()
    return {
        "available": item.available,
        "reason": item.reason,
        "voice": item.voice,
        "model": item.model,
        "backend": item.backend,
    }


@router.post("/jobs", status_code=202)
async def submit(
    payload: SpeechJobRequest, service: Annotated[SpeechJobs, Depends(get_speech_service)]
) -> dict:
    try:
        return await submit_speech(service, payload)
    except SpeechError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/capabilities")
async def capabilities(service: Annotated[SpeechJobs, Depends(get_speech_service)]) -> dict:
    return await speech_capabilities(service)


@router.get("/jobs/{job_id}")
def job(job_id: str, service: Annotated[SpeechJobs, Depends(get_speech_service)]) -> dict:
    try:
        return service.get(job_id)
    except SpeechError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/assets/{asset_id}")
def asset(asset_id: str, service: Annotated[SpeechJobs, Depends(get_speech_service)]) -> Response:
    try:
        if not service.assets:
            raise SpeechError("Audio asset not found in this service session.", 404)
        content = service.assets.read(asset_id)
        return Response(content, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    except SpeechError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
