# 008 — Save and restore local projects and output history

## Priority and status

- Priority: **P3** — after the accepted MVP and P2 visual/voice features.
- Status: **in progress** — owner approved [ADR 0004](../../docs/architecture/decisions/0004-project-history-persistence.md) on 2026-10-04.

## Goal

Save local projects and output history so the user can reopen their work after closing the
browser or restarting the service, with valid existing audio/video available again.

## Context

The owner consolidated restart audio reuse into project/history preservation on 2026-10-04.
This replaces the narrower Task008 audio-cache task: one project recovery workflow covers
source/editor state, resource selections and trusted media associations. Task009 already
persists its visual library; Task010 supplies exact voice/configuration bindings.
Frontend-cached association keys remain convenient hints; saved backend metadata is authoritative.

## Requirements

- Save, list and reopen local projects. Persist stable project/sentence identities, original
  source, current ordered/edited sentences, selected document voice, background and
  sentence-ID illustration associations.
- Record generated audio and completed MP4 outputs with their frozen inputs/configuration.
  Show historical outputs against their recorded snapshot, rather than the current edited
  project. Saving or generating again must preserve earlier files and output records.
- Retain successfully saved work across browser/service restarts. Define save triggers and
  failure feedback before implementation; never report a failed durable save as successful.
- Keep small versioned project/asset metadata separate from large WAV/MP4 files. Cache stable
  association keys in the frontend, but never trust browser values or old service IDs as
  proof of a valid binding or permission to access a filesystem path.
- Restore only application-owned resources through backend APIs. Validate bindings, file
  boundaries/ownership, content digest and media format before returning preview/export references.
- Current reusable audio must match exact sentence ID/text, voice, language, model identity/
  revision and effective configuration, including relevant runtime/normalization changes.
  Successful reuse runs no inference. Changed inputs make old audio ineligible for new
  exports while preserving it; returning to a valid matching binding may restore it.
- Historical MP4s retain their own frozen inputs and remain previewable/downloadable after
  integrity checks even when the current project has changed.
- Explain missing/corrupt metadata/files and stale associations. Preserve readable editor
  data and unrelated assets; require explicit regeneration/reselection where necessary.
  Clearing browser cache may lose convenience hints but must not prevent listing/reopening
  projects that remain in authoritative local storage. Removed local files are not recoverable
  by promise.
- Restore must not automatically run AI/TTS/export, resume interrupted jobs or label
  unfinished output complete. No automatic pruning, overwrite or media deletion; no
  full dialogue/secrets in diagnostic logs.

## Architecture constraints

Canonical models remain project-owned and storage-independent. Keep the existing visual
library, SpeechProvider/VideoRenderer, validated media APIs and one-heavy-job rule.
Persistence owns project/history metadata; frontend cache is optional convenience data.
No cloud/account synchronization or scheduler/MCP implementation in this task.

## Acceptance criteria

- [ ] Save/reopen after browser/service restart restores source, stable sentence IDs,
  order/edits, voice, background and illustration associations.
- [ ] Completed outputs remain listed with their original input/configuration snapshots;
  later edits or generation preserve earlier media and history records.
- [ ] Matching saved audio restores without a model call and supports normal preview/export.
- [ ] Voice/text/configuration changes prevent stale audio reuse; valid historical MP4s
  remain accessible against their recorded snapshots.
- [ ] Missing/corrupt cache/project/asset metadata or media gives an actionable error,
  preserving recoverable editor state and unrelated assets, without automatic inference.
- [ ] Forged references/paths cannot serve unrelated files or bypass integrity/binding checks.
- [ ] Browser cache clearing still permits reopening locally saved projects; missing local
  files are reported as unavailable.
- [ ] Failed/interrupted saves preserve the last successful state under the selected
  atomic recovery policy and clearly identify unsaved changes.

## Out of scope

Full edit-by-edit version control/undo history, project merge/collaboration, media deletion/
pruning, cloud/cross-device sync, batch/scheduler/MCP runtime, automatic job resumption,
and changes to the accepted TTS backend/model.

## Validation

Retain existing tests; cover key save/reopen, atomic-save failure, exact audio restoration,
stale/missing/corrupt resources, file safety and historical preview/download paths.
Use the owner's focused testing and GPT-6 Luna/max frontend/test/critical-review policies.

On the actual Mac, save edited sentences with images/voice/audio/MP4; close/reopen the
browser and restart the service. Verify project recovery, no-inference audio reuse,
preview/export and access to previous outputs after later edits. Run applicable checks/CI.

## Human decisions required

Before implementation, document the required persistence ADR/owner decisions for:

- Backend project/history/asset format and location, schema versioning/compatibility.
- Frontend cache format and stable project/document/sentence identity restoration.
- Explicit save/autosave triggers, failure feedback and atomic-write/recovery policy.
- Minimum output-history snapshot representation and save/open UX.

Scope and storage/save choices are approved under ADR 0004.

[Accepted ADR 0004](../../docs/architecture/decisions/0004-project-history-persistence.md)
selects SQLite metadata in the existing media workspace, explicit first save with later
autosave, and project controls/output history.

## Standards affected

Existing architecture, security, focused-testing, documentation and delivery standards.

## Implementation notes

Implementation started on 2026-10-04. Validation and delivery evidence will be recorded here.

### Collaboration checkpoint — 2026-10-04

The owner requested an early remote branch checkpoint because other tasks depend on this
work. Branch: `feature/008-project-history`. This is an implementation checkpoint, not an
accepted or merged delivery; dependent work should use the project-scoped API contracts
and allow for corrective changes before final acceptance.

- SQLite store, project commands/API, durable speech/video bindings and frontend
  save/open/autosave/history integration are implemented.
- Backend suite: **202 passed, 4 skipped** on Windows; focused new scenarios: **8 passed,
  1 skipped**. Windows symlink tests are limited by symlink creation permissions.
- Frontend typecheck and production build pass. Existing tests currently report **151
  passed, 16 failed**; adapting old API/cache mocks and resolving regressions remains open.
- Actual Mac restart/media validation, final frontend checks, PR CI and acceptance are
  pending. No completion claim is made by this checkpoint.

The owner explicitly waived code review for Task008 on 2026-10-04. The review subagent
was interrupted. Existing checks, focused critical-path tests, CI and actual Mac validation
remain required; this waiver does not change the repository-wide review policy.

### Validation follow-up — 2026-10-04

- Frontend existing API mocks now cover project-scoped commands; all **167 tests across
  10 files**, typecheck and production build pass. Changing voice hides audio playback
  with a mismatched current binding while preserving the old recording.
- Backend rerun after startup recovery fix: **202 passed, 4 skipped**. Ruff lint/format
  pass, spike shell syntax passes, and 11 deterministic spike checks run with 1 skip.
- A damaged unfinished attempt no longer blocks all readable projects at startup; its
  original evidence is retained and its status becomes interrupted. A synthetic storage
  integration check verified editor preservation and unchanged damaged evidence.
- Draft [PR #15](https://github.com/Jayden-X/shadowing-video-studio/pull/15) is attached.
  The first checkpoint passed backend/hygiene CI but failed frontend before the mock fixes;
  the corrective head requires a fresh CI result.
- Mac Task008 service deployed successfully at `http://127.0.0.1:8877/`, reusing the
  approved existing media workspace and preserving the Mac checkout. Deployment sources,
  logs and nonsecret settings live under project `tmp/task008-20261004-001`.
  Subsequent SSH connections timed out, before real speech/video smoke execution could be
  confirmed. Actual media/restart and owner browser acceptance remain **unverified**;
  the owner was asked to restore the SSH connection. The task remains in progress.
