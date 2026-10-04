"""Video HTTP boundary: frozen sentence/asset IDs only; no client filesystem paths."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from shadowing_video_studio.application_commands import submit_video
from shadowing_video_studio.generation_requests import VideoJobRequest
from shadowing_video_studio.project_store import ProjectStore
from shadowing_video_studio.speech import SpeechError
from shadowing_video_studio.speech_api import get_speech_service, verify_local_request
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.video_jobs import VideoJobError, VideoJobs
from shadowing_video_studio.video_settings import VideoSettings
from shadowing_video_studio.visual_assets import VisualLibrary

router = APIRouter(prefix="/api/video", dependencies=[Depends(verify_local_request)])


def create_video_service(
    speech: SpeechJobs,
    visuals: VisualLibrary | None = None,
    project_store: ProjectStore | None = None,
) -> VideoJobs:
    return VideoJobs(
        VideoSettings.from_environment(), speech, visuals=visuals, project_store=project_store
    )


def get_video_service(request: Request) -> VideoJobs:
    if not hasattr(request.app.state, "video"):
        request.app.state.video = create_video_service(
            get_speech_service(request),
            getattr(getattr(request.app.state, "visuals", None), "library", None),
            getattr(getattr(request.app.state, "projects", None), "store", None),
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
        return await submit_video(service, payload)
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
