# 001 — Select the application stack

## Status

Completed.

## Goal

Choose the concrete local application stack and packaging direction for the MVP.

## Decision

Selected stack:

- Python 3.12.
- FastAPI backend.
- uv for Python dependency/project management.
- React 19 + TypeScript + Vite 8 frontend.
- npm for the initial frontend package workflow.
- pytest + Ruff for backend validation.
- Vitest + TypeScript build/type checks for frontend validation.
- FFmpeg behind a VideoRenderer adapter.
- Qwen3-TTS behind a SpeechProvider adapter.

See `docs/architecture/decisions/0001-application-stack.md`.

## Acceptance criteria

- [x] ADR records options, rationale, tradeoffs, and consequences.
- [x] Minimal FastAPI application shell exists.
- [x] Minimal React/Vite browser shell exists.
- [x] Frontend can call the backend health endpoint through the Vite proxy.
- [x] Exact local setup/start/test commands are documented.
- [x] CI runs repository hygiene, backend lint/tests, and frontend typecheck/tests/build.
- [x] Heavy Qwen3-TTS dependencies/model weights are excluded from ordinary CI.

## Out of scope

- Full text editor.
- AI provider implementations.
- Qwen3-TTS runtime integration.
- FFmpeg rendering.
- Cloud deployment.
- Accounts or multi-user functionality.

## Validation

Automated validation is delegated to the pull-request CI for the bootstrap branch.

Local full check:

```bash
bash scripts/check.sh
```

## Implementation notes

- Development intentionally uses two processes for fast iteration: FastAPI + Vite.
- End-user direction is one local Python service serving the built frontend in the system browser.
- Exact macOS double-click packaging is deferred until Qwen3-TTS behavior on the target Mac is validated.
- Persistence remains a separate architecture decision.
