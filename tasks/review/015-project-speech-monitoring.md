# 015 — Validate project speech consistently during monitoring

## Goal

Accept valid project-bound speech progress during submission, polling and explicit resume.

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

Backend contracts, persistence changes, video monitoring, model inference and deployment.

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
