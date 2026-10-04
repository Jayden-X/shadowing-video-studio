"""Explicit cleanup of one unused shared image, with persistent retry evidence."""

import asyncio
import re
import uuid
from pathlib import Path

from shadowing_video_studio.project_cleanup import ProjectCleanup
from shadowing_video_studio.project_store import ProjectError
from shadowing_video_studio.visual_assets import KINDS, VisualLibrary

VISUAL_PATH = re.compile(
    r"visuals/(?:backgrounds|illustrations)/[0-9a-f]{32}/(?:asset\.json|image\.(?:png|jpg|webp))"
)


class VisualCleanup(ProjectCleanup):
    def __init__(self, store, gate, library: VisualLibrary):
        super().__init__(store, gate)
        self.library = library

    def _safe_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not VISUAL_PATH.fullmatch(relative):
            raise ProjectError("Untrusted image cleanup file reference.", 409)
        path = self.store.workspace / relative
        for parent in (path, *path.parents):
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise ProjectError("Linked image resources are preserved.", 409)
            if parent == self.store.workspace:
                break
        if path.resolve() != path or not path.is_relative_to(self.store.workspace):
            raise ProjectError("Image cleanup resource is outside its workspace.", 409)
        return path

    def _image_manifest(self, asset_id: str) -> dict:
        self.store.visual_unused(asset_id)
        asset = self.library.get(asset_id)
        relative = asset.path.relative_to(self.store.workspace).as_posix()
        sidecar = asset.path.parent / "asset.json"
        # Unknown contents must be preserved, not guessed to belong to this image.
        if {p.name for p in asset.path.parent.iterdir()} != {asset.path.name, "asset.json"}:
            raise ProjectError("This image folder has unknown files. Resolve them manually.", 409)
        files = [
            self._file(relative),
            self._file(sidecar.relative_to(self.store.workspace).as_posix()),
        ]
        if any(item is None for item in files):
            raise ProjectError("This image changed. Preview cleanup again.", 409)
        return {
            "assetId": asset_id,
            "name": asset.name,
            "kind": asset.kind,
            "delete": files,
            "warnings": [],
        }

    async def preview(self, asset_id: str) -> dict:
        owner = "visual-preview-" + uuid.uuid4().hex
        if not self.gate.claim(owner):
            raise ProjectError("Wait for local media work to finish before cleanup.", 409)
        try:
            plan = await asyncio.to_thread(self._image_manifest, asset_id)
            token = uuid.uuid4().hex
            await asyncio.to_thread(self.store.save_visual_cleanup, token, asset_id, plan)
            return {
                "assetId": asset_id,
                "name": plan["name"],
                "planToken": token,
                "deleteFiles": {
                    "count": len(plan["delete"]),
                    "bytes": sum(f["bytes"] for f in plan["delete"]),
                },
                "warnings": plan["warnings"],
            }
        finally:
            self.gate.release(owner)

    def _execute(self, asset_id: str, token: str) -> dict:
        operation = self.store.visual_cleanup_operation(asset_id, token)
        plan = operation["plan"]
        if plan["assetId"] != asset_id or plan["kind"] not in KINDS:
            raise ProjectError("Invalid image cleanup plan.", 409)
        prefix = f"visuals/{KINDS[plan['kind']]}/{asset_id}/"
        if any(not item["path"].startswith(prefix) for item in plan["delete"]):
            raise ProjectError("This image plan does not own its files.", 409)
        if operation["status"] == "completed":
            return {k: v for k, v in operation["result"].items() if k != "donePaths"}
        if operation["status"] == "planned":
            if self._image_manifest(asset_id) != plan:
                raise ProjectError("Image changed. Preview cleanup again.", 409)
            result = {
                "assetId": asset_id,
                "name": plan["name"],
                "operationToken": token,
                "status": "pending",
                "deletedFiles": 0,
                "failedFiles": 0,
                "warnings": [],
                "error": None,
            }
            # Same transaction rechecks references and blocks later save/freeze choices.
            self.store.update_visual_cleanup(asset_id, token, result, begin=True)
        else:
            result = dict(operation["result"])
        done = set(result.get("donePaths", []))
        failures = 0
        for item in plan["delete"]:
            relative = item["path"]
            if relative in done:
                continue
            try:
                current = self._file(relative)
                if current is not None:
                    if current != item:
                        raise ProjectError("Changed image files are preserved.", 409)
                    self._safe_path(relative).unlink()
                done.add(relative)
            except (ProjectError, OSError):
                failures += 1
            result.update(
                status="pending",
                deletedFiles=len(done),
                failedFiles=failures,
                donePaths=sorted(done),
            )
            self.store.update_visual_cleanup(asset_id, token, result)
        if not failures:
            try:
                # Only remove the exact, empty asset directory. Never recurse.
                directory = self._safe_path(prefix + "asset.json").parent
                if directory.exists():
                    directory.rmdir()
            except (ProjectError, OSError):
                failures += 1
        result.update(
            status="partial" if failures else "completed",
            failedFiles=failures,
            error="Some image files could not be deleted. Retry explicitly." if failures else None,
        )
        self.store.update_visual_cleanup(asset_id, token, result)
        return {k: v for k, v in result.items() if k != "donePaths"}
