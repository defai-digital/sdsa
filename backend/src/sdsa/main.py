"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .core.config import get_config
from .core.logging import get_logger, setup_logging
from .core.session import get_store

log = get_logger("sdsa.main")


async def _sweep_loop() -> None:
    """Reap expired sessions every 60s so memory doesn't grow unbounded."""
    store = get_store()
    while True:
        try:
            await asyncio.sleep(60)
            n = await asyncio.to_thread(store.sweep)
            if n:
                log.info("session_sweep", extra={"expired": n})
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("session_sweep_error", extra={"err": str(e)})


@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def create_app() -> FastAPI:
    setup_logging()
    cfg = get_config()
    app = FastAPI(title="SDSA", version="1.2.0", lifespan=_lifespan)
    if cfg.allowed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.allowed_cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-API-Key"],
        )
    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"ok": True}

    # Serve packaged frontend assets first. Fall back to the repository layout
    # for editable installs and source-tree development.
    packaged_frontend = Path(__file__).resolve().parent / "frontend"
    repo_frontend = Path(__file__).resolve().parents[3] / "frontend"
    frontend = packaged_frontend if (packaged_frontend / "index.html").exists() else repo_frontend
    if frontend.is_dir() and (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")

    return app


app = create_app()
