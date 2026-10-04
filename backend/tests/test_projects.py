import asyncio
import hashlib
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from test_speech_jobs import FakeSpeech, write_wav
from test_video_api import FakeCapabilityRunner, FakeRenderer

from shadowing_video_studio.project_api import (
    ProjectService,
    get_project_service,
)
from shadowing_video_studio.project_api import (
    router as project_router,
)
from shadowing_video_studio.project_store import ProjectError, ProjectStore
from shadowing_video_studio.speech import VOICE, HeavyJobGate, SpeechError, SpeechSentence
from shadowing_video_studio.speech_api import (
    get_speech_service,
)
from shadowing_video_studio.speech_api import (
    router as speech_router,
)
from shadowing_video_studio.speech_assets import SpeechAssets
from shadowing_video_studio.speech_jobs import SpeechJobs
from shadowing_video_studio.video_api import (
    get_video_service,
)
from shadowing_video_studio.video_api import (
    router as video_router,
)
from shadowing_video_studio.video_jobs import VideoJobs
from shadowing_video_studio.video_settings import VideoSettings, VideoToolPreflight

FINGERPRINT = "a" * 64
DOCUMENT_ID = "d" * 32


class ProjectSpeechProvider(FakeSpeech):
    fingerprint = FINGERPRINT


class Services:
    def __init__(self, workspace):
        self.store = ProjectStore(workspace)
        self.provider = ProjectSpeechProvider()
        self.assets = SpeechAssets(workspace, self.store)
        self.speech = SpeechJobs(self.provider, self.assets, HeavyJobGate())
        tool = workspace / "synthetic-tool"
        font = workspace / "synthetic-font.ttf"
        if not tool.exists():
            tool.write_text("synthetic executable")
        tool.chmod(0o755)
        if not font.exists():
            font.write_bytes(b"synthetic font for the fake renderer")
        self.renderer = FakeRenderer()
        self.video = VideoJobs(
            VideoSettings(tool, tool, font),
            self.speech,
            self.renderer,
            VideoToolPreflight(FakeCapabilityRunner()),
        )
        self.projects = ProjectService(self.store, self.assets)


def client_for(services):
    app = FastAPI()
    app.include_router(project_router)
    app.include_router(speech_router)
    app.include_router(video_router)
    app.dependency_overrides[get_project_service] = lambda: services.projects
    app.dependency_overrides[get_speech_service] = lambda: services.speech
    app.dependency_overrides[get_video_service] = lambda: services.video
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    )


def snapshot(
    sentences=None,
    *,
    document_id=DOCUMENT_ID,
    source_draft="",
    source_text="",
    next_sequence=None,
    has_prepared=True,
    voice=VOICE,
    background=None,
    illustrations=None,
    mode="manual",
):
    sentences = sentences or []
    maximum = max((int(row["id"].removeprefix("sentence-")) for row in sentences), default=0)
    return {
        "version": 1,
        "documentId": document_id,
        "sourceDraft": source_draft,
        "document": {
            "sourceText": source_text,
            "sentences": [dict(row) for row in sentences],
            "nextSequence": next_sequence if next_sequence is not None else maximum + 1,
        },
        "hasPrepared": has_prepared,
        "mode": mode,
        "voice": voice,
        "backgroundAssetId": background,
        "illustrationsBySentence": illustrations or {},
    }


def sentence(identifier, text):
    return {"id": identifier, "text": text}


async def create_project(client, editor, operation_token="1" * 32, name="Practice"):
    response = await client.post(
        "/api/projects",
        json={"operationToken": operation_token, "name": name, "snapshot": editor},
    )
    assert response.status_code == 201, response.text
    return response.json()


def speech_request(editor, operation_token, *, project_name="Practice", revision=1):
    return {
        "operationToken": operation_token,
        "name": project_name,
        "snapshot": editor,
        "expectedRevision": revision,
        "configurationFingerprint": FINGERPRINT,
        "singleSentenceId": None,
    }


def test_empty_draft_and_stable_editor_state_reopen_after_service_restart(tmp_path):
    async def scenario():
        first = Services(tmp_path)
        initial = snapshot(has_prepared=False, source_draft="Typed but not prepared")
        async with client_for(first) as client:
            created = await create_project(client, initial)
            opened = (await client.get(f"/api/projects/{created['id']}")).json()
            assert opened["snapshot"]["sourceDraft"] == "Typed but not prepared"
            assert opened["snapshot"]["document"]["sentences"] == []
            assert opened["snapshot"]["document"]["nextSequence"] == 1
            assert opened["snapshot"]["hasPrepared"] is False

            edited = snapshot(
                [
                    sentence("sentence-004", "Fourth, moved first."),
                    sentence("sentence-002", "Second."),
                ],
                source_draft="Draft after preparation",
                source_text="Original source snapshot",
                next_sequence=8,
                voice="Ryan",
                background="b" * 32,
                illustrations={"sentence-004": "c" * 32},
                mode="ai",
            )
            saved = await client.put(
                f"/api/projects/{created['id']}",
                json={
                    "operationToken": "2" * 32,
                    "name": "Reviewed practice",
                    "snapshot": edited,
                    "expectedRevision": 1,
                },
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["revision"] == 2

        restarted = Services(tmp_path)
        async with client_for(restarted) as client:
            restored = (await client.get(f"/api/projects/{created['id']}")).json()
            current = restored["snapshot"]
            assert restored["revision"] == 2
            assert current["sourceDraft"] == "Draft after preparation"
            assert current["document"]["sourceText"] == "Original source snapshot"
            assert current["document"]["sentences"] == edited["document"]["sentences"]
            assert current["document"]["nextSequence"] == 8
            assert current["voice"] == "Ryan"
            assert current["backgroundAssetId"] == "b" * 32
            assert current["illustrationsBySentence"] == {"sentence-004": "c" * 32}

    asyncio.run(scenario())


def test_create_save_receipts_and_revision_conflicts_preserve_last_save(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        original = snapshot(has_prepared=False, source_draft="Initial")
        async with client_for(services) as client:
            created = await create_project(client, original, "1" * 32)
            replayed_create = await client.post(
                "/api/projects",
                json={"operationToken": "1" * 32, "name": "Practice", "snapshot": original},
            )
            assert replayed_create.status_code == 201
            assert replayed_create.json() == created
            assert len((await client.get("/api/projects")).json()["projects"]) == 1

            conflicting_create = await client.post(
                "/api/projects",
                json={"operationToken": "1" * 32, "name": "Different", "snapshot": original},
            )
            assert conflicting_create.status_code == 409

            saved_snapshot = snapshot(has_prepared=False, source_draft="Saved revision")
            save_body = {
                "operationToken": "3" * 32,
                "name": "Practice",
                "snapshot": saved_snapshot,
                "expectedRevision": 1,
            }
            saved = await client.put(f"/api/projects/{created['id']}", json=save_body)
            assert saved.status_code == 200 and saved.json()["revision"] == 2
            replayed_save = await client.put(f"/api/projects/{created['id']}", json=save_body)
            assert replayed_save.json() == saved.json()

            altered_replay = {**save_body, "name": "Different name"}
            assert (
                await client.put(f"/api/projects/{created['id']}", json=altered_replay)
            ).status_code == 409
            stale = {
                **save_body,
                "operationToken": "4" * 32,
                "snapshot": snapshot(has_prepared=False, source_draft="Stale draft"),
            }
            assert (
                await client.put(f"/api/projects/{created['id']}", json=stale)
            ).status_code == 409
            current = (await client.get(f"/api/projects/{created['id']}")).json()
            assert current["revision"] == 2
            assert current["snapshot"] == saved_snapshot

    asyncio.run(scenario())


def test_generation_token_replay_returns_original_job_and_rejects_changed_input(tmp_path):
    async def scenario():
        services = Services(tmp_path)
        editor = snapshot([sentence("sentence-001", "One stable request.")], source_text="One.")
        async with client_for(services) as client:
            project = await create_project(client, editor)
            body = speech_request(editor, "5" * 32)
            first = await client.post(f"/api/projects/{project['id']}/speech", json=body)
            assert first.status_code == 202, first.text
            await services.speech.wait()
            original_job = services.speech.get(first.json()["id"])
            assert original_job["status"] == "completed"
            assert len(services.provider.calls) == 1

            replay = await client.post(f"/api/projects/{project['id']}/speech", json=body)
            assert replay.status_code == 202
            assert replay.json()["id"] == original_job["id"]
            assert replay.json()["status"] == "completed"
            assert len(services.store.attempts(project["id"])) == 1
            assert len(services.provider.calls) == 1

            changed = snapshot([sentence("sentence-001", "Changed under the same token.")])
            conflict = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(changed, "5" * 32),
            )
            assert conflict.status_code == 409
            assert len(services.provider.calls) == 1

    asyncio.run(scenario())


def test_partial_audio_is_reused_after_restart_only_for_its_project_and_document(tmp_path):
    async def scenario():
        first = Services(tmp_path)
        first.provider.fail.add("Fail this sentence.")
        editor = snapshot(
            [
                sentence("sentence-001", "Keep this success."),
                sentence("sentence-002", "Fail this sentence."),
            ],
            source_text="Two sentences.",
        )
        async with client_for(first) as client:
            project = await create_project(client, editor)
            submitted = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(editor, "6" * 32),
            )
            await first.speech.wait()
            failed = first.speech.get(submitted.json()["id"])
            assert failed["status"] == "failed"
            assert [row["status"] for row in failed["sentences"]] == ["ready", "failed"]
            asset_id = failed["sentences"][0]["assetId"]
            item = first.assets.match(
                asset_id,
                SpeechSentence("sentence-001", "Keep this success."),
                FINGERPRINT,
                VOICE,
                project["id"],
                DOCUMENT_ID,
            )
            for wrong_project, wrong_document in (
                ("e" * 32, DOCUMENT_ID),
                (project["id"], "f" * 32),
            ):
                with pytest.raises(SpeechError) as mismatch:
                    first.assets.match(
                        asset_id,
                        SpeechSentence("sentence-001", "Keep this success."),
                        FINGERPRINT,
                        VOICE,
                        wrong_project,
                        wrong_document,
                    )
                assert mismatch.value.status_code == 409

        restarted = Services(tmp_path)
        restarted.provider.fail.add("Fail this sentence.")
        async with client_for(restarted) as client:
            opened = (await client.get(f"/api/projects/{project['id']}")).json()
            assert [row["id"] for row in opened["audio"]] == ["sentence-001"]
            assert opened["audio"][0]["assetId"] == asset_id
            assert opened["audio"][0]["reused"] is True
            assert restarted.provider.calls == []

            retry = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(editor, "7" * 32),
            )
            await restarted.speech.wait()
            recovered = restarted.speech.get(retry.json()["id"])
            assert recovered["sentences"][0]["reused"] is True
            assert recovered["sentences"][0]["assetId"] == asset_id
            assert [text for text, _ in restarted.provider.calls] == ["Fail this sentence."]
            assert item.path.is_file()

    asyncio.run(scenario())


def test_video_history_keeps_frozen_inputs_and_playback_after_edit_and_restart(tmp_path):
    async def scenario():
        first = Services(tmp_path)
        editor = snapshot([sentence("sentence-001", "Historical sentence.")])
        async with client_for(first) as client:
            project = await create_project(client, editor)
            speech = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(editor, "8" * 32),
            )
            await first.speech.wait()
            audio_id = first.speech.get(speech.json()["id"])["sentences"][0]["assetId"]
            video_body = {
                "operationToken": "9" * 32,
                "name": "Practice",
                "snapshot": editor,
                "expectedRevision": 1,
                "configurationFingerprint": FINGERPRINT,
                "audioAssetIds": {"sentence-001": audio_id},
            }
            video = await client.post(f"/api/projects/{project['id']}/video", json=video_body)
            assert video.status_code == 202, video.text
            await first.video.wait()
            finished = first.video.get(video.json()["id"])
            assert finished["status"] == "completed"
            video_id = finished["assetId"]

            edited = snapshot([sentence("sentence-001", "Current edited sentence.")])
            saved = await client.put(
                f"/api/projects/{project['id']}",
                json={
                    "operationToken": "a" * 32,
                    "name": "Practice",
                    "snapshot": edited,
                    "expectedRevision": 1,
                },
            )
            assert saved.status_code == 200 and saved.json()["revision"] == 2

        restarted = Services(tmp_path)
        async with client_for(restarted) as client:
            reopened = (await client.get(f"/api/projects/{project['id']}")).json()
            assert reopened["snapshot"]["document"]["sentences"][0]["text"] == (
                "Current edited sentence."
            )
            assert len(reopened["history"]) == 1
            historical = reopened["history"][0]
            assert historical["available"] is True
            assert historical["snapshot"]["editor"]["document"]["sentences"][0]["text"] == (
                "Historical sentence."
            )
            playback = await client.get(f"/api/video/assets/{video_id}")
            assert playback.status_code == 200
            assert playback.headers["content-type"] == "video/mp4"
            assert playback.content == b"synthetic video fixture for opaque download"

    asyncio.run(scenario())


def test_missing_and_corrupt_audio_leave_project_and_other_assets_readable(tmp_path):
    async def scenario():
        first = Services(tmp_path)
        editor = snapshot(
            [
                sentence("sentence-001", "Keep available."),
                sentence("sentence-002", "Remove this file."),
                sentence("sentence-003", "Corrupt this file."),
            ]
        )
        async with client_for(first) as client:
            project = await create_project(client, editor)
            submitted = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(editor, "b" * 32),
            )
            await first.speech.wait()
            rows = first.speech.get(submitted.json()["id"])["sentences"]
            records = {row["id"]: first.store.speech_asset(row["assetId"]) for row in rows}
            missing_path = (
                tmp_path
                / "speech"
                / records["sentence-002"]["sessionId"]
                / f"{records['sentence-002']['id']}.wav"
            )
            corrupt_path = (
                tmp_path
                / "speech"
                / records["sentence-003"]["sessionId"]
                / f"{records['sentence-003']['id']}.wav"
            )
            missing_path.unlink()
            corrupt_path.write_bytes(b"corrupt WAV bytes")

        restarted = Services(tmp_path)
        async with client_for(restarted) as client:
            restored = (await client.get(f"/api/projects/{project['id']}")).json()
            assert [row["id"] for row in restored["audio"]] == ["sentence-001"]
            assert restored["snapshot"]["document"]["sentences"] == editor["document"]["sentences"]
            assert (
                len(
                    restarted.store.speech_candidates(
                        project["id"],
                        DOCUMENT_ID,
                        "sentence-001",
                        "Keep available.",
                        FINGERPRINT,
                        VOICE,
                    )
                )
                == 1
            )
            assert restarted.provider.calls == []
            assert any("unavailable" in warning.lower() for warning in restored["warnings"])

    asyncio.run(scenario())


def test_registered_wav_symlink_cannot_read_outside_workspace(tmp_path):
    services = Services(tmp_path)
    editor = snapshot([sentence("sentence-001", "Do not follow a link.")])

    async def create_and_generate():
        async with client_for(services) as client:
            project = await create_project(client, editor)
            submitted = await client.post(
                f"/api/projects/{project['id']}/speech",
                json=speech_request(editor, "c" * 32),
            )
            await services.speech.wait()
            asset_id = services.speech.get(submitted.json()["id"])["sentences"][0]["assetId"]
            return project, asset_id

    project, asset_id = asyncio.run(create_and_generate())
    record = services.store.speech_asset(asset_id)
    path = tmp_path / "speech" / record["sessionId"] / f"{asset_id}.wav"
    outside = tmp_path.parent / f"outside-{asset_id}.wav"
    write_wav(outside)
    outside_bytes = outside.read_bytes()
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create file symlinks.")

    restarted = Services(tmp_path)
    with pytest.raises(SpeechError) as rejected:
        restarted.assets.read(asset_id)
    assert rejected.value.status_code == 404
    assert outside.read_bytes() == outside_bytes
    assert restarted.store.get(project["id"])["snapshot"] == editor


def test_save_and_media_registration_failures_roll_back_metadata(tmp_path):
    store = ProjectStore(tmp_path)
    original = snapshot([sentence("sentence-001", "Committed state.")])
    created = store.create("Practice", original, "1" * 32)
    changed = snapshot([sentence("sentence-001", "Uncommitted state.")])
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_project_update BEFORE UPDATE ON projects "
            "BEGIN SELECT RAISE(ABORT, 'injected save failure'); END"
        )
    with pytest.raises(ProjectError):
        store.save(created["id"], "Practice", changed, 1, "2" * 32)
    assert store.get(created["id"])["snapshot"] == original
    assert store.get(created["id"])["revision"] == 1

    with sqlite3.connect(store.database) as connection:
        connection.execute("DROP TRIGGER reject_project_update")
    attempt = store.freeze(
        created["id"],
        "Practice",
        original,
        1,
        "3" * 32,
        "speech",
        {"configurationFingerprint": FINGERPRINT},
    )
    job = {
        "id": attempt["id"],
        "status": "running",
        "voice": VOICE,
        "configurationFingerprint": FINGERPRINT,
        "sentences": [
            {
                "id": "sentence-001",
                "text": "Committed state.",
                "voice": VOICE,
                "configurationFingerprint": FINGERPRINT,
                "status": "ready",
                "assetId": "4" * 32,
                "durationSeconds": 0.01,
                "error": None,
                "reused": False,
            }
        ],
        "error": None,
    }
    asset = {
        "id": "4" * 32,
        "sessionId": "5" * 32,
        "sentenceId": "sentence-001",
        "text": "Committed state.",
        "fingerprint": FINGERPRINT,
        "voice": VOICE,
        "durationSeconds": 0.01,
        "sizeBytes": 44,
        "sha256": hashlib.sha256(b"unregistered fixture").hexdigest(),
    }
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_attempt_update BEFORE UPDATE ON attempts "
            "BEGIN SELECT RAISE(ABORT, 'injected registration failure'); END"
        )
    with pytest.raises(ProjectError):
        store.record_speech(attempt["id"], asset, job)
    assert (
        store.speech_candidates(
            created["id"], DOCUMENT_ID, "sentence-001", "Committed state.", FINGERPRINT, VOICE
        )
        == []
    )
    assert store.get_attempt(attempt["id"])["status"] == "accepted"
    assert store.get_attempt(attempt["id"])["job"] is None
    assert store.get(created["id"])["snapshot"] == original


def test_restart_marks_accepted_and_running_attempts_interrupted_without_work(tmp_path):
    store = ProjectStore(tmp_path)
    editor = snapshot([sentence("sentence-001", "Never resume automatically.")])
    project = store.create("Practice", editor, "1" * 32)
    accepted = store.freeze(
        project["id"],
        "Practice",
        editor,
        1,
        "2" * 32,
        "speech",
        {"configurationFingerprint": FINGERPRINT},
    )
    running = store.freeze(
        project["id"],
        "Practice",
        editor,
        1,
        "3" * 32,
        "speech",
        {"configurationFingerprint": FINGERPRINT},
    )
    job = {
        "id": running["id"],
        "status": "running",
        "voice": VOICE,
        "configurationFingerprint": FINGERPRINT,
        "sentences": [
            {
                "id": "sentence-001",
                "text": "Never resume automatically.",
                "voice": VOICE,
                "configurationFingerprint": FINGERPRINT,
                "status": "generating",
                "assetId": None,
                "durationSeconds": None,
                "error": None,
                "reused": False,
            }
        ],
        "error": None,
    }
    store.update_attempt(running["id"], "running", job)

    restarted = Services(tmp_path)
    assert restarted.store.get_attempt(accepted["id"])["status"] == "interrupted"
    interrupted = restarted.store.get_attempt(running["id"])
    assert interrupted["status"] == "interrupted"
    assert interrupted["job"]["status"] == "failed"
    assert interrupted["job"]["sentences"][0]["status"] == "failed"

    async def open_without_resuming():
        async with client_for(restarted) as client:
            restored = (await client.get(f"/api/projects/{project['id']}")).json()
            attempts = {row["submissionToken"]: row for row in restored["attempts"]}
            assert attempts["2" * 32]["status"] == "interrupted"
            assert attempts["3" * 32]["status"] == "interrupted"
            assert restarted.provider.calls == []

    asyncio.run(open_without_resuming())
