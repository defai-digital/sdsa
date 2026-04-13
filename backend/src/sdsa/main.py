"""FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="SDSA", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # MVP; tighten for production
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"ok": True}

    # Serve the static frontend if present (single-binary dev experience).
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    if frontend.is_dir() and (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")

    return app


app = create_app()
