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

### 3. TTS

Abstraction:

`SpeechProvider`

Initial target:
- Qwen3-TTS

Voice selection such as Aiden should be configuration/domain data, not scattered constants.

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

The exact storage format is not selected yet.

Keep persistent project metadata separate from large generated media where practical.

## Extension seams

MVP architecture should allow later:
- additional AI providers
- additional TTS engines
- additional video templates
- batch orchestration
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
