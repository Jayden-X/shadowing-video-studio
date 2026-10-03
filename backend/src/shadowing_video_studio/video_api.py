"""Video HTTP boundary: frozen sentence/asset IDs only; no client filesystem paths."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from shadowing_video_studio.speech import MAX_SPEECH_SENTENCES, SpeechError
from shadowing_video_studio.speech_api import get_speech_service, verify_local_request
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.video_jobs import VideoJobError, VideoJobs, VideoSentenceSelection
from shadowing_video_studio.video_settings import VideoSettings
from shadowing_video_studio.visual_assets import VisualLibrary

router = APIRouter(prefix="/api/video", dependencies=[Depends(verify_local_request)])


class VideoSentenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr = Field(min_length=1, max_length=100)
    text: StrictStr = Field(min_length=1, max_length=4000)
    assetId: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
    illustrationAssetId: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class VideoJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sentences: list[VideoSentenceRequest] = Field(min_length=1, max_length=MAX_SPEECH_SENTENCES)
    backgroundAssetId: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


def create_video_service(speech: SpeechJobs, visuals: VisualLibrary | None = None) -> VideoJobs:
    return VideoJobs(VideoSettings.from_environment(), speech, visuals=visuals)


def get_video_service(request: Request) -> VideoJobs:
    if not hasattr(request.app.state, "video"):
        request.app.state.video = create_video_service(
            get_speech_service(request),
            getattr(getattr(request.app.state, "visuals", None), "library", None),
        )
    return request.app.state.video


@router.get("/status")
async def status(service: Annotated[VideoJobs, Depends(get_video_service)]) -> dict:
    return await service.readiness()


@router.post("/jobs", status_code=202)
async def submit(
    payload: VideoJobRequest, service: Annotated[VideoJobs, Depends(get_video_service)]
) -> dict:
    try:
        return await service.submit(
            [
                VideoSentenceSelection(item.id, item.text, item.assetId, item.illustrationAssetId)
                for item in payload.sentences
            ],
            background_asset_id=payload.backgroundAssetId,
        )
    except (VideoJobError, SpeechError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/jobs/{job_id}")
def job(job_id: str, service: Annotated[VideoJobs, Depends(get_video_service)]) -> dict:
    try:
        return service.get(job_id)
    except VideoJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/assets/{asset_id}")
def asset(
    asset_id: str, service: Annotated[VideoJobs, Depends(get_video_service)], download: bool = False
) -> FileResponse:
    try:
        item = service.asset(asset_id)
        return FileResponse(
            item.path,
            media_type="video/mp4",
            filename=f"shadowing-{item.id}.mp4",
            content_disposition_type="attachment" if download else "inline",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    except VideoJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
