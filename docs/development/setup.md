# Development Setup

## Supported development target

The first target is macOS.

Required:
- Python 3.12.
- uv.
- Node.js 22.12+.
- npm.
- FFmpeg.

The repository contains `.python-version` and `.nvmrc` as local tool hints.

## Install system tools on macOS

With Homebrew:

```bash
brew install uv ffmpeg node
```

If you manage Node with nvm instead, use a Node release satisfying Vite 8's requirement (22.12+ is sufficient for this project baseline).

## Backend setup

```bash
cd backend
uv sync --extra dev
```

Run the API:

```bash
uv run uvicorn shadowing_video_studio.main:app \
  --app-dir src \
  --reload \
  --host 127.0.0.1 \
  --port 8765
```

Health endpoint:

```text
http://127.0.0.1:8765/api/health
```

## Frontend setup

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite development server proxies `/api` to FastAPI on port 8765.

## Combined development launcher

After dependencies are installed:

```bash
bash scripts/dev.sh
```

On macOS the script also attempts to open the browser automatically.

## Validation

Run everything currently required:

```bash
bash scripts/check.sh
```

Or separately:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest

cd ../frontend
npm run typecheck
npm run test
npm run build
```

## Qwen3-TTS

Qwen3-TTS is declared as an optional backend dependency because it is large and should not be pulled into normal CI.

Install the Python package into the backend environment with:

```bash
cd backend
uv sync --extra dev --extra tts
```

Do not download or commit model weights into this repository.

The actual acceleration/backend behavior on the target Mac must be validated before the end-user packaging strategy is finalized. Use the separate [Task 004 Mac runtime spike](qwen3-tts-macos-spike.md) for an isolated, reproducible experiment rather than changing the normal backend/CI environment.

## Environment configuration

Copy the committed template if local provider credentials are needed:

```bash
cp .env.example .env
```

Never commit `.env`.

`bash scripts/dev.sh` loads the root `.env` when present. Already exported environment variables take precedence. For a separately started API, add `--env-file ../.env` to `uv run` when that file exists.

For DeepSeek, set `DEEPSEEK_API_KEY` and optionally `DEEPSEEK_MODEL` (default `deepseek-flash`). Only the backend reads the key and contacts the fixed official HTTPS endpoint. A provider is selected explicitly in the UI before sending dialogue.

For Codex, install a current CLI and run `codex login` locally. The adapter reuses this login and checks the CLI's isolation capabilities. It runs in an isolated system temporary directory with repository/user configuration and unnecessary tools disabled. An unsupported or unverifiable configuration makes the provider unavailable instead of weakening these controls. `CODEX_EXECUTABLE` can select a server-side executable; no Codex API key is required.

On 2026-10-03, the local Windows CLI 0.160.0 kept `unified_exec` enabled despite disable/configuration overrides. The adapter correctly reported it unavailable and no live Codex inference was attempted. A successful login alone does not establish safe readiness; another installation must pass the same checks. Raw CLI output/configuration is never displayed or logged by the adapter.

`TEXT_PROVIDER_TIMEOUT_SECONDS` sets the preparation deadline (default 60, range 1–110). Requests are never automatically retried. AI proposals must be reviewed and applied explicitly; provider errors or discarded proposals preserve source and existing edits. Preparation is limited to 20,000 source UTF-16 code units, 500 proposed sentences, and 4,000 UTF-16 code units per sentence before trimming. Isolated Unicode surrogates are rejected. Provider output is bounded to 128 KiB.

Normal checks use fake providers and fixtures. They do not require provider credentials, paid API calls, or model downloads. Real provider access must be validated locally with synthetic dialogue; record it separately from contract-test results.

## Generated/runtime data

Model caches, generated audio/video, user assets, logs, and local runtime state must remain outside Git-tracked paths covered by `.gitignore`.

The exact local project/history persistence location is still an open architecture decision.
