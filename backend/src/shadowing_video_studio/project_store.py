"""Small durable metadata boundary; media bytes stay in their existing owned folders.

All methods are synchronous. Async callers run them with asyncio.to_thread; no
transaction is held while generating, probing, hashing or serving media.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from shadowing_video_studio.speech import MAX_WAV_BYTES, MAX_WAV_SECONDS
from shadowing_video_studio.video_rendering import MAX_VIDEO_ASSET_BYTES

MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 2 * MAX_SNAPSHOT_BYTES
MAX_PROJECTS = 1_000
MAX_RECEIPTS = 50_000
MAX_ATTEMPTS = 50_000
MAX_SPEECH_ASSETS = 100_000
MAX_VIDEO_OUTPUTS = 10_000
MAX_SEQUENCE = 2**53 - 1
OPAQUE_ID = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SENTENCE_ID = re.compile(r"sentence-[0-9]{3,16}")
ATTEMPT_STATUSES = {"accepted", "running", "completed", "failed", "interrupted"}
SNAPSHOT_KEYS = {
    "version",
    "documentId",
    "sourceDraft",
    "document",
    "hasPrepared",
    "mode",
    "voice",
    "backgroundAssetId",
    "illustrationsBySentence",
}


class ProjectError(Exception):
    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _token(value: object) -> str:
    if not isinstance(value, str) or not OPAQUE_ID.fullmatch(value):
        raise ProjectError("Use a valid opaque project, document, operation or media ID.")
    return value


def _text(value: object, maximum: int, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise ProjectError("Project text must be a string.")
    try:
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeError as exc:
        raise ProjectError("Project text contains invalid Unicode.") from exc
    if length > maximum or (nonempty and not value.strip()):
        raise ProjectError(f"Use text no longer than {maximum} characters.")
    return value


def validate_name(name: str) -> str:
    name = _text(name, 120, nonempty=True).strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ProjectError("Use a project name without control characters.")
    return name


def _integer(value: object, minimum: int, maximum: int = MAX_SEQUENCE) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProjectError("Project metadata contains an invalid integer.")
    return value


def _encode(value: object, limit: int = MAX_RECORD_BYTES) -> str:
    try:
        result = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if len(result.encode("utf-8")) > limit:
            raise ProjectError("Project metadata exceeds its size limit.", 413)
        return result
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProjectError("Project metadata must be valid bounded JSON.") from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("Nonfinite JSON number")


def _decode(value: str, limit: int = MAX_RECORD_BYTES) -> dict:
    try:
        if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
            raise ValueError
        result = json.loads(value, object_pairs_hook=_pairs, parse_constant=_reject_constant)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ProjectError(
            "Saved project metadata is invalid; the draft was preserved.", 503
        ) from exc


def validate_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or snapshot.keys() != SNAPSHOT_KEYS:
        raise ProjectError("Use a complete versioned editor snapshot.")
    if type(snapshot["version"]) is not int or snapshot["version"] != 1:
        raise ProjectError("This editor snapshot version is unsupported.")
    _token(snapshot["documentId"])
    _text(snapshot["sourceDraft"], 20_000)
    document = snapshot["document"]
    if not isinstance(document, dict) or document.keys() != {
        "sourceText",
        "sentences",
        "nextSequence",
    }:
        raise ProjectError("Use a complete sentence document.")
    _text(document["sourceText"], 20_000)
    sentences = document["sentences"]
    if not isinstance(sentences, list) or len(sentences) > 500:
        raise ProjectError("Save at most 500 sentences in one project.")
    seen = set()
    maximum = 0
    for sentence in sentences:
        if not isinstance(sentence, dict) or sentence.keys() != {"id", "text"}:
            raise ProjectError("Use sentence IDs and text in the editor snapshot.")
        sentence_id = sentence["id"]
        if not isinstance(sentence_id, str) or not SENTENCE_ID.fullmatch(sentence_id):
            raise ProjectError("Saved sentence identities are invalid.")
        sequence = _integer(int(sentence_id.removeprefix("sentence-")), 1)
        if sentence_id != f"sentence-{sequence:03d}" or sentence_id in seen:
            raise ProjectError("Saved sentence identities must be unique and canonical.")
        seen.add(sentence_id)
        maximum = max(maximum, sequence)
        _text(sentence["text"], 4_000)
    if _integer(document["nextSequence"], 1) <= maximum:
        raise ProjectError("The saved sentence counter would reuse an existing identity.")
    if (
        type(snapshot["hasPrepared"]) is not bool
        or not isinstance(snapshot["mode"], str)
        or snapshot["mode"] not in {"manual", "ai"}
    ):
        raise ProjectError("Saved preparation settings are invalid.")
    _text(snapshot["voice"], 64, nonempty=True)
    if snapshot["backgroundAssetId"] is not None:
        _token(snapshot["backgroundAssetId"])
    illustrations = snapshot["illustrationsBySentence"]
    if not isinstance(illustrations, dict) or not illustrations.keys() <= seen:
        raise ProjectError("Illustrations must refer to sentences in this document.")
    for asset_id in illustrations.values():
        _token(asset_id)
    return _decode(_encode(snapshot, MAX_SNAPSHOT_BYTES), MAX_SNAPSHOT_BYTES)


def _unsafe(path: Path) -> bool:
    return any(
        item.is_symlink() or getattr(item, "is_junction", lambda: False)()
        for item in (path, *path.parents)
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise ProjectError("Saved project timestamps are invalid.")
    try:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise ProjectError("Saved project timestamps are invalid.") from exc
    return value


def _job(job: dict, attempt: dict) -> dict:
    status = job.get("status") if isinstance(job, dict) else None
    if (
        not isinstance(status, str)
        or status not in {"queued", "running", "completed", "failed"}
        or job.get("id") != attempt["id"]
    ):
        raise ProjectError("The saved generation job is invalid.")
    metadata = {
        "projectId": attempt["projectId"],
        "documentId": attempt["documentId"],
        "projectRevision": attempt["revision"],
        "submissionToken": attempt["submissionToken"],
    }
    if any(key in job and job[key] != value for key, value in metadata.items()):
        raise ProjectError("The generation job belongs to different frozen inputs.")
    if job.get("error") is not None:
        _text(job["error"], 2_000)
    editor = attempt["snapshot"]["editor"]
    if attempt["kind"] == "speech":
        fields = {"id", "voice", "configurationFingerprint", "status", "sentences", "error"}
        if not fields <= job.keys() or not job.keys() <= fields | metadata.keys():
            raise ProjectError("The speech job contains invalid fields.")
        fingerprint = job["configurationFingerprint"]
        if (
            job["voice"] != editor["voice"]
            or not isinstance(fingerprint, str)
            or not SHA256.fullmatch(fingerprint)
            or attempt["snapshot"]["request"].get("configurationFingerprint", fingerprint)
            != fingerprint
        ):
            raise ProjectError("The speech job configuration is invalid.")
        sentences = job["sentences"]
        if not isinstance(sentences, list) or not 1 <= len(sentences) <= 100:
            raise ProjectError("The speech job sentence list is invalid.")
        frozen = {item["id"]: item["text"] for item in editor["document"]["sentences"]}
        seen = set()
        for sentence in sentences:
            if not isinstance(sentence, dict) or sentence.keys() != {
                "id",
                "text",
                "voice",
                "configurationFingerprint",
                "status",
                "assetId",
                "durationSeconds",
                "error",
                "reused",
            }:
                raise ProjectError("The saved speech sentence is invalid.")
            sentence_id, sentence_status = sentence["id"], sentence["status"]
            if (
                not isinstance(sentence_id, str)
                or sentence_id in seen
                or frozen.get(sentence_id) != sentence["text"]
                or sentence["voice"] != editor["voice"]
                or sentence["configurationFingerprint"] != fingerprint
                or not isinstance(sentence_status, str)
                or sentence_status not in {"pending", "generating", "ready", "failed"}
                or type(sentence["reused"]) is not bool
            ):
                raise ProjectError("The saved speech sentence binding is invalid.")
            seen.add(sentence_id)
            if sentence["assetId"] is not None:
                _token(sentence["assetId"])
            if sentence_status == "ready":
                duration = sentence["durationSeconds"]
                if (
                    sentence["assetId"] is None
                    or type(duration) not in {int, float}
                    or not 0 < duration <= MAX_WAV_SECONDS
                ):
                    raise ProjectError("The ready speech result is invalid.")
            if sentence["error"] is not None:
                _text(sentence["error"], 2_000)
        if status == "completed" and any(item["status"] != "ready" for item in sentences):
            raise ProjectError("An incomplete speech job cannot be marked completed.")
    else:
        fields = {
            "id",
            "status",
            "completedSentences",
            "totalSentences",
            "assetId",
            "durationSeconds",
            "error",
        }
        if not fields <= job.keys() or not job.keys() <= fields | metadata.keys():
            raise ProjectError("The video job contains invalid fields.")
        total = _integer(job["totalSentences"], 1, 500)
        _integer(job["completedSentences"], 0, total)
        if job["assetId"] is not None:
            _token(job["assetId"])
        if status == "completed":
            duration = job["durationSeconds"]
            if (
                job["assetId"] is None
                or type(duration) not in {int, float}
                or not 0 < duration <= 600
                or job["completedSentences"] != total
            ):
                raise ProjectError("The completed video result is invalid.")
    return _decode(_encode(job))


SCHEMA = (
    "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL, "
    "snapshot TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE receipts (token TEXT PRIMARY KEY, kind TEXT NOT NULL, digest TEXT NOT NULL, "
    "result TEXT NOT NULL)",
    "CREATE TABLE attempts (id TEXT PRIMARY KEY, "
    "project_id TEXT NOT NULL REFERENCES projects(id), "
    "document_id TEXT NOT NULL, revision INTEGER NOT NULL, "
    "kind TEXT NOT NULL, status TEXT NOT NULL, "
    "snapshot TEXT NOT NULL, job TEXT, submission_token TEXT NOT NULL, digest TEXT NOT NULL, "
    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(project_id, submission_token))",
    "CREATE INDEX attempts_project ON attempts(project_id, created_at DESC)",
    "CREATE TABLE speech_assets (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
    "id TEXT NOT NULL UNIQUE, attempt_id TEXT NOT NULL REFERENCES attempts(id), "
    "project_id TEXT NOT NULL REFERENCES projects(id), "
    "document_id TEXT NOT NULL, sentence_id TEXT NOT NULL, text TEXT NOT NULL, "
    "fingerprint TEXT NOT NULL, voice TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX speech_binding ON speech_assets "
    "(project_id, document_id, sentence_id, fingerprint, voice, sequence DESC)",
    "CREATE TABLE video_outputs (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE "
    "REFERENCES attempts(id), project_id TEXT NOT NULL REFERENCES projects(id), "
    "payload TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE INDEX videos_project ON video_outputs(project_id, created_at DESC)",
)


class ProjectStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.directory = workspace / "state"
        self.database = self.directory / "projects.sqlite3"
        self._lock = threading.RLock()
        try:
            self._check_paths()
            self.directory.mkdir(mode=0o700, exist_ok=True)
            self._check_paths()
            self.directory.chmod(0o700)
            created = False
            try:
                descriptor = os.open(
                    self.database,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                os.close(descriptor)
                created = True
            except FileExistsError:
                pass
            self.database.chmod(0o600)
            with self._transaction(write=True, initialize=created) as connection:
                if created:
                    for statement in SCHEMA:
                        connection.execute(statement)
                    connection.execute("PRAGMA user_version = 1")
                self._interrupt(connection)
        except OSError as exc:
            raise ProjectError("Could not open private local project storage.", 503) from exc

    def _check_paths(self) -> None:
        if (
            not self.workspace.is_absolute()
            or not self.workspace.is_dir()
            or _unsafe(self.workspace)
            or self.workspace.resolve() != self.workspace
        ):
            raise ProjectError("Configure an existing project workspace without links.", 503)
        if _unsafe(self.directory) or (self.directory.exists() and not self.directory.is_dir()):
            raise ProjectError("The private project-state directory is unsafe.", 503)
        for path in (
            self.database,
            Path(f"{self.database}-journal"),
            Path(f"{self.database}-wal"),
            Path(f"{self.database}-shm"),
        ):
            if _unsafe(path) or (
                path.exists()
                and (not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1)
            ):
                raise ProjectError("The project database or journal is unsafe.", 503)

    @contextmanager
    def _transaction(
        self, *, write: bool = False, initialize: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = None
            try:
                self._check_paths()
                connection = sqlite3.connect(self.database, timeout=2, isolation_level=None)
                connection.row_factory = sqlite3.Row
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if not initialize and version != 1:
                    raise ProjectError(
                        "This project database schema is unsupported; keep the file.", 503
                    )
                connection.execute("PRAGMA foreign_keys = ON")
                if connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
                    raise ProjectError("Could not enable safe project journal mode.", 503)
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                connection.commit()
            except (sqlite3.Error, OSError) as exc:
                raise ProjectError(
                    "Local project storage failed. Keep your unsaved draft and retry.", 503
                ) from exc
            finally:
                if connection is not None:
                    connection.close()  # An uncommitted transaction is rolled back.

    @staticmethod
    def _capacity(connection: sqlite3.Connection, table: str, maximum: int) -> None:
        # Table names are fixed adapter constants, never request values.
        if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= maximum:
            raise ProjectError(
                "Local project metadata reached its limit; existing work is preserved.", 409
            )

    @staticmethod
    def _project(row: sqlite3.Row) -> dict:
        try:
            return {
                "id": _token(row["id"]),
                "name": validate_name(row["name"]),
                "revision": _integer(row["revision"], 1),
                "snapshot": validate_snapshot(_decode(row["snapshot"], MAX_SNAPSHOT_BYTES)),
                "createdAt": _timestamp(row["created_at"]),
                "updatedAt": _timestamp(row["updated_at"]),
            }
        except ProjectError as exc:
            raise ProjectError(
                "This saved project is invalid; the current draft was preserved.", 503
            ) from exc

    @staticmethod
    def _project_row(connection: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ProjectError("Saved project not found. Keep the current draft.", 404)
        return row

    def get(self, project_id: str) -> dict:
        _token(project_id)
        with self._transaction() as connection:
            return self._project(self._project_row(connection, project_id))

    def list_projects(self) -> list[dict]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id"
            ).fetchall()
            # Listing remains possible when one project's editor payload is damaged.
            return [
                {
                    "id": _token(row["id"]),
                    "name": validate_name(row["name"]),
                    "revision": _integer(row["revision"], 1),
                    "createdAt": _timestamp(row["created_at"]),
                    "updatedAt": _timestamp(row["updated_at"]),
                }
                for row in rows
            ]

    @staticmethod
    def _receipt(connection: sqlite3.Connection, token: str, kind: str, digest: str) -> dict | None:
        row = connection.execute("SELECT * FROM receipts WHERE token = ?", (token,)).fetchone()
        if row is None:
            return None
        if (row["kind"], row["digest"]) != (kind, digest):
            raise ProjectError("This operation token already belongs to a different request.", 409)
        result = _decode(row["result"])
        if result.keys() != {"id", "name", "revision", "snapshot", "createdAt", "updatedAt"}:
            raise ProjectError("The saved operation receipt is invalid.", 503)
        _token(result["id"])
        validate_name(result["name"])
        _integer(result["revision"], 1)
        validate_snapshot(result["snapshot"])
        _timestamp(result["createdAt"])
        _timestamp(result["updatedAt"])
        return result

    @staticmethod
    def _digest(command: dict) -> str:
        return hashlib.sha256(_encode(command).encode("utf-8")).hexdigest()

    def create(self, name: str, snapshot: dict, operation_token: str) -> dict:
        name, snapshot = validate_name(name), validate_snapshot(snapshot)
        _token(operation_token)
        digest = self._digest({"name": name, "snapshot": snapshot})
        with self._transaction(write=True) as connection:
            if result := self._receipt(connection, operation_token, "create", digest):
                return result
            self._capacity(connection, "projects", MAX_PROJECTS)
            self._capacity(connection, "receipts", MAX_RECEIPTS)
            project_id, timestamp = uuid.uuid4().hex, _now()
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, 1, ?, ?, ?)",
                (project_id, name, _encode(snapshot), timestamp, timestamp),
            )
            result = self._project(self._project_row(connection, project_id))
            connection.execute(
                "INSERT INTO receipts VALUES (?, 'create', ?, ?)",
                (operation_token, digest, _encode(result)),
            )
            return result

    def _save(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        name: str,
        snapshot: dict,
        expected_revision: int,
    ) -> dict:
        current = self._project(self._project_row(connection, project_id))
        if current["revision"] != expected_revision:
            raise ProjectError(
                "This project changed elsewhere. Keep your draft or explicitly reload.", 409
            )
        if (current["name"], current["snapshot"]) != (name, snapshot):
            revision = _integer(current["revision"] + 1, 1)
            connection.execute(
                "UPDATE projects SET name = ?, revision = ?, snapshot = ?, "
                "updated_at = ? WHERE id = ?",
                (name, revision, _encode(snapshot), _now(), project_id),
            )
        return self._project(self._project_row(connection, project_id))

    def save(
        self,
        project_id: str,
        name: str,
        snapshot: dict,
        expected_revision: int,
        operation_token: str,
    ) -> dict:
        _token(project_id)
        _token(operation_token)
        _integer(expected_revision, 1)
        name, snapshot = validate_name(name), validate_snapshot(snapshot)
        digest = self._digest(
            {
                "projectId": project_id,
                "name": name,
                "snapshot": snapshot,
                "expectedRevision": expected_revision,
            }
        )
        with self._transaction(write=True) as connection:
            if result := self._receipt(connection, operation_token, "save", digest):
                return result
            self._capacity(connection, "receipts", MAX_RECEIPTS)
            result = self._save(connection, project_id, name, snapshot, expected_revision)
            connection.execute(
                "INSERT INTO receipts VALUES (?, 'save', ?, ?)",
                (operation_token, digest, _encode(result)),
            )
            return result

    @staticmethod
    def _attempt(row: sqlite3.Row, *, include_job: bool = True) -> dict:
        try:
            frozen = _decode(row["snapshot"])
            if (
                frozen.keys() != {"editor", "request", "media"}
                or not isinstance(frozen["request"], dict)
                or not isinstance(frozen["media"], dict)
            ):
                raise ProjectError("The frozen generation snapshot is invalid.")
            validate_snapshot(frozen["editor"])
            if (
                row["kind"] not in {"speech", "video"}
                or row["status"] not in ATTEMPT_STATUSES
                or frozen["editor"]["documentId"] != row["document_id"]
            ):
                raise ProjectError("The saved generation attempt is invalid.")
            result = {
                "id": _token(row["id"]),
                "projectId": _token(row["project_id"]),
                "documentId": _token(row["document_id"]),
                "revision": _integer(row["revision"], 1),
                "kind": row["kind"],
                "status": row["status"],
                "snapshot": frozen,
                "job": None,
                "submissionToken": _token(row["submission_token"]),
                "createdAt": _timestamp(row["created_at"]),
                "updatedAt": _timestamp(row["updated_at"]),
            }
            if include_job and row["job"] is not None:
                result["job"] = _job(_decode(row["job"]), result)
            return result
        except ProjectError as exc:
            raise ProjectError(
                "This saved generation record is invalid; regenerate explicitly.", 503
            ) from exc

    @staticmethod
    def _attempt_row(connection: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise ProjectError("Generation attempt not found.", 404)
        return row

    def get_attempt(self, attempt_id: str) -> dict:
        _token(attempt_id)
        with self._transaction() as connection:
            return self._attempt(self._attempt_row(connection, attempt_id))

    def find_attempt(self, project_id: str, submission_token: str) -> dict | None:
        _token(project_id)
        _token(submission_token)
        with self._transaction() as connection:
            self._project_row(connection, project_id)
            row = connection.execute(
                "SELECT * FROM attempts WHERE project_id = ? AND submission_token = ?",
                (project_id, submission_token),
            ).fetchone()
            return self._attempt(row) if row is not None else None

    def freeze(
        self,
        project_id: str,
        name: str,
        snapshot: dict,
        expected_revision: int,
        submission_token: str,
        kind: str,
        request_binding: dict,
        frozen_details: dict | None = None,
    ) -> dict:
        _token(project_id)
        _token(submission_token)
        _integer(expected_revision, 1)
        name, snapshot = validate_name(name), validate_snapshot(snapshot)
        if (
            not isinstance(kind, str)
            or kind not in {"speech", "video"}
            or not isinstance(request_binding, dict)
        ):
            raise ProjectError("Choose a supported generation command.")
        request_binding = _decode(_encode(request_binding, MAX_SNAPSHOT_BYTES), MAX_SNAPSHOT_BYTES)
        digest = self._digest(
            {
                "projectId": project_id,
                "name": name,
                "snapshot": snapshot,
                "expectedRevision": expected_revision,
                "kind": kind,
                "request": request_binding,
            }
        )
        with self._transaction(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE project_id = ? AND submission_token = ?",
                (project_id, submission_token),
            ).fetchone()
            if row is not None:
                if row["digest"] != digest:
                    raise ProjectError(
                        "This submission token belongs to a different generation request.", 409
                    )
                return self._attempt(row)
            self._capacity(connection, "attempts", MAX_ATTEMPTS)
            if frozen_details is not None and not isinstance(frozen_details, dict):
                raise ProjectError("Use bounded frozen media/configuration details.")
            media = _decode(_encode(frozen_details or {}, MAX_SNAPSHOT_BYTES), MAX_SNAPSHOT_BYTES)
            saved = self._save(connection, project_id, name, snapshot, expected_revision)
            attempt_id, timestamp = uuid.uuid4().hex, _now()
            connection.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, 'accepted', ?, NULL, ?, ?, ?, ?)",
                (
                    attempt_id,
                    project_id,
                    snapshot["documentId"],
                    saved["revision"],
                    kind,
                    _encode(
                        {"editor": saved["snapshot"], "request": request_binding, "media": media}
                    ),
                    submission_token,
                    digest,
                    timestamp,
                    timestamp,
                ),
            )
            return self._attempt(self._attempt_row(connection, attempt_id))

    def attempts(self, project_id: str) -> list[dict]:
        _token(project_id)
        with self._transaction() as connection:
            self._project_row(connection, project_id)
            rows = connection.execute(
                "SELECT * FROM attempts WHERE project_id = ? "
                "ORDER BY created_at DESC, id LIMIT 100",
                (project_id,),
            ).fetchall()
            return [self._attempt(row) for row in rows]

    def _update_attempt(
        self, connection: sqlite3.Connection, attempt_id: str, status: str, job: dict
    ) -> None:
        current = self._attempt(self._attempt_row(connection, attempt_id))
        if not isinstance(status, str) or status not in ATTEMPT_STATUSES:
            raise ProjectError("Use a valid generation outcome.")
        job = _job(job, current)
        if current["status"] in {"completed", "failed", "interrupted"}:
            if status != current["status"] or job != current["job"]:
                raise ProjectError(
                    "A terminal attempt cannot change; submit a new attempt explicitly.", 409
                )
            return
        if current["status"] == "running" and status == "accepted":
            raise ProjectError("A running attempt cannot return to acceptance.", 409)
        connection.execute(
            "UPDATE attempts SET status = ?, job = ?, updated_at = ? WHERE id = ?",
            (status, _encode(job), _now(), attempt_id),
        )

    def update_attempt(self, attempt_id: str, status: str, job: dict) -> None:
        _token(attempt_id)
        with self._transaction(write=True) as connection:
            self._update_attempt(connection, attempt_id, status, job)

    def _interrupt(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM attempts WHERE status IN ('accepted', 'running')"
        ).fetchall()
        detail = (
            "The service restarted before this attempt finished. "
            "Successful media is preserved; regenerate explicitly."
        )
        for row in rows:
            try:
                attempt = self._attempt(row)
            except ProjectError:
                # Keep damaged evidence, but prevent one unfinished record from
                # making every otherwise readable project unavailable at startup.
                connection.execute(
                    "UPDATE attempts SET status = 'interrupted', updated_at = ? WHERE id = ?",
                    (_now(), row["id"]),
                )
                continue
            job = attempt["job"]
            if job is not None:
                if isinstance(job.get("sentences"), list):
                    for sentence in job["sentences"]:
                        if not isinstance(sentence, dict):
                            raise ProjectError("The unfinished speech record is invalid.", 503)
                        if sentence.get("status") not in {"ready", "failed"}:
                            sentence.update(status="failed", error=detail)
                job.update(status="failed", error=detail)
            connection.execute(
                "UPDATE attempts SET status = 'interrupted', job = ?, updated_at = ? WHERE id = ?",
                (_encode(job) if job is not None else None, _now(), attempt["id"]),
            )

    @staticmethod
    def _media(asset: dict, kind: str) -> dict:
        fields = (
            {
                "id",
                "sessionId",
                "sentenceId",
                "text",
                "fingerprint",
                "voice",
                "durationSeconds",
                "sizeBytes",
                "sha256",
            }
            if kind == "speech"
            else {"id", "jobId", "durationSeconds", "sizeBytes", "sha256"}
        )
        if not isinstance(asset, dict) or asset.keys() != fields:
            raise ProjectError("Use a complete media registration without filesystem paths.")
        _token(asset["id"])
        _token(asset["sessionId" if kind == "speech" else "jobId"])
        if not isinstance(asset["sha256"], str) or not SHA256.fullmatch(asset["sha256"]):
            raise ProjectError("Media integrity metadata is invalid.")
        maximum_bytes = MAX_WAV_BYTES if kind == "speech" else MAX_VIDEO_ASSET_BYTES
        _integer(asset["sizeBytes"], 44 if kind == "speech" else 1, maximum_bytes)
        duration = asset["durationSeconds"]
        if (
            type(duration) not in {int, float}
            or not 0 < duration <= (MAX_WAV_SECONDS if kind == "speech" else 600)
            or not math.isfinite(duration)
        ):
            raise ProjectError("Media duration metadata is invalid.")
        if kind == "speech":
            if (
                not isinstance(asset["sentenceId"], str)
                or not SENTENCE_ID.fullmatch(asset["sentenceId"])
                or not isinstance(asset["fingerprint"], str)
                or not SHA256.fullmatch(asset["fingerprint"])
            ):
                raise ProjectError("Speech binding metadata is invalid.")
            _text(asset["text"], 4_000, nonempty=True)
            _text(asset["voice"], 64, nonempty=True)
        return _decode(_encode(asset))

    def record_speech(self, attempt_id: str, asset: dict, job: dict) -> None:
        _token(attempt_id)
        asset = self._media(asset, "speech")
        with self._transaction(write=True) as connection:
            attempt = self._attempt(self._attempt_row(connection, attempt_id))
            editor = attempt["snapshot"]["editor"]
            sentence = next(
                (
                    item
                    for item in editor["document"]["sentences"]
                    if item["id"] == asset["sentenceId"]
                ),
                None,
            )
            fingerprint = attempt["snapshot"]["request"].get("configurationFingerprint")
            if (
                attempt["status"] not in {"accepted", "running"}
                or attempt["kind"] != "speech"
                or sentence is None
                or sentence["text"] != asset["text"]
                or editor["voice"] != asset["voice"]
                or (fingerprint is not None and fingerprint != asset["fingerprint"])
            ):
                raise ProjectError("Speech cannot attach to different frozen inputs.", 409)
            self._capacity(connection, "speech_assets", MAX_SPEECH_ASSETS)
            connection.execute(
                "INSERT INTO speech_assets (id, attempt_id, project_id, document_id, "
                "sentence_id, text, fingerprint, voice, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset["id"],
                    attempt_id,
                    attempt["projectId"],
                    attempt["documentId"],
                    asset["sentenceId"],
                    asset["text"],
                    asset["fingerprint"],
                    asset["voice"],
                    _encode(asset),
                ),
            )
            status = _job(job, attempt)["status"]
            self._update_attempt(
                connection,
                attempt_id,
                status if status in {"completed", "failed"} else "running",
                job,
            )

    def _speech(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        try:
            asset = self._media(_decode(row["payload"]), "speech")
            if (
                asset["id"],
                asset["sentenceId"],
                asset["text"],
                asset["fingerprint"],
                asset["voice"],
            ) != (row["id"], row["sentence_id"], row["text"], row["fingerprint"], row["voice"]):
                raise ProjectError("The saved speech binding is invalid.")
            attempt = self._attempt(
                self._attempt_row(connection, row["attempt_id"]), include_job=False
            )
            editor = attempt["snapshot"]["editor"]
            sentence = next(
                (
                    item
                    for item in editor["document"]["sentences"]
                    if item["id"] == asset["sentenceId"]
                ),
                None,
            )
            fingerprint = attempt["snapshot"]["request"].get("configurationFingerprint")
            if (
                attempt["kind"] != "speech"
                or attempt["projectId"] != row["project_id"]
                or attempt["documentId"] != row["document_id"]
                or sentence is None
                or sentence["text"] != asset["text"]
                or editor["voice"] != asset["voice"]
                or (fingerprint is not None and fingerprint != asset["fingerprint"])
            ):
                raise ProjectError("The saved audio differs from its frozen generation inputs.")
            return {
                **asset,
                "projectId": _token(row["project_id"]),
                "documentId": _token(row["document_id"]),
                "attemptId": _token(row["attempt_id"]),
                "registrationSequence": _integer(row["sequence"], 1),
            }
        except ProjectError as exc:
            raise ProjectError(
                "This saved audio registration is invalid; regenerate explicitly.", 404
            ) from exc

    def speech_asset(self, asset_id: str) -> dict | None:
        _token(asset_id)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM speech_assets WHERE id = ?", (asset_id,)
            ).fetchone()
            return self._speech(connection, row) if row is not None else None

    def speech_candidates(
        self,
        project_id: str,
        document_id: str,
        sentence_id: str,
        text: str,
        fingerprint: str,
        voice: str,
    ) -> list[dict]:
        _token(project_id)
        _token(document_id)
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM speech_assets WHERE project_id = ? AND document_id = ? "
                "AND sentence_id = ? AND text = ? AND fingerprint = ? AND voice = ? "
                "ORDER BY sequence DESC",
                (project_id, document_id, sentence_id, text, fingerprint, voice),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    result.append(self._speech(connection, row))
                except ProjectError:
                    # Invalid individual registrations cannot hide older safe matches.
                    continue
            return result

    def record_video(self, attempt_id: str, asset: dict, job: dict) -> None:
        _token(attempt_id)
        asset = self._media(asset, "video")
        with self._transaction(write=True) as connection:
            attempt = self._attempt(self._attempt_row(connection, attempt_id))
            if (
                attempt["status"] not in {"accepted", "running"}
                or attempt["kind"] != "video"
                or asset["jobId"] != attempt_id
                or not isinstance(job, dict)
                or job.get("status") != "completed"
                or job.get("assetId") != asset["id"]
            ):
                raise ProjectError(
                    "Video completion must match its frozen attempt and output.", 409
                )
            self._capacity(connection, "video_outputs", MAX_VIDEO_OUTPUTS)
            connection.execute(
                "INSERT INTO video_outputs VALUES (?, ?, ?, ?, ?)",
                (asset["id"], attempt_id, attempt["projectId"], _encode(asset), _now()),
            )
            self._update_attempt(connection, attempt_id, "completed", job)

    def _video(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        try:
            asset = self._media(_decode(row["payload"]), "video")
            attempt = self._attempt(
                self._attempt_row(connection, row["attempt_id"]), include_job=False
            )
            if (
                asset["id"] != row["id"]
                or asset["jobId"] != attempt["id"]
                or attempt["kind"] != "video"
                or attempt["status"] != "completed"
                or attempt["projectId"] != row["project_id"]
            ):
                raise ProjectError("The saved video output binding is invalid.")
            return {
                **asset,
                "projectId": _token(row["project_id"]),
                "createdAt": _timestamp(row["created_at"]),
                "snapshot": attempt["snapshot"],
            }
        except ProjectError as exc:
            raise ProjectError(
                "This saved video registration is invalid; regenerate explicitly.", 404
            ) from exc

    def video_asset(self, asset_id: str) -> dict | None:
        _token(asset_id)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM video_outputs WHERE id = ?", (asset_id,)
            ).fetchone()
            return self._video(connection, row) if row is not None else None

    def history(self, project_id: str) -> list[dict]:
        _token(project_id)
        with self._transaction() as connection:
            self._project_row(connection, project_id)
            rows = connection.execute(
                "SELECT * FROM video_outputs WHERE project_id = ? ORDER BY created_at DESC, id",
                (project_id,),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    result.append(self._video(connection, row))
                except ProjectError as exc:
                    # Keep unrelated outputs readable; unsafe fields never become paths.
                    try:
                        result.append(
                            {
                                "id": _token(row["id"]),
                                "projectId": project_id,
                                "jobId": _token(row["attempt_id"]),
                                "createdAt": _timestamp(row["created_at"]),
                                "available": False,
                                "reason": exc.detail,
                                "durationSeconds": None,
                                "sizeBytes": None,
                                "sha256": None,
                                "snapshot": None,
                            }
                        )
                    except ProjectError:
                        continue
            return result
