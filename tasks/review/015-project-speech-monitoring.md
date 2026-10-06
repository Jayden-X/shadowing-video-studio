# 015 — Validate project speech and video consistently during monitoring

## Goal

Accept valid project-bound speech and video progress during submission, polling and explicit resume.

## Context

The owner reported that `speechApi.ts` accepts the four project metadata fields on
submission, but rejects them during polling and submission-token recovery. Follow
ADR 0004 and the existing project speech API contract.

## Requirements

- Use one project job schema throughout submission, polling and recovery.
- Preserve strict key, sentence, voice/configuration and project identity validation.
- Resume by querying the existing job/token without submitting generation again.
- Add focused frontend regression coverage.

## Acceptance criteria

- [x] Valid project speech submissions continue through polling to completion.
- [x] Explicit resume accepts project jobs from both job and token queries.
- [x] Malformed/mismatched project metadata remains rejected.
- [x] Ordinary speech jobs and existing checks remain compatible.

## Out of scope

Backend contracts, persistence changes and unrelated generation features.

## Validation

- Focused speech API and monitoring regression tests.
- Frontend typecheck, full test suite and production build.
- Repository checks when the configured local tools are available.

## Human decisions required

None.

## Standards affected

None; existing frontend delegation and focused testing policies apply.

## Implementation notes

Branch: `codex/fix-project-speech-monitoring`. Frontend implementation/tests delegated to
GPT-6 Luna/max as required by the repository standards.

- `speechApi.ts` shares strict project schema validation across submission, polling and
  token recovery. `useSpeech.ts` carries project expectations through monitoring and uses
  the recorded attempt revision and frozen inputs during recovery.
- Regression tests cover project metadata in all three API paths and explicit monitoring
  resume. The project API test server now returns project metadata consistently.
- Verified on 2026-10-06: focused frontend tests 51 passed; full frontend suite 170 passed;
  TypeScript typecheck and Vite production build passed; backend suite 217 passed, 1 skipped;
  Ruff lint/format, 11 spike helper tests and spike shell syntax passed. `git diff --check`
  passed. The same checks as `scripts/check.sh` ran directly with existing bundled Node
  and backend virtual environment tools because `npm` and `uv` were unavailable on PATH.
- Frontend code and tests are excluded from independent code review by the current
  repository review policy. No backend production logic changed.
- Delivery PR: [#21](https://github.com/Jayden-X/shadowing-video-studio/pull/21).
- On 2026-10-06, updated the existing Mac service's frontend under
  `tmp/task014-20261004-003/source/dist` with the verified build. Preserved the previous
  index under ignored `tmp/task015-local-run/previous-index.html` and kept old hashed
  assets. No service restart, project write or media generation was needed.
- `http://127.0.0.1:8877/` serves index/JavaScript bytes identical to the fixed build;
  `/api/health` returns `ok`, and speech status reports available. Requested opening the
  page in Codex. Real Qwen generation/browser workflow smoke was not rerun.
- Ready for delivery review; remote CI and merge are not yet confirmed.

### Edge recovery regression — 2026-10-06

The owner reported `invalid speech attempt details` after the local frontend update.
Native Edge inspection confirmed the error on a saved ten-sentence project. Read-only
API inspection showed completed jobs with ten sentences and a frozen request containing
`singleSentenceId: null`. No dialogue or user project payload is stored in this task.
Recovery treated null as a whole-document selection, but its next length guard treated
every value other than undefined as a single-sentence selection. The previous recovery
test used only one sentence and missed this mismatch. The follow-up fix uses the same
null/undefined predicate for selection and length checking; the recovery regression now
uses two sentences with the backend's explicit null selection.

- Follow-up validation: focused frontend tests 51 passed; full frontend suite 170 passed;
  TypeScript typecheck, Vite production build and `git diff --check` passed.
- Updated the same local service frontend. In the owner's Edge window, refreshed,
  reopened the saved project and clicked **Resume speech monitoring**. The page showed
  **Speech is ready**, **10 of 10 current sentences have audio**, and enabled **Generate
  video**. Recovery read existing completed results without starting generation.
- This is actual browser recovery evidence. No real synthesis or video export was rerun.

### Project video monitoring — 2026-10-06

The owner subsequently reported the same strict-schema mismatch in video polling.
Read-only local API inspection confirmed a completed ten-sentence video with a registered
asset and matching project/document/revision/token fields. Edge displayed invalid video
progress and an available Resume video monitoring action. The owner authorized fixing
the video counterpart; the same PR now covers both project media monitoring paths.

Acceptance: submission, polling and token recovery use the same strict Project Video Job
schema, reject mismatched metadata, and recover an existing output without resubmission.
Implemented in `videoApi.ts` and `useVideo.ts`, with project-bound API/UI fixtures and
regressions. Verification: video API/UI focused tests 10 passed; full frontend suite
173 passed; TypeScript typecheck and production build passed. No backend logic changed.

Updated the same local frontend, refreshed the owner's Edge page, reopened the saved
project and clicked **Resume video monitoring**. The page showed **Video is ready.
Preview it and download the MP4.**, enabled Generate video, and exposed the existing
MP4 in preview/download and saved history. Ten of ten sentence audios remained available.
No speech generation or video rendering was started during recovery verification.

The testing standard now requires realistic project DTOs throughout submission/polling/
recovery and multi-sentence recovery with backend optional-field encoding.
