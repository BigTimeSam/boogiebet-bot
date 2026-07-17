"""
Integration tests for bet resolution, wager limits and leaderboard.
All tests run against a real PostgreSQL instance (see conftest.py) and exercise
the production data layer (bot/db.py) rather than re-implementations.
"""
import pytest

import db
from constants import MAX_WAGER

# ── helpers ────────────────────────────────────────────────────────────────────
# Setup helpers (add_user / create_*) insert rows directly. Behaviour helpers
# (place_wager / lock / resolve / leaderboard) delegate to bot/db.py so the tests
# cover the real money paths, including the atomic balance guard and the
# status-guarded, idempotent resolution logic.

async def add_user(conn, telegram_id: int, username: str) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username) VALUES ($1, $2) RETURNING *",
        telegram_id, username,
    )
    return dict(row)


async def create_simple_bet(conn, title: str, yes_odds: float, no_odds: float, created_by: int) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, created_by) "
        "VALUES ($1, $2, $3, 'simple', $4) RETURNING *",
        title, yes_odds, no_odds, created_by,
    )
    return dict(row)


async def create_winner_bet(conn, title: str, options: list, created_by: int) -> dict:
    bet = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, created_by) "
        "VALUES ($1, 0, 0, 'winner', $2) RETURNING *",
        title, created_by,
    )
    opt_rows = []
    for i, opt in enumerate(options):
        row = await conn.fetchrow(
            "INSERT INTO bet_options (bet_id, label, odds, position) "
            "VALUES ($1, $2, $3, $4) RETURNING *",
            bet["id"], opt["label"], opt["odds"], i,
        )
        opt_rows.append(dict(row))
    result = dict(bet)
    result["options"] = opt_rows
    return result


async def place_wager(conn, user_id: int, bet_id: int, side: str,
                      amount: float, option_id: int = None) -> float:
    """Place or replace a wager via the real data layer; returns new balance."""
    balance, _ = await db.place_wager(user_id, bet_id, side, amount, option_id)
    return balance


async def lock_bet(conn, bet_id: int):
    await db.lock_bet(bet_id)


async def resolve_simple_bet(conn, bet_id: int, result: str) -> list:
    return await db.resolve_bet(bet_id, result)


async def resolve_winner_bet(conn, bet_id: int, winning_option_id: int) -> list:
    return await db.resolve_winner_bet(bet_id, winning_option_id)


async def get_balance(conn, user_id: int) -> float:
    return float(await conn.fetchval("SELECT balance FROM users WHERE id = $1", user_id))


async def get_leaderboard(conn) -> list:
    return await db.get_leaderboard()


# ── tests: simple yes/no bets ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simple_bet_winners_paid_correctly(conn):
    """Winners receive amount × odds; losers keep their reduced balance."""
    alice = await add_user(conn, 1, "alice")
    bob   = await add_user(conn, 2, "bob")
    carol = await add_user(conn, 3, "carol")

    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Testikohde", yes_odds=2.00, no_odds=3.00, created_by=admin["id"])
    bet_id = bet["id"]

    # alice & bob bet yes (200 € each), carol bets no (150 €)
    await place_wager(conn, alice["id"], bet_id, "yes", 200.0)
    await place_wager(conn, bob["id"],   bet_id, "yes", 200.0)
    await place_wager(conn, carol["id"], bet_id, "no",  150.0)

    await lock_bet(conn, bet_id)
    winners = await resolve_simple_bet(conn, bet_id, "yes")

    # Two winners
    assert len(winners) == 2

    alice_bal = await get_balance(conn, alice["id"])
    bob_bal   = await get_balance(conn, bob["id"])
    carol_bal = await get_balance(conn, carol["id"])

    # alice: 1000 - 200 + (200 × 2.00) = 1200
    assert alice_bal == pytest.approx(1200.0)
    # bob: same
    assert bob_bal == pytest.approx(1200.0)
    # carol lost her stake: 1000 - 150 = 850
    assert carol_bal == pytest.approx(850.0)


@pytest.mark.asyncio
async def test_simple_bet_no_side_wins(conn):
    """Verify no-side resolution pays correct odds."""
    alice = await add_user(conn, 1, "alice")
    bob   = await add_user(conn, 2, "bob")

    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Ei-veto", yes_odds=1.50, no_odds=3.25, created_by=admin["id"])
    bet_id = bet["id"]

    await place_wager(conn, alice["id"], bet_id, "no",  100.0)
    await place_wager(conn, bob["id"],   bet_id, "yes", 100.0)

    await lock_bet(conn, bet_id)
    winners = await resolve_simple_bet(conn, bet_id, "no")

    assert len(winners) == 1
    alice_bal = await get_balance(conn, alice["id"])
    # 1000 - 100 + (100 × 3.25) = 1225
    assert alice_bal == pytest.approx(1225.0)

    bob_bal = await get_balance(conn, bob["id"])
    assert bob_bal == pytest.approx(900.0)


@pytest.mark.asyncio
async def test_no_winners_when_no_matching_wagers(conn):
    """Resolve returns empty list if no one bet on the winning side."""
    alice = await add_user(conn, 1, "alice")

    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Tyhjiö", yes_odds=2.0, no_odds=2.0, created_by=admin["id"])
    await place_wager(conn, alice["id"], bet["id"], "no", 100.0)

    await lock_bet(conn, bet["id"])
    winners = await resolve_simple_bet(conn, bet["id"], "yes")

    assert winners == []
    # alice's balance stays at 900 (lost stake)
    assert await get_balance(conn, alice["id"]) == pytest.approx(900.0)


# ── tests: winner (multi-option) bets ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_winner_bet_correct_option_paid(conn):
    """Only the player who chose the winning option is paid."""
    alice = await add_user(conn, 1, "alice")
    bob   = await add_user(conn, 2, "bob")
    carol = await add_user(conn, 3, "carol")

    admin = await add_user(conn, 99, "admin")
    bet = await create_winner_bet(conn, "Turnauksen voittaja", [
        {"label": "Tiimi A", "odds": 2.00},
        {"label": "Tiimi B", "odds": 3.50},
        {"label": "Tiimi C", "odds": 5.00},
    ], created_by=admin["id"])

    opt_a = bet["options"][0]["id"]
    opt_b = bet["options"][1]["id"]
    opt_c = bet["options"][2]["id"]
    bet_id = bet["id"]

    await place_wager(conn, alice["id"], bet_id, "opt", 200.0, option_id=opt_a)
    await place_wager(conn, bob["id"],   bet_id, "opt", 150.0, option_id=opt_b)
    await place_wager(conn, carol["id"], bet_id, "opt", 100.0, option_id=opt_c)

    await lock_bet(conn, bet_id)
    winners = await resolve_winner_bet(conn, bet_id, opt_b)  # Tiimi B wins

    assert len(winners) == 1
    assert winners[0]["username"] == "bob"

    # bob: 1000 - 150 + (150 × 3.50) = 1375
    assert await get_balance(conn, bob["id"])   == pytest.approx(1375.0)
    # alice lost: 1000 - 200 = 800
    assert await get_balance(conn, alice["id"]) == pytest.approx(800.0)
    # carol lost: 1000 - 100 = 900
    assert await get_balance(conn, carol["id"]) == pytest.approx(900.0)


@pytest.mark.asyncio
async def test_winner_bet_four_options(conn):
    """Four-option bet: verify all losers lose and winner is paid."""
    users = [await add_user(conn, i, f"player{i}") for i in range(1, 5)]
    admin = await add_user(conn, 99, "admin")

    bet = await create_winner_bet(conn, "Lani-voittaja", [
        {"label": "Tiimi 1", "odds": 1.85},
        {"label": "Tiimi 2", "odds": 1.95},
        {"label": "Tiimi 3", "odds": 2.50},
        {"label": "Tiimi 4", "odds": 4.00},
    ], created_by=admin["id"])

    options = bet["options"]
    bet_id = bet["id"]
    amounts = [200.0, 150.0, 100.0, 50.0]

    for user, opt, amount in zip(users, options, amounts):
        await place_wager(conn, user["id"], bet_id, "opt", amount, option_id=opt["id"])

    await lock_bet(conn, bet_id)
    winning_opt = options[2]  # Tiimi 3 @ 2.50
    winners = await resolve_winner_bet(conn, bet_id, winning_opt["id"])

    assert len(winners) == 1
    winner_user = users[2]
    # 1000 - 100 + (100 × 2.50) = 1150
    assert await get_balance(conn, winner_user["id"]) == pytest.approx(1150.0)

    for user, amount, opt in zip(users, amounts, options):
        if opt["id"] != winning_opt["id"]:
            expected = 1000.0 - amount
            assert await get_balance(conn, user["id"]) == pytest.approx(expected)


# ── tests: max wager enforcement ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_wager_at_max_allowed(conn):
    """Placing exactly 200 € succeeds and balance is deducted correctly."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Max test", 2.0, 2.0, created_by=admin["id"])

    bal = await place_wager(conn, alice["id"], bet["id"], "yes", MAX_WAGER)
    assert bal == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_wager_replaces_previous_not_accumulates(conn):
    """
    Placing 100 € and then 100 € again results in a total wager of 100 €,
    NOT 200 €, because the second call replaces the first.
    Balance after both placements: 1000 - 100 = 900 (not 1000 - 200 = 800).
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Replace test", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 100.0)
    bal = await place_wager(conn, alice["id"], bet["id"], "yes", 100.0)

    # Balance unchanged from the first placement because second replaces it
    assert bal == pytest.approx(900.0)

    # Only one wager row exists for this user/bet
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM wagers WHERE user_id = $1 AND bet_id = $2",
        alice["id"], bet["id"],
    )
    assert count == 1

    # The stored wager amount is 100, not 200
    amount = await conn.fetchval(
        "SELECT amount FROM wagers WHERE user_id = $1 AND bet_id = $2",
        alice["id"], bet["id"],
    )
    assert float(amount) == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_three_sequential_placements_balance_correct(conn):
    """
    Placing 100 €, then 100 €, then 100 € results in total wager of 100 €
    and balance of 900 €. Simulates the '100+100+100 ei kumuloidu' requirement.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Triple test", 2.0, 2.0, created_by=admin["id"])

    for _ in range(3):
        bal = await place_wager(conn, alice["id"], bet["id"], "yes", 100.0)

    assert bal == pytest.approx(900.0)

    stored = float(await conn.fetchval(
        "SELECT amount FROM wagers WHERE user_id = $1 AND bet_id = $2",
        alice["id"], bet["id"],
    ))
    assert stored == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_wager_update_respects_balance(conn):
    """
    Updating a wager from 100 € to 200 € correctly charges the extra 100 €.
    Balance: 1000 - 100 (first) = 900, then 900 - 100 extra = 800.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Update test", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 100.0)
    bal = await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)

    assert bal == pytest.approx(800.0)

    stored = float(await conn.fetchval(
        "SELECT amount FROM wagers WHERE user_id = $1 AND bet_id = $2",
        alice["id"], bet["id"],
    ))
    assert stored == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_cannot_wager_more_than_balance(conn):
    """
    A user with 1000 € cannot place a wager of 1001 €.
    db.place_wager's atomic SQL guard rejects the overdraw, returns None, and
    makes no change — this is the load-bearing overdraw protection.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Balance test", 2.0, 2.0, created_by=admin["id"])

    balance, existed = await db.place_wager(alice["id"], bet["id"], "yes", 1001.0)
    assert balance is None
    assert existed is False

    # No wager should be placed; balance unchanged.
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM wagers WHERE user_id = $1 AND bet_id = $2",
        alice["id"], bet["id"],
    )
    assert count == 0
    assert await get_balance(conn, alice["id"]) == pytest.approx(1000.0)


# ── tests: leaderboard ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leaderboard_order_after_resolution(conn):
    """Leaderboard is sorted by balance descending after resolution."""
    alice = await add_user(conn, 1, "alice")  # will win big
    bob   = await add_user(conn, 2, "bob")    # will win smaller
    carol = await add_user(conn, 3, "carol")  # will lose
    await add_user(conn, 4, "dave")           # no bet, stays at 1000

    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Leaderboard test", yes_odds=3.00, no_odds=2.00, created_by=admin["id"])
    bet_id = bet["id"]

    await place_wager(conn, alice["id"], bet_id, "yes", 200.0)   # wins: +600 → 1400
    await place_wager(conn, bob["id"],   bet_id, "yes", 100.0)   # wins: +300 → 1200
    await place_wager(conn, carol["id"], bet_id, "no",  150.0)   # loses → 850

    await lock_bet(conn, bet_id)
    await resolve_simple_bet(conn, bet_id, "yes")

    board = await get_leaderboard(conn)

    # admin is in the DB too; filter to our four players for assertion clarity
    # alice 1400, bob 1200, dave 1000, carol 850
    players = [r for r in board if r["username"] in {"alice", "bob", "carol", "dave"}]
    assert players[0]["username"] == "alice"
    assert players[1]["username"] == "bob"
    assert players[2]["username"] == "dave"
    assert players[3]["username"] == "carol"
    balances = [float(p["balance"]) for p in players]
    assert balances == sorted(balances, reverse=True)
    assert balances[0] == pytest.approx(1400.0)
    assert balances[1] == pytest.approx(1200.0)
    assert balances[2] == pytest.approx(1000.0)
    assert balances[3] == pytest.approx(850.0)


@pytest.mark.asyncio
async def test_leaderboard_multiple_bets(conn):
    """Leaderboard reflects cumulative balance across multiple resolved bets."""
    alice = await add_user(conn, 1, "alice")
    bob   = await add_user(conn, 2, "bob")

    admin = await add_user(conn, 99, "admin")

    bet1 = await create_simple_bet(conn, "Veto 1", yes_odds=2.00, no_odds=2.00, created_by=admin["id"])
    bet2 = await create_winner_bet(conn, "Veto 2", [
        {"label": "X", "odds": 2.00},
        {"label": "Y", "odds": 3.00},
    ], created_by=admin["id"])

    opt_x = bet2["options"][0]["id"]
    opt_y = bet2["options"][1]["id"]

    # Bet 1: alice bets yes 200 → wins; bob bets no 200 → loses
    await place_wager(conn, alice["id"], bet1["id"], "yes", 200.0)
    await place_wager(conn, bob["id"],   bet1["id"], "no",  200.0)
    await lock_bet(conn, bet1["id"])
    await resolve_simple_bet(conn, bet1["id"], "yes")
    # alice: 1000 - 200 + 400 = 1200, bob: 800

    # Bet 2: alice bets Y 100 → loses; bob bets X 100 → wins
    await place_wager(conn, alice["id"], bet2["id"], "opt", 100.0, option_id=opt_y)
    await place_wager(conn, bob["id"],   bet2["id"], "opt", 100.0, option_id=opt_x)
    await lock_bet(conn, bet2["id"])
    await resolve_winner_bet(conn, bet2["id"], opt_x)  # X wins
    # alice: 1200 - 100 = 1100, bob: 800 - 100 + 200 = 900

    alice_bal = await get_balance(conn, alice["id"])
    bob_bal   = await get_balance(conn, bob["id"])

    assert alice_bal == pytest.approx(1100.0)
    assert bob_bal   == pytest.approx(900.0)

    board = [r for r in await get_leaderboard(conn) if r["username"] in {"alice", "bob"}]
    assert board[0]["username"] == "alice"
    assert board[1]["username"] == "bob"


# ── tests: resolution is status-guarded and idempotent ─────────────────────────

@pytest.mark.asyncio
async def test_double_resolve_simple_pays_once(conn):
    """Resolving an already-resolved simple bet is a no-op (no double payout)."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Double resolve", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    await lock_bet(conn, bet["id"])

    winners = await db.resolve_bet(bet["id"], "yes")
    assert winners is not None and len(winners) == 1
    # 1000 - 200 + 200*2.0 = 1200
    assert await get_balance(conn, alice["id"]) == pytest.approx(1200.0)

    # Second resolve must do nothing: returns None, balance unchanged.
    again = await db.resolve_bet(bet["id"], "yes")
    assert again is None
    assert await get_balance(conn, alice["id"]) == pytest.approx(1200.0)


@pytest.mark.asyncio
async def test_double_resolve_winner_pays_once(conn):
    """Resolving an already-resolved winner bet is a no-op."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_winner_bet(conn, "Winner double", [
        {"label": "A", "odds": 2.0},
        {"label": "B", "odds": 3.0},
    ], created_by=admin["id"])
    opt_a = bet["options"][0]["id"]

    await place_wager(conn, alice["id"], bet["id"], "opt", 100.0, option_id=opt_a)
    await lock_bet(conn, bet["id"])

    winners = await db.resolve_winner_bet(bet["id"], opt_a)
    assert winners is not None and len(winners) == 1
    # 1000 - 100 + 100*2.0 = 1100
    assert await get_balance(conn, alice["id"]) == pytest.approx(1100.0)

    again = await db.resolve_winner_bet(bet["id"], opt_a)
    assert again is None
    assert await get_balance(conn, alice["id"]) == pytest.approx(1100.0)


@pytest.mark.asyncio
async def test_resolve_requires_locked_bet(conn):
    """An open (never-locked) bet cannot be resolved; no payout occurs."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Still open", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    # No lock_bet() call → status is 'open'.
    winners = await db.resolve_bet(bet["id"], "yes")
    assert winners is None
    # Balance reflects only the placed wager (1000 - 200), no payout.
    assert await get_balance(conn, alice["id"]) == pytest.approx(800.0)


# ── tests: revert resolution (clawback) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_revert_resolved_bet_claws_back_payout(conn):
    """Reverting a resolved bet returns it to locked and claws back winnings."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Revert me", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    await lock_bet(conn, bet["id"])
    await db.resolve_bet(bet["id"], "yes")
    assert await get_balance(conn, alice["id"]) == pytest.approx(1200.0)

    ok = await db.revert_resolved_bet(bet["id"])
    assert ok is True
    # Payout (400) clawed back → 800; bet returns to locked.
    assert await get_balance(conn, alice["id"]) == pytest.approx(800.0)
    reverted = await db.get_bet(bet["id"])
    assert reverted["status"] == "locked"
    assert reverted["result"] is None


@pytest.mark.asyncio
async def test_revert_clamps_balance_at_zero(conn):
    """If a winner already spent the payout, clawback clamps at 0, not negative."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Spent it", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    await lock_bet(conn, bet["id"])
    await db.resolve_bet(bet["id"], "yes")  # alice → 1200

    # Drain alice's balance to 100 so a 400 clawback would go negative.
    await conn.execute("UPDATE users SET balance = 100 WHERE id = $1", alice["id"])

    ok = await db.revert_resolved_bet(bet["id"])
    assert ok is True
    # Clamped at 0 rather than violating CHECK (balance >= 0).
    assert await get_balance(conn, alice["id"]) == pytest.approx(0.0)


# ── delete_bet status guard ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_bet_refuses_resolved_and_keeps_wagers(conn):
    """Deleting a resolved bet must be a no-op.

    The wagers/bet_options deletes are unconditional, so without a status guard
    a resolved bet loses its wagers (and the Voittajat view empties) while the
    caller is told the delete failed.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Already called", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    await lock_bet(conn, bet["id"])
    await db.resolve_bet(bet["id"], "yes")
    balance_after_resolve = await get_balance(conn, alice["id"])

    deleted = await db.delete_bet(bet["id"])

    assert deleted is False
    wagers_left = await conn.fetchval(
        "SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet["id"]
    )
    assert wagers_left == 1, "a resolved bet's wagers must survive a refused delete"
    assert await db.get_bet(bet["id"]) is not None
    assert await get_balance(conn, alice["id"]) == pytest.approx(balance_after_resolve)


@pytest.mark.asyncio
async def test_delete_bet_refuses_resolved_winner_bet_keeps_options(conn):
    """Same guard, winner bets: bet_options must survive too."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_winner_bet(
        conn, "Who wins",
        [{"label": "A", "odds": 2.0}, {"label": "B", "odds": 3.0}],
        created_by=admin["id"],
    )
    opt_a = bet["options"][0]["id"]

    await place_wager(conn, alice["id"], bet["id"], "opt", 100.0, option_id=opt_a)
    await lock_bet(conn, bet["id"])
    await db.resolve_winner_bet(bet["id"], opt_a)

    deleted = await db.delete_bet(bet["id"])

    assert deleted is False
    assert await conn.fetchval("SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet["id"]) == 1
    assert await conn.fetchval("SELECT COUNT(*) FROM bet_options WHERE bet_id = $1", bet["id"]) == 2


@pytest.mark.asyncio
async def test_delete_bet_still_refunds_open_bet(conn):
    """The guard must not break the supported path: deleting an open bet
    refunds every stake in full."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Called off", 2.0, 2.0, created_by=admin["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    assert await get_balance(conn, alice["id"]) == pytest.approx(800.0)

    deleted = await db.delete_bet(bet["id"])

    assert deleted is True
    assert await get_balance(conn, alice["id"]) == pytest.approx(1000.0)
    assert await conn.fetchval("SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet["id"]) == 0
    assert await db.get_bet(bet["id"]) is None


# ── resolve type guards ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_bet_refuses_winner_bet(conn):
    """resolve_bet() is the simple-bet path. A winner bet's wagers all carry
    side 'opt', so resolving one as yes/no matches nobody: every stake is lost
    and revert_resolved_bet() can no longer parse result back to an option id.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_winner_bet(
        conn, "Who wins",
        [{"label": "A", "odds": 2.0}, {"label": "B", "odds": 3.0}],
        created_by=admin["id"],
    )
    opt_a = bet["options"][0]["id"]

    await place_wager(conn, alice["id"], bet["id"], "opt", 100.0, option_id=opt_a)
    await lock_bet(conn, bet["id"])
    balance_before = await get_balance(conn, alice["id"])

    winners = await db.resolve_bet(bet["id"], "yes")

    assert winners is None, "a winner bet must not resolve through the simple path"
    still_locked = await db.get_bet(bet["id"])
    assert still_locked["status"] == "locked"
    assert still_locked["result"] is None
    assert await get_balance(conn, alice["id"]) == pytest.approx(balance_before)


@pytest.mark.asyncio
async def test_resolve_winner_bet_refuses_simple_bet(conn):
    """The mirror guard: a simple bet must not resolve through the winner path."""
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    simple = await create_simple_bet(conn, "Yes or no", 2.0, 2.0, created_by=admin["id"])
    # An option row belonging to a *different* winner bet.
    other = await create_winner_bet(
        conn, "Other", [{"label": "A", "odds": 2.0}], created_by=admin["id"]
    )

    await place_wager(conn, alice["id"], simple["id"], "yes", 100.0)
    await lock_bet(conn, simple["id"])

    winners = await db.resolve_winner_bet(simple["id"], other["options"][0]["id"])

    assert winners is None
    assert (await db.get_bet(simple["id"]))["status"] == "locked"


# ── add_balance / bonus_balance visibility ──────────────────────────────────────

@pytest.mark.asyncio
async def test_add_balance_returns_new_balance(conn):
    alice = await add_user(conn, 1, "alice")
    new_balance = await db.add_balance(alice["id"], 250)
    assert float(new_balance) == pytest.approx(1250.0)


@pytest.mark.asyncio
async def test_negative_add_balance_keeps_player_on_leaderboard(conn):
    """A withdrawal must not drive bonus_balance negative, which used to drop the
    player off BOTH the leaderboard (bonus = 0) and the kepuli list (bonus > 0)."""
    alice = await add_user(conn, 1, "alice")
    await db.add_balance(alice["id"], -100)  # withdraw

    assert float((await db.get_user(1))["balance"]) == pytest.approx(900.0)
    assert float((await db.get_user(1))["bonus_balance"]) == pytest.approx(0.0)
    board = await db.get_leaderboard()
    assert any(r["telegram_id"] == 1 for r in board), "player must stay on the leaderboard"
    assert all(r["telegram_id"] != 1 for r in await db.get_kepulit())


@pytest.mark.asyncio
async def test_add_balance_topup_then_revert_restores_leaderboard(conn):
    alice = await add_user(conn, 1, "alice")
    await db.add_balance(alice["id"], 500)   # kepuli now
    assert any(r["telegram_id"] == 1 for r in await db.get_kepulit())
    await db.add_balance(alice["id"], -500)  # revert the top-up
    # bonus back to 0 → back on the leaderboard, off the kepuli list.
    assert any(r["telegram_id"] == 1 for r in await db.get_leaderboard())
    assert all(r["telegram_id"] != 1 for r in await db.get_kepulit())


@pytest.mark.asyncio
async def test_add_balance_rejects_overdraw(conn):
    alice = await add_user(conn, 1, "alice")
    result = await db.add_balance(alice["id"], -5000)  # more than the balance
    assert result is None
    assert float((await db.get_user(1))["balance"]) == pytest.approx(1000.0)


# ── cancel_wager whole-euro refund ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_wager_refunds_whole_euros(conn):
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Cashout me", 2.0, 2.0, created_by=admin["id"])
    await conn.execute("UPDATE bets SET status = 'open' WHERE id = $1", bet["id"])

    await place_wager(conn, alice["id"], bet["id"], "yes", 50.0)  # balance 950
    refund = await db.cancel_wager(alice["id"], bet["id"])

    # 50 × 0.95 = 47.5 → 47 credited; the balance stays a whole number.
    assert refund == 47
    assert await get_balance(conn, alice["id"]) == pytest.approx(997.0)
    assert await db.get_user_wager(alice["id"], bet["id"]) is None


# ── resolve reports NET profit ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_bet_profit_is_net(conn):
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Net check", 2.0, 2.0, created_by=admin["id"])
    await place_wager(conn, alice["id"], bet["id"], "yes", 100.0)
    await lock_bet(conn, bet["id"])

    winners = await db.resolve_bet(bet["id"], "yes")

    assert len(winners) == 1
    # stake 100 @ 2.0 → payout 200, net profit 100.
    assert winners[0]["profit"] == pytest.approx(100.0)
    assert winners[0]["payout"] == pytest.approx(200.0)


# ── money conservation across a full round ──────────────────────────────────────

async def _total_equity(conn) -> float:
    """All money in the game: free balances plus stakes locked in open/locked bets."""
    balances = float(await conn.fetchval("SELECT COALESCE(SUM(balance), 0) FROM users"))
    staked = float(await conn.fetchval(
        "SELECT COALESCE(SUM(w.amount), 0) FROM wagers w "
        "JOIN bets b ON b.id = w.bet_id WHERE b.status IN ('open', 'locked')"
    ))
    return balances + staked


@pytest.mark.asyncio
async def test_money_conserved_through_place_and_resolve(conn):
    """With a balanced book at even (2.0/2.0) odds the winners' gains exactly
    fund the losers' losses, so total equity is invariant across placing and
    resolving. This is the global check the 74 balance-by-balance tests never
    made; it catches a double-payout or a lost stake that per-player asserts on
    one bet can miss.

    (Note: fixed-odds betting only conserves money when the book balances — an
    unbalanced book at fixed odds legitimately creates or destroys money.)"""
    players = [await add_user(conn, i, f"p{i}") for i in range(1, 6)]
    admin = await add_user(conn, 99, "admin")
    start = await _total_equity(conn)
    assert start == pytest.approx(6 * 1000.0)

    bet = await create_simple_bet(conn, "Coin flip", 2.0, 2.0, created_by=admin["id"])
    await place_wager(conn, players[0]["id"], bet["id"], "yes", 100.0)
    await place_wager(conn, players[1]["id"], bet["id"], "yes", 50.0)
    await place_wager(conn, players[2]["id"], bet["id"], "no", 150.0)  # yes 150 == no 150
    assert await _total_equity(conn) == pytest.approx(start), "placing wagers moves no money out of the game"

    await lock_bet(conn, bet["id"])
    await db.resolve_bet(bet["id"], "yes")
    assert await _total_equity(conn) == pytest.approx(start)


@pytest.mark.asyncio
async def test_money_conserved_through_resolve_and_revert(conn):
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    start = await _total_equity(conn)

    bet = await create_simple_bet(conn, "Reverted", 2.0, 2.0, created_by=admin["id"])
    await place_wager(conn, alice["id"], bet["id"], "yes", 200.0)
    await lock_bet(conn, bet["id"])
    await db.resolve_bet(bet["id"], "yes")
    await db.revert_resolved_bet(bet["id"])

    assert await _total_equity(conn) == pytest.approx(start)
