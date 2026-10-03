# 008 — Save and restore local projects and output history

## Priority and status

- Priority: **P3** — after the accepted MVP and P2 visual/voice features.
- Status: **backlog** — unified scope approved; persistence/save design pending.

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

Scope consolidation is approved; these storage/implementation choices remain unresolved.
Do not assume a browser cache API, database or checkpoint format.

## Standards affected

Existing architecture, security, focused-testing, documentation and delivery standards.

## Implementation notes

Requirements only. No persistent store/history UI/restore API/runtime change is delivered
by consolidation. The accepted MVP's volatile document/audio/video lookup behavior remains
until this unified task is implemented.
