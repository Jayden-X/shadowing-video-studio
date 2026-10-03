# 005 — Reserve scheduled task and MCP control capabilities

## Goal

Record the owner's future task scheduling and MCP control requirements and the architecture seams that preserve them without expanding MVP implementation.

## Context

Direct owner request during Task 002: prepare/assign multiple tasks while using the computer, suspend or schedule them for idle/overnight execution, declare human intervention during assignment, trace exceptions, and allow later AI control through MCP.

## Requirements

- Keep scheduling and MCP implementation outside the first release.
- Preserve frozen/versioned input, canonical sentence identity, and separate task/run identities.
- Declare required human decisions and validate readiness before unattended execution.
- Reserve scheduling, suspension, safe recovery, and diagnostic trace boundaries.
- Route future UI/CLI/MCP control through shared application commands and review rules.

## Acceptance criteria

- [x] Product requirements record both requested future capabilities.
- [x] Architecture documents preserve task, execution, trace, and control boundaries.
- [x] No scheduler, MCP runtime, dependency, persistence format, or credential policy is selected or implemented.
- [x] Relative links in the changed documentation resolve.

- [x] Repository CI passed for the submitted documentation PR.

## Out of scope

Runtime implementation, unattended jobs, actual MCP tools, project storage, framework selection, cloud access, and new product task execution.

## Validation

- Read changed requirements and architecture notes against the owner's request and existing MVP constraints.
- Check Markdown relative links and `git diff --check`.
- Verify repository CI on the PR head.

## Human decisions required

None for these design reservations. The design note lists decisions needed before runtime implementation.

## Implementation notes

- Updated product requirements and architecture overview.
- Added `docs/architecture/future-task-control.md` with preparation/review gates, schedule semantics, checkpoint/idempotency requirements, safe diagnostic events, and local MCP command boundaries.
- Validation: PR #3 CI run 37141382210 passed all repository, backend, and frontend jobs on 2026-10-03. This final task-state update remains gated by the next PR CI run and squash merge.
