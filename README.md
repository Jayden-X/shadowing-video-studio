# Shadowing Video Studio

Local-first English shadowing video generator for macOS.

The project turns an English dialogue into a repeatable shadowing-video workflow:

**paste dialogue → process/confirm sentences → preview voice → generate video → review/regenerate → export MP4**

## Current status

The local application shell and manual sentence editor are available. The MVP is intentionally small, while the architecture leaves explicit extension seams for later capabilities.

### Confirmed MVP boundaries

- Primary user: the repository owner, on the current Mac.
- One video at a time.
- Text input starts with paste-in dialogue.
- No account system, multi-user collaboration, cloud runtime, or batch jobs in the MVP.
- These are product-scope constraints, not architecture constraints.

### Current media defaults

- 16:9, 1920 × 1080.
- One sentence per page.
- Default 5-second shadowing pause after each sentence.
- Large English text on the left, reserved character/background area on the right, dynamic waveform at the bottom.
- Qwen3-TTS with Aiden as the default voice.
- MP4 output.

### Text processing

Text preparation has two modes:

1. **Manual (available)** — paste dialogue, prepare a local sentence list, then edit, split at the cursor, merge adjacent sentences, add, delete, and reorder sentences. The original source snapshot stays separate from edits. Replacing a prepared list requires confirmation.
2. **AI-assisted (planned)** — let an AI provider prepare the sentence list, then require user confirmation before media generation.

Initial AI-provider targets: **DeepSeek** and **Codex**, behind a provider abstraction.

The manual editor works without the backend, AI, TTS, or FFmpeg. Splitting uses simple punctuation/newline rules; abbreviations and decimals may need manual correction. Work is held in the current browser session and is lost on refresh or closing the tab. Speech and video generation are not implemented yet.

## Technology stack

- Backend: Python 3.12 + FastAPI.
- Python project/dependencies: uv.
- Frontend: React 19 + TypeScript + Vite 8.
- Frontend packages: npm.
- Backend tests: pytest.
- Python lint/format: Ruff.
- Frontend tests: Vitest.
- Media: FFmpeg behind an adapter.
- TTS: Qwen3-TTS behind an adapter.

See [ADR 0001](docs/architecture/decisions/0001-application-stack.md).

## Quick start

Prerequisites: Python 3.12, uv, Node.js 22.12+ and FFmpeg.

```bash
cd backend
uv sync --extra dev

cd ../frontend
npm ci

cd ..
bash scripts/dev.sh
```

The browser UI opens at `http://127.0.0.1:5173`; Vite proxies `/api` to the local FastAPI service.

Run repository checks with:

```bash
bash scripts/check.sh
```

See [development setup](docs/development/setup.md) for full details.

## AI-first development

This repository is structured so Codex/AI agents can take small, well-specified tasks and verify their own work.

Start here:

1. Read [AGENTS.md](AGENTS.md).
2. Read [Product requirements](docs/requirements/product-requirements.md).
3. Read [Architecture overview](docs/architecture/overview.md).
4. Pick only a task from [tasks/ready](tasks/ready).
5. Follow [AI development workflow](docs/development/ai-development.md).
6. Satisfy every acceptance criterion and validation step before moving the task forward.

## Repository map

- `AGENTS.md` — repository-wide instructions for AI coding agents.
- `backend/` — FastAPI application and Python-side integrations.
- `frontend/` — React/TypeScript browser UI.
- `docs/requirements/` — product requirements and scope.
- `docs/architecture/` — architecture boundaries and ADRs.
- `docs/development/` — setup, testing, and AI-development conventions.
- `docs/product/` — roadmap and product sequencing.
- `tasks/` — executable work queue for humans and AI agents.
- `prompts/` — runtime prompt assets used by product AI features.
- `samples/` — small, safe example inputs/assets only.
- `scripts/` — developer automation.

## Important repository rules

Do **not** commit:

- API keys, credentials, tokens, or local `.env` files.
- TTS/model weights or model caches.
- Generated audio/video.
- User-provided backgrounds or other personal source media.
- Runtime databases/state, logs, caches, or temporary workspaces.

See [.gitignore](.gitignore) and [.env.example](.env.example).
