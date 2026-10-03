# Shadowing Video Studio

Local-first English shadowing video generator for macOS.

The project turns an English dialogue into a repeatable shadowing-video workflow:

**paste dialogue → process/confirm sentences → preview voice → generate video → review/regenerate → export MP4**

## Current status

This repository is in the product/bootstrap stage. The MVP is intentionally small, while the architecture should leave room for later expansion.

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

Two modes are planned:

1. **Manual** — edit, split, merge, add, delete, and reorder sentences.
2. **AI-assisted** — let an AI provider prepare the sentence list, then require user confirmation before media generation.

Initial AI-provider targets: **DeepSeek** and **Codex**, behind a provider abstraction.

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
- `docs/requirements/` — product requirements and scope.
- `docs/architecture/` — architecture boundaries and ADRs.
- `docs/development/` — setup, testing, and AI-development conventions.
- `docs/product/` — roadmap and product sequencing.
- `tasks/` — executable work queue for humans and AI agents.
- `prompts/` — runtime prompt assets used by product AI features.
- `samples/` — small, safe example inputs/assets only.
- `scripts/` — developer automation.
- `src/` — application source once the implementation stack is selected.

## Important repository rules

Do **not** commit:

- API keys, credentials, tokens, or local `.env` files.
- TTS/model weights or model caches.
- Generated audio/video.
- User-provided backgrounds or other personal source media.
- Runtime databases/state, logs, caches, or temporary workspaces.

See [.gitignore](.gitignore) and [.env.example](.env.example).

## Implementation status

The concrete frontend/backend packaging stack is intentionally **not selected yet**. The first ready task is to make that decision against the product constraints rather than prematurely locking the repository into a framework.
