# Architecture Guardrails

## Core rule

MVP limitations are not architecture limitations.

The current single-user, single-Mac, one-video-at-a-time scope must not be unnecessarily hard-coded into domain boundaries.

At the same time, do not prebuild infrastructure for hypothetical future scale.

## Dependency direction

Preferred conceptual direction:

```text
UI / API
   ↓
Application workflows
   ↓
Domain models and deterministic operations
   ↓
Ports / interfaces
   ↓
Adapters: DeepSeek, Codex, Qwen3-TTS, FFmpeg, filesystem
```

Vendor-specific adapters may depend inward on application contracts.

Domain/application code must not depend outward on vendor SDK types.

## Current volatility boundaries

Keep explicit boundaries around:

- AI text processing
- TTS
- video rendering
- local project persistence
- external process execution

Current target interfaces include:

- `TextProcessingProvider`
- `SpeechProvider`
- `VideoRenderer`

Names may evolve through ADRs, but the separation principle remains.

## Canonical models

Canonical application/domain models belong to this project.

Do not treat DeepSeek/Codex/Qwen/FFmpeg response formats as domain models.

Convert external data at the adapter boundary.

## UI/backend boundary

The frontend communicates through explicit APIs.

Do not create hidden coupling where frontend code assumes Python implementation details or filesystem internals.

## Local-first runtime

For MVP:

- expensive model/media work runs locally
- generated media is local
- secrets remain local
- ordinary CI does not download model weights

## Persistence

Persistence is an implementation boundary, not the domain model.

Until an ADR selects a format:

- do not couple domain objects to SQLite/file-layout details
- keep large media separate from small metadata where practical
- preserve stable IDs for resources that may later have generated artifacts

## Avoid premature architecture

Do not introduce without a demonstrated requirement:

- microservices
- message brokers
- Kubernetes
- distributed caches
- cloud databases
- generic plugin systems
- event sourcing
- repository/service abstractions around every class
- deep inheritance hierarchies

## Architecture changes

A change requires an ADR when it:

- introduces/replaces a major framework
- changes process boundaries
- selects a persistent storage format
- materially changes dependency direction
- introduces a required external/cloud service
- changes the packaging/runtime model
