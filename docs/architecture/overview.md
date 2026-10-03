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

Persist enough state to avoid losing successfully generated sentence audio/results.

The full project/audio/history format is not selected yet. The visual resource library
uses immutable image files and version-1 JSON sidecars under the existing media workspace,
as defined in [ADR 0003](decisions/0003-local-visual-library.md). Image IDs cross the API;
filesystem paths remain inside the adapter. Future image producers use the same validated
registration boundary. This does not make speech/export lookup metadata durable.

Keep persistent project metadata separate from large generated media where practical.

### 6. Future task execution and control

Preserve an application-level task boundary so several tasks can eventually be prepared, suspended, scheduled, and recovered without tying execution to an open UI session. Assigned work must reference frozen or versioned source, reviewed canonical sentences with stable IDs, and validated configuration; its stable task identity must be distinct from each execution attempt.

Future scheduling coordinates application workflows. It does not own domain operations or replace human review. The first future local executor is limited to one heavy model/media job at a time; scheduling policy, checkpoints, persistence, and later concurrency need explicit decisions before implementation.

UI, a future CLI, and a future MCP adapter must call the same application commands and status queries. MCP is a control adapter, not a path to mutate domain objects or persistence directly. Local access, validated inputs, declared permissions, and required approvals apply at the command boundary.

Keep diagnostic events behind an application observability boundary. Task/run/correlation and canonical sentence IDs must connect state changes, provider attempts, safe configuration references, asset references, and sanitized failures without placing secrets or full user dialogue in logs.

The MVP remains manually initiated, with one video at a time and no scheduler or MCP runtime. See [future task and control seams](future-task-control.md) for the reserved boundaries and decisions that remain open.

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
