# ADR 0005 — Explicit project deletion and retained resources

- Status: **Accepted product/lifecycle choices; implemented and owner accepted**.
- Date: 2026-10-04.
- Task: [014](../../../tasks/done/014-project-resource-cleanup.md).
- Extends [ADR 0004](0004-project-history-persistence.md).

## Decision and owner approval

The owner approved three deletion modes, a retained-resource list and keeping shared
background/illustration originals on 2026-10-04, then authorized development.
The owner subsequently approved an independent image-library cleanup entry in the same task.

| Mode | Editable project | Generated/intermediate files | Final MP4 |
| --- | --- | --- | --- |
| `project_only` | Remove | Retain | Retain |
| `intermediate` | Remove | Delete eligible files | Retain |
| `all` | Remove | Delete eligible files | Delete eligible files |

Generated WAVs, frozen render copies of WAV/images, page clips/text, renderer font copies
and concat files are intermediate resources. Shared visual-library originals, TTS models,
runtime/cache/configuration files and migration backups are outside project cleanup.
Existing unregistered files without reliable project ownership are retained.

## Metadata and compatibility

Extend SQLite schema 1 to 2 through a short rollback-journal transaction. Before migrating
an existing v1 database, keep a private consistent `state/projects-v1-backup.sqlite3` using
SQLite backup; never overwrite an existing backup. Keep existing records and IDs intact.
Unknown versions and unsafe database/backup paths fail closed. Old schema-1 application
versions cannot operate on schema 2; restoring a stopped-service backup is a deliberate
operator action, not an automatic rollback.

Projects receive a deletion timestamp and cleanup-token association. Once confirmed,
remove the editor snapshot, hide the project from the active list and reject editing,
generation and old create/save receipt replay. The remaining tombstone identifies retained
resources and deletion outcomes; it is not a recoverable editing project.

Keep frozen registrations/snapshots needed to identify retained audio/video. On successful
`all` cleanup, remove the project's speech/video registrations, owned allocations and
attempt snapshots. Keep a minimal tombstone/deletion receipt to make response recovery and
repeated commands safe. This is application deletion, not secure erasure of disk sectors
or operator backups.

New speech destinations are associated with a project/attempt before model writing, so
failed/partial files can be cleaned later. Older successful audio uses its trusted durable
registrations. Do not reconstruct ownership of old unregistered WAVs from session names.

## Preview, confirmation and execution

Preview uses a server-generated opaque plan token, current project revision and a frozen
manifest containing identities/hashes of eligible files, retained counts/bytes and warnings.
The UI defaults to project-only, flushes changes, displays scope and requests confirmation.
There is no client-supplied path or recursive folder deletion command.

Confirmation rechecks revision and the manifest, then atomically writes deletion intent
and removes the editable project. Heavy media work and cleanup share the existing single
worker gate. Unfinished attempts block deletion. An HTTP disconnect does not release the
gate until the deletion worker has finished its journal writes.

Delete only individual known layout files tied to trusted project registrations/attempts.
Protect foreign-project references, shared library originals, links/junctions, hardlinks,
unknown files and resources whose identity/content changed. Preserve unknown contents of
an owned job folder; do not recursively delete the folder. Empty directories may remain.

Filesystem deletion and SQLite cannot be one atomic transaction. Journal per-file outcomes;
missing files during retry are idempotent success. Report partial failure accurately.
Confirmed deleted allocations/files also release their current-process speech/video storage
charges while the heavy-job gate is held. Replayed cleanup does not reclaim those charges
twice; unknown or undeleted resources keep their reservation. Session job-count limits remain.
Restart never executes pending cleanup. The retained list exposes pending/partial status
and an explicit same-token retry; an operation-status query resolves lost responses.

## Retained-resource UI and APIs

Group retained resources by original project name with read-only audio playback and video
preview/download. They cannot reopen an editing project or become another project's audio
selection. Intermediate cleanup keeps final video snapshots even when rebuild inputs are
gone. All-mode completed groups disappear from the retained list; partial groups remain.

- `POST /api/projects/{id}/cleanup/preview`: mode + expected revision.
- `POST /api/projects/{id}/cleanup`: confirmed plan token, also explicit retry.
- `GET /api/projects/{id}/cleanup/{token}`: outcome query, never performs deletion.
- `GET /api/projects/retained/resources`: read-only groups and resource availability.
- Existing opaque speech/video media APIs continue serving valid retained files.

## Alternatives and limits

### Independent image-library cleanup

An explicit library action previews and confirms deletion of one background or illustration.
Project deletion never invokes it. Active editor snapshots and all remaining frozen attempts,
including retained historical outputs, block deletion of their referenced originals. Invalid
reference metadata fails closed. Successful all-resource project cleanup removes its frozen
attempts, allowing an otherwise unused original to be deleted separately.

The schema-2 `visual_cleanups` journal stores image plans and outcomes. Confirmation checks
references in the same SQLite transaction that marks deletion intent; subsequent project
create/save/freeze commands reject marked image IDs. Library listing/preview hides marked
images. This prevents a stale browser from assigning an image while its files are deleted.
Only the verified image file and `asset.json` sidecar are eligible; unknown contents, links,
hardlinks or changed files block/preserve cleanup. Remove only the exact empty asset directory
after its files are gone, using nonrecursive `rmdir` to release the library item quota.

Pending/partial deletion requires explicit same-token retry, including after restart. An
operation query resolves lost responses. No startup/background deletion occurs.

- `POST /api/visuals/assets/{id}/cleanup/preview`: preview one unused original.
- `POST /api/visuals/assets/{id}/cleanup`: confirmed plan token or explicit retry.
- `GET /api/visuals/assets/{id}/cleanup/{token}`: read-only outcome.
- `GET /api/visuals/cleanup/operations`: unfinished confirmed operations for manual retry
  after a refresh/restart; marked images are excluded from ordinary selection lists.

Owner acceptance feedback additionally places the library and retained-resource list on
a separate Resource manager page, preserving the video draft when switching pages.
`PATCH /api/visuals/assets/{id}` renames display metadata with an expected-name conflict
check, atomic sidecar replacement and the media gate held through completion. It preserves
opaque IDs, file locations, image hashes and project/history associations; referenced
images may be renamed, but images with confirmed cleanup intent cannot. Image cleanup
rejection lists occupying current-project and retained-history names, bounded per category.

Recursive deletion of project folders is rejected: speech sessions can contain several
projects and shared image originals must survive. Hard-deleting all metadata first loses
retained-resource discovery and retry evidence. Automatic cleanup on startup is rejected
because the owner required explicit control and accurate failure recovery.

No global orphan collector, automatic pruning, batch cleanup,
cross-device sync, restore/undo interface or arbitrary filesystem paths are introduced.
The supported runtime remains one local owner and one application worker. Concurrent
external filesystem modification must be resolved manually if identity checks detect it.

## Validation

Keep existing tests and add representative mode/ownership/CAS/busy/retry/migration checks.
Frontend and critical tests/review use GPT-6 Luna max per owner policy. Validate deletion
on synthetic projects in the authorized Mac directory, preserving all actual user projects
and shared images. Record exact checks and limitations in Task014 before claiming done.
