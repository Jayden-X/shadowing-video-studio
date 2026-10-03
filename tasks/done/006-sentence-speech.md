# 006 — Generate and preview sentence speech

## Goal

Connect reviewed sentences to real local Qwen3-TTS generation, with preview, regeneration,
and safe reuse of successful audio.

## Context

The manual editor and reviewed AI proposals are delivered in Tasks 002/003. Task 004
validated the target Mac's official CPU/0.6B CustomVoice path; the owner accepted Aiden
and explicitly authorized continuing speech/video integration. Follow the product
requirements, ADR 0001, and existing standards.

## Requirements

- Start speech only through an explicit user action using a frozen sentence ID/text list.
- Use a project-owned SpeechProvider contract and optional, lazy Qwen integration.
- Default to the validated CPU/float32/eager, English/Aiden, frozen local 0.6B model;
  reuse the existing isolated runtime and never silently substitute a backend or model.
- Keep the model loaded across sentences; serialize heavy local generation.
- Report per-sentence progress, safe errors, and partial success. Failed/repeated work
  must preserve successful audio and the editor's text.
- Support sentence preview and explicit regeneration; reuse unchanged successful audio.
- Edited/deleted/replaced sentence content must not use stale audio for preview/export.
- Serve WAV assets by opaque server-owned IDs, never arbitrary client paths.
- Confine media/cache/temp writes to an explicit existing local workspace; prevent path
  escapes, avoid overwriting old assets, and keep runtime files outside Git.
- Use volatile run/job metadata for this delivery, with the restart limitation visible.
  Do not introduce a durable project/history format before its separate decision.
- Provide readiness reasons without installing models or invoking generation.

## Architecture constraints

FastAPI/React and optional Python Qwen runtime remain unchanged. Domain/application code
must not depend on vendor tensors. UI and later video rendering share validated application
commands/assets. No ordinary CI model download, external inference, cloud or scheduler.

## Acceptance criteria

- [x] A reviewed sentence list can trigger local generation with observable progress.
- [x] Successful sentences can be played; unchanged audio is reused.
- [x] Regeneration replaces current selection while preserving prior generated assets.
- [x] Provider failure reports an actionable safe message and preserves text/partial audio.
- [x] Stale audio is ineligible after sentence edits or document replacement.
- [x] One heavy generation job runs at a time; repeated clicks do not create duplicates.
- [x] Actual target Mac generates and serves at least two synthetic sentences through API.
- [x] UI behavior, provider/asset/API failures, and path boundaries have deterministic tests.

## Out of scope

Video rendering (Task 007), voice cloning, MPS optimization, project/history persistence,
double-click packaging, scheduling, MCP server, multi-user access and multiple videos.

## Validation

Run `bash scripts/check.sh`, deterministic provider/job/filesystem/API/UI tests, browser
smoke for generate/preview/regenerate/edit invalidation/failure, and an actual Mac API
integration using synthetic English. Resolve review findings and pass PR CI before squash.

## Human decisions required

None for this scope. CPU/0.6B/Aiden is already approved. Request approval for any Mac write
outside `/Users/QinWei/Documents/shadowing-video-studio` or `~/.cache`.

## Implementation notes

- Target Mac application API generated two synthetic sentences in 37.35 s, serving valid
  24 kHz WAVs of 3.76/3.12 s. An unchanged request reused the same asset IDs in 0.01 s.
  Explicit regeneration took 10.23 s, created a new asset ID, and kept the prior WAV accessible.
- The full local check passed after synchronization with Task 004: 129 backend tests,
  one Windows symlink-permission skip, 148 frontend tests, typecheck/build, Ruff and spike
  helpers. The owner subsequently confirmed that browser speech playback and explicit
  single-sentence regeneration both passed on the target Mac.
- The owner's focused MVP testing policy and GPT-6 Luna/max frontend/review assignment
  are recorded in the smallest relevant standards files.

Backend implementation includes:

The owner's latest MVP testing policy keeps existing tests and adds coverage at key
workflow/risk boundaries only; it is recorded in `docs/standards/testing-standards.md`.
ADR 0002 records the worker as an internal SpeechProvider execution boundary, preserving
the existing framework, user startup flow and application/port/adapter dependency direction.

- Project-owned `SpeechProvider`, frozen sentence bindings, and a shared `HeavyJobGate`.
- Lazy persistent official Qwen worker in the explicitly selected Python runtime;
  CPU/float32/eager, English/Aiden, approved snapshot
  `85e237c12c027371202489a0ec509ded67b5e4b5`. Runtime metadata is pinned to the Task 004
  tested package versions; no install/download or silent backend/model fallback.
- A single queued/running heavy job, polling DTOs, partial success, unchanged exact
  ID/text/config reuse, explicit single-sentence regeneration, and preserved prior WAVs.
- Opaque asset IDs, validated mono PCM16/24 kHz WAVs, bounded session reservations,
  content hashes and exact bindings for later video rendering. No durable metadata format.
- Loopback Host/Origin controls protect speech routes. Deadlines/cancellation kill and
  reap worker ownership; runtime caches/TMP/bytecode behavior are confined to the workspace.
- Production token budget is 4096; a restored per-call observer requires EOS before
  an asset can become ready. EOS does not replace listening/content review.

Backend validation on Windows, 2026-10-03:

```powershell
# backend/ in the Task 006 worktree, using the existing lightweight temporary environment
python -m ruff check .
python -m ruff format --check .
python -m pytest -q --tb=short
```

Ruff checks passed; pytest **129 passed, 1 skipped**, with one pre-existing Starlette/httpx
deprecation warning. The skip is Windows symlink-creation permission; boundary checks
otherwise ran. Tests use offline providers/process fakes and temporary tiny WAVs, including
generation/reuse/force/partial failure, exact bindings, filesystem limits, EOS/restoration,
worker startup deadline/cancellation/output bounds and cleanup, and the HTTP contract.

Target Mac generation/serving and the full repository check passed as recorded above.
GPT-6 Luna/max reviewed the critical implementation with no Blocker/Required findings.
PR #7 CI runs 37149563043 and 37150077565 passed. The owner confirmed browser playback
and single-sentence regeneration on the target Mac. Video export failed in Task 007 because
the configured FFmpeg lacks `drawtext`; that separate renderer issue does not invalidate
the accepted speech workflow. The final documentation-only revision must pass CI before squash.
See [speech runtime](../../docs/development/speech-runtime.md) and ADR 0002 for setup,
lifecycle, limits, volatile metadata/restart behavior and the shared rendering gate.
No generated media, model/cache files, personal dialogue or secrets are committed.
