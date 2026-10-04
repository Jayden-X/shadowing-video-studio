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

- [ ] Official SDK client connects and discovers schemas over local Streamable HTTP.
- [ ] Disabled/unauthorized/nonlocal connections fail; read-only mutations fail.
- [ ] MCP tools expose neither approval operations nor approval nonces; local review
  escapes user content under the documented trusted-local-user boundary.
- [ ] Changed inputs require a new ID/review; stale configuration cannot use old approval.
- [ ] Concurrent/repeated execution submits at most once in a service session.
- [ ] Existing media services validate exact bindings, preserve files and expose progress.
- [ ] Task008 seam and session/restart limitations are documented.
- [ ] Relevant checks pass and required backend review findings are resolved.

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
Validation and required code review remain pending; acceptance boxes stay unchecked.

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
