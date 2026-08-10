"""Shared fixtures.

The database URL is set before the app is imported, so the tests run against a throwaway
SQLite file rather than the developer's ``lineups.db``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Default to a throwaway SQLite file, but respect an explicit DATABASE_URL so the suite
# can be pointed at Postgres (as CI does) to check the same code against both backends.
if not os.getenv("DATABASE_URL"):
    _TMP_DB = Path(tempfile.mkdtemp(prefix="lineups-tests-")) / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.seed import load_dataset  # noqa: E402


@pytest.fixture(scope="session")
def dataset() -> dict:
    return load_dataset()


@pytest_asyncio.fixture
async def client():
    """An HTTP client wired straight to the ASGI app, with the lifespan run.

    The engine is disposed afterwards. Each test runs on its own event loop, but the
    engine is built once at import and pools its connections; a Postgres connection is
    pinned to the loop that opened it, so without this the second test inherits a
    connection whose loop has closed and asyncpg reports "another operation is in
    progress". SQLite tolerates the reuse, which is why this only shows up on Postgres.
    """
    from backend.app.db import engine

    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                yield c
    finally:
        await engine.dispose()
