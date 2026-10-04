# Local projects and output history

Task008 implements [ADR 0004](../architecture/decisions/0004-project-history-persistence.md).

## Use

Name the draft and choose **Save**. After the first save, editing autosaves after two
seconds. Generation saves and freezes the current project before it starts. Watch the
save indicator: an error means the latest changes are still unsaved. Switching projects
flushes changes first; failed saves preserve the current editor.

Use **Open project** after a browser or service restart. Clearing browser storage loses
only reopening hints; the project list still comes from the local backend. Restoration
does not call AI, synthesize speech, export video or resume interrupted jobs.

Matching audio is reusable only within its original project/document and with exact
sentence ID/text, voice and current configuration. Changed inputs invalidate current
reuse, while older files remain. Output history shows immutable generation snapshots;
valid previous videos remain playable/downloadable after later edits.

## Storage and operation

Configure an existing absolute `SPEECH_WORKSPACE`, separate from the read-only model cache.
Run one backend worker, as required by the existing in-process heavy-job gate.

- `state/projects.sqlite3`: schema-versioned project snapshots, operation receipts,
  frozen attempts and trusted media registrations. SQLite uses rollback journaling,
  foreign keys and full synchronous writes; no additional dependency is required.
- `speech/<session-id>/<asset-id>.wav`: immutable validated audio.
- `video/<job-id>/render/video.mp4`: immutable validated output, with frozen render inputs.
- `visuals/`: existing visual library and JSON sidecars, unchanged.

Back up the entire workspace with the service stopped, including metadata and media.
Copying only SQLite does not copy audio/video/images. Do not edit its schema or sidecars,
run two services against the same database, or delete media while generating.
This feature does not implement cross-computer synchronization.

## Recovery and limits

Missing/corrupt/stale audio is reported as unavailable; regenerate explicitly. Missing
images keep their saved selection but require reselection before export. Valid unrelated
media and readable editor data remain available when a damaged history record is detected.
An unreadable database fails closed without replacement or automatic repair.

The last committed save remains authoritative after a failed transaction. Stale revisions
return a conflict instead of overwriting another save. Save/generation tokens support
response recovery for the same frozen request; generation is never retried implicitly.
Restart marks unfinished attempts interrupted and retains registered successful audio.

Pre-Task008 files are preserved without importing guessed bindings or recreating lost
project state. No automatic pruning/deletion occurs. Bounded metadata limits return an
explicit capacity error rather than discarding existing work. Unsaved drafts can still
be lost when closing a tab; save status is the source of truth.
