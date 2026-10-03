# Architecture Overview

## Principle

Keep the MVP small, but preserve clear seams around capabilities that are likely to change.

Avoid speculative infrastructure. Prefer interfaces at genuine volatility points.

## Recommended capability boundaries

### 1. Application / workflow

Coordinates the end-to-end flow:
- ingest text
- produce/edit sentence list
- generate/preview TTS
- assemble video
- review/regenerate
- export

This layer should not depend directly on a specific AI or TTS vendor.

### 2. Text processing

Suggested abstraction:

`TextProcessingProvider`

Implementations may include:
- manual/no-op preparation
- DeepSeek
- Codex

The canonical sentence list belongs to the application/domain model, not to any provider response format.

### 3. TTS

Suggested abstraction:

`SpeechProvider`

Initial implementation:
- Qwen3-TTS

Voice selection such as Aiden should be configuration/domain data, not scattered constants.

### 4. Video rendering

Suggested abstraction:

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

Significant architecture choices should be recorded under `docs/architecture/decisions/` as short ADRs.
