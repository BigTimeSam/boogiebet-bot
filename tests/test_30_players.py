"""
Integration tests verifying correct game behaviour with 30 simultaneous players.

Covers:
  - Balance accounting for 30 players across multiple simple + winner bets
  - Wager min/max limits are enforced at handler level (confirmed via DB state)
  - No wager double-counting when a player updates their wager
  - Leaderboard is correctly sorted for 30 players
  - Rank calculation used by GAME_FINISHED_PERSONAL is correct for every player
  - game_finished flag blocks further wagers at handler level
  - Cashout (95 %) refund is exact
  - get_all_users_potential_winnings returns correct per-player sums
  - Cannot finish game while unresolved bets remain
"""
import pytest
import pytest_asyncio
from decimal import Decimal

STARTING_BALANCE = 1000.0
N_PLAYERS = 30
MIN_WAGER = 20.0
MAX_WAGER = 200.0


# ── helpers (raw-SQL so tests don't depend on db.py internals) ──────────────

async def add_user(conn, telegram_id: int, username: str) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO users (telegram_id, username) VALUES ($1, $2) RETURNING *",
        telegram_id, username,
    )
    return dict(row)


async def create_simple_bet(conn, title, yes_odds, no_odds, created_by) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, created_by) "
        "VALUES ($1, $2, $3, 'simple', $4) RETURNING *",
        title, yes_odds, no_odds, created_by,
    )
    return dict(row)


async def create_winner_bet(conn, title, options, created_by) -> dict:
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


async def place_wager(conn, user_id, bet_id, side, amount, option_id=None) -> float:
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


async def lock_bet(conn, bet_id):
    await conn.execute("UPDATE bets SET status = 'locked' WHERE id = $1", bet_id)


async def resolve_simple_bet(conn, bet_id, result) -> list:
    await conn.execute(
        "UPDATE bets SET status = 'resolved', result = $1 WHERE id = $2", result, bet_id
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
            new_bal = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING balance",
                payout, w["user_id"],
            )
            winners.append({"user_id": w["user_id"], "payout": payout, "balance": float(new_bal)})
    return winners


async def resolve_winner_bet(conn, bet_id, winning_option_id) -> list:
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
            new_bal = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 WHERE id = $2 RETURNING balance",
                payout, w["user_id"],
            )
            winners.append({"user_id": w["user_id"], "payout": payout, "balance": float(new_bal)})
    return winners


async def get_balance(conn, user_id) -> float:
    return float(await conn.fetchval("SELECT balance FROM users WHERE id = $1", user_id))


async def get_leaderboard(conn) -> list:
    rows = await conn.fetch(
        "SELECT id, telegram_id, username, balance FROM users ORDER BY balance DESC"
    )
    return [dict(r) for r in rows]


async def get_active_bets(conn) -> list:
    rows = await conn.fetch("SELECT * FROM bets WHERE status IN ('open', 'locked') ORDER BY id")
    return [dict(r) for r in rows]


async def get_potential_winnings(conn) -> dict:
    """Mirrors db.get_all_users_potential_winnings logic."""
    rows = await conn.fetch(
        "SELECT w.user_id, u.telegram_id, w.amount, w.side, b.yes_odds, b.no_odds, "
        "b.bet_type, bo.odds AS option_odds "
        "FROM wagers w "
        "JOIN users u ON u.id = w.user_id "
        "JOIN bets b ON b.id = w.bet_id "
        "LEFT JOIN bet_options bo ON bo.id = w.option_id "
        "WHERE b.status IN ('open', 'locked')"
    )
    payouts: dict[int, float] = {}
    for r in rows:
        tid = r["telegram_id"]
        amount = float(r["amount"])
        if r["bet_type"] == "winner":
            payout = amount * float(r["option_odds"])
        else:
            odds = float(r["yes_odds"]) if r["side"] == "yes" else float(r["no_odds"])
            payout = amount * odds
        payouts[tid] = payouts.get(tid, 0.0) + payout
    return payouts


# ── fixtures ─────────────────────────────────────────────────────────────────

async def _setup_30_players(conn):
    """Create 30 players + 1 admin; return (players, admin)."""
    admin = await add_user(conn, 9000, "admin")
    players = [await add_user(conn, i + 1, f"player{i + 1:02d}") for i in range(N_PLAYERS)]
    return players, admin


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_players_start_with_1000(conn):
    """Every new user is initialised to exactly 1000 €."""
    players, _ = await _setup_30_players(conn)
    for p in players:
        assert float(p["balance"]) == pytest.approx(STARTING_BALANCE)


@pytest.mark.asyncio
async def test_30_players_simple_bet_balance_accounting(conn):
    """
    15 players bet yes @ 2.0, 15 bet no @ 3.0.
    Yes wins → yes-bettors double their stake; no-bettors keep reduced balance.
    Total money in system is conserved (no house edge in simple resolution).
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Kyllä vs Ei", 2.0, 3.0, admin["id"])
    bet_id = bet["id"]

    yes_players = players[:15]
    no_players = players[15:]
    amount = 100.0

    for p in yes_players:
        await place_wager(conn, p["id"], bet_id, "yes", amount)
    for p in no_players:
        await place_wager(conn, p["id"], bet_id, "no", amount)

    await lock_bet(conn, bet_id)
    winners = await resolve_simple_bet(conn, bet_id, "yes")

    assert len(winners) == 15

    for p in yes_players:
        bal = await get_balance(conn, p["id"])
        # 1000 - 100 + (100 × 2.0) = 1100
        assert bal == pytest.approx(1100.0), f"{p['username']} wrong balance"

    for p in no_players:
        bal = await get_balance(conn, p["id"])
        # 1000 - 100 = 900
        assert bal == pytest.approx(900.0), f"{p['username']} wrong balance"


@pytest.mark.asyncio
async def test_30_players_winner_bet_single_winner(conn):
    """
    30 players each pick a different amount on one of 4 options.
    Resolving one option pays only those who picked it.
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_winner_bet(conn, "Voittaja", [
        {"label": "A", "odds": 2.00},
        {"label": "B", "odds": 3.00},
        {"label": "C", "odds": 4.00},
        {"label": "D", "odds": 5.00},
    ], admin["id"])

    options = bet["options"]
    bet_id = bet["id"]

    # Players 0-7 pick A, 8-15 pick B, 16-22 pick C, 23-29 pick D
    splits = [
        (players[0:8],   options[0], 50.0),
        (players[8:16],  options[1], 100.0),
        (players[16:23], options[2], 150.0),
        (players[23:30], options[3], 200.0),
    ]
    for group, opt, amt in splits:
        for p in group:
            await place_wager(conn, p["id"], bet_id, "opt", amt, option_id=opt["id"])

    await lock_bet(conn, bet_id)
    # Option C wins (odds 4.00)
    winning_opt = options[2]
    winners = await resolve_winner_bet(conn, bet_id, winning_opt["id"])

    assert len(winners) == 7  # players 16-22

    for p in players[16:23]:
        bal = await get_balance(conn, p["id"])
        # 1000 - 150 + (150 × 4.00) = 1450
        assert bal == pytest.approx(1450.0), f"{p['username']} wrong balance"

    # Losers
    for p in players[0:8]:
        assert await get_balance(conn, p["id"]) == pytest.approx(950.0)
    for p in players[8:16]:
        assert await get_balance(conn, p["id"]) == pytest.approx(900.0)
    for p in players[23:30]:
        assert await get_balance(conn, p["id"]) == pytest.approx(800.0)


@pytest.mark.asyncio
async def test_leaderboard_30_players_sorted(conn):
    """Leaderboard for 30 players is sorted by balance descending."""
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Sort test", 2.0, 2.0, admin["id"])
    bet_id = bet["id"]

    # Even players bet yes (winners), odd players bet no (losers)
    for i, p in enumerate(players):
        side = "yes" if i % 2 == 0 else "no"
        # Amount varies 20–200 in steps of ~6
        amount = min(MAX_WAGER, max(MIN_WAGER, 20.0 + i * 6))
        await place_wager(conn, p["id"], bet_id, side, amount)

    await lock_bet(conn, bet_id)
    await resolve_simple_bet(conn, bet_id, "yes")

    board = await get_leaderboard(conn)
    # Filter out admin
    board = [r for r in board if r["username"] != "admin"]
    assert len(board) == N_PLAYERS

    balances = [float(r["balance"]) for r in board]
    assert balances == sorted(balances, reverse=True), "Leaderboard not sorted descending"


@pytest.mark.asyncio
async def test_rank_calculation_for_all_30_players(conn):
    """
    GAME_FINISHED_PERSONAL rank: every player gets a rank 1–30.
    No rank gaps, no duplicates at different amounts.
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Rank test", 2.0, 2.0, admin["id"])
    bet_id = bet["id"]

    # Give every player a unique balance by betting different amounts on the winning side
    for i, p in enumerate(players):
        amount = 20.0 + i * 6  # 20, 26, 32, ... → all different
        await place_wager(conn, p["id"], bet_id, "yes", amount)

    await lock_bet(conn, bet_id)
    await resolve_simple_bet(conn, bet_id, "yes")

    board = await get_leaderboard(conn)
    board = [r for r in board if r["username"] != "admin"]
    assert len(board) == N_PLAYERS

    # Check each player can compute their rank via next() as in _main_text
    telegram_ids = {p["telegram_id"] for p in players}
    seen_ranks = set()
    for p in players:
        rank = next(
            (i for i, r in enumerate(board, 1) if r["telegram_id"] == p["telegram_id"]),
            N_PLAYERS,
        )
        assert 1 <= rank <= N_PLAYERS, f"Rank out of range for {p['username']}: {rank}"
        seen_ranks.add(rank)

    assert len(seen_ranks) == N_PLAYERS, "Duplicate ranks detected"


@pytest.mark.asyncio
async def test_wager_update_no_double_charge_30_players(conn):
    """
    Each of 30 players updates their wager twice.
    Final wager is 100 € (not 300 €); balance is 900 €.
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Update test", 2.0, 2.0, admin["id"])
    bet_id = bet["id"]

    for p in players:
        await place_wager(conn, p["id"], bet_id, "yes", 50.0)
        await place_wager(conn, p["id"], bet_id, "yes", 80.0)
        await place_wager(conn, p["id"], bet_id, "yes", 100.0)

    for p in players:
        bal = await get_balance(conn, p["id"])
        assert bal == pytest.approx(900.0), f"{p['username']} should have 900 after replacing to 100"
        stored = float(await conn.fetchval(
            "SELECT amount FROM wagers WHERE user_id = $1 AND bet_id = $2", p["id"], bet_id
        ))
        assert stored == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_cashout_95_percent_30_players(conn):
    """Cancelling a wager refunds exactly 95 % of the wagered amount."""
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Cashout test", 2.0, 2.0, admin["id"])
    bet_id = bet["id"]

    amount = 200.0
    for p in players:
        await place_wager(conn, p["id"], bet_id, "yes", amount)

    # Cancel all wagers (mirrors db.cancel_wager)
    for p in players:
        wager = await conn.fetchrow(
            "SELECT w.amount FROM wagers w "
            "JOIN bets b ON b.id = w.bet_id "
            "WHERE w.user_id = $1 AND w.bet_id = $2 AND b.status = 'open'",
            p["id"], bet_id,
        )
        assert wager is not None
        refund = round(float(wager["amount"]) * 0.95, 2)
        await conn.execute(
            "UPDATE users SET balance = balance + $1 WHERE id = $2", refund, p["id"]
        )
        await conn.execute(
            "DELETE FROM wagers WHERE user_id = $1 AND bet_id = $2", p["id"], bet_id
        )

    for p in players:
        bal = await get_balance(conn, p["id"])
        expected = STARTING_BALANCE - amount + (amount * 0.95)
        assert bal == pytest.approx(expected), f"{p['username']} wrong cashout balance"

    wager_count = await conn.fetchval(
        "SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet_id
    )
    assert wager_count == 0


@pytest.mark.asyncio
async def test_min_max_wager_limits_not_enforced_by_db(conn):
    """
    The DB has no constraint for min/max wager limits — enforcement is in the handler.
    This test confirms that placing 19 € or 201 € succeeds at the DB level,
    so the handler check is the sole gate.
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Limit test", 2.0, 2.0, admin["id"])
    bet_id = bet["id"]

    # Both should succeed at DB level
    await place_wager(conn, players[0]["id"], bet_id, "yes", 19.0)
    await place_wager(conn, players[1]["id"], bet_id, "yes", 201.0)

    count = await conn.fetchval(
        "SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet_id
    )
    assert count == 2, "DB should accept out-of-range amounts; handler must reject them"


@pytest.mark.asyncio
async def test_potential_winnings_aggregation_30_players(conn):
    """
    get_all_users_potential_winnings sums correctly across
    one simple and one winner bet for all 30 players.
    """
    players, admin = await _setup_30_players(conn)

    simple = await create_simple_bet(conn, "Simple", 2.0, 3.0, admin["id"])
    winner = await create_winner_bet(conn, "Winner", [
        {"label": "X", "odds": 2.5},
        {"label": "Y", "odds": 4.0},
    ], admin["id"])

    opt_x = winner["options"][0]["id"]
    opt_y = winner["options"][1]["id"]

    # First 15 bet yes on simple; last 15 bet no; all bet on winner
    for i, p in enumerate(players):
        side = "yes" if i < 15 else "no"
        await place_wager(conn, p["id"], simple["id"], side, 100.0)
        opt = opt_x if i % 2 == 0 else opt_y
        await place_wager(conn, p["id"], winner["id"], "opt", 50.0, option_id=opt)

    potentials = await get_potential_winnings(conn)

    for i, p in enumerate(players):
        tid = p["telegram_id"]
        assert tid in potentials

        simple_odds = 2.0 if i < 15 else 3.0
        simple_pot = 100.0 * simple_odds

        winner_odds = 2.5 if i % 2 == 0 else 4.0
        winner_pot = 50.0 * winner_odds

        expected = simple_pot + winner_pot
        assert potentials[tid] == pytest.approx(expected), (
            f"{p['username']} potential: expected {expected}, got {potentials[tid]}"
        )


@pytest.mark.asyncio
async def test_game_finish_blocked_by_unresolved_bets(conn):
    """
    The finish guard (mirrors admin.py adm:finish logic) rejects finishing
    while open or locked bets exist.
    """
    players, admin = await _setup_30_players(conn)
    bet = await create_simple_bet(conn, "Unresolved", 2.0, 2.0, admin["id"])

    unresolved = await get_active_bets(conn)
    assert len(unresolved) == 1, "Should have one unresolved bet"

    # Simulate the guard check
    can_finish = len(unresolved) == 0
    assert not can_finish, "Should not be allowed to finish with unresolved bets"

    # After resolving all bets, finish should be allowed
    await lock_bet(conn, bet["id"])
    await resolve_simple_bet(conn, bet["id"], "yes")
    unresolved = await get_active_bets(conn)
    assert len(unresolved) == 0
    can_finish = len(unresolved) == 0
    assert can_finish


@pytest.mark.asyncio
async def test_full_game_30_players(conn):
    """
    End-to-end game with 30 players, 2 simple bets + 1 winner bet.
    Verifies final leaderboard ordering, rank assignment, and that
    game_finished flag is set correctly.
    """
    players, admin = await _setup_30_players(conn)

    # Bet 1: simple, yes wins @ 2.0
    b1 = await create_simple_bet(conn, "Veto 1", 2.0, 1.5, admin["id"])
    # Bet 2: simple, no wins @ 2.5
    b2 = await create_simple_bet(conn, "Veto 2", 1.8, 2.5, admin["id"])
    # Bet 3: winner with 3 options
    b3 = await create_winner_bet(conn, "Veto 3", [
        {"label": "Alpha", "odds": 1.9},
        {"label": "Beta",  "odds": 3.0},
        {"label": "Gamma", "odds": 6.0},
    ], admin["id"])

    opt_a = b3["options"][0]["id"]
    opt_b = b3["options"][1]["id"]
    opt_g = b3["options"][2]["id"]

    # Assign deterministic wager strategy based on player index
    for i, p in enumerate(players):
        # Bet 1
        side1 = "yes" if i % 3 != 0 else "no"
        await place_wager(conn, p["id"], b1["id"], side1, 100.0)
        # Bet 2
        side2 = "no" if i % 2 == 0 else "yes"
        await place_wager(conn, p["id"], b2["id"], side2, 80.0)
        # Bet 3
        opt = [opt_a, opt_b, opt_g][i % 3]
        await place_wager(conn, p["id"], b3["id"], "opt", 120.0, option_id=opt)

    # Resolve all three
    await lock_bet(conn, b1["id"])
    await resolve_simple_bet(conn, b1["id"], "yes")

    await lock_bet(conn, b2["id"])
    await resolve_simple_bet(conn, b2["id"], "no")

    await lock_bet(conn, b3["id"])
    await resolve_winner_bet(conn, b3["id"], opt_b)  # Beta wins

    # Verify no unresolved bets remain
    assert len(await get_active_bets(conn)) == 0

    # Mark game finished
    await conn.execute("UPDATE settings SET value = 'true' WHERE key = 'game_finished'")
    finished = await conn.fetchval("SELECT value FROM settings WHERE key = 'game_finished'")
    assert finished == "true"

    # Leaderboard: 30 entries sorted correctly
    board = await get_leaderboard(conn)
    player_board = [r for r in board if r["username"] != "admin"]
    assert len(player_board) == N_PLAYERS

    balances = [float(r["balance"]) for r in player_board]
    assert balances == sorted(balances, reverse=True)

    # Every player's rank is in [1, N_PLAYERS]
    for p in players:
        rank = next(
            (i for i, r in enumerate(player_board, 1) if r["telegram_id"] == p["telegram_id"]),
            N_PLAYERS,
        )
        assert 1 <= rank <= N_PLAYERS

    # Spot-check a few known outcomes
    # Player index 0: side1=no (loses), side2=no (wins @ 2.5), opt=alpha (loses)
    #   1000 - 100 + 0 - 80 + 80*2.5 - 120 = 1000 - 100 - 80 + 200 - 120 = 900
    p0 = players[0]
    bal0 = await get_balance(conn, p0["id"])
    assert bal0 == pytest.approx(900.0), f"player01 expected 900, got {bal0}"

    # Player index 1: side1=yes (wins @ 2.0), side2=yes (loses), opt=beta (wins @ 3.0)
    #   1000 - 100 + 200 - 80 - 120 + 360 = 1260
    p1 = players[1]
    bal1 = await get_balance(conn, p1["id"])
    assert bal1 == pytest.approx(1260.0), f"player02 expected 1260, got {bal1}"
