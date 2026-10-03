#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

(
  cd "$ROOT_DIR/backend"
  uv run ruff check --config pyproject.toml . ../scripts/spikes
  uv run ruff format --check --config pyproject.toml . ../scripts/spikes
  uv run pytest
  bash -n ../scripts/spikes/qwen3_tts_macos.sh
  uv run python -m unittest discover -s ../scripts/spikes -p 'test_*.py' -v
)

(
  cd "$ROOT_DIR/frontend"
  npm run check
)
