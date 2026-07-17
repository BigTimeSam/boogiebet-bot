"""Unit tests for the liveness heartbeat behind the container healthcheck.

No database or telegram involved — health.py is deliberately dependency-free so
the healthcheck can run as a bare `python bot/health.py` inside the container.
"""
import time
from types import SimpleNamespace

import pytest

import health


@pytest.fixture(autouse=True)
def heartbeat_file(tmp_path, monkeypatch):
    """Point the module at a throwaway file instead of /tmp/boogiebet-heartbeat."""
    path = tmp_path / "heartbeat"
    monkeypatch.setattr(health, "HEARTBEAT_FILE", str(path))
    return path


def test_is_alive_false_before_any_beat():
    """A container that never reached post_init must report unhealthy, not
    healthy-by-default."""
    assert health.is_alive() is False


def test_beat_then_alive():
    health.beat()
    assert health.is_alive() is True


def test_stale_beat_is_not_alive():
    now = time.time()
    health.beat(now=now - health.HEARTBEAT_MAX_AGE - 1)
    assert health.is_alive(now=now) is False


def test_beat_just_inside_max_age_is_alive():
    now = time.time()
    health.beat(now=now - health.HEARTBEAT_MAX_AGE + 1)
    assert health.is_alive(now=now) is True


def test_beat_interval_leaves_room_for_a_missed_beat():
    """The check must not trip on one slow write; keep real headroom between the
    beat interval and the staleness cutoff."""
    assert health.HEARTBEAT_INTERVAL * 3 <= health.HEARTBEAT_MAX_AGE


def test_corrupt_heartbeat_is_not_alive(heartbeat_file):
    heartbeat_file.write_text("not a timestamp")
    assert health.is_alive() is False


def test_beat_never_raises_when_file_unwritable(monkeypatch):
    """A heartbeat write failure must not kill an otherwise healthy bot — going
    stale is already the signal."""
    monkeypatch.setattr(health, "HEARTBEAT_FILE", "/nonexistent-dir/heartbeat")
    health.beat()  # must not raise
    assert health.is_alive() is False


def test_beat_is_atomic_and_leaves_no_temp_file(heartbeat_file, tmp_path):
    health.beat()
    assert heartbeat_file.exists()
    assert list(tmp_path.iterdir()) == [heartbeat_file], "temp file must be renamed away"


# ── wiring into the bot ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_init_beats_before_polling_and_starts_the_loop():
    """post_init must beat immediately (so `up --wait` doesn't sit through the
    first interval) and then keep the loop running."""
    import os

    os.environ.setdefault("BOT_TOKEN", "test-token")
    import main

    scheduled = []
    app = SimpleNamespace(create_task=scheduled.append)

    await main._post_init(app)

    assert health.is_alive() is True, "post_init must beat before polling starts"
    assert len(scheduled) == 1, "the repeating heartbeat loop must be scheduled"
    scheduled[0].close()  # don't leave the never-ending coroutine pending
