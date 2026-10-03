"""Volatile sentence jobs: freeze input, serialize work, preserve partial success."""

import asyncio
import uuid
from copy import deepcopy
from typing import Any

from shadowing_video_studio.speech import (
    MAX_SESSION_JOBS,
    MAX_SPEECH_SENTENCES,
    MAX_SPEECH_TEXT,
    MAX_SPEECH_TOTAL_TEXT,
    HeavyJobGate,
    SpeechError,
    SpeechProvider,
    SpeechReadiness,
    SpeechSentence,
)
from shadowing_video_studio.speech_assets import OPAQUE_ID, SpeechAssets
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

    async def submit(self, sentences: list[SpeechSentence], force: bool = False) -> dict:
        validate_sentences(sentences, force)
        if self._closed:
            raise SpeechError("Speech service is stopping. Restart before submitting work.", 503)
        if len(self._jobs) >= MAX_SESSION_JOBS:
            raise SpeechError(
                "This service session has reached its job limit. Restart to continue.", 409
            )
        rows = []
        fingerprint = self.provider.fingerprint
        for sentence in sentences:
            asset = (
                self.assets.reusable(sentence, fingerprint) if self.assets and not force else None
            )
            rows.append(
                {
                    "id": sentence.id,
                    "text": sentence.text,
                    "status": "ready" if asset else "pending",
                    "assetId": asset.id if asset else None,
                    "durationSeconds": asset.duration_seconds if asset else None,
                    "error": None,
                    "reused": asset is not None,
                }
            )
        job_id = uuid.uuid4().hex
        needs_work = any(row["status"] != "ready" for row in rows)
        if needs_work and not self.gate.claim(job_id):
            raise SpeechError("A local media job is already running. Wait for it to finish.", 409)
        try:
            if needs_work:
                readiness = await self.provider.readiness()
                if not readiness.available or self.assets is None:
                    raise SpeechError(
                        readiness.reason or "Configure speech before generating audio.", 503
                    )
            job = {
                "id": job_id,
                "status": "queued" if needs_work else "completed",
                "sentences": rows,
                "error": None,
            }
            self._jobs[job_id] = job
            if needs_work:
                self._task = asyncio.create_task(self._run(job, fingerprint))
            return deepcopy(job)
        except BaseException:
            if needs_work:
                self.gate.release(job_id)
            raise

    async def _run(self, job: dict, fingerprint: str) -> None:
        job["status"] = "running"
        try:
            assert self.assets is not None
            for row in job["sentences"]:
                if row["status"] == "ready":
                    continue
                row["status"] = "generating"
                try:
                    asset_id, destination = self.assets.allocate()
                    await self.provider.generate(row["text"], destination)
                    asset = self.assets.register(
                        asset_id, SpeechSentence(row["id"], row["text"]), fingerprint, destination
                    )
                    row.update(
                        status="ready", assetId=asset.id, durationSeconds=asset.duration_seconds
                    )
                except SpeechError as exc:
                    row.update(status="failed", error=exc.detail)
                except Exception:
                    row.update(
                        status="failed",
                        error="Speech generation failed. Check the runtime and try again.",
                    )
            if any(row["status"] == "failed" for row in job["sentences"]):
                job.update(
                    status="failed",
                    error="Some sentences failed. Successful audio is preserved; "
                    "retry the failed sentences.",
                )
            else:
                job["status"] = "completed"
        except asyncio.CancelledError:
            self._fail_remaining(job, "The speech service stopped. Successful audio is preserved.")
            raise
        except Exception:
            self._fail_remaining(
                job, "Speech generation could not continue. Successful audio is preserved."
            )
        finally:
            self.gate.release(job["id"])

    @staticmethod
    def _fail_remaining(job: dict, detail: str) -> None:
        for row in job["sentences"]:
            if row["status"] not in {"ready", "failed"}:
                row.update(status="failed", error=detail)
        job.update(status="failed", error=detail)

    def get(self, job_id: str) -> dict:
        if not OPAQUE_ID.fullmatch(job_id) or job_id not in self._jobs:
            raise SpeechError("Speech job not found in this service session.", 404)
        return deepcopy(self._jobs[job_id])

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def close(self) -> None:
        self._closed = True
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.provider.close()
