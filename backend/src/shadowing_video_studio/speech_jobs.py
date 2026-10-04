"""Volatile sentence jobs: freeze input, serialize work, preserve partial success."""

import asyncio
import uuid
from copy import deepcopy
from typing import Any

from shadowing_video_studio.project_commands import ProjectCommand, attempt_job
from shadowing_video_studio.project_store import ProjectError
from shadowing_video_studio.speech import (
    MAX_SESSION_JOBS,
    MAX_SPEECH_SENTENCES,
    MAX_SPEECH_TEXT,
    MAX_SPEECH_TOTAL_TEXT,
    VOICE,
    HeavyJobGate,
    SpeechCapabilities,
    SpeechError,
    SpeechProvider,
    SpeechReadiness,
    SpeechSentence,
)
from shadowing_video_studio.speech_assets import OPAQUE_ID, SpeechAssets, flush_media
from shadowing_video_studio.speech_settings import MAX_NEW_TOKENS, MODEL_REVISION
from shadowing_video_studio.text_processing import text_length


def validate_sentences(sentences: list[SpeechSentence], force: bool) -> None:
    try:
        if not 1 <= len(sentences) <= MAX_SPEECH_SENTENCES or (force and len(sentences) != 1):
            raise ValueError
        seen = set()
        total = 0
        for sentence in sentences:
            if (
                not isinstance(sentence.id, str)
                or not sentence.id.strip()
                or text_length(sentence.id) > 100
                or sentence.id in seen
                or not isinstance(sentence.text, str)
                or not sentence.text.strip()
                or text_length(sentence.text) > MAX_SPEECH_TEXT
            ):
                raise ValueError
            seen.add(sentence.id)
            total += text_length(sentence.text)
        if total > MAX_SPEECH_TOTAL_TEXT:
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SpeechError(
            "Use 1–100 unique sentences, up to 4,000 characters each and 20,000 total; "
            "regenerate one sentence.",
            422,
        ) from exc


class SpeechJobs:
    def __init__(
        self, provider: SpeechProvider, assets: SpeechAssets | None, gate: HeavyJobGate
    ) -> None:
        self.provider = provider
        self.assets = assets
        self.gate = gate
        self._jobs: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task | None = None
        self._closed = False

    async def readiness(self) -> SpeechReadiness:
        return await self.provider.readiness()

    async def capabilities(self) -> SpeechCapabilities:
        return await self.provider.capabilities()

    async def resolve_voice(self, voice: str, configuration_fingerprint: str | None = None) -> str:
        capabilities = await self.capabilities()
        if not capabilities.available:
            raise SpeechError(
                capabilities.reason or "Configure speech before selecting a voice.", 503
            )
        selected = next((item for item in capabilities.voices if item.id == voice), None)
        if selected is None:
            raise SpeechError(
                "This voice is unsupported. Refresh the voice list and select again.", 422
            )
        fingerprint = self.provider.fingerprint_for_voice(voice)
        if selected.configuration_fingerprint != fingerprint or (
            configuration_fingerprint is not None and configuration_fingerprint != fingerprint
        ):
            raise SpeechError(
                "Speech configuration changed. Refresh voices and generate matching audio.", 409
            )
        return fingerprint

    async def submit(
        self,
        sentences: list[SpeechSentence],
        force: bool = False,
        voice: str = VOICE,
        configuration_fingerprint: str | None = None,
        project: ProjectCommand | None = None,
    ) -> dict:
        if project and (replay := await project.replay()) is not None:
            return deepcopy(self._jobs.get(replay["id"], replay))
        sentences = list(sentences)
        validate_sentences(sentences, force)
        if self._closed:
            raise SpeechError("Speech service is stopping. Restart before submitting work.", 503)
        if len(self._jobs) >= MAX_SESSION_JOBS:
            raise SpeechError(
                "This service session has reached its job limit. Restart to continue.", 409
            )
        rows = []
        fingerprint = await self.resolve_voice(voice, configuration_fingerprint)
        # Capability probing yields; shutdown/capacity must still be enforced at acceptance.
        if self._closed:
            raise SpeechError("Speech service is stopping. Restart before submitting work.", 503)
        if len(self._jobs) >= MAX_SESSION_JOBS:
            raise SpeechError(
                "This service session has reached its job limit. Restart to continue.", 409
            )
        for sentence in sentences:
            asset = None
            if self.assets and not force:
                asset = await asyncio.to_thread(
                    self.assets.reusable,
                    sentence,
                    fingerprint,
                    voice,
                    project.project_id if project else None,
                    project.snapshot["documentId"] if project else None,
                )
            rows.append(
                {
                    "id": sentence.id,
                    "text": sentence.text,
                    "voice": voice,
                    "configurationFingerprint": fingerprint,
                    "status": "ready" if asset else "pending",
                    "assetId": asset.id if asset else None,
                    "durationSeconds": asset.duration_seconds if asset else None,
                    "error": None,
                    "reused": asset is not None,
                }
            )
        if self._closed or len(self._jobs) >= MAX_SESSION_JOBS:
            raise SpeechError("Speech service is stopping or has reached its job limit.", 503)
        job_id = uuid.uuid4().hex
        needs_work = any(row["status"] != "ready" for row in rows)
        if needs_work and not self.gate.claim(job_id):
            raise SpeechError("A local media job is already running. Wait for it to finish.", 409)
        try:
            # resolve_voice already checked runtime availability. Accept without
            # another await so shutdown/capacity cannot change after gate claim.
            if needs_work and self.assets is None:
                raise SpeechError("Configure speech before generating audio.", 503)
            attempt = (
                await project.freeze(
                    {
                        "speech": {
                            "fingerprint": fingerprint,
                            "fingerprintVersion": "qwen-cpu-v2",
                            "normalizationVersion": "exact-v1",
                            "modelRevision": MODEL_REVISION,
                            "voice": voice,
                            "language": "English",
                            "backend": "cpu",
                            "dtype": "float32",
                            "attention": "eager",
                            "qwenTts": "0.1.1",
                            "maxNewTokens": MAX_NEW_TOKENS,
                        },
                    }
                )
                if project
                else None
            )
            if attempt:
                previous_owner = job_id
                job_id = attempt["id"]
                if needs_work:
                    self.gate.release(previous_owner)
                    if not self.gate.claim(job_id):
                        raise SpeechError("A local media job is already running.", 409)
            job = {
                "id": job_id,
                "voice": voice,
                "configurationFingerprint": fingerprint,
                "status": "queued" if needs_work else "completed",
                "sentences": rows,
                "error": None,
            }
            if attempt:
                job.update(
                    projectId=attempt["projectId"],
                    documentId=attempt["documentId"],
                    projectRevision=attempt["revision"],
                    submissionToken=project.submission_token,
                )
                await asyncio.to_thread(
                    project.store.update_attempt,
                    job_id,
                    "running" if needs_work else "completed",
                    job,
                )
            self._jobs[job_id] = job
            if needs_work:
                self._task = asyncio.create_task(self._run(job, fingerprint, voice, project))
            return deepcopy(job)
        except BaseException:
            if needs_work:
                self.gate.release(job_id)
            raise

    async def _run(
        self, job: dict, fingerprint: str, voice: str, project: ProjectCommand | None = None
    ) -> None:
        job["status"] = "running"
        try:
            assert self.assets is not None
            for index in range(len(job["sentences"])):
                row = job["sentences"][index]
                if row["status"] == "ready":
                    continue
                row["status"] = "generating"
                try:
                    asset_id, destination = self.assets.allocate()
                    await self.provider.generate(row["text"], destination, voice)
                    asset = await asyncio.to_thread(
                        self.assets.register,
                        asset_id,
                        SpeechSentence(row["id"], row["text"]),
                        fingerprint,
                        destination,
                        voice,
                        project.project_id if project else None,
                        project.snapshot["documentId"] if project else None,
                    )
                    updated = deepcopy(job)
                    updated["sentences"][index].update(
                        status="ready", assetId=asset.id, durationSeconds=asset.duration_seconds
                    )
                    if project:
                        if all(r["status"] in {"ready", "failed"} for r in updated["sentences"]):
                            self._finish(updated)
                        await asyncio.to_thread(flush_media, asset.path)
                        await asyncio.to_thread(
                            project.store.record_speech,
                            job["id"],
                            {
                                "id": asset.id,
                                "sessionId": asset.path.parent.name,
                                "sentenceId": asset.sentence_id,
                                "text": asset.text,
                                "fingerprint": asset.fingerprint,
                                "voice": asset.voice,
                                "durationSeconds": asset.duration_seconds,
                                "sizeBytes": asset.size_bytes,
                                "sha256": asset.sha256,
                            },
                            updated,
                        )
                    job.update(updated)
                except SpeechError as exc:
                    row.update(status="failed", error=exc.detail)
                except ProjectError as exc:
                    row.update(status="failed", error=exc.detail)
                except Exception:
                    row.update(
                        status="failed",
                        error="Speech generation failed. Check the runtime and try again.",
                    )
            self._finish(job)
        except asyncio.CancelledError:
            self._fail_remaining(job, "The speech service stopped. Successful audio is preserved.")
            raise
        except Exception:
            self._fail_remaining(
                job, "Speech generation could not continue. Successful audio is preserved."
            )
        finally:
            if project and job["status"] != "completed":
                try:
                    await asyncio.to_thread(project.store.update_attempt, job["id"], "failed", job)
                except ProjectError:
                    job["error"] = (
                        "Could not save the final task state. Earlier saved audio remains."
                    )
            self.gate.release(job["id"])

    @staticmethod
    def _finish(job: dict) -> None:
        if any(row["status"] == "failed" for row in job["sentences"]):
            job.update(
                status="failed",
                error=(
                    "Some sentences failed. Successful audio is preserved; retry failed sentences."
                ),
            )
        else:
            job.update(status="completed", error=None)

    @staticmethod
    def _fail_remaining(job: dict, detail: str) -> None:
        for row in job["sentences"]:
            if row["status"] not in {"ready", "failed"}:
                row.update(status="failed", error=detail)
        job.update(status="failed", error=detail)

    def get(self, job_id: str) -> dict:
        if not OPAQUE_ID.fullmatch(job_id):
            raise SpeechError("Speech job not found in this service session.", 404)
        if job_id in self._jobs:
            return deepcopy(self._jobs[job_id])
        store = self.assets.store if self.assets else None
        if store:
            try:
                attempt = store.get_attempt(job_id)
                if attempt and attempt["kind"] == "speech":
                    return attempt_job(attempt)
            except ProjectError as exc:
                raise SpeechError(exc.detail, exc.status_code) from exc
        raise SpeechError("Speech job not found.", 404)

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def close(self) -> None:
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.provider.close()
