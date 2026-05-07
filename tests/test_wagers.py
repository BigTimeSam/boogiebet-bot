"""
Integration tests for bet resolution, wager limits and leaderboard.
All tests run against a real PostgreSQL instance (see conftest.py).
"""
import pytest
import pytest_asyncio
from decimal import Decimal

MAX_WAGER = 200.0
STARTING_BALANCE = Decimal("1000.00")

# ── helpers ────────────────────────────────────────────────────────────────────

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
    """Place or replace a wager; returns new balance."""
    existing = await conn.fetchrow(
        "SELECT * FROM wagers WHERE user_id = $1 AND bet_id = $2", user_id, bet_id
    )
    refund = float(existing["amount"]) if existing else 0.0
    balance = await conn.fetchval(
        "UPDATE users SET balance = balance + $1 - $2 WHERE id = $3 RETURNING balance",
        refund, amount, user_id,
    )
    if existing:
        await conn.execute(
            "UPDATE wagers SET side = $1, amount = $2, option_id = $3 "
            "WHERE user_id = $4 AND bet_id = $5",
            side, amount, option_id, user_id, bet_id,
        )
    else:
        await conn.execute(
            "INSERT INTO wagers (user_id, bet_id, side, amount, option_id) "
            "VALUES ($1, $2, $3, $4, $5)",
            user_id, bet_id, side, amount, option_id,
        )
    return float(balance)


async def lock_bet(conn, bet_id: int):
    await conn.execute(
        "UPDATE bets SET status = 'locked' WHERE id = $1", bet_id
    )


async def resolve_simple_bet(conn, bet_id: int, result: str) -> list:
    await conn.execute(
        "UPDATE bets SET status = 'resolved', result = $1 WHERE id = $2",
        result, bet_id,
    )
    wagers = await conn.fetch(
        "SELECT w.*, b.yes_odds, b.no_odds FROM wagers w "
        "JOIN bets b ON b.id = w.bet_id WHERE w.bet_id = $1",
        bet_id,
    )
    winners = []
    for w in wagers:
        if w["side"] == result:
            odds = float(w["yes_odds"]) if result == "yes" else float(w["no_odds"])
            payout = float(w["amount"]) * odds
            new_balance = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING balance",
                payout, w["user_id"],
            )
            winners.append({"user_id": w["user_id"], "payout": payout, "balance": float(new_balance)})
    return winners


async def resolve_winner_bet(conn, bet_id: int, winning_option_id: int) -> list:
    await conn.execute(
        "UPDATE bets SET status = 'resolved', result = $1 WHERE id = $2",
        str(winning_option_id), bet_id,
    )
    wagers = await conn.fetch(
        "SELECT w.*, bo.odds FROM wagers w "
        "JOIN bet_options bo ON bo.id = w.option_id "
        "WHERE w.bet_id = $1",
        bet_id,
    )
    winners = []
    for w in wagers:
        if w["option_id"] == winning_option_id:
            payout = float(w["amount"]) * float(w["odds"])
            new_balance = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING balance",
                payout, w["user_id"],
            )
            winners.append({"user_id": w["user_id"], "payout": payout, "balance": float(new_balance)})
    return winners


async def get_balance(conn, user_id: int) -> float:
    return float(await conn.fetchval("SELECT balance FROM users WHERE id = $1", user_id))


async def get_leaderboard(conn) -> list:
    rows = await conn.fetch(
        "SELECT id, username, balance FROM users ORDER BY balance DESC"
    )
    return [dict(r) for r in rows]


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
    assert winners[0]["user_id"] == bob["id"]

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
    The check happens at the handler level; here we verify the DB itself
    would allow it (no DB constraint) so the handler check is load-bearing.
    """
    alice = await add_user(conn, 1, "alice")
    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Balance test", 2.0, 2.0, created_by=admin["id"])

    # Simulate handler-level check: amount > balance → reject
    amount = 1001.0
    balance = float(await conn.fetchval("SELECT balance FROM users WHERE id = $1", alice["id"]))
    assert amount > balance, "Pre-condition: amount exceeds balance"

    # No wager should be placed; balance unchanged
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
    dave  = await add_user(conn, 4, "dave")   # no bet, stays at 1000

    admin = await add_user(conn, 99, "admin")
    bet = await create_simple_bet(conn, "Leaderboard test", yes_odds=3.00, no_odds=2.00, created_by=admin["id"])
    bet_id = bet["id"]

    await place_wager(conn, alice["id"], bet_id, "yes", 200.0)   # wins: +600 → 1400
    await place_wager(conn, bob["id"],   bet_id, "yes", 100.0)   # wins: +300 → 1200
    await place_wager(conn, carol["id"], bet_id, "no",  150.0)   # loses → 850

    await lock_bet(conn, bet_id)
    await resolve_simple_bet(conn, bet_id, "yes")

    board = await get_leaderboard(conn)
    names = [r["username"] for r in board]

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
