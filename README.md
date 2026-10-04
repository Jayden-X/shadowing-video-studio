# Shadowing Video Studio

Local-first English shadowing video generator for macOS.

The project turns an English dialogue into a repeatable shadowing-video workflow:

**paste dialogue → process/confirm sentences → preview voice → generate video → review/regenerate → export MP4**

## Current status

The local application shell, manual sentence editor, AI sentence proposals, local sentence speech, and fixed-template MP4 export are available. Local background/illustration resources extend that template. The MVP is intentionally small, while the architecture leaves explicit extension seams for later capabilities.

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
2. **AI-assisted** — explicitly select a configured DeepSeek or locally logged-in Codex CLI provider, prepare a proposal, then review and apply it. Discard/failure preserves the current document. Accepted sentences use the same manual editor.

**DeepSeek** and the **Codex CLI** sit behind a replaceable provider abstraction. See [provider setup](docs/development/setup.md#environment-configuration). Credentials remain in the backend/local CLI, and AI preparation is limited to 20,000 source characters.

The manual editor works without the backend, AI, TTS, or FFmpeg. Splitting uses simple punctuation/newline rules; abbreviations and decimals may need manual correction. Work is held in the current browser session and is lost on refresh or closing the tab.

### Sentence speech

With the local Qwen runtime configured, select a document voice and explicitly choose **Generate speech** after reviewing the sentence list. The application uses the validated CPU/0.6B CustomVoice path with English and Aiden as the default when supported. Available voices come from the configured local model; selecting one does not run inference. Jobs freeze the selected voice and configuration, show per-sentence progress, and provide native audio previews and single-sentence regeneration. Unchanged successful audio with the same voice/configuration is reused; editing text or switching voices makes mismatched audio ineligible. Earlier WAVs are preserved. Replacing a document clears its current audio selections.

Generation locks editing while the UI waits. **Stop waiting for speech** ends monitoring without cancelling the local generation job; a known job can be monitored again. Jobs are serialized by the service. Speech accepts up to 100 sentences, 4,000 characters each, and 20,000 total characters. Metadata is volatile: after a service restart, generate again. Generated WAV files are kept locally and are never overwritten by regeneration. See [runtime setup](docs/development/setup.md).

### Video export

After reviewing the current sentence audio, explicitly choose **Generate video**. The fixed 1920 × 1080 template shows one sentence per page, a reserved visual area, 36 black rounded frequency bars below the text, and a five-second silent practice pause after every sentence. The bars react to speech and disappear during silence. The default background is light blue; choose a light uploaded background for clear black bars. Sentences without matching current audio are ineligible; text that cannot fit a page must be split and its speech generated again.

Rendering shows progress and locks editing while the UI waits. **Stop waiting for video** ends monitoring without cancelling rendering; a known job can be monitored again. Preview completed exports with native video controls and download MP4 files. Repeated exports retain prior outputs. Download before restarting the service: export links and job metadata are volatile, while generated files remain locally preserved. Development uses Vite; the target Mac run can use the same local FastAPI service to serve the built frontend.

### Backgrounds and illustrations

Upload a static PNG/JPEG/WebP background or a right-side illustration for each sentence,
or choose an existing image from the local library. Resources retain their IDs and bytes
after a service restart. Backgrounds cover the frame under a dim layer; illustrations fit
inside the right panel and remain visible during speech and the five-second pause.
Video generation freezes the selected images alongside its sentence/audio inputs.
See [local visual library](docs/development/visual-library.md) for limits and editing rules.

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
