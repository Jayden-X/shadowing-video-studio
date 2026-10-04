import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from test_projects import (
    FINGERPRINT,
    Services,
    create_project,
    sentence,
    snapshot,
    speech_request,
)
from test_visual_assets import FakeProbe, png

from shadowing_video_studio.project_api import get_project_service
from shadowing_video_studio.project_api import router as project_router
from shadowing_video_studio.project_store import SCHEMA, ProjectError, ProjectStore
from shadowing_video_studio.speech_api import get_speech_service
from shadowing_video_studio.speech_api import router as speech_router
from shadowing_video_studio.video_api import get_video_service
from shadowing_video_studio.video_api import router as video_router
from shadowing_video_studio.visual_api import (
    VisualService,
    get_visual_service,
)
from shadowing_video_studio.visual_api import (
    router as visual_router,
)
from shadowing_video_studio.visual_assets import VisualLibrary
from shadowing_video_studio.visual_cleanup import VisualCleanup


async def generate_project_media(client, services, index, background_id):
    if not getattr(services, "_cleanup_renderer_wrapped", False):
        render = services.renderer.render

        async def render_with_intermediate(sentences, directory, **kwargs):
            result = await render(sentences, directory, **kwargs)
            (directory / "page-0001.mkv").write_bytes(b"synthetic render intermediate")
            return result

        services.renderer.render = render_with_intermediate
        services._cleanup_renderer_wrapped = True
    token = format(index, "x")
    editor = snapshot(
        [sentence("sentence-001", f"Cleanup fixture {index}.")],
        source_text=f"Cleanup fixture {index}.",
        background=background_id,
    )
    project = await create_project(
        client, editor, operation_token=token * 32, name=f"Cleanup {index}"
    )
    speech = await client.post(
        f"/api/projects/{project['id']}/speech",
        json=speech_request(editor, format(index + 3, "x") * 32, project_name=project["name"]),
    )
    assert speech.status_code == 202, speech.text
    await services.speech.wait()
    audio_id = services.speech.get(speech.json()["id"])["sentences"][0]["assetId"]

    video = await client.post(
        f"/api/projects/{project['id']}/video",
        json={
            "operationToken": format(index + 6, "x") * 32,
            "name": project["name"],
            "snapshot": editor,
            "expectedRevision": 1,
            "configurationFingerprint": FINGERPRINT,
            "audioAssetIds": {"sentence-001": audio_id},
        },
    )
    assert video.status_code == 202, video.text
    await services.video.wait()
    video_job = services.video.get(video.json()["id"])
    assert video_job["status"] == "completed"

    audio_record = services.store.speech_asset(audio_id)
    video_record = services.store.video_asset(video_job["assetId"])
    audio_path = services.store.workspace / "speech" / audio_record["sessionId"] / f"{audio_id}.wav"
    video_directory = services.store.workspace / "video" / video_record["jobId"]
    render_intermediate = video_directory / "render" / "page-0001.mkv"
    return {
        "project": project,
        "editor": editor,
        "speechJobId": speech.json()["id"],
        "audioId": audio_id,
        "audioPath": audio_path,
        "videoId": video_job["assetId"],
        "videoDirectory": video_directory,
        "videoPath": video_directory / "render" / "video.mp4",
        "renderIntermediatePath": render_intermediate,
        "frozenAudioPath": video_directory / "input-0001.wav",
        "createToken": token * 32,
    }


async def preview_cleanup(client, project, mode, revision=1):
    response = await client.post(
        f"/api/projects/{project['id']}/cleanup/preview",
        json={"mode": mode, "expectedRevision": revision},
    )
    return response


async def execute_cleanup(client, project_id, plan_token):
    return await client.post(f"/api/projects/{project_id}/cleanup", json={"planToken": plan_token})


def client_for(services, library=None):
    app = FastAPI()
    app.include_router(project_router)
    app.include_router(speech_router)
    app.include_router(video_router)
    app.include_router(visual_router)
    # Cleanup handlers call these getters directly, outside dependency overrides.
    app.state.projects = services.projects
    app.state.speech = services.speech
    app.state.video = services.video
    app.state.visuals = VisualService(library)
    app.dependency_overrides[get_project_service] = lambda: services.projects
    app.dependency_overrides[get_speech_service] = lambda: services.speech
    app.dependency_overrides[get_video_service] = lambda: services.video
    app.dependency_overrides[get_visual_service] = lambda: app.state.visuals
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    )


def visual_client_for(services, library):
    return client_for(services, library)


def test_cleanup_modes_keep_registered_scope_and_unrelated_files(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        library = VisualLibrary(tmp_path, FakeProbe())
        visual = await library.import_asset("background", "reusable.png", png())
        services.video.visuals = library
        async with client_for(services) as client:
            projects = [
                await generate_project_media(client, services, index, visual.id)
                for index in (1, 2, 3)
            ]

            # A legacy WAV in the shared session and unknown job-directory evidence
            # have no trusted project registration and must survive every mode.
            legacy = projects[0]["audioPath"].with_name(f"{'f' * 32}.wav")
            legacy.write_bytes(b"unregistered legacy audio")
            unknown_paths = []
            for item in projects:
                unknown = item["videoDirectory"] / "owner-notes.txt"
                unknown.write_text("keep unknown job files")
                unknown_paths.append(unknown)

            modes = ("project_only", "intermediate", "all")
            for index, (item, mode) in enumerate(zip(projects, modes, strict=True)):
                preview = await preview_cleanup(client, item["project"], mode)
                assert preview.status_code == 200, preview.text
                plan = preview.json()
                assert plan["projectId"] == item["project"]["id"]
                assert plan["mode"] == mode
                assert plan["planToken"]
                if mode == "project_only":
                    assert plan["deleteFiles"] == {"count": 0, "bytes": 0}
                    assert plan["retainFiles"]["bytes"] > 0
                elif mode == "intermediate":
                    assert plan["deleteFiles"]["count"] >= 3
                    assert plan["retainFiles"]["bytes"] >= item["videoPath"].stat().st_size
                else:
                    assert plan["deleteFiles"]["count"] >= 4

                speech_before = services.speech.assets._bytes
                video_before = services.video._reserved_bytes
                stored_plan = services.store.cleanup_operation(
                    item["project"]["id"], plan["planToken"]
                )["plan"]
                audio_relative = item["audioPath"].relative_to(tmp_path).as_posix()
                speech_deleted_bytes = sum(
                    path["bytes"]
                    for path in stored_plan["delete"]
                    if path["path"] == audio_relative
                )
                video_prefix = f"video/{item['videoDirectory'].name}/"
                video_deleted_bytes = sum(
                    path["bytes"]
                    for path in stored_plan["delete"]
                    if path["path"].startswith(video_prefix)
                )
                executed = await execute_cleanup(client, item["project"]["id"], plan["planToken"])
                assert executed.status_code == 200, executed.text
                result = executed.json()
                assert result["status"] == "completed"
                assert result["mode"] == mode
                assert result["failedFiles"] == 0
                speech_after = services.speech.assets._bytes
                video_after = services.video._reserved_bytes
                if mode == "project_only":
                    assert (speech_after, video_after) == (speech_before, video_before)
                else:
                    assert speech_deleted_bytes > 0 and video_deleted_bytes > 0
                    assert speech_after == speech_before - speech_deleted_bytes
                    assert video_after == video_before - video_deleted_bytes

                replay = await execute_cleanup(client, item["project"]["id"], plan["planToken"])
                assert replay.status_code == 200, replay.text
                assert replay.json() == result
                assert (services.speech.assets._bytes, services.video._reserved_bytes) == (
                    speech_after,
                    video_after,
                )

                speech_job = await client.get(f"/api/speech/jobs/{item['speechJobId']}")
                video_job = await client.get(f"/api/video/jobs/{item['videoDirectory'].name}")
                expected_job_status = 404 if mode == "all" else 200
                assert speech_job.status_code == expected_job_status, speech_job.text
                assert video_job.status_code == expected_job_status, video_job.text

                if mode == "project_only":
                    assert item["audioPath"].is_file()
                    assert item["frozenAudioPath"].is_file()
                    assert item["renderIntermediatePath"].is_file()
                    assert item["videoPath"].is_file()
                elif mode == "intermediate":
                    assert not item["audioPath"].exists()
                    assert not item["frozenAudioPath"].exists()
                    assert not item["renderIntermediatePath"].exists()
                    assert item["videoPath"].is_file()
                    # Another project's WAV is in the same service session.
                    assert projects[2]["audioPath"].is_file()
                else:
                    assert not item["audioPath"].exists()
                    assert not item["frozenAudioPath"].exists()
                    assert not item["renderIntermediatePath"].exists()
                    assert not item["videoPath"].exists()

                assert unknown_paths[index].read_text() == "keep unknown job files"
                assert legacy.read_bytes() == b"unregistered legacy audio"
                assert visual.path.is_file()

            active = (await client.get("/api/projects")).json()["projects"]
            assert active == []
            retained = (await client.get("/api/projects/retained/resources")).json()["projects"]
            by_id = {row["projectId"]: row for row in retained}
            assert projects[0]["project"]["id"] in by_id
            assert by_id[projects[0]["project"]["id"]]["audio"][0]["available"] is True
            assert by_id[projects[0]["project"]["id"]]["videos"][0]["available"] is True
            assert projects[1]["project"]["id"] in by_id
            assert by_id[projects[1]["project"]["id"]]["audio"] == []
            assert by_id[projects[1]["project"]["id"]]["videos"][0]["available"] is True
            assert projects[2]["project"]["id"] not in by_id

    asyncio.run(scenario())


def test_cleanup_preview_rejects_revision_and_resource_changes(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        async with client_for(services) as client:
            item = await generate_project_media(client, services, 1, None)
            old_plan = await preview_cleanup(client, item["project"], "intermediate")
            assert old_plan.status_code == 200, old_plan.text

            changed = snapshot(
                [sentence("sentence-001", "Saved after cleanup preview.")],
                source_text="Saved after cleanup preview.",
            )
            saved = services.store.save(item["project"]["id"], "Cleanup 1", changed, 1, "a" * 32)
            assert saved["revision"] == 2
            stale_revision = await execute_cleanup(
                client, item["project"]["id"], old_plan.json()["planToken"]
            )
            assert stale_revision.status_code == 409
            assert item["audioPath"].is_file()

            fresh_plan = await preview_cleanup(client, item["project"], "intermediate", 2)
            assert fresh_plan.status_code == 200, fresh_plan.text
            with item["audioPath"].open("ab") as handle:
                handle.write(b"changed after preview")
            stale_file = await execute_cleanup(
                client, item["project"]["id"], fresh_plan.json()["planToken"]
            )
            assert stale_file.status_code == 409
            assert services.store.get(item["project"]["id"])["revision"] == 2
            assert item["audioPath"].is_file()

    asyncio.run(scenario())


def test_busy_media_gate_blocks_execution_after_preview(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        async with client_for(services) as client:
            project = await create_project(
                client, snapshot(has_prepared=False), "1" * 32, name="Gate check"
            )
            preview = await preview_cleanup(client, project, "project_only")
            assert preview.status_code == 200, preview.text
            assert services.speech.gate.claim("synthetic-running-render")
            try:
                rejected = await execute_cleanup(client, project["id"], preview.json()["planToken"])
                assert rejected.status_code == 409
                assert services.store.get(project["id"])["id"] == project["id"]
            finally:
                services.speech.gate.release("synthetic-running-render")

    asyncio.run(scenario())


def test_partial_cleanup_retries_with_the_same_persisted_plan_token(tmp_path, monkeypatch):
    async def scenario():
        services = Services(tmp_path)
        async with client_for(services) as client:
            item = await generate_project_media(client, services, 1, None)
            preview = await preview_cleanup(client, item["project"], "intermediate")
            assert preview.status_code == 200, preview.text
            plan_token = preview.json()["planToken"]

            unlink = Path.unlink
            failed_once = False

            def fail_one_registered_audio(path, *args, **kwargs):
                nonlocal failed_once
                if path == item["audioPath"] and not failed_once:
                    failed_once = True
                    raise PermissionError("injected single-file deletion failure")
                return unlink(path, *args, **kwargs)

            monkeypatch.setattr(Path, "unlink", fail_one_registered_audio)
            partial = await execute_cleanup(client, item["project"]["id"], plan_token)
            assert partial.status_code == 200, partial.text
            assert partial.json()["status"] == "partial"
            assert partial.json()["failedFiles"] == 1
            assert item["audioPath"].is_file()
            assert item["videoPath"].is_file()

            monkeypatch.setattr(Path, "unlink", unlink)
            retried = await execute_cleanup(client, item["project"]["id"], plan_token)
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "completed"
            assert retried.json()["operationToken"] == plan_token
            assert not item["audioPath"].exists()
            assert item["videoPath"].is_file()

    asyncio.run(scenario())


def test_archived_project_rejects_old_commands_but_retained_media_survives_restart(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        async with client_for(services) as client:
            item = await generate_project_media(client, services, 1, None)
            preview = await preview_cleanup(client, item["project"], "project_only")
            assert preview.status_code == 200, preview.text
            result = await execute_cleanup(
                client, item["project"]["id"], preview.json()["planToken"]
            )
            assert result.status_code == 200, result.text

        with pytest.raises(ProjectError):
            services.store.get(item["project"]["id"])
        with pytest.raises(ProjectError):
            services.store.save(
                item["project"]["id"],
                item["project"]["name"],
                item["editor"],
                1,
                "b" * 32,
            )
        with pytest.raises(ProjectError):
            services.store.freeze(
                item["project"]["id"],
                item["project"]["name"],
                item["editor"],
                1,
                "c" * 32,
                "speech",
                {"configurationFingerprint": FINGERPRINT},
            )
        with pytest.raises(ProjectError):
            services.store.create(item["project"]["name"], item["editor"], item["createToken"])

        restarted = Services(tmp_path)
        async with client_for(restarted) as client:
            retained = await client.get("/api/projects/retained/resources")
            assert retained.status_code == 200
            row = retained.json()["projects"][0]
            assert row["projectId"] == item["project"]["id"]
            assert row["audio"][0]["available"] is True
            assert row["videos"][0]["available"] is True
            audio = await client.get(f"/api/speech/assets/{item['audioId']}")
            assert audio.status_code == 200
            assert audio.headers["content-type"] == "audio/wav"
            video = await client.get(f"/api/video/assets/{item['videoId']}")
            assert video.status_code == 200
            assert video.headers["content-type"] == "video/mp4"

    asyncio.run(scenario())


def test_cleanup_preserves_hardlink_and_external_symlink_targets(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        async with client_for(services) as client:
            item = await generate_project_media(client, services, 1, None)
            hardlink_target = tmp_path.parent / "cleanup-hardlink-target.wav"
            symlink_target = tmp_path.parent / "cleanup-symlink-target.wav"
            hardlink_target.write_bytes(item["audioPath"].read_bytes())
            symlink_target.write_bytes(b"outside symlink target")
            item["audioPath"].unlink()
            try:
                os.link(hardlink_target, item["audioPath"])
            except OSError:
                pytest.skip("This filesystem cannot create hard links.")

            frozen = item["frozenAudioPath"]
            frozen.unlink()
            has_symlink = True
            try:
                frozen.symlink_to(symlink_target)
            except OSError:
                has_symlink = False

            preview = await preview_cleanup(client, item["project"], "all")
            assert preview.status_code == 200, preview.text
            warnings = " ".join(preview.json()["warnings"]).lower()
            assert "retained" in warnings or "unsafe" in warnings or "linked" in warnings
            result = await execute_cleanup(
                client, item["project"]["id"], preview.json()["planToken"]
            )
            assert result.status_code == 200, result.text
            assert hardlink_target.read_bytes() == item["audioPath"].read_bytes()
            assert item["audioPath"].is_file()
            if has_symlink:
                assert frozen.is_symlink()
                assert symlink_target.read_bytes() == b"outside symlink target"

    asyncio.run(scenario())


def test_visual_cleanup_blocks_references_and_recovers_after_lost_response(tmp_path, monkeypatch):
    async def scenario():
        services = Services(tmp_path)
        library = VisualLibrary(tmp_path, FakeProbe())
        services.video.visuals = library
        active_image = await library.import_asset("background", "active.png", png())
        historical_image = await library.import_asset("background", "history.png", png())
        unused_image = await library.import_asset("illustration", "unused.png", png())
        cleanup = VisualCleanup(services.store, services.speech.gate, library)

        active_editor = snapshot(
            [sentence("sentence-001", "Still selected.")], background=active_image.id
        )
        active_project = services.store.create("Active selection", active_editor, "1" * 32)
        with pytest.raises(ProjectError) as active_reference:
            await cleanup.preview(active_image.id)
        assert active_reference.value.status_code == 409
        assert "Current projects" in active_reference.value.detail
        assert "Active selection" in active_reference.value.detail
        original_image_bytes = active_image.path.read_bytes()
        async with visual_client_for(services, library) as client:
            renamed = await client.patch(
                f"/api/visuals/assets/{active_image.id}",
                json={"name": "renamed-active.png", "expectedName": "active.png"},
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["name"] == "renamed-active.png"
            assert renamed.json()["id"] == active_image.id
            renamed_image = library.get(active_image.id)
            assert renamed_image.sha256 == active_image.sha256
            assert renamed_image.path == active_image.path
            assert renamed_image.path.read_bytes() == original_image_bytes
            assert (
                services.store.get(active_project["id"])["snapshot"]["backgroundAssetId"]
                == active_image.id
            )

            stale_name = await client.patch(
                f"/api/visuals/assets/{active_image.id}",
                json={"name": "stale-name.png", "expectedName": "active.png"},
            )
            assert stale_name.status_code == 409
            assert library.get(active_image.id).name == "renamed-active.png"

            assert services.speech.gate.claim("synthetic-running-render")
            try:
                busy = await client.patch(
                    f"/api/visuals/assets/{active_image.id}",
                    json={
                        "name": "busy-rename.png",
                        "expectedName": "renamed-active.png",
                    },
                )
                assert busy.status_code == 409
                assert library.get(active_image.id).name == "renamed-active.png"
            finally:
                services.speech.gate.release("synthetic-running-render")

            original_get = library.get
            active_sidecar = active_image.path.parent / "asset.json"
            concurrent_name = "external-rename.png"
            changed_after_get = False

            def change_name_after_get(asset_id):
                nonlocal changed_after_get
                asset = original_get(asset_id)
                if asset_id == active_image.id and not changed_after_get:
                    record = json.loads(active_sidecar.read_text(encoding="utf-8"))
                    record["name"] = concurrent_name
                    active_sidecar.write_text(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    changed_after_get = True
                return asset

            monkeypatch.setattr(library, "get", change_name_after_get)
            raced_rename = await client.patch(
                f"/api/visuals/assets/{active_image.id}",
                json={
                    "name": "should-not-overwrite.png",
                    "expectedName": "renamed-active.png",
                },
            )
            monkeypatch.setattr(library, "get", original_get)
            assert changed_after_get
            assert raced_rename.status_code == 409
            assert library.get(active_image.id).name == concurrent_name

        async with client_for(services) as client:
            history = await generate_project_media(client, services, 2, historical_image.id)
        current_without_image = snapshot(
            [sentence("sentence-001", "Current editor no longer selects it.")]
        )
        services.store.save(
            history["project"]["id"],
            history["project"]["name"],
            current_without_image,
            1,
            "a" * 32,
        )
        with pytest.raises(ProjectError) as historical_reference:
            await cleanup.preview(historical_image.id)
        assert historical_reference.value.status_code == 409
        assert "Generation history" in historical_reference.value.detail
        assert history["project"]["name"] in historical_reference.value.detail

        unused_editor = snapshot(
            [sentence("sentence-001", "Remove the unused image.")],
            background=unused_image.id,
        )
        unused_project = services.store.create("Unused image", unused_editor, "3" * 32)
        with pytest.raises(ProjectError) as current_reference:
            await cleanup.preview(unused_image.id)
        assert current_reference.value.status_code == 409
        no_image_editor = snapshot([sentence("sentence-001", "No image reference remains.")])
        saved = services.store.save(
            unused_project["id"], "Unused image", no_image_editor, 1, "4" * 32
        )
        assert saved["revision"] == 2
        assert services.store.attempts(unused_project["id"]) == []

        sidecar = unused_image.path.parent / "asset.json"
        async with visual_client_for(services, library) as client:
            before = await client.get("/api/visuals/assets")
            assert unused_image.id in {item["id"] for item in before.json()["assets"]}
            preview = await client.post(f"/api/visuals/assets/{unused_image.id}/cleanup/preview")
            assert preview.status_code == 200, preview.text
            plan_token = preview.json()["planToken"]
            assert preview.json()["deleteFiles"]["count"] == 2

            original_unlink = Path.unlink
            unlink_failed = False

            def fail_once_for_sidecar(path, *args, **kwargs):
                nonlocal unlink_failed
                if path == sidecar and not unlink_failed:
                    unlink_failed = True
                    raise PermissionError("injected single-file deletion failure")
                return original_unlink(path, *args, **kwargs)

            original_execute = VisualCleanup.execute

            async def lose_post_response(self, asset_id, token):
                await original_execute(self, asset_id, token)
                raise httpx.ReadError("synthetic response loss after journal commit")

            monkeypatch.setattr(Path, "unlink", fail_once_for_sidecar)
            monkeypatch.setattr(VisualCleanup, "execute", lose_post_response)
            with pytest.raises(httpx.ReadError):
                await client.post(
                    f"/api/visuals/assets/{unused_image.id}/cleanup",
                    json={"planToken": plan_token},
                )
            monkeypatch.setattr(Path, "unlink", original_unlink)
            monkeypatch.setattr(VisualCleanup, "execute", original_execute)

            outcome = await client.get(
                f"/api/visuals/assets/{unused_image.id}/cleanup/{plan_token}"
            )
            assert outcome.status_code == 200, outcome.text
            assert outcome.json()["operationToken"] == plan_token
            assert outcome.json()["status"] == "partial"
            assert outcome.json()["failedFiles"] == 1
            pending = await client.get("/api/visuals/cleanup/operations")
            assert any(
                row["operationToken"] == plan_token and row["status"] == "partial"
                for row in pending.json()["operations"]
            )
            hidden = await client.get("/api/visuals/assets")
            assert unused_image.id not in {item["id"] for item in hidden.json()["assets"]}
            assert not unused_image.path.exists()
            assert sidecar.is_file()

        # Opening the same database and library performs no cleanup by itself.
        restarted = Services(tmp_path)
        restarted_library = VisualLibrary(tmp_path, FakeProbe())
        assert sidecar.is_file()
        assert unused_image.id in restarted.store.hidden_visual_ids()
        async with visual_client_for(restarted, restarted_library) as client:
            status_after_restart = await client.get(
                f"/api/visuals/assets/{unused_image.id}/cleanup/{plan_token}"
            )
            assert status_after_restart.json()["status"] == "partial"
            assert unused_image.id not in {
                item["id"] for item in (await client.get("/api/visuals/assets")).json()["assets"]
            }
            pending_after_restart = await client.get("/api/visuals/cleanup/operations")
            assert any(
                row["operationToken"] == plan_token
                for row in pending_after_restart.json()["operations"]
            )
            retried = await client.post(
                f"/api/visuals/assets/{unused_image.id}/cleanup",
                json={"planToken": plan_token},
            )
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "completed"
            assert retried.json()["operationToken"] == plan_token
            assert not sidecar.exists()
            assert not unused_image.path.exists()
            deleted_rename = await client.patch(
                f"/api/visuals/assets/{unused_image.id}",
                json={"name": "resurrected.png", "expectedName": "unused.png"},
            )
            assert deleted_rename.status_code == 409

        with pytest.raises(ProjectError) as deleted_reference:
            restarted.store.save(
                unused_project["id"],
                "Unused image",
                unused_editor,
                2,
                "5" * 32,
            )
        assert deleted_reference.value.status_code == 409

    asyncio.run(scenario())


def test_schema_one_database_migrates_in_place_without_losing_projects(tmp_path):
    async def scenario():
        workspace = tmp_path
        (workspace / "state").mkdir(mode=0o700)
        database = workspace / "state" / "projects.sqlite3"
        project_id = "a" * 32
        editor = snapshot([sentence("sentence-001", "Legacy project survives migration.")])
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(database) as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    "Legacy project",
                    3,
                    json.dumps(editor, ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute("PRAGMA user_version = 1")

        migrated = ProjectStore(workspace)
        restored = migrated.get(project_id)
        assert restored["name"] == "Legacy project"
        assert restored["revision"] == 3
        assert restored["snapshot"] == editor
        assert [item["id"] for item in migrated.list_projects()] == [project_id]
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
            columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
            assert {"deleted_at", "cleanup_token"} <= columns
            assert connection.execute("SELECT count(*) FROM cleanups").fetchone()[0] == 0

    asyncio.run(scenario())
