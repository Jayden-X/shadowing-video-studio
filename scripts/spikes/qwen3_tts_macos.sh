#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: bash scripts/spikes/qwen3_tts_macos.sh --workspace-root ABSOLUTE_PATH prepare"
  echo "       bash scripts/spikes/qwen3_tts_macos.sh --workspace-root ABSOLUTE_PATH run RUNTIME_NAME cpu|mps [--mps-cpu-fallback]"
}

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "This spike requires an ARM64 macOS shell; no environment or model was created." >&2
  exit 2
fi

[[ "${1:-}" == --workspace-root && -n "${2:-}" ]] || { usage >&2; exit 2; }
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
WORKSPACE_ROOT="$(/usr/bin/python3 "$SCRIPT_DIR/qwen3_tts_workspace.py" "$2")"
shift 2

checked_path() {
  /usr/bin/python3 "$SCRIPT_DIR/qwen3_tts_workspace.py" "$WORKSPACE_ROOT" "$1"
}

checked_interpreter() {
  # Validate the symlink target, but retain the venv path so Python/uv see pyvenv.cfg.
  checked_path "$1" >/dev/null || return $?
  printf '%s\n' "$1"
}

TASK_DIR="$(checked_path "$WORKSPACE_ROOT/spikes/task004")"
SPIKE_ENV="$(/usr/bin/python3 "$SCRIPT_DIR/qwen3_tts_workspace.py" "$WORKSPACE_ROOT" --environment)"
while IFS=$'\t' read -r SPIKE_ENV_NAME SPIKE_ENV_VALUE; do
  export "$SPIKE_ENV_NAME=$SPIKE_ENV_VALUE"
done <<< "$SPIKE_ENV"

case "${1:-}" in
  prepare)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    SPIKE_UV="${UV_BIN:-uv}"
    command -v "$SPIKE_UV" >/dev/null || {
      echo "Set UV_BIN to an already authorized uv executable, or add uv to PATH." >&2; exit 2;
    }
    RUNTIMES_DIR="$(checked_path "$TASK_DIR/runtimes")"
    mkdir -p "$RUNTIMES_DIR" "$TMPDIR"
    RUNTIME_DIR="$(mktemp -d "$RUNTIMES_DIR/prepare-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
    "$SPIKE_UV" venv --managed-python --python 3.12 "$RUNTIME_DIR/.venv"
    SPIKE_PYTHON="$(checked_interpreter "$RUNTIME_DIR/.venv/bin/python")"
    "$SPIKE_UV" pip compile "$SCRIPT_DIR/qwen3-tts-requirements.in" \
      --python "$SPIKE_PYTHON" --generate-hashes --quiet \
      --output-file "$RUNTIME_DIR/requirements.lock"
    "$SPIKE_UV" pip sync "$RUNTIME_DIR/requirements.lock" \
      --python "$SPIKE_PYTHON" --require-hashes \
      2>&1 | tee "$RUNTIME_DIR/install.log"
    "$SPIKE_PYTHON" "$SCRIPT_DIR/qwen3_tts_macos.py" prepare \
      --workspace-root "$WORKSPACE_ROOT" --runtime-dir "$RUNTIME_DIR" \
      --uv-version "$("$SPIKE_UV" --version)" \
      2>&1 | tee "$RUNTIME_DIR/prepare.log"
    echo "Prepared runtime: $RUNTIME_DIR"
    echo "Runtime name: $(basename "$RUNTIME_DIR")"
    echo "Use this runtime name with the run command and the same --workspace-root."
    ;;
  run)
    [[ $# -eq 3 || $# -eq 4 ]] || { usage >&2; exit 2; }
    [[ "$2" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ && "$2" != *..* ]] || {
      echo "Use the generated runtime name, without a path or '..'." >&2; exit 2;
    }
    [[ "$3" == cpu || "$3" == mps ]] || { usage >&2; exit 2; }
    [[ $# -ne 4 || "$4" == --mps-cpu-fallback ]] || { usage >&2; exit 2; }
    [[ $# -ne 4 || "$3" == mps ]] || {
      echo "CPU fallback requires the explicit mps profile." >&2; exit 2;
    }
    RUNTIME_DIR="$(checked_path "$TASK_DIR/runtimes/$2")"
    [[ -f "$RUNTIME_DIR/preparation.json" && -x "$RUNTIME_DIR/.venv/bin/python" ]] || {
      echo "RUNTIME_DIR must be a successfully prepared spike environment." >&2; exit 2;
    }
    SPIKE_PYTHON="$(checked_interpreter "$RUNTIME_DIR/.venv/bin/python")"
    mkdir -p "$TMPDIR"
    "$SPIKE_PYTHON" "$SCRIPT_DIR/qwen3_tts_macos.py" run \
      --workspace-root "$WORKSPACE_ROOT" --runtime-dir "$RUNTIME_DIR" \
      --device "$3" "${@:4}"
    ;;
  *) usage >&2; exit 2 ;;
esac
