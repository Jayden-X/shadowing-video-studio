"""Local image import/list/preview; client names are metadata, never filesystem paths."""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from shadowing_video_studio.providers.image_probe import ImageProbe
from shadowing_video_studio.speech_api import get_speech_service, verify_local_request
from shadowing_video_studio.speech_settings import SpeechSettings
from shadowing_video_studio.video_rendering import VideoRenderingError
from shadowing_video_studio.video_settings import VideoSettings
from shadowing_video_studio.visual_assets import VisualAssetError, VisualLibrary

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
FORMATS = ["image/png", "image/jpeg", "image/webp"]
router = APIRouter(prefix="/api/visuals", dependencies=[Depends(verify_local_request)])


class UnavailableImageProbe:
    async def validate(self, _path: Path, _mime_type: str) -> tuple[int, int]:
        raise VisualAssetError(
            "Configure working local FFmpeg/ffprobe tools before uploading.", 503
        )


@dataclass
class VisualService:
    library: VisualLibrary | None
    error: str | None = None

    def readiness(self) -> dict:
        return {
            "available": self.library is not None and self.error is None,
            "reason": self.error,
            "maxUploadBytes": MAX_UPLOAD_BYTES,
            "formats": FORMATS,
        }


def create_visual_service() -> VisualService:
    settings = SpeechSettings.from_environment()
    workspace = settings.workspace
    try:
        if not workspace or not workspace.is_absolute() or not workspace.is_dir():
            raise VisualAssetError(
                "Set SPEECH_WORKSPACE to an existing local media directory.", 503
            )
        if any(
            item.is_symlink() or getattr(item, "is_junction", lambda: False)()
            for item in (workspace, *workspace.parents)
        ):
            raise VisualAssetError("Use a real media directory without symbolic links.", 503)
        workspace = workspace.resolve()
        if settings.model_path:
            model = settings.model_path.resolve()
            if (
                workspace == model
                or workspace.is_relative_to(model)
                or model.is_relative_to(workspace)
            ):
                raise VisualAssetError("Keep media separate from the read-only model cache.", 503)
        tools = VideoSettings.from_environment()
        probe = UnavailableImageProbe()
        error = None
        if all(
            path
            and path.is_absolute()
            and path.is_file()
            and os.access(path, os.X_OK)
            and path.suffix.lower() not in {".cmd", ".bat", ".ps1"}
            for path in (tools.ffmpeg_executable, tools.ffprobe_executable)
        ):
            assert tools.ffmpeg_executable and tools.ffprobe_executable
            probe = ImageProbe(
                tools.ffmpeg_executable.resolve(), tools.ffprobe_executable.resolve()
            )
        else:
            error = "Configure working local FFmpeg/ffprobe tools before uploading."
        return VisualService(VisualLibrary(workspace, probe), error)
    except (VisualAssetError, VideoRenderingError, OSError, ValueError):
        return VisualService(
            None, "The local visual workspace is unavailable. Check its configuration."
        )


def get_visual_service(request: Request) -> VisualService:
    if not hasattr(request.app.state, "visuals"):
        request.app.state.visuals = create_visual_service()
    return request.app.state.visuals


def required_library(service: VisualService) -> VisualLibrary:
    if service.library is None:
        raise HTTPException(status_code=503, detail=service.error or "Visual library unavailable.")
    return service.library


@router.get("/status")
def status(service: Annotated[VisualService, Depends(get_visual_service)]) -> dict:
    return service.readiness()


@router.get("/assets")
def list_assets(service: Annotated[VisualService, Depends(get_visual_service)]) -> dict:
    try:
        return {"assets": required_library(service).list_assets()}
    except VisualAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/assets", status_code=201)
async def upload(
    request: Request,
    service: Annotated[VisualService, Depends(get_visual_service)],
    kind: Literal["background", "illustration"],
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> dict:
    library = required_library(service)
    if service.error:
        raise HTTPException(status_code=503, detail=service.error)
    if length := request.headers.get("content-length"):
        try:
            count = int(length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid image upload length.") from exc
        if count < 0 or count > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Upload an image of at most 10 MiB.")
    gate = get_speech_service(request).gate
    operation_id = uuid.uuid4().hex
    if not gate.claim(operation_id):
        raise HTTPException(
            status_code=409, detail="A local media job is running. Wait before uploading."
        )
    try:
        content = bytearray()
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413, detail="Upload an image of at most 10 MiB."
                    )
                content.extend(chunk)
        asset = await library.import_asset(kind, name, bytes(content))
        return asset.dto()
    except VisualAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=408, detail="Image upload timed out. Retry explicitly."
        ) from exc
    finally:
        gate.release(operation_id)


@router.get("/assets/{asset_id}")
def preview(
    asset_id: str, service: Annotated[VisualService, Depends(get_visual_service)]
) -> Response:
    library = required_library(service)
    try:
        asset = library.get(asset_id)
        content = library.read(asset_id)
        return Response(
            content,
            media_type=asset.mime_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except VisualAssetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
