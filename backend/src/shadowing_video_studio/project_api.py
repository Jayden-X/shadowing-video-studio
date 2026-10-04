"""Local saved-project API: metadata is authoritative, browser values are hints."""

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from shadowing_video_studio.project_commands import ProjectCommand
from shadowing_video_studio.project_store import ProjectError, ProjectStore, validate_snapshot
from shadowing_video_studio.speech import SpeechError, SpeechSentence
from shadowing_video_studio.speech_api import get_speech_service, verify_local_request
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.speech_settings import SpeechSettings
from shadowing_video_studio.video_api import get_video_service
from shadowing_video_studio.video_jobs import VideoJobError, VideoJobs, VideoSentenceSelection

router = APIRouter(prefix="/api/projects", dependencies=[Depends(verify_local_request)])
TOKEN = r"^[0-9a-f]{32}$"


@dataclass
class ProjectService:
    store: ProjectStore | None
    assets: SpeechAssets | None
    error: str | None = None


def create_project_service() -> ProjectService:
    settings = SpeechSettings.from_environment()
    configured = settings.workspace
    if configured is None:
        return ProjectService(None, None, "Configure the local media workspace to save projects.")
    workspace = Path(configured)
    try:
        if settings.model_path:
            model = settings.model_path.resolve()
            resolved = workspace.resolve()
            if (
                resolved == model
                or resolved.is_relative_to(model)
                or model.is_relative_to(resolved)
            ):
                raise ProjectError(
                    "Keep project storage separate from the read-only model cache.", 503
                )
        store = ProjectStore(workspace)
        return ProjectService(store, SpeechAssets(workspace, store))
    except (ProjectError, OSError, ValueError) as exc:
        detail = (
            exc.detail if isinstance(exc, ProjectError) else "The project workspace is unavailable."
        )
        return ProjectService(None, None, detail)


def get_project_service(request: Request) -> ProjectService:
    lock = request.app.state._state.setdefault("project_initialization_lock", threading.Lock())
    with lock:
        if not hasattr(request.app.state, "projects"):
            request.app.state.projects = create_project_service()
        return request.app.state.projects


def get_store(service: Annotated[ProjectService, Depends(get_project_service)]) -> ProjectStore:
    if service.store is None:
        raise HTTPException(
            status_code=503, detail=service.error or "Project storage is unavailable."
        )
    return service.store


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operationToken: StrictStr = Field(pattern=TOKEN)
    name: StrictStr = Field(min_length=1, max_length=120)
    snapshot: dict[str, Any]

    @field_validator("snapshot")
    @classmethod
    def editor_snapshot(cls, value: dict) -> dict:
        try:
            return validate_snapshot(value)
        except ProjectError as exc:
            raise ValueError("Invalid project snapshot.") from exc


class ProjectSaveRequest(ProjectCreateRequest):
    expectedRevision: StrictInt = Field(ge=1)


class ProjectSpeechRequest(ProjectSaveRequest):
    configurationFingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    singleSentenceId: StrictStr | None = Field(default=None, min_length=1, max_length=100)


class ProjectVideoRequest(ProjectSaveRequest):
    configurationFingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    audioAssetIds: dict[StrictStr, StrictStr]


def command(
    store: ProjectStore, project_id: str, payload: ProjectSaveRequest, kind: str
) -> ProjectCommand:
    fields = payload.model_dump(exclude={"operationToken", "expectedRevision", "name", "snapshot"})
    return ProjectCommand(
        store,
        project_id,
        payload.name,
        payload.snapshot,
        payload.expectedRevision,
        payload.operationToken,
        kind,
        fields,
    )


def project_failure(exc: ProjectError | SpeechError | VideoJobError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("")
async def list_projects(store: Annotated[ProjectStore, Depends(get_store)]) -> dict:
    try:
        return {"projects": await asyncio.to_thread(store.list_projects)}
    except ProjectError as exc:
        raise project_failure(exc) from exc


@router.post("", status_code=201)
async def create(
    payload: ProjectCreateRequest, store: Annotated[ProjectStore, Depends(get_store)]
) -> dict:
    try:
        return await asyncio.to_thread(
            store.create, payload.name, payload.snapshot, payload.operationToken
        )
    except ProjectError as exc:
        raise project_failure(exc) from exc


@router.put("/{project_id}")
async def save(
    project_id: str, payload: ProjectSaveRequest, store: Annotated[ProjectStore, Depends(get_store)]
) -> dict:
    try:
        return await asyncio.to_thread(
            store.save,
            project_id,
            payload.name,
            payload.snapshot,
            payload.expectedRevision,
            payload.operationToken,
        )
    except ProjectError as exc:
        raise project_failure(exc) from exc


@router.get("/{project_id}")
async def open_project(
    project_id: str,
    store: Annotated[ProjectStore, Depends(get_store)],
    speech: Annotated[SpeechJobs, Depends(get_speech_service)],
    video: Annotated[VideoJobs, Depends(get_video_service)],
) -> dict:
    try:
        project = await asyncio.to_thread(store.get, project_id)
        snapshot = project["snapshot"]
        warnings: list[str] = []
        audio: list[dict] = []
        # Frozen historical files stay playable even when the current model is unavailable.
        fingerprint = speech.provider.fingerprint_for_voice(snapshot["voice"])
        for sentence in snapshot["document"]["sentences"]:
            candidates = await asyncio.to_thread(
                store.speech_candidates,
                project_id,
                snapshot["documentId"],
                sentence["id"],
                sentence["text"],
                fingerprint,
                snapshot["voice"],
            )
            asset = None
            for index, record in enumerate(candidates):
                try:
                    if not speech.assets:
                        break
                    asset = await asyncio.to_thread(
                        speech.assets.match,
                        record["id"],
                        SpeechSentence(sentence["id"], sentence["text"]),
                        fingerprint,
                        snapshot["voice"],
                        project_id,
                        snapshot["documentId"],
                    )
                    if index:
                        warnings.append(
                            "A newer audio file is unavailable; "
                            "restored an earlier matching recording."
                        )
                    break
                except SpeechError:
                    continue
            if asset:
                audio.append(
                    {
                        **sentence,
                        "voice": asset.voice,
                        "configurationFingerprint": fingerprint,
                        "status": "ready",
                        "assetId": asset.id,
                        "durationSeconds": asset.duration_seconds,
                        "error": None,
                        "reused": True,
                    }
                )
            elif candidates:
                warnings.append(
                    f"Saved audio for {sentence['id']} is unavailable. Explicitly regenerate it."
                )
        history = await asyncio.to_thread(store.history, project_id)
        for output in history:
            if output.get("available") is False:
                warnings.append(output["reason"])
                continue
            try:
                await asyncio.to_thread(video.asset, output["id"])
                output.update(available=True, reason=None)
            except VideoJobError as exc:
                output.update(available=False, reason=exc.detail)
        try:
            attempts = await asyncio.to_thread(store.attempts, project_id)
        except ProjectError:
            attempts = []
            warnings.append(
                "Some saved task metadata is unreadable. The editor and files are preserved."
            )
        if len(audio) < len(snapshot["document"]["sentences"]) and any(
            item["kind"] == "speech" and item["documentId"] == snapshot["documentId"]
            for item in attempts
        ):
            warnings.append(
                "Some saved audio is missing or no longer matches the current voice/configuration. "
                "Explicitly regenerate it."
            )
        if service_visuals := video.visuals:
            selections = [(snapshot["backgroundAssetId"], "background")]
            selections.extend(
                (value, "illustration") for value in snapshot["illustrationsBySentence"].values()
            )
            for asset_id, kind in set(selections):
                if asset_id is not None:
                    from shadowing_video_studio.visual_assets import VisualAssetError

                    try:
                        await asyncio.to_thread(service_visuals.get, asset_id, kind)
                    except VisualAssetError:
                        warnings.append(
                            "A saved image is unavailable. Reselect or upload it before export."
                        )
        elif snapshot["backgroundAssetId"] or snapshot["illustrationsBySentence"]:
            warnings.append("The image library is unavailable; saved image choices are retained.")
        project.update(
            audio=audio,
            warnings=list(dict.fromkeys(warnings)),
            history=history,
            attempts=attempts,
        )
        return project
    except (ProjectError, SpeechError) as exc:
        raise project_failure(exc) from exc


@router.get("/{project_id}/attempts/{submission_token}")
async def attempt(
    project_id: str, submission_token: str, store: Annotated[ProjectStore, Depends(get_store)]
) -> dict:
    try:
        result = await asyncio.to_thread(store.find_attempt, project_id, submission_token)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Submission has not been confirmed. Do not automatically retry.",
            )
        return result
    except ProjectError as exc:
        raise project_failure(exc) from exc


@router.post("/{project_id}/speech", status_code=202)
async def generate_speech(
    project_id: str,
    payload: ProjectSpeechRequest,
    store: Annotated[ProjectStore, Depends(get_store)],
    service: Annotated[SpeechJobs, Depends(get_speech_service)],
) -> dict:
    try:
        snapshot = payload.snapshot
        sentences = snapshot["document"]["sentences"]
        if not snapshot["hasPrepared"]:
            raise SpeechError("Review and prepare the sentences before generating speech.", 422)
        if payload.singleSentenceId is not None:
            sentences = [row for row in sentences if row["id"] == payload.singleSentenceId]
        return await service.submit(
            [SpeechSentence(row["id"], row["text"]) for row in sentences],
            payload.singleSentenceId is not None,
            snapshot["voice"],
            payload.configurationFingerprint,
            command(store, project_id, payload, "speech"),
        )
    except (ProjectError, SpeechError) as exc:
        raise project_failure(exc) from exc


@router.post("/{project_id}/video", status_code=202)
async def generate_video(
    project_id: str,
    payload: ProjectVideoRequest,
    store: Annotated[ProjectStore, Depends(get_store)],
    service: Annotated[VideoJobs, Depends(get_video_service)],
) -> dict:
    try:
        snapshot = payload.snapshot
        if not snapshot["hasPrepared"]:
            raise VideoJobError("Review the prepared sentences before exporting.", 422)
        sentences = snapshot["document"]["sentences"]
        if set(payload.audioAssetIds) != {row["id"] for row in sentences}:
            raise VideoJobError("Select matching speech for every current sentence.", 422)
        return await service.submit(
            [
                VideoSentenceSelection(
                    row["id"],
                    row["text"],
                    payload.audioAssetIds[row["id"]],
                    snapshot["illustrationsBySentence"].get(row["id"]),
                )
                for row in sentences
            ],
            snapshot["backgroundAssetId"],
            snapshot["voice"],
            payload.configurationFingerprint,
            command(store, project_id, payload, "video"),
        )
    except (ProjectError, SpeechError, VideoJobError) as exc:
        raise project_failure(exc) from exc
