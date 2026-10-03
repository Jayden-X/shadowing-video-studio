# 001 — Select the application stack

## Goal

Choose the concrete local application stack and packaging approach for the MVP.

## Context

The product is a local browser-operated tool on the user's Mac and will orchestrate:
- local UI
- local application logic
- Qwen3-TTS
- FFmpeg/video rendering
- optional DeepSeek/Codex text-processing providers

The MVP should be easy to run locally and friendly to AI-assisted development.

## Requirements

Evaluate a small set of realistic options and record the decision as an ADR.

The chosen stack must:
- run locally on macOS
- provide a browser-based UI
- integrate cleanly with local Python/model execution if Qwen3-TTS requires it
- invoke FFmpeg reliably
- support automated tests
- be straightforward for Codex/AI agents to understand and modify
- avoid unnecessary distributed/cloud infrastructure

## Acceptance criteria

- A short ADR exists under `docs/architecture/decisions/`.
- The ADR documents considered options, decision, rationale, tradeoffs, and consequences.
- The selected stack has a minimal runnable application shell.
- Exact local setup/start/test commands are documented.
- CI is updated to run the real lint/test/build checks.

## Out of scope

- Building full text/TTS/video functionality.
- Cloud deployment.
- Accounts or multi-user functionality.

## Validation

- Fresh-clone setup steps are executable on the target Mac.
- Application starts locally.
- Browser UI loads.
- Automated test command passes.
- CI passes.

## Human decision required

Yes. The final stack choice must be explicitly approved before committing the architecture to it.
