"""
Test fixtures: spin up a fresh schema in the test DB before each test,
tear it down after.  Set DATABASE_URL env var to a PostgreSQL instance
before running (e.g. the local Docker Compose db service).
"""
import asyncio
import os
import asyncpg
import pytest
import pytest_asyncio

# Allow DATABASE_URL override; fall back to the Compose default.
TEST_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://boogiebet:boogiebet@localhost:5432/boogiebet",
)

DDL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username    VARCHAR(255),
    balance     NUMERIC(10,2) DEFAULT 1000.00,
    is_admin    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bets (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    yes_odds    NUMERIC(5,2) NOT NULL DEFAULT 0,
    no_odds     NUMERIC(5,2) NOT NULL DEFAULT 0,
    bet_type    VARCHAR(10) NOT NULL DEFAULT 'simple',
    status      VARCHAR(20) DEFAULT 'open',
    result      TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bet_options (
    id          SERIAL PRIMARY KEY,
    bet_id      INTEGER REFERENCES bets(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    odds        NUMERIC(5,2) NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wagers (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    bet_id      INTEGER REFERENCES bets(id),
    side        VARCHAR(3) NOT NULL,
    option_id   INTEGER REFERENCES bet_options(id),
    amount      NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, bet_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO settings (key, value) VALUES ('game_finished', 'false') ON CONFLICT DO NOTHING;
"""


@pytest_asyncio.fixture
async def conn():
    """Isolated connection with its own schema; rolled back after each test."""
    connection = await asyncpg.connect(TEST_DB_URL)
    await connection.execute(DDL)
    # Reset sequences and data between tests
    await connection.execute(
        "TRUNCATE TABLE wagers, bet_options, bets, users RESTART IDENTITY CASCADE"
    )
    await connection.execute(
        "UPDATE settings SET value = 'false' WHERE key = 'game_finished'"
    )
    yield connection
    await connection.close()
