"""Session-only AI requests with frozen inputs, human review and at-most-once submission.

Task008 supplies the future durable project port. No project storage is invented here.
"""

import asyncio
import hashlib
import json
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from shadowing_video_studio.application_commands import submit_speech, submit_video
from shadowing_video_studio.generation_requests import SpeechJobRequest, VideoJobRequest
from shadowing_video_studio.speech import SpeechError, SpeechSentence
from shadowing_video_studio.speech_jobs import SpeechJobs, validate_sentences
from shadowing_video_studio.video_jobs import VideoJobError, VideoJobs

Operation = Literal["speech", "video"]
MAX_CONTROL_REQUESTS = 100
REVIEW_SECONDS = 1800


class ControlError(Exception):
    def __init__(self, code: str, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requestId: StrictStr = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    operation: Operation
    payload: SpeechJobRequest | VideoJobRequest


@dataclass
class ReviewRequest:
    id: str
    operation: Operation
    payload: SpeechJobRequest | VideoJobRequest
    input_digest: str
    expires: float
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    state: str = "needs_review"
    result: dict | None = None
    error: dict | None = None
    execution: asyncio.Task | None = None

    def dto(self) -> dict:
        return deepcopy(
            {
                "requestId": self.id,
                "operation": self.operation,
                "state": self.state,
                "reviewPath": f"/control/{self.id}",
                "result": self.result,
                "error": self.error,
            }
        )


class ApplicationControl:
    def __init__(self, speech: SpeechJobs, video: VideoJobs) -> None:
        self.speech = speech
        self.video = video
        self._requests: dict[str, ReviewRequest] = {}
        self._lock = asyncio.Lock()

    async def request_generation(self, request: GenerationRequest) -> dict:
        expected_type = SpeechJobRequest if request.operation == "speech" else VideoJobRequest
        if not isinstance(request.payload, expected_type):
            raise ControlError("invalid_input", "Use the payload for the selected operation.", 422)
        payload = request.payload.model_copy(deep=True)
        validate_sentences(
            [SpeechSentence(item.id, item.text) for item in payload.sentences],
            payload.force if isinstance(payload, SpeechJobRequest) else False,
        )
        digest = hashlib.sha256(
            json.dumps(
                {"operation": request.operation, "payload": payload.model_dump()},
                sort_keys=True,
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        async with self._lock:
            if existing := self._requests.get(request.requestId):
                if existing.input_digest != digest:
                    raise ControlError(
                        "idempotency_conflict", "Use a new requestId for changed inputs."
                    )
                return self.get_request(existing.id)
            if len(self._requests) >= MAX_CONTROL_REQUESTS:
                raise ControlError("session_limit", "This session's review limit is reached.")
            # Freeze the effective configuration before approval, then revalidate at execution.
            payload.configurationFingerprint = await self.speech.resolve_voice(
                payload.voice, payload.configurationFingerprint
            )
            item = ReviewRequest(
                request.requestId,
                request.operation,
                payload,
                digest,
                time.monotonic() + REVIEW_SECONDS,
            )
            self._requests[item.id] = item
            return item.dto()

    def review(self, request_id: str) -> ReviewRequest:
        item = self._requests.get(request_id)
        if item is None:
            raise ControlError("not_found", "Request unavailable in this service session.", 404)
        if item.state in {"needs_review", "approved"} and time.monotonic() >= item.expires:
            item.state = "expired"
        return item

    def get_request(self, request_id: str) -> dict:
        return self.review(request_id).dto()

    def list_reviews(self) -> list[dict]:
        return [self.get_request(request_id) for request_id in self._requests]

    def decide(self, request_id: str, nonce: str, decision: Literal["approve", "reject"]) -> dict:
        item = self.review(request_id)
        if not nonce.isascii() or not secrets.compare_digest(item.nonce, nonce):
            raise ControlError("invalid_review", "Reload the local review page.", 403)
        if item.state != "needs_review":
            raise ControlError("review_closed", "This request is no longer awaiting review.")
        if decision not in {"approve", "reject"}:
            raise ControlError("invalid_review", "Choose approve or reject.", 422)
        item.state = "approved" if decision == "approve" else "rejected"
        item.nonce = secrets.token_urlsafe(32)
        return item.dto()

    async def execute_request(self, request_id: str) -> dict:
        item = self.review(request_id)
        if item.execution is not None:
            await asyncio.shield(item.execution)
            return item.dto()
        if item.state != "approved":
            raise ControlError(
                "review_required", "Review these exact inputs on the local page first."
            )
        # No await between state transition and task ownership; concurrent/reconnected callers
        # share the same submission. Client disconnection cannot cancel accepted submission.
        item.state = "submitting"
        item.execution = asyncio.create_task(self._submit(item))
        await asyncio.shield(item.execution)
        return item.dto()

    async def _submit(self, item: ReviewRequest) -> None:
        try:
            if isinstance(item.payload, SpeechJobRequest):
                item.result = await submit_speech(self.speech, item.payload)
            else:
                item.result = await submit_video(self.video, item.payload)
            item.state = "submitted"
        except (SpeechError, VideoJobError) as exc:
            item.state = "failed"
            item.error = {
                "code": "submission_failed",
                "detail": exc.detail,
                "statusCode": exc.status_code,
            }
        except (Exception, asyncio.CancelledError):
            # Do not expose arbitrary provider errors or automatically repeat unknown effects.
            item.state = "unknown_outcome"
            item.error = {
                "code": "unknown_outcome",
                "detail": "Inspect local jobs before retrying.",
            }

    async def close(self) -> None:
        await asyncio.gather(
            *(item.execution for item in self._requests.values() if item.execution is not None),
            return_exceptions=True,
        )
