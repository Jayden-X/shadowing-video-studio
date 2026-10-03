#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  if [[ -n "${frontend_pid:-}" ]]; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/backend"
  backend_env_args=()
  if [[ -f "$ROOT_DIR/.env" ]]; then
    backend_env_args=(--env-file "$ROOT_DIR/.env")
  fi
  uv run "${backend_env_args[@]}" uvicorn shadowing_video_studio.main:app \
    --app-dir src --reload --host 127.0.0.1 --port 8765
) &
backend_pid=$!

(
  cd "$ROOT_DIR/frontend"
  npm run dev
) &
frontend_pid=$!

sleep 2

if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:5173"
fi

wait
