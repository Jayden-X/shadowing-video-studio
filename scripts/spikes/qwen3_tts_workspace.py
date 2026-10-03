"""Workspace path guard, also runnable by macOS's existing system Python (3.9+)."""

import os
import sys
from pathlib import Path


def checked_workspace(raw_path: str) -> Path:
    requested = Path(raw_path)
    if any(character in raw_path for character in "\n\r\t"):
        raise ValueError("The workspace path must not contain control characters.")
    if not requested.is_absolute() or ".." in requested.parts:
        raise ValueError("Provide the approved workspace as an absolute path without '..'.")
    if not requested.is_dir():
        raise ValueError("The approved workspace must already exist.")
    # Resolve casing on case-insensitive macOS volumes without rejecting a valid spelling.
    original_directory = Path.cwd()
    try:
        os.chdir(requested)
        physical = Path.cwd()
    finally:
        os.chdir(original_directory)
    if not os.path.samefile(requested, physical):
        raise ValueError("The workspace does not resolve to its physical directory.")
    # A workspace supplied through a symlink could silently change the authorized boundary.
    for component in (requested, *requested.parents):
        if component.is_symlink():
            raise ValueError("Provide the physical workspace path, without symlink components.")
    return physical


def checked_child(workspace: Path, candidate: Path) -> Path:
    root = workspace.resolve(strict=True)
    resolved = candidate.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Every runtime/cache/output path must remain under the workspace.")
    return resolved


def runtime_environment(workspace: Path) -> dict:
    task = workspace / "spikes" / "task004"
    cache = task / "cache"
    paths = {
        "UV_CACHE_DIR": cache / "uv",
        "UV_PYTHON_INSTALL_DIR": cache / "python",
        "UV_PYTHON_BIN_DIR": task / "tools" / "python-bin",
        "HF_HOME": cache / "huggingface",
        "HF_HUB_CACHE": cache / "huggingface" / "hub",
        "XDG_CACHE_HOME": cache / "xdg",
        "PIP_CACHE_DIR": cache / "pip",
        "TORCH_HOME": cache / "torch",
        "TORCH_EXTENSIONS_DIR": cache / "torch-extensions",
        "NUMBA_CACHE_DIR": cache / "numba",
        "MPLCONFIGDIR": cache / "matplotlib",
        "TMPDIR": task / "tmp",
        "GRADIO_TEMP_DIR": task / "tmp" / "gradio",
    }
    environment = {name: str(checked_child(workspace, path)) for name, path in paths.items()}
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "UV_NO_CONFIG": "1",
            "PIP_CONFIG_FILE": "/dev/null",
        }
    )
    return environment


def main() -> int:
    try:
        root = checked_workspace(sys.argv[1])
        if len(sys.argv) == 3 and sys.argv[2] == "--environment":
            for name, value in runtime_environment(root).items():
                print(name + "\t" + value)
        else:
            print(root if len(sys.argv) == 2 else checked_child(root, Path(sys.argv[2])))
        return 0
    except (IndexError, OSError, ValueError) as error:
        print(f"Workspace check failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
