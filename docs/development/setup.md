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

The actual acceleration/backend behavior on the target Mac must be validated before the end-user packaging strategy is finalized. That validation belongs in a dedicated TTS integration/spike task.

## Environment configuration

Copy the committed template if local provider credentials are needed:

```bash
cp .env.example .env
```

Never commit `.env`.

Provider authentication details are finalized only when the corresponding adapter is implemented.

## Generated/runtime data

Model caches, generated audio/video, user assets, logs, and local runtime state must remain outside Git-tracked paths covered by `.gitignore`.

The exact local project/history persistence location is still an open architecture decision.
