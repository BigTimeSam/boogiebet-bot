"""Integration tests for the results-site data generator.

Runs the real generator against the test database (the same conn fixture the
rest of the suite uses) and asserts on the JSON it writes.
"""
import json
import os
import sys

import pytest

# The generator lives in results/, not on the default path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "results"))
import generate_results  # noqa: E402


async def _seed_basic(conn):
    alice = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username, balance) VALUES (1, 'alice', 1100) RETURNING *"
    )
    bob = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username, balance) VALUES (2, 'bob', 900) RETURNING *"
    )
    # A kepuli: manually credited, so excluded from the site.
    kepuli = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username, balance, bonus_balance) "
        "VALUES (3, 'kepuli', 5000, 4000) RETURNING *"
    )
    bet = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status, result) "
        "VALUES ('Match', 2.0, 2.0, 'simple', 'resolved', 'yes') RETURNING *"
    )
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'yes', 100)",
        alice["id"], bet["id"],
    )
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'no', 100)",
        bob["id"], bet["id"],
    )
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'yes', 200)",
        kepuli["id"], bet["id"],
    )


@pytest.fixture
def output_to(tmp_path, monkeypatch):
    out = tmp_path / "data.json"
    monkeypatch.setattr(generate_results, "OUTPUT", out)
    monkeypatch.setattr(generate_results, "DATABASE_URL", os.environ["DATABASE_URL"])
    return out


@pytest.mark.asyncio
async def test_generated_at_is_timezone_aware(conn, output_to):
    await _seed_basic(conn)
    await generate_results.main()
    data = json.loads(output_to.read_text())
    # An aware timestamp ends in an offset (…+00:00), so the page parses it as an
    # instant instead of the viewer's local zone.
    assert data["generated_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_kepuli_excluded_from_leaderboard_and_stats(conn, output_to):
    await _seed_basic(conn)
    await generate_results.main()
    data = json.loads(output_to.read_text())

    names = {p["username"] for p in data["leaderboard"]}
    assert names == {"alice", "bob"}, "kepuli must not appear on the leaderboard"

    # The kepuli's 200 stake must not inflate the pot either — only alice's 100
    # and bob's 100 count.
    assert data["stats"]["total_pot"] == pytest.approx(200.0)
    the_bet = data["bets"][0]
    assert the_bet["num_bettors"] == 2
    assert the_bet["total_wagered"] == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_anonymous_players_are_matched_by_id_not_name(conn, output_to):
    """Two username-less players share the same 'user…' fallback; the win/loss
    tally must be attributed by id, not by that shared display name."""
    a = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username, balance) VALUES (10, NULL, 1200) RETURNING *"
    )
    b = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username, balance) VALUES (11, NULL, 800) RETURNING *"
    )
    bet = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status, result) "
        "VALUES ('Anon', 2.0, 2.0, 'simple', 'resolved', 'yes') RETURNING *"
    )
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'yes', 100)",
        a["id"], bet["id"],
    )
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'no', 100)",
        b["id"], bet["id"],
    )

    await generate_results.main()
    data = json.loads(output_to.read_text())

    by_name = {p["username"]: p for p in data["leaderboard"]}
    # Distinct fallback names, and exactly one winner and one loser — not both
    # attributed to whichever name sorted first.
    assert len(by_name) == 2
    assert sum(p["bets_won"] for p in data["leaderboard"]) == 1
    assert sum(p["bets_lost"] for p in data["leaderboard"]) == 1
