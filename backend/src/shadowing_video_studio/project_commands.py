"""Saved-project commands and durable job DTOs, independent of model availability."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from shadowing_video_studio.project_store import ProjectStore


def attempt_job(attempt: dict[str, Any]) -> dict[str, Any]:
    """Interrupted work is readable through the existing job APIs, never resumed."""
    job = deepcopy(attempt.get("job"))
    if job is None:
        snapshot = attempt["snapshot"]["editor"]
        binding = attempt["snapshot"]["request"]
        terminal = attempt["status"] in {"failed", "interrupted"}
        error = "Generation did not complete. Review the saved project and explicitly retry."
        if attempt["kind"] == "speech":
            sentences = snapshot["document"]["sentences"]
            if selected := binding.get("singleSentenceId"):
                sentences = [item for item in sentences if item["id"] == selected]
            job = {
                "id": attempt["id"],
                "status": "failed" if terminal else "queued",
                "voice": snapshot["voice"],
                "configurationFingerprint": binding["configurationFingerprint"],
                "sentences": [
                    {
                        **item,
                        "voice": snapshot["voice"],
                        "configurationFingerprint": binding["configurationFingerprint"],
                        "status": "failed" if terminal else "pending",
                        "assetId": None,
                        "durationSeconds": None,
                        "error": error if terminal else None,
                        "reused": False,
                    }
                    for item in sentences
                ],
                "error": error if terminal else None,
            }
        else:
            job = {
                "id": attempt["id"],
                "status": "failed" if terminal else "queued",
                "completedSentences": 0,
                "totalSentences": len(snapshot["document"]["sentences"]),
                "assetId": None,
                "durationSeconds": None,
                "error": error if terminal else None,
            }
    job.update(
        projectId=attempt["projectId"],
        documentId=attempt["documentId"],
        projectRevision=attempt["revision"],
        submissionToken=attempt["submissionToken"],
    )
    return job


@dataclass(frozen=True)
class ProjectCommand:
    store: ProjectStore
    project_id: str
    name: str
    snapshot: dict[str, Any]
    expected_revision: int
    submission_token: str
    kind: str
    binding: dict[str, Any]

    async def freeze(self, details: dict | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.store.freeze,
            self.project_id,
            self.name,
            self.snapshot,
            self.expected_revision,
            self.submission_token,
            self.kind,
            self.binding,
            details,
        )

    async def replay(self) -> dict[str, Any] | None:
        existing = await asyncio.to_thread(
            self.store.find_attempt, self.project_id, self.submission_token
        )
        # freeze verifies the original operation digest before returning an existing attempt.
        # Check before model/file preflight so a lost response is queryable after changes.
        if existing is not None:
            return attempt_job(await self.freeze())
        return None
