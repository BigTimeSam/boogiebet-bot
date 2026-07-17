"""Liveness heartbeat for the container healthcheck.

The bot polls Telegram and serves no HTTP, so there is nothing to probe from
outside: `docker compose up -d bot` returns as soon as the container is created
and says nothing about whether the bot actually came up. A crash-looping bot
deployed green.

So the bot writes a timestamp here on a timer from its own event loop, and the
healthcheck fails when that timestamp goes stale. Beating from an asyncio task
(rather than just touching the file at startup) means the check proves the loop
is still turning, not merely that a process exists.

Run as a script, this module *is* the healthcheck: exit 0 = alive, 1 = stale.
"""
import os
import time

HEARTBEAT_FILE = os.environ.get("HEARTBEAT_FILE", "/tmp/boogiebet-heartbeat")

# Beat well inside MAX_AGE so a single slow write can't trip the check.
HEARTBEAT_INTERVAL = 15.0
HEARTBEAT_MAX_AGE = 60.0


def beat(now: float | None = None) -> None:
    """Record that the event loop is alive. Never raises: a heartbeat failure
    must not take down an otherwise healthy bot — the check going stale is
    already the signal."""
    try:
        tmp = f"{HEARTBEAT_FILE}.tmp"
        with open(tmp, "w") as fh:
            fh.write(str(time.time() if now is None else now))
        os.replace(tmp, HEARTBEAT_FILE)  # atomic: never read a half-written beat
    except OSError:
        pass


def last_beat() -> float | None:
    """The most recent heartbeat as a unix timestamp, or None if unreadable."""
    try:
        with open(HEARTBEAT_FILE) as fh:
            return float(fh.read().strip())
    except (OSError, ValueError):
        return None


def is_alive(now: float | None = None) -> bool:
    last = last_beat()
    if last is None:
        return False
    return (time.time() if now is None else now) - last < HEARTBEAT_MAX_AGE


if __name__ == "__main__":
    raise SystemExit(0 if is_alive() else 1)
