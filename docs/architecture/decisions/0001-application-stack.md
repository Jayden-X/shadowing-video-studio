# ADR 0001 — Application stack

- Status: Accepted
- Date: 2026-10-03

## Context

Shadowing Video Studio is a local-first macOS tool with a browser UI. It needs to orchestrate local AI/TTS workloads, FFmpeg, editable sentence workflows, progress reporting, and later recoverable media generation.

Qwen3-TTS is distributed as a Python package and currently declares Python support through 3.12+; this makes Python the natural integration boundary for TTS/model work. The UI needs more flexibility than a demo-oriented ML UI because the product will include sentence editing, per-sentence state, waveform/progress display, regeneration, and project/history views.

## Decision

Use:

- **Backend:** Python 3.12 + FastAPI.
- **Python dependency/project management:** uv.
- **Frontend:** React 19 + TypeScript + Vite 8.
- **Frontend package manager:** npm for the initial MVP.
- **Backend tests:** pytest.
- **Python lint/format:** Ruff.
- **Frontend tests:** Vitest.
- **Media integration:** FFmpeg behind a `VideoRenderer` adapter.
- **TTS integration:** Qwen3-TTS behind a `SpeechProvider` adapter.
- **AI text processing:** provider abstraction with DeepSeek and Codex implementations.

Development runs a FastAPI process and a Vite development server. Vite proxies `/api` to FastAPI.

For the local product build, the intended direction is to build the frontend to static assets and serve them from the local Python application so the end user can run one local service and use the system browser. The exact macOS double-click launcher/package mechanism is intentionally deferred until Qwen3-TTS runtime behavior on the target Mac is validated.

## Considered options

### Python + FastAPI + React/Vite — selected

Pros:
- Native fit for Qwen3-TTS and Python ML tooling.
- Strong separation between UI and model/media adapters.
- Full browser UI flexibility for sentence editing and progress-heavy workflows.
- Very common, well-understood structure for coding agents.
- FastAPI provides typed API contracts and simple local execution.
- Vite provides a small, fast frontend toolchain.

Cons:
- Two toolchains during development (Python and Node).
- More initial structure than a Python-only UI framework.
- Production packaging still requires a local launcher/install strategy.

### Python-only UI with Gradio or NiceGUI

Pros:
- Fastest prototype path.
- Single primary language/toolchain.
- Natural for ML demos.

Cons:
- Product UI becomes coupled to the server-side component framework.
- Custom editing interactions and layout evolution can become awkward.
- Gradio in particular is optimized for ML interfaces/demos rather than a growing product workflow.

Decision: useful for isolated model experiments, not the primary product shell.

### Tauri + web frontend + Python sidecar

Pros:
- Strong native desktop packaging and OS integration.
- Small native shell compared with Electron.

Cons:
- Adds Rust/Tauri and sidecar lifecycle/packaging complexity while Python is already required for TTS.
- More moving parts for an MVP whose desired UI is explicitly browser-based.

Decision: reconsider only if native app packaging becomes a product requirement.

### Electron + web frontend + Python service

Pros:
- Mature desktop packaging ecosystem.
- Full web UI flexibility.

Cons:
- Bundles another large runtime.
- Still needs Python/model process management.
- Adds complexity without solving a current MVP requirement.

Decision: not justified for the MVP.

## Consequences

- Domain/application code must not import DeepSeek/Codex/Qwen/FFmpeg details directly.
- Frontend communicates through explicit local APIs rather than reaching into Python internals.
- Qwen3-TTS remains an optional/heavy dependency and must not be installed in ordinary CI.
- CI validates the lightweight application shell without downloading model weights.
- A macOS runtime spike must validate the actual Qwen3-TTS backend/performance before finalizing end-user packaging.
- Persistence technology remains a separate decision.

## Why this is favorable for AI-assisted development

The stack is intentionally conventional:
- typed Python API code
- typed TypeScript UI code
- deterministic unit tests
- explicit adapters around volatile external tools
- standard folder boundaries

This gives Codex/other agents a large amount of familiar ecosystem context while keeping tasks independently testable.
