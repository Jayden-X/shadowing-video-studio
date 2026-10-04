"""Explicit, journaled deletion of project-owned files; no recursive directory deletion."""

import asyncio
import hashlib
import os
import re
import stat
import uuid
from collections.abc import Callable
from pathlib import Path

from shadowing_video_studio.project_store import ProjectError, ProjectStore
from shadowing_video_studio.speech import HeavyJobGate, SpeechError
from shadowing_video_studio.speech_assets import SpeechAssets

MODES = {"project_only", "intermediate", "all"}
SPEECH_PATH = re.compile(r"speech/[0-9a-f]{32}/[0-9a-f]{32}\.wav")
VIDEO_PATH = re.compile(
    r"video/[0-9a-f]{32}/(?:input-\d{4}\.wav|visual-\d{4}\.(?:png|jpg|webp)|"
    r"render/(?:video\.mp4|font\.ttf|pages\.txt|(?:audio|page)-\d{4}\.(?:wav|txt|mp4|mkv)|"
    r"visual-\d{4}\.(?:png|jpg|webp)))"
)
MAX_FILES = 10_000
MAX_FILE_BYTES = 512 * 1024 * 1024


class ProjectCleanup:
    def __init__(
        self,
        store: ProjectStore,
        gate: HeavyJobGate,
        on_deleted: Callable[[list[dict]], None] | None = None,
    ):
        self.store = store
        self.gate = gate
        self.on_deleted = on_deleted

    def _safe_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not (
            SPEECH_PATH.fullmatch(relative) or VIDEO_PATH.fullmatch(relative)
        ):
            raise ProjectError("Untrusted cleanup file reference.", 409)
        path = self.store.workspace / relative
        for parent in (path, *path.parents):
            if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                raise ProjectError(
                    "Linked cleanup resources are preserved; resolve them manually.", 409
                )
            if parent == self.store.workspace:
                break
        if path.resolve() != path or not path.is_relative_to(self.store.workspace):
            raise ProjectError("Cleanup resource is outside its workspace.", 409)
        return path

    def _file(self, relative: str) -> dict | None:
        path = self._safe_path(relative)
        try:
            before = path.stat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ProjectError("Nonregular or shared hardlinked files are preserved.", 409)
        if not 0 <= before.st_size <= MAX_FILE_BYTES:
            raise ProjectError("Cleanup file exceeds the bounded file limit.", 409)
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ProjectError("Cleanup file changed. Preview deletion again.", 409)
            total = 0
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise ProjectError("Cleanup file grew beyond its limit.", 409)
                digest.update(chunk)
        after = path.stat()

        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)

        if identity(before) != identity(after) or total != before.st_size:
            raise ProjectError("Cleanup file changed. Preview deletion again.", 409)
        return {
            "path": relative,
            "bytes": total,
            "sha256": digest.hexdigest(),
            "device": before.st_dev,
            "inode": before.st_ino,
            "mtime": before.st_mtime_ns,
        }

    def _manifest(self, project_id: str, mode: str) -> dict:
        if mode not in MODES:
            raise ProjectError("Choose one of the three cleanup modes.")
        records = self.store.cleanup_records(project_id)
        if any(a["status"] in {"accepted", "running"} for a in records["attempts"]):
            raise ProjectError("Wait for project generation to finish before deleting.", 409)
        candidates = set(records["ownedSpeech"])
        candidates.update(f"speech/{a['sessionId']}/{a['id']}.wav" for a in records["audio"])
        warnings = list(records["warnings"])
        retained_unknown = {"count": 0, "bytes": 0}
        for attempt in records["attempts"]:
            if attempt["kind"] != "video":
                continue
            job = self.store.workspace / "video" / attempt["id"]
            for folder in (job, job / "render"):
                # Check directory ancestry without following a symlink/junction.
                for parent in (folder, *folder.parents):
                    if parent.is_symlink() or (
                        hasattr(parent, "is_junction") and parent.is_junction()
                    ):
                        raise ProjectError("Unsafe video directory is preserved.", 409)
                    if parent == self.store.workspace:
                        break
                if not folder.exists():
                    continue
                if not folder.is_dir() or folder.resolve() != folder:
                    raise ProjectError("Unsafe video directory is preserved.", 409)
                with os.scandir(folder) as entries:
                    for entry in entries:
                        relative = Path(entry.path).relative_to(self.store.workspace).as_posix()
                        if VIDEO_PATH.fullmatch(relative):
                            candidates.add(relative)
                        elif not (
                            folder == job
                            and entry.name == "render"
                            and entry.is_dir(follow_symlinks=False)
                        ):
                            retained_unknown["count"] += 1
                            if entry.is_file(follow_symlinks=False):
                                retained_unknown["bytes"] += entry.stat(
                                    follow_symlinks=False
                                ).st_size
        if len(candidates) > MAX_FILES:
            raise ProjectError("This cleanup exceeds the bounded file limit.", 409)
        if retained_unknown["count"]:
            warnings.append(
                "Unknown files in render folders are retained, not recursively deleted."
            )
        foreign = set(records["foreignSpeech"])
        delete, retain = [], []
        for relative in sorted(candidates):
            try:
                item = self._file(relative)
            except (ProjectError, OSError):
                warnings.append(
                    "An unsafe or unreadable resource is retained. Resolve it manually."
                )
                retained_unknown["count"] += 1
                continue
            if item is None:
                continue
            final = relative.endswith("/render/video.mp4")
            eligible = mode == "all" or (mode == "intermediate" and not final)
            if relative in foreign:
                eligible = False
                warnings.append("A resource referenced by another project is retained.")
            (delete if eligible else retain).append(item)
        return {
            "projectId": project_id,
            "projectName": records["name"],
            "mode": mode,
            "revision": records["revision"],
            "delete": delete,
            "retain": retain,
            "unknown": retained_unknown,
            "warnings": list(dict.fromkeys(warnings)),
        }

    async def preview(self, project_id: str, mode: str, expected_revision: int) -> dict:
        owner = "cleanup-preview-" + uuid.uuid4().hex
        if not self.gate.claim(owner):
            raise ProjectError("Wait for local media work to finish before cleanup.", 409)
        try:
            await asyncio.to_thread(self.store.get, project_id)
            plan = await asyncio.to_thread(self._manifest, project_id, mode)
            if plan["revision"] != expected_revision:
                raise ProjectError("Project changed. Save and preview deletion again.", 409)
            token = uuid.uuid4().hex
            await asyncio.to_thread(self.store.save_cleanup_plan, token, project_id, mode, plan)
            return {key: plan[key] for key in ("projectId", "projectName", "mode", "revision")} | {
                "planToken": token,
                "deleteFiles": {
                    "count": len(plan["delete"]),
                    "bytes": sum(p["bytes"] for p in plan["delete"]),
                },
                "retainFiles": {
                    "count": len(plan["retain"]) + plan["unknown"]["count"],
                    "bytes": sum(p["bytes"] for p in plan["retain"]) + plan["unknown"]["bytes"],
                },
                "warnings": plan["warnings"]
                + ["Shared image-library originals are always retained."],
            }
        finally:
            self.gate.release(owner)

    async def execute(self, project_id: str, plan_token: str) -> dict:
        owner = "cleanup-" + uuid.uuid4().hex
        if not self.gate.claim(owner):
            raise ProjectError("Wait for local media work to finish before cleanup.", 409)
        try:

            async def run():
                result = await asyncio.to_thread(self._execute, project_id, plan_token)
                if self.on_deleted is not None:
                    operation = await asyncio.to_thread(
                        self.store.cleanup_operation, project_id, plan_token
                    )
                    done = set(operation["result"].get("donePaths", []))
                    self.on_deleted([f for f in operation["plan"]["delete"] if f["path"] in done])
                return result

            task = asyncio.create_task(run())
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # An HTTP disconnect must not release the generation gate while the
                # deletion thread is still operating on its journal and media files.
                await task
                raise
        finally:
            self.gate.release(owner)

    def _execute(self, project_id: str, token: str) -> dict:
        operation = self.store.cleanup_operation(project_id, token)
        plan = operation["plan"]
        if operation["status"] == "completed":
            return {k: v for k, v in operation["result"].items() if k != "donePaths"}
        if operation["status"] == "planned":
            current = self._manifest(project_id, operation["mode"])
            if current != plan:
                raise ProjectError("Resources or project changed. Preview deletion again.", 409)
            result = {
                "projectId": project_id,
                "projectName": plan["projectName"],
                "mode": plan["mode"],
                "operationToken": token,
                "status": "pending",
                "deletedFiles": 0,
                "failedFiles": 0,
                "warnings": plan["warnings"],
                "error": None,
            }
            self.store.begin_cleanup(project_id, token, plan["revision"], result)
        else:
            result = dict(operation["result"])
        records = self.store.cleanup_records(project_id)
        if records["cleanupToken"] != token:
            raise ProjectError("This plan does not own the project's deletion.", 409)
        trusted = self._manifest(project_id, plan["mode"])
        eligible = {item["path"] for item in trusted["delete"]}
        done = set(result.get("donePaths", []))
        failures = 0
        for item in plan["delete"]:
            relative = item["path"]
            if relative in done:
                continue
            try:
                current = self._file(relative)
                if current is not None:
                    if current != item or relative not in eligible:
                        raise ProjectError("Changed or newly shared resources are preserved.", 409)
                    self._safe_path(relative).unlink()
                done.add(relative)
            except (OSError, ProjectError):
                failures += 1
            result.update(
                status="pending",
                deletedFiles=len(done),
                failedFiles=failures,
                donePaths=sorted(done),
            )
            self.store.update_cleanup(project_id, token, result)
        result.update(
            status="partial" if failures else "completed",
            failedFiles=failures,
            error="Some files could not be deleted. Retry cleanup explicitly."
            if failures
            else None,
        )
        self.store.update_cleanup(project_id, token, result)
        return {k: v for k, v in result.items() if k != "donePaths"}

    async def retained(self) -> dict:
        return await asyncio.to_thread(self._retained)

    def _retained(self) -> dict:
        projects = []
        assets = SpeechAssets(self.store.workspace, self.store)
        for project_id in self.store.retained_ids():
            records = self.store.cleanup_records(project_id)
            operation = self.store.cleanup_operation(project_id, records["cleanupToken"])
            mode, status = operation["mode"], operation["status"]
            if mode == "all" and status == "completed":
                continue
            audio = []
            if mode == "project_only" or status != "completed":
                for item in records["audio"]:
                    available, reason = True, None
                    try:
                        assets.read(item["id"])
                    except (SpeechError, OSError):
                        available, reason = False, "Audio is missing, unsafe or changed."
                    audio.append(
                        {
                            k: item[k]
                            for k in (
                                "id",
                                "sentenceId",
                                "text",
                                "voice",
                                "durationSeconds",
                                "sizeBytes",
                            )
                        }
                        | {"available": available, "reason": reason}
                    )
            videos = []
            for item in records["videos"]:
                available, reason = True, None
                try:
                    actual = self._file(f"video/{item['jobId']}/render/video.mp4")
                    if actual is None or (actual["bytes"], actual["sha256"]) != (
                        item["sizeBytes"],
                        item["sha256"],
                    ):
                        raise ProjectError("Historical video unavailable.")
                except (ProjectError, OSError):
                    available, reason = False, "Video is missing, unsafe or changed."
                videos.append(item | {"available": available, "reason": reason})
            cleanup = operation["result"] or {}
            cleanup = {k: v for k, v in cleanup.items() if k != "donePaths"}
            projects.append(
                {
                    "projectId": project_id,
                    "projectName": records["name"],
                    "mode": mode,
                    "deletedAt": records["deletedAt"],
                    "cleanup": cleanup,
                    "audio": audio,
                    "videos": videos,
                }
            )
        return {"projects": projects}
