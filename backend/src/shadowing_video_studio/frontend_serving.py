"""Serve a trusted built frontend through the existing local application."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def configure_frontend(app: FastAPI, configured_path: str | None = None) -> None:
    raw = os.environ.get("FRONTEND_DIST_DIR", "") if configured_path is None else configured_path
    directory = Path(raw) if raw else None
    available = bool(
        directory
        and directory.is_absolute()
        and directory.is_dir()
        and not directory.is_symlink()
        and (directory / "index.html").is_file()
        and not (directory / "index.html").is_symlink()
        and (directory / "assets").is_dir()
        and not (directory / "assets").is_symlink()
    )
    if available:
        assert directory is not None
        directory = directory.resolve()
        app.mount("/assets", StaticFiles(directory=directory / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def index():
        if not available or directory is None:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Build the frontend and configure FRONTEND_DIST_DIR "
                    "to use this local page."
                },
            )
        return FileResponse(directory / "index.html", headers={"Cache-Control": "no-cache"})
