# ADR 0004 — Local project and output-history persistence

- Status: **Accepted — owner approved the proposed scope and choices on 2026-10-04**
- Date: 2026-10-04
- Task: [008](../../../tasks/done/008-project-history-persistence.md)
- Baseline: `055b081` on `main`

## Context

Task008 consolidates project saving, output history and restart audio reuse. The accepted
MVP already preserves media bytes, but cannot reconstruct their trusted associations
after a service restart.

At the recorded pre-Task008 baseline, code established these boundaries:

- `frontend/src/App.tsx` keeps the current source draft separately from the prepared
  document's source snapshot. Both must be saved; they can legitimately differ.
- `frontend/src/domain/sentences.ts` assigns document-local `sentence-001` identities and
  a `nextSequence` counter. Recreating a list starts that namespace again.
- `frontend/src/useVisualSelections.ts` uses one browser-wide image-selection key;
  the library itself is durable under ADR0003. Project selection must replace that global
  association state without silently attaching it to an unrelated document.
- `speech_assets.py` already validates WAV format, digest and exact ID/text/voice/configuration
  bindings. Its registry/cache and its restriction to the current session directory are volatile.
- `video_jobs.py` already freezes inputs, preserves earlier attempts, validates MP4 output,
  and serves by opaque asset ID. Its asset/job dictionaries are volatile.
- `speech_settings.py` includes model/runtime paths in its configuration fingerprint.
  Moving an equivalent environment therefore invalidates reuse today.

The design keeps the existing speech/renderer interfaces, visual library and one-heavy-job
gate. It introduces a project-storage boundary rather than a new service.

## Decision

### 1. One metadata database; existing media folders remain

Use Python's standard-library `sqlite3` adapter for small project/history metadata.
Store it at `SPEECH_WORKSPACE/state/projects.sqlite3`, inside the owner's approved project
directory. Derive this location from the configured workspace; do not hard-code a home
directory or create a second media root.

```text
SPEECH_WORKSPACE/
  state/projects.sqlite3       # project state, attempt snapshots, media registrations
  speech/<session-id>/*.wav    # existing immutable generated audio
  video/<job-id>/...           # existing frozen inputs and generated video
  visuals/...                 # existing ADR0003 image library
```

All are private runtime data excluded from Git. Existing media is not moved or duplicated
by this task. The target Mac's configured workspace must be checked before deployment;
no writes outside `/Users/QinWei/Documents/shadowing-video-studio` are authorized here.

Use explicit short transactions, foreign keys and an integer schema version. Start with
rollback-journal mode (`DELETE`) and `synchronous=FULL`; no ORM, separate database server
or WAL machinery. Database operations run off the async request loop with connections
owned by the executing thread. Never hold a transaction during model work, rendering,
hashing or media probing. Unknown newer schemas are reported rather than reset/recreated.
Create the state directory with private permissions and the database as owner-only where
supported (0700/0600 on Mac); reject linked state/database/journal paths. Use bounded lock
waits and report storage errors without hiding an unsaved draft.

The database is authoritative. A small project-storage interface owns save/list/open,
attempt snapshots and result registration. Domain objects do not expose SQL or paths.
Project listing/saving and historical audio playback must not require a working TTS model;
storage initialization is separate from `SpeechSettings.validated_paths()`.

### 2. Minimal records and stable identities

| Record | Stored data | Lifecycle |
| --- | --- | --- |
| Project | ID, name, revision, payload version, timestamps, current editor snapshot | Latest successfully saved editor state |
| Generation attempt | Project/document IDs, editor revision, attempt ID/type, immutable input/configuration snapshot, terminal/interrupted outcome | One explicit submission; no resume checkpoint engine |
| Speech asset | Opaque asset/session IDs, attempt/project/document/sentence IDs, registration sequence, exact text and configuration binding, digest, bytes, WAV metadata | Append on each successfully registered sentence |
| Video output | Opaque asset/job IDs, attempt/project IDs, digest, bytes and verified MP4 metadata | Append on each successfully registered export |

Store the editor and frozen input snapshots as versioned, validated JSON payloads in the
database; avoid a table for every UI property. The editor snapshot includes:

- Current source draft, original prepared-source snapshot, preparation mode and whether
  a prepared list exists. Unapplied AI proposals and active request state are not persisted.
- Document identity, ordered sentence IDs/text and `nextSequence`.
- Document-level selected voice, background ID and sentence-ID illustration associations.
- Authoritative audio associations kept separately from untrusted frontend reopening hints.

Saving a draft allows incomplete/empty sentence edits within bounded editor limits.
Generation still enforces the existing stricter 100-sentence/nonempty input limits; a
save must not secretly segment, trim, repair or regenerate the user's draft.

Create opaque project/document UUIDs. Preserve existing sentence IDs/counter within each
document and resolve bindings with `(projectId, documentId, sentenceId)`. Preparing or
applying a replacement list gives it a new document identity, even when its local sentence
IDs/text repeat. Text editing and reordering retain the document and surviving sentence
identities. Validate restored counters to prevent ID reuse after deleting/reopening.

Generation results are appended to their frozen attempt. They do not replace the current
editor snapshot or advance its edit revision. Reopening resolves valid audio for the current
document and exact binding, choosing the valid asset with the highest backend registration
sequence. Earlier audio remains registered; report when a newer unavailable result caused
an older matching asset to be restored. No user-selectable historical audio picker is added.
Backend-generated associations cannot be overwritten by an older browser save payload.

### 3. Save and browser-cache behavior

Minimum UI: **New project / Open project / project name / Save**, plus a save-status label
and a **Video history** section in the current workflow. No separate project dashboard.

Recommended behavior:

1. Work can start as an unsaved draft. First **Save**, or an explicit generation action,
   registers a project with a suggested name; the user can rename it. Show **Unsaved** and
   an available Save action from the first edit, including before project registration.
2. Once registered, save editor changes after two seconds without changes. **Save** remains
   available for immediate persistence. Serialize saves; coalesce pending edits and acknowledge
   only the exact local state that was committed. Show **Unsaved / Saving / Saved / Save failed**.
3. Before speech/video submission, wait for any in-flight save, then atomically save the
   exact draft and freeze its attempt through one generation command. If that transaction
   fails, report the error and do not start generation. Retries of the same submission
   identity must not create duplicate heavy jobs.
4. Before opening/creating another project, flush unsaved changes. On failure keep the current
   document and offer retry/cancel; an explicit discard returns to the last saved state.
5. A dirty page has an unload warning. Closing/crashing during the debounce window can lose
   changes not yet acknowledged as saved; do not rely on an unload request to guarantee storage.
6. After refresh, list saved projects and offer to reopen the last one. Opening/restoring
   does not start AI, TTS or rendering. Interrupted attempts are shown as interrupted.

Restore the editor, identity, voice and image selections as one coherent state before enabling
autosave; initialization must not save an empty document over a recovered one. Wait for voice
capabilities before applying the saved voice, and retain an unavailable saved choice with a
warning rather than silently substituting Aiden. Project switches invalidate pending save/load
responses and AI proposals through request/session guards; a late response cannot affect the
new project. Discarding a draft explicitly also discards its unapplied AI proposal.

Use a versioned `localStorage` key containing the last project ID and project/document-scoped
audio-association hints. Do not put dialogue, full project copies, filesystem paths or media
bytes in it. Cache loss/quota failure does not prevent backend project listing/opening.
The existing global image-selection cache is only an untrusted legacy hint for the current
unsaved session: offer reselection rather than automatically applying it to a new project or
replacement document. Never apply it to a reopened project over its recorded selections.

### 4. Results survive independently of the browser

At acceptance, each job is bound to an immutable project/document snapshot, distinct from
its transient UI polling handle. Register each successful WAV as it completes, including
when later sentences fail. Register each verified MP4 and its frozen input snapshot before
announcing durable success. This happens in the backend even if the browser stopped waiting.
Commit the video-output row and completed attempt state together. Each speech registration
also commits that sentence's success; finishing the last sentence commits the terminal outcome
in the same transaction. A crash after partial success leaves an interrupted attempt with its
registered successful sentences, rather than losing them or advertising the whole run complete.

For the first UI, disable project switching while actively monitoring a heavy job. After
**Stop waiting**, switching may proceed, with the notice that generation continues. A late
result stays with its originating project; it must not attach to the currently open project.
Keep the existing heavy-job gate and stale-response guards. No automatic job restart occurs
when reopening a project or restarting the service.
Keep an application-wide outstanding-task identity across project changes; do not lose it by
remounting project-specific speech/video hooks. Display the originating project and known or
unconfirmed submission state. Switching back reloads that project's authoritative associations
and history rather than reusing the current hook's global selection/export list.

History rows show creation time, voice, sentence count, duration and preview/download actions.
Viewing a row also shows its frozen text/visual/settings summary. Later edits never relabel
that row as the new document. Only successfully registered MP4s appear as available outputs;
failed/interrupted attempts can show an actionable outcome without a download link.

Historical media access validates the registered file and recorded generation-format evidence;
it does not depend on the current model/voice configuration being available. Current audio
reuse for a new export additionally requires a match with the current generation configuration.

### 5. Crash consistency and safe reopening

SQLite metadata commits and filesystem writes are separate operations. Use this order:

1. Write a new exclusively owned media file; finish/close it, validate it and flush its
   bytes and directory entry as supported by the target filesystem.
2. Commit its trusted registration and result association in one metadata transaction.
3. Only then return a durable ready/completed result to the UI.

Crash before step 2 can leave an unregistered file. Preserve it, but do not guess a binding,
advertise it as complete or automatically delete it. Registration/save failure must preserve
the last committed editor state and earlier media, and report that the new result was not
durably registered. A retry may require explicit regeneration.

Resolve paths only from validated opaque session/job/asset tokens and fixed application-owned
layouts. Do not accept client paths or arbitrary stored paths. Reject links/junctions and
escapes; retain bounded size, SHA-256 and format checks before serving/reusing media. A
registered audio asset may come from a previous owned session directory, unlike today's
current-session-only reader.

Exact audio reuse includes the scoped sentence identity/text, voice, language, model revision
and effective runtime/adapter configuration. Keep the current conservative fingerprint for
this task and store its version plus a nonsecret descriptor of versions/options, excluding
raw executable/model paths. Include an
explicit adapter/normalization version for any change affecting generated audio. A path or
configuration change makes reuse ineligible, preserves historical playback and asks for
explicit regeneration. Cross-machine or path-independent fingerprinting is deferred.
The approved frozen model snapshot remains immutable/read-only: replacing its weights under
the same path/revision is unsupported and is not detected by today's fingerprint. This task
does not introduce a full model-weight hashing scan on every project open.

On opening, return readable editor state with resource-specific warnings: missing/corrupt
images or audio require reselection/regeneration; missing MP4s remain unavailable history
entries. Do not clear unrelated resources or start a model call. Invalid editor metadata
blocks opening that project without replacing the current document. Unknown schemas or a
damaged database produce a clear error; never silently recreate it. Transactions do not
promise recovery from disk loss or arbitrary database corruption.

Existing pre-Task008 WAV/MP4 files without trusted durable bindings stay untouched. Durable
project/history registration starts with the new implementation; the old service has no
project-save/export API. Before restarting it for deployment, download any wanted outputs
and retain the source/edits separately. This task does not infer ownership/configuration from
legacy filenames, or promise to recover already-lost bindings. A separate legacy importer
would require its own verified binding source and scope decision.

## Alternatives considered

| Choice | Benefit | Cost for this task |
| --- | --- | --- |
| SQLite metadata + existing files (recommended) | Transactional project/result updates, bounded lookup, no new Python package/server | Database schema/versioning and one storage adapter |
| One JSON manifest per project | Easy to inspect manually | Coordinating edits, per-sentence results and output history needs a custom locking/atomic-update protocol |
| Browser-only storage | Very small UI change | Cannot authoritatively restore after cache loss or safely resolve files |

No ORM, event sourcing, edit-by-edit versions, cloud/device sync, deletion/pruning UI,
scheduler or MCP runtime is introduced. This task preserves a command/storage seam for those
future capabilities. Copying code through Git does not copy user projects or media.

## Implementation sequence

Deliver Task008 on one feature branch, one PR and one squash commit, in this order:

1. Storage adapter, bounded schemas, identity/revision validation and project save/list/open API.
2. Durable audio registrations and exact restoration; durable output records/frozen snapshots.
3. GPT-6 Luna/max frontend: project controls, save status, restore integration and history.
4. Focused critical-path checks, GPT-6 Luna/max backend-critical review, actual Mac acceptance,
   CI and synchronized task/runtime documentation.

Use optimistic edit revisions: a stale save returns a conflict rather than overwriting newer
edits. On conflict retain the local draft and offer reload after explicit confirmation;
automatic merge/multi-user collaboration is out of scope. At generation acceptance, use one
short write transaction to check the expected revision, save the validated exact editor payload
if changed, and insert the self-contained frozen attempt from that committed payload. Start
the heavy job only after commit. Another tab saving later cannot alter this attempt; a CAS
conflict before acceptance starts no work.
Create a stable client submission token before sending a generation request; the backend
records/maps it to the frozen attempt and exposes a query by that token. Keep pending tokens
as versioned browser hints so a lost response or refresh can be checked without resubmitting.
An unknown outcome remains unconfirmed; query/idempotent retries never silently launch a
second attempt, and reopening must not automatically submit work.
Use a unique `(projectId, submissionToken)` bound to the validated request digest: replay of
the same request returns the original attempt even when terminal/interrupted; a different
payload with that token returns a conflict. Explicit regeneration uses a new token. Create
and save operations use stable operation tokens and bounded durable receipts in the same
transaction as their writes, so a lost response does not create duplicate projects or report
a committed save as a stale-write conflict. No implicit retries of failed media attempts.

## Validation requirements

Keep existing tests. Add representative checks for:

- Save/reopen including unprepared/empty drafts, sentence identity/counter, voice and images.
- Failed transactions, lost-response retries and stale revisions preserving the last save.
- Partial speech success and exact reuse without inference; stale/forged/missing/corrupt media.
- Late completion bound to the original project and immutable historical MP4 snapshots.
- Restart marking unfinished work interrupted; no automatic generation; cache clearing.

On the approved Mac, save a project containing edits/images/voice/audio/video, close/reopen
the browser and restart the service. Confirm no-inference audio playback/reuse, a new export
and previous-video download after later edits. Also confirm save-failure feedback and an
unavailable-resource case. Run existing applicable checks and CI; no new cosmetic/frontend
test suite or independent per-helper scripts are needed.

## Owner decision

The owner approved these choices on 2026-10-04:

1. SQLite metadata under the existing workspace, with media folders retained.
2. Explicit first save + two-second autosave afterward, save-before-generation and visible
   failure/unsaved indicators.
3. Minimal project controls + immutable output history; preserve older files without
   automatic import of unregistered legacy media or cross-device project sync.

Task008 implements this decision; the owner accepted the Mac save/reopen/history workflow on 2026-10-04. Actual validation and delivery evidence is recorded in its task file.

## Technical references

- [Python 3.12 sqlite3 documentation](https://docs.python.org/3.12/library/sqlite3.html)
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html)

These describe the metadata mechanism; the application still owns file validation and the
two-step media-registration policy above.
