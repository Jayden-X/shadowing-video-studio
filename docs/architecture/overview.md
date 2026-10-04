# Architecture Overview

## Principle

Keep the MVP small, but preserve clear seams around capabilities that are likely to change.

Avoid speculative infrastructure. Prefer interfaces at genuine volatility points.

## Selected application stack

ADR 0001 selects:

- Python 3.12 + FastAPI backend.
- React 19 + TypeScript + Vite 8 frontend.
- uv for Python project/dependency management.
- npm for the initial frontend workflow.
- pytest + Ruff for backend validation.
- Vitest + TypeScript build checks for frontend validation.

During development, Vite proxies local API requests to FastAPI. The intended end-user direction is a local Python service serving a built frontend in the system browser, with the exact macOS launcher/package mechanism deferred until TTS runtime validation.

## Capability boundaries

### 1. Application / workflow

Coordinates the end-to-end flow:
- ingest text
- produce/edit sentence list
- generate/preview TTS
- assemble video
- review/regenerate
- export

This layer must not depend directly on a specific AI or TTS vendor.

### 2. Text processing

Abstraction:

`TextProcessingProvider`

Implementations may include:
- manual/no-op preparation
- DeepSeek
- Codex

The canonical sentence list belongs to the application/domain model, not to any provider response format.

The text-preparation application service validates a provider-neutral sentence proposal before returning it through the local API. Provider responses carry text only; canonical sentence IDs are assigned in the frontend domain when a user applies the reviewed proposal. The exact source snapshot and the current edited document remain separate from a pending proposal.

DeepSeek uses its official HTTPS API with a backend-only environment key. Codex uses the existing local CLI login from an isolated temporary working directory with configuration/tool isolation checks. Failure and unavailable configuration return safe application errors and never trigger automatic retries or media generation.

### 3. TTS

Abstraction:

`SpeechProvider`

Initial target:
- Qwen3-TTS

Voice selection such as Aiden should be configuration/domain data, not scattered constants.

Task010 exposes `SpeechCapabilities` through the local API. Document-level voice selection
binds immutable speech requests/results and audio reuse; video export validates the same
voice/configuration binding. The Qwen adapter discovers voices from the configured frozen
snapshot, with an independent loaded-model check inside the existing worker. Selection
does not start inference or change the accepted process/persistence boundaries.

Qwen3-TTS is treated as an optional heavy runtime dependency and is intentionally excluded from normal CI.

### 4. Video rendering

Abstraction:

`VideoRenderer`

Responsibilities:
- compose background/layout
- render sentence text
- place waveform
- combine sentence audio and pauses
- encode MP4

FFmpeg may be used internally, but higher layers should not build command strings everywhere.

### 5. Local project persistence

[ADR 0004](decisions/0004-project-history-persistence.md) selects standard-library SQLite
metadata under `SPEECH_WORKSPACE/state/projects.sqlite3`, separate from immutable media.
Project commands atomically save a revision and freeze an execution attempt before heavy
work. Media bytes are validated and flushed before registration; only then is success exposed.
Successful partial speech and historical video associations survive restart. Unfinished
attempts become interrupted and never resume automatically.

Saved editor snapshots retain document-scoped sentence identities, original/current text,
voice and visual selections. Browser cache holds optional association hints; backend metadata
and byte validation are authoritative. Exact current bindings govern audio reuse, while
historical MP4s retain their own frozen inputs. Existing visual JSON sidecars remain unchanged
under [ADR 0003](decisions/0003-local-visual-library.md). No legacy media import or pruning occurs.

Task013 shares the Task008-backed media service instances but its transient MCP
requests do not bind to saved project revisions or write project history. That binding
and editor synchronization remain a follow-up using Task008 application commands.

### 6. Future task execution and control

Preserve an application-level task boundary so several tasks can eventually be prepared, suspended, scheduled, and recovered without tying execution to an open UI session. Assigned work must reference frozen or versioned source, reviewed canonical sentences with stable IDs, and validated configuration; its stable task identity must be distinct from each execution attempt.

Future scheduling coordinates application workflows. It does not own domain operations or replace human review. The first future local executor is limited to one heavy model/media job at a time; scheduling policy, checkpoints, persistence, and later concurrency need explicit decisions before implementation.

UI, a future CLI, and the Task013 MCP adapter must call the same application commands and status queries. MCP is a control adapter, not a path to mutate domain objects or persistence directly. Local access, validated inputs, declared permissions, and required approvals apply at the command boundary.

Keep diagnostic events behind an application observability boundary. Task/run/correlation and canonical sentence IDs must connect state changes, provider attempts, safe configuration references, asset references, and sanitized failures without placing secrets or full user dialogue in logs.

The original MVP remains the baseline, with one video at a time and no scheduler.
Task013 adds explicitly authorized local MCP control after MVP; see
[ADR0006](decisions/0006-local-mcp-control.md) and [its contracts](../development/mcp-control.md).
MCP project binding/editor synchronization remains a follow-up against Task008. See [future task and control seams](future-task-control.md) for the reserved boundaries and decisions that remain open.

## Extension seams

MVP architecture should allow later:
- additional AI providers
- additional TTS engines
- additional video templates
- batch orchestration
- prepared, suspended, and scheduled local tasks
- UI/CLI/MCP control through shared application commands
- alternate storage/runtime modes

Do not implement those features before needed.

## Non-goals for bootstrap

Do not introduce:
- microservices
- Kubernetes
- distributed queues
- cloud databases
- generic plugin frameworks
- complex event-driven architecture

unless a later requirement materially justifies them.

## Decision records

Significant architecture choices are recorded under `docs/architecture/decisions/`.
