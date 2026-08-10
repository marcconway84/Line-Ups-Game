"""Application entry point.

Creates the tables, seeds the lineup catalogue on first run, mounts the API under /api
and serves the browser client from the repository's ``frontend/`` directory, so a single
``uvicorn`` command gives you a playable game.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import AsyncSessionLocal, create_all
from .routes import router
from .seed import seed_if_empty

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all()
    if os.getenv("LINEUPS_SKIP_SEED", "").lower() not in {"1", "true", "yes"}:
        async with AsyncSessionLocal() as session:
            seeded = await seed_if_empty(session)
            if seeded:
                print(f"Seeded {seeded} lineups from data/lineups.json")
    yield


app = FastAPI(
    title="Line-Ups Game API",
    version="1.0.0",
    description="Name the missing players from famous starting XIs.",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api")

if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
