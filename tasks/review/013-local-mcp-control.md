# 013 — Local MCP control with transient reviewed requests

## Goal

Let a local AI client discover application capabilities, prepare sentence proposals and
submit reviewed speech/video work through the same generation commands used by HTTP.

## Context

The owner authorized MCP implementation on 2026-10-04 while Task008 is developed in
another chat. Do not implement its persistence or project/editor synchronization here.
Task005 reserved the control boundary; this task is an explicit post-MVP exception.

## Requirements

- Official Python MCP SDK inside the existing single local FastAPI process.
- Discover live speech/video/visual availability; list text providers and visual assets.
- Explicit-provider sentence proposals, never automatic acceptance or media generation.
- Frozen transient speech/video requests, explicit local human review, configuration
  revalidation, session-bounded idempotency, job/result queries and safe errors.
- A read-only connection cannot create proposals/requests or execute work.
- No arbitrary paths, shell execution, credential retrieval, media deletion, automatic
  retries, actual cancellation, restart resume, scheduling or batch execution.
- Advertise project/history integration as deferred to Task008. Do not pretend a transient
  request is a saved project, or that it changes the existing frontend document.

## Architecture constraints

MCP and HTTP share application generation commands and the same SpeechJobs/VideoJobs
instances/heavy-job gate. No adapter writes persistent project metadata or runs providers
directly. Review does not launch generation; approved requests require explicit execution.

## Acceptance criteria

- [x] Official SDK client connects and discovers schemas over local Streamable HTTP.
- [x] Disabled/unauthorized/nonlocal connections fail; read-only mutations fail.
- [x] MCP tools expose neither approval operations nor approval nonces; local review
  escapes user content under the documented trusted-local-user boundary.
- [x] Changed inputs require a new ID/review; stale configuration cannot use old approval.
- [x] Concurrent/repeated execution submits at most once in a service session.
- [x] Existing media services validate exact bindings, preserve files and expose progress.
- [x] Task008 seam and session/restart limitations are documented.
- [x] Relevant local checks pass and required backend review findings are resolved.
- [ ] Pull request CI passes before merge.

## Out of scope

Task008 storage/restore/editor synchronization; new templates/providers; scheduling,
cancel/resume; remote/cloud access; OAuth/accounts; frontend redesign.

## Validation

Focused backend tests for review/idempotency/security and actual SDK HTTP transport;
existing backend tests and Ruff; repository checks/CI. Deterministic providers exercise
control without paid calls or model downloads. Real Qwen/FFmpeg regeneration is not
represented by fake-provider tests.

## Human decisions required

The owner explicitly approved the official SDK and the default-disabled, direct-local
read/execute credential and per-request human-review policy on 2026-10-04. See ADR0005.

## Implementation notes

Worktree isolated from Task008. Session-only review tickets expire 30 minutes after
creation; submitted outcomes remain idempotent until service restart. No new project
persistence format is selected. A dedicated server-rendered review page works without a
frontend build. Task008 follow-up must attach reviewed requests to authoritative project
versions and restore history; it must not silently reuse session approval or auto-run work.

Documentation review reconciles the original MVP exclusion with owner-authorized Task013
and ADR 0005, documents backend-origin review paths (development port 8765 or explicit
standalone port 8000), operation-specific payloads and structured/safe protocol results.
Local validation and required code review completed; pull request CI remains a merge gate.

The owner subsequently reported an initial Task008 implementation on
`feature/008-project-history`, subject to further changes. Its fetched API/application
contracts and project-history guide have been inspected. This branch is the docking
target; MCP project tools and durable request binding remain reserved. Task013 must
preserve the saved-project store, revision conflicts, trusted media registration and
explicit restart recovery. ADR 0005 records MCP; ADR 0004 belongs to Task008 persistence.

The MCP branch is based on the supplied Task008 initial commit `902bb3a`. Existing
project storage/restore remains supported; only MCP binding is deferred. This task
does not modify Task008 production storage behavior. Review guarantees exclude
isolation from trusted local processes with separate HTTP/browser access.


## Validation evidence

- Integration target rebased from initial `902bb3a` to owner's corrected `4e0e3e5`.
- Backend pytest: 217 passed, one existing skip. Ruff lint/format passed.
- Spike helpers: 11 passed; shell syntax passed.
- Frontend typecheck, 167 tests and production build passed. Frontend is unchanged from
  Task008's corrected target; its initial 16 UI failures were fixed by that task.
- Official MCP SDK HTTP integration verifies discovery, authorization, frozen review,
  idempotent submission/query, sanitized errors and reserved project-history rejection.
- Task008-backed integration preserves saved project revision/history during transient
  MCP generation. Actual loopback SDK connection verified eight tools, read-only
  capabilities, review page and startup with a real empty Task008 store.
- GPT-6 Luna/max backend production review found no remaining Blocker/Required findings;
  required image-preview and durable job-query scope findings were resolved. Tests and
  frontend excluded from review per selected scope. Docs mention image/audio review.
- Documentation links/JSON examples validated. No secrets or generated media staged.

## Delivery limitations

MCP is disabled until local credentials are configured. Requests/approval/idempotency are
session-only; saved-project tools, editor synchronization and durable request binding
remain reserved. No scheduling or cancel/resume. No real Qwen/FFmpeg generation or paid
provider request ran; fake providers validate controls, not media quality. PR CI is pending.
