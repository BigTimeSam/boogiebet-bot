"""Test fixtures.

The schema is loaded from the project's single source of truth — ``init.sql`` —
and the real ``db`` module pool is initialised against the same test database, so
tests exercise production code (``bot/db.py``) rather than re-implementations.

Set ``DATABASE_URL`` to a PostgreSQL instance before running (e.g. the local
Docker Compose ``db`` service). Each test gets a clean slate.
"""
import os
import sys
from unittest.mock import MagicMock

import asyncpg
import pytest_asyncio

# Make the bot package importable (so tests can `import db`) and the tests dir
# importable (so tests can `import fakes`).
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "bot"))
sys.path.insert(0, os.path.dirname(__file__))

# python-telegram-bot and python-dotenv aren't test dependencies; stub them so
# the bot modules import. The handlers build telegram objects and hand them to
# the (faked) bot without introspecting them, so MagicMock stand-ins are
# sufficient; load_dotenv() is a no-op here because the env is set below.
for _mod in ("telegram", "telegram.ext", "telegram.error", "dotenv"):
    sys.modules.setdefault(_mod, MagicMock())

# Allow DATABASE_URL override; fall back to the Compose default.
TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://boogiebet:boogiebet@localhost:5432/boogiebet",
)
# db.get_pool() reads DATABASE_URL from the environment.
os.environ["DATABASE_URL"] = TEST_DB_URL

INIT_SQL = os.path.join(ROOT, "init.sql")

import db  # noqa: E402  (import after sys.path/env setup above)


async def _ensure_schema():
    """Create the base schema from init.sql, then initialise the db pool.

    init.sql must run before db.get_pool() triggers db._migrate(), because the
    baseline ALTERs there assume the tables already exist (mirrors production,
    where Docker runs init.sql before the bot starts).
    """
    setup = await asyncpg.connect(TEST_DB_URL)
    try:
        with open(INIT_SQL, encoding="utf-8") as fh:
            await setup.execute(fh.read())
    finally:
        await setup.close()
    # Triggers _migrate() + _apply_migrations() against the now-present schema.
    await db.get_pool()


@pytest_asyncio.fixture
async def conn():
    """Clean DB per test; yields a raw connection for setup/assertions.

    Production code under test uses the shared db pool; this connection (on the
    same database, autocommit) is for arranging fixtures and reading results.
    """
    # pytest-asyncio runs each test on a fresh event loop, but db._pool is a
    # module-global bound to the loop it was created on. Build a fresh pool on
    # THIS test's loop and tear it down here (on the same loop), otherwise
    # asyncpg raises "got Future attached to a different loop" / "loop is closed".
    db._pool = None
    await _ensure_schema()
    pool = await db.get_pool()
    async with pool.acquire() as c:
        await c.execute(
            "TRUNCATE TABLE wagers, bet_options, bets, users RESTART IDENTITY CASCADE"
        )
        await c.execute(
            "UPDATE settings SET value = 'false' WHERE key = 'game_finished'"
        )

    connection = await asyncpg.connect(TEST_DB_URL)
    try:
        yield connection
    finally:
        await connection.close()
        if db._pool is not None:
            await db._pool.close()
            db._pool = None
