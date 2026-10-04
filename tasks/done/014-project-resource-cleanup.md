# 014 — Delete local projects with explicit resource choices

## Priority and status

- Priority: **P3**.
- Status: **done — implementation, focused review, automated checks, Mac deployment and owner UI acceptance complete**.

## Goal

Let the owner remove unwanted local projects and choose which associated files to keep.

## Context

Task008 preserves project/history metadata and immutable local media without deletion or
automatic pruning. On 2026-10-04 the owner requested three deletion choices. They belong
to this follow-up rather than expanding Task008's accepted persistence scope.

## Requirements

Offer exactly these owner-confirmed choices:

1. **Delete project only** — retain intermediate resources and final outputs.
2. **Delete project and intermediate resources** — retain final outputs.
3. **Delete project and all resources** — include final outputs in the deletion scope.

Before deletion, show which project and resource categories will be affected, the selected
mode, file counts/size and what will be retained. Request explicit confirmation. Never
interpret "all resources" as every file in the shared workspace or visual library.

Only delete trusted, application-owned resources attributable to this project. Protect
resources still referenced by another project, generation attempt or historical output;
report retained/shared resources in the result. Do not infer ownership from filenames.
Block destructive cleanup of active work. Preserve unrelated projects and media.

Define incomplete/crashed deletion recovery and idempotency before implementation. Report
partial failure accurately; avoid orphaning metadata through a false success response.
Resources retained by a deletion mode must remain locatable through a defined mechanism,
even when their project is no longer listed.

## Architecture constraints

Use Task008's project commands and authoritative storage/registration boundaries. Deletion
must not expose arbitrary filesystem paths or bypass local request guards. Any schema or
resource-lifecycle change requires an accepted ADR/owner decision first.

## Acceptance criteria

- [x] UI exposes the three choices with a clear scope preview and confirmation.
- [x] Project-only deletion retains all associated resource bytes.
- [x] Intermediate cleanup retains final MP4s and defines how to find them afterward.
- [x] All-resource cleanup deletes only eligible resources associated with the project.
- [x] Shared resources and unrelated project/history files remain intact.
- [x] Independent image-library cleanup previews/confirms one unused image; active project
  and retained historical references block deletion, with explicit partial-failure retry.
- [x] Image reference rejection names the occupying current projects and generation history.
- [x] Image library and retained resources appear on a separate resource-management page;
  switching pages preserves the current video draft and running-work restrictions.
- [x] Images can be renamed in the library without changing their IDs, bytes or project
  associations; stale-name conflicts and cleanup/busy restrictions give explicit feedback.
- [x] Active-work rejection, cancellation, partial failure and interrupted cleanup give
  accurate feedback without silently losing unrelated data.
- [x] Critical reference/ownership and recovery checks pass; validate the main workflow
  on the authorized Mac with synthetic projects before using real user projects.

## Out of scope

Automatic/background pruning, cloud sync, bulk deletion, arbitrary folder deletion,
and deletion of referenced shared library resources.

## Human decisions required

No unresolved product/lifecycle decision. The owner approved the three modes, retaining
shared library originals during project cleanup, read-only retained-resource discovery,
and the independent unused-image cleanup entry. ADR0005 defines the accepted migration,
reference accounting and partial-failure recovery. Browser acceptance remains a delivery gate.

No destructive deletion has been authorized against any particular existing project by
the feature request. Implementing a confirmed deletion UI does not authorize agents to
clean user projects automatically.

## Validation

Keep existing checks. Use a small representative set of critical ownership/shared-resource,
mode-selection and failure-recovery scenarios. Delegate frontend/unit-test work to GPT-6
Luna with max reasoning, following the owner's current focused-testing policy.

## Implementation notes

Requirement recorded on 2026-10-04. Implementation and isolated synthetic validation are
recorded below. No existing user project has been selected for deletion by the agent.

## Approved implementation plan — 2026-10-04

The owner confirmed shared image originals remain in the library and retained files are
found through a read-only retained-resource list. [ADR0005](../../docs/architecture/decisions/0005-project-resource-cleanup.md)
records compatible schema migration, tombstones, resource ownership and explicit journaled
cleanup/retry. No actual user project is selected for deletion by this development approval.

Validation/review/Mac/CI evidence remains pending while implementation proceeds.

The owner also approved the independent image-library cleanup entry for this delivery.
Its reference protection, deletion journal and separate confirmation are defined in ADR0005.

## Implementation and validation evidence — 2026-10-04

- Added schema-2 project tombstones, allocation ownership, project/image cleanup journals
  and consistent non-overwritten v1 database backup. No startup deletion.
- Added three-mode project preview/confirmation, retained audio/video groups and image
  library preview/confirmation with active/frozen-history reference protection.
- Same-token outcomes/retry survive restart; image cleanup operations remain discoverable
  even after a confirmed image is hidden from selection lists.
- Existing frontend tests retained: `npm run check` passed typecheck, 167 tests and build.
- Final backend `pytest -q` passed 214 tests with 4 environment skips and one existing
  Starlette/httpx deprecation warning. Eight focused
  scenarios cover modes, shared/session ownership, unknown files, CAS/busy/retry, archival,
  links, migration and image references. Final focused rerun also passed all 8 scenarios,
  including quota/replay, cached-job visibility and image partial/restart/API recovery.
- Final Ruff/format and Git whitespace checks passed; existing spike helper checks: 11 checks with
  one Windows symlink skip. Git Bash `bash -n scripts/spikes/qwen3_tts_macos.sh` passed.
- GPT-6 Luna/max frontend/test delegates and backend review followed the owner policy.
  Review identified and fixed missing `.mkv` page-clip cleanup and stale current-process
  media storage charges and all-mode cached-job API visibility. Final review covered all
  8 selected backend production files with no remaining P1/P2 blocker. Frontend/tests
  were excluded from review as requested; OCR used deterministic delegation only.
- Mac isolated port 8878 used only new synthetic projects under
  `/Users/QinWei/Documents/shadowing-video-studio/tmp/task014-20261004-001/media`.
  Real CPU/Aiden synthesis and FFmpeg exports passed all three modes, retained media hash
  comparisons, outcome replay and shared-image reference checks. Unused-image cleanup
  succeeded after its all-resource history was removed. The isolated process was stopped.
  Evidence remains in that stage's `evidence/cleanup-matrix.json` (not committed).
- PR #17 at code commit `36b254e`: backend, frontend and repository-hygiene CI all passed.
  [PR #17](https://github.com/Jayden-X/shadowing-video-studio/pull/17) remains draft pending
  live deployment and owner browser acceptance. Documentation-only updates retain this code.
- SSH recovered and final production build was revalidated in the separate Mac stage
  `tmp/task014-20261004-002/media`: all three real TTS/FFmpeg cleanup modes, media hashes,
  retry replay and gallery references passed. Its isolated 8878 process was stopped.
- Live Mac service at port 8877 now runs Task014 (PID 85525). Deployment verified all
  3 existing project snapshots/revisions/history availability and SHA-256 hashes of all
  622 existing media files unchanged. Schema 2 migration passed and the preserved backup
  was verified as schema 1. No existing user project was deleted or edited.
  Evidence: `tmp/task014-20261004-002/evidence/user-data-preserved.json` on the Mac.
- Owner browser acceptance remains pending; the owner was given port 8877 and asked to
  use new test projects/images for confirmation. PR remains draft until acceptance.

### Owner acceptance feedback

The owner requested named occupying-project/history feedback, a separate resource page,
and image display-name editing. These are included in Task014 rather than new product tasks.
Backend naming and rename changes passed focused tests and the 214-test backend regression
(4 environment skips). Targeted GPT-6 Luna/max review found a sidecar read-window conflict
gap; exact metadata comparison fixed it, and re-review reported no remaining blocker.
The rename read-window regression also passed: a concurrent external name edit returns
409 and is preserved. Final backend regression remains 214 passed / 4 skipped with all
8 focused scenarios passing. Frontend typecheck, 167 tests and production build passed.
Feedback build deployed to Mac port 8877 (PID 85900), stage `tmp/task014-20261004-003`.
Isolated Mac rename/ref test confirmed image bytes/project snapshot unchanged, stale-name
409 and the occupying project's name in the response. Live deployment preserved hashes of
all 594 media files present immediately before deployment; no user project was deleted by
the agent. SSH briefly failed after deployment, then recovered; isolated PID 85861 at
port 8878 was stopped successfully. Owner UI reacceptance pending.

The owner accepted naming/rename behavior but observed resource components still visible
on Create video. Root cause: `.resource-manager-page { display: grid }` overrode native
`hidden` display behavior. GPT-6 Luna added `.app-page[hidden] { display: none }`;
frontend typecheck, 167 tests and build passed. Frontend-only build004 was deployed with
atomic index replacement, without restarting the backend. Mac HTTP check verified the
served CSS includes the hidden-page rule. Evidence: stage003 `evidence/page-visibility-fix.json`.
The owner confirmed final visual acceptance on 2026-10-04. The complete Task014 workflow,
including feedback refinements, is accepted; final squash delivery uses PR #17.

Known limits: no undo/secure erase/background pruning; unknown/unregistered files stay;
project render directories may remain empty; cleanup does not reset session job-count
limits or unverified failed reservations. Backups retain their original user data.
For unknown nested directories, retained size measures direct known/unknown files only;
it does not recursively sum preserved nested contents. This is a low-priority preview
precision limitation, not deletion of those contents.
