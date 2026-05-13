import asyncpg
import os

_pool = None


async def _migrate(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS bet_type VARCHAR(10) NOT NULL DEFAULT 'simple'"
        )
        await conn.execute(
            "ALTER TABLE bets ALTER COLUMN yes_odds SET DEFAULT 0"
        )
        await conn.execute(
            "ALTER TABLE bets ALTER COLUMN no_odds SET DEFAULT 0"
        )
        await conn.execute(
            "ALTER TABLE bets ALTER COLUMN result TYPE TEXT"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bet_options (
                id       SERIAL PRIMARY KEY,
                bet_id   INTEGER REFERENCES bets(id) ON DELETE CASCADE,
                label    TEXT NOT NULL,
                odds     NUMERIC(5,2) NOT NULL,
                position INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute(
            "ALTER TABLE wagers ADD COLUMN IF NOT EXISTS option_id INTEGER REFERENCES bet_options(id)"
        )
        await conn.execute(
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS min_wager NUMERIC(6,2) NOT NULL DEFAULT 20"
        )
        await conn.execute(
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS max_wager NUMERIC(6,2) NOT NULL DEFAULT 200"
        )
        await conn.execute(
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS weight INTEGER NOT NULL DEFAULT 0"
        )
        await conn.execute(
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS opened_once BOOLEAN NOT NULL DEFAULT FALSE"
        )


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
        await _migrate(_pool)
    return _pool


async def get_or_create_user(telegram_id: int, username: str):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
    if row:
        return dict(row), False
    row = await pool.fetchrow(
        "INSERT INTO users (telegram_id, username) VALUES ($1, $2) RETURNING *",
        telegram_id, username,
    )
    return dict(row), True


async def get_user(telegram_id: int):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
    return dict(row) if row else None


async def set_admin(telegram_id: int):
    pool = await get_pool()
    await pool.execute("UPDATE users SET is_admin = TRUE WHERE telegram_id = $1", telegram_id)


async def get_active_bets():
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT b.*, u.username AS creator_name "
        "FROM bets b LEFT JOIN users u ON u.id = b.created_by "
        "WHERE b.status IN ('open', 'locked') ORDER BY b.weight DESC, b.id"
    )
    return [dict(r) for r in rows]


async def get_open_bets():
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM bets WHERE status = 'open' ORDER BY weight DESC, id")
    return [dict(r) for r in rows]


async def get_bet(bet_id: int):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM bets WHERE id = $1", bet_id)
    return dict(row) if row else None


async def get_bet_options(bet_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM bet_options WHERE bet_id = $1 ORDER BY position, id", bet_id
    )
    return [dict(r) for r in rows]


async def create_bet(title: str, yes_odds: float, no_odds: float, created_by: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, created_by, status) "
        "VALUES ($1, $2, $3, 'simple', $4, 'locked') RETURNING *",
        title, yes_odds, no_odds, created_by,
    )
    return dict(row)


async def create_winner_bet(title: str, options: list, created_by: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            bet = await conn.fetchrow(
                "INSERT INTO bets (title, yes_odds, no_odds, bet_type, created_by, status) "
                "VALUES ($1, 0, 0, 'winner', $2, 'locked') RETURNING *",
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


async def set_bet_weight(bet_id: int, weight: int) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE bets SET weight = $1 WHERE id = $2 AND status IN ('open', 'locked')",
        weight, bet_id,
    )
    return result == "UPDATE 1"


async def get_bet_wager_count(bet_id: int) -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet_id)


async def update_simple_bet_odds(bet_id: int, yes_odds: float, no_odds: float) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE bets SET yes_odds = $1, no_odds = $2 "
        "WHERE id = $3 AND status = 'locked' AND bet_type = 'simple'",
        yes_odds, no_odds, bet_id,
    )
    return result == "UPDATE 1"


async def update_winner_bet_option_odds(bet_id: int, option_odds: list) -> bool:
    """Update odds for winner bet options by position. option_odds: list of (position, new_odds)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            check = await conn.fetchval(
                "SELECT COUNT(*) FROM bets WHERE id = $1 AND status = 'locked' AND bet_type = 'winner'",
                bet_id,
            )
            if not check:
                return False
            for position, new_odds in option_odds:
                await conn.execute(
                    "UPDATE bet_options SET odds = $1 WHERE bet_id = $2 AND position = $3",
                    new_odds, bet_id, position,
                )
    return True


async def set_bet_wager_limits(bet_id: int, min_wager: float, max_wager: float):
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE bets SET min_wager = $1, max_wager = $2 WHERE id = $3 AND status = 'open'",
        min_wager, max_wager, bet_id,
    )
    return result == "UPDATE 1"


async def delete_bet(bet_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            wagers = await conn.fetch(
                "SELECT w.user_id, w.amount FROM wagers w "
                "JOIN bets b ON b.id = w.bet_id "
                "WHERE w.bet_id = $1 AND b.status = 'open'",
                bet_id,
            )
            for w in wagers:
                await conn.execute(
                    "UPDATE users SET balance = balance + $1 WHERE id = $2",
                    w["amount"], w["user_id"],
                )
            await conn.execute("DELETE FROM wagers WHERE bet_id = $1", bet_id)
            await conn.execute("DELETE FROM bet_options WHERE bet_id = $1", bet_id)
            result = await conn.execute(
                "DELETE FROM bets WHERE id = $1 AND status = 'open'", bet_id
            )
            return result == "DELETE 1"


async def lock_bet(bet_id: int):
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE bets SET status = 'locked' WHERE id = $1 AND status = 'open'", bet_id
    )
    return result == "UPDATE 1"


async def unlock_bet(bet_id: int):
    """Unlock a locked bet. Returns (success, is_first_open) where is_first_open is True
    if this is the first time this bet has ever been opened."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        WITH prev AS (SELECT opened_once FROM bets WHERE id = $1 AND status = 'locked')
        UPDATE bets SET status = 'open', opened_once = TRUE
        WHERE id = $1 AND status = 'locked'
        RETURNING (SELECT NOT opened_once FROM prev) AS is_first_open
        """,
        bet_id,
    )
    if row is None:
        return False, False
    return True, bool(row["is_first_open"])


async def resolve_bet(bet_id: int, result: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE bets SET status = 'resolved', result = $1 WHERE id = $2",
                result, bet_id,
            )
            wagers = await conn.fetch(
                "SELECT w.*, u.telegram_id, u.username, b.yes_odds, b.no_odds "
                "FROM wagers w "
                "JOIN users u ON u.id = w.user_id "
                "JOIN bets b ON b.id = w.bet_id "
                "WHERE w.bet_id = $1",
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
                    winners.append({
                        "username": w["username"] or f"user{w['telegram_id']}",
                        "profit": payout,
                        "balance": float(new_balance),
                    })
            return winners


async def resolve_winner_bet(bet_id: int, winning_option_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE bets SET status = 'resolved', result = $1 WHERE id = $2",
                str(winning_option_id), bet_id,
            )
            wagers = await conn.fetch(
                "SELECT w.*, u.telegram_id, u.username, bo.odds "
                "FROM wagers w "
                "JOIN users u ON u.id = w.user_id "
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
                    winners.append({
                        "username": w["username"] or f"user{w['telegram_id']}",
                        "profit": payout,
                        "balance": float(new_balance),
                    })
            return winners


async def get_user_wager(user_id: int, bet_id: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM wagers WHERE user_id = $1 AND bet_id = $2", user_id, bet_id
    )
    return dict(row) if row else None


async def place_wager(user_id: int, bet_id: int, side: str, amount: float, option_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT * FROM wagers WHERE user_id = $1 AND bet_id = $2", user_id, bet_id
            )
            refund = float(existing["amount"]) if existing else 0.0
            balance = await conn.fetchval(
                "UPDATE users SET balance = balance + $1 - $2 "
                "WHERE id = $3 AND balance + $1 - $2 >= 0 RETURNING balance",
                refund, amount, user_id,
            )
            if balance is None:
                return None, existing is not None
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
            return float(balance), existing is not None


async def cancel_wager(user_id: int, bet_id: int):
    """Cancel an open wager and refund 95% of the amount."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            wager = await conn.fetchrow(
                "SELECT w.amount FROM wagers w "
                "JOIN bets b ON b.id = w.bet_id "
                "WHERE w.user_id = $1 AND w.bet_id = $2 AND b.status = 'open'",
                user_id, bet_id,
            )
            if not wager:
                return None
            refund = round(float(wager["amount"]) * 0.95, 2)
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE id = $2",
                refund, user_id,
            )
            await conn.execute(
                "DELETE FROM wagers WHERE user_id = $1 AND bet_id = $2",
                user_id, bet_id,
            )
            return refund


async def get_user_wagers_with_bets(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT w.*, b.title, b.yes_odds, b.no_odds, b.status, b.result, b.bet_type, "
        "bo.label AS option_label, bo.odds AS option_odds "
        "FROM wagers w JOIN bets b ON b.id = w.bet_id "
        "LEFT JOIN bet_options bo ON bo.id = w.option_id "
        "WHERE w.user_id = $1 ORDER BY w.bet_id",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_user_open_wager_stats(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT w.amount, w.side, b.yes_odds, b.no_odds, b.bet_type, bo.odds AS option_odds "
        "FROM wagers w "
        "JOIN bets b ON b.id = w.bet_id "
        "LEFT JOIN bet_options bo ON bo.id = w.option_id "
        "WHERE w.user_id = $1 AND b.status IN ('open', 'locked')",
        user_id,
    )
    total_wagered = 0.0
    total_payout = 0.0
    for r in rows:
        amount = float(r["amount"])
        total_wagered += amount
        if r["bet_type"] == "winner":
            total_payout += amount * float(r["option_odds"])
        else:
            odds = float(r["yes_odds"]) if r["side"] == "yes" else float(r["no_odds"])
            total_payout += amount * odds
    return total_wagered, total_payout


async def get_all_telegram_ids() -> list[int]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM users")
    return [r["telegram_id"] for r in rows]


async def get_leaderboard():
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT telegram_id, username, balance FROM users ORDER BY balance DESC"
    )
    return [dict(r) for r in rows]


async def get_all_users_wager_stats():
    """Returns {telegram_id: (wager_count, potential_payout)} for open/locked bets."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT w.user_id, u.telegram_id, w.amount, w.side, b.yes_odds, b.no_odds, "
        "b.bet_type, bo.odds AS option_odds "
        "FROM wagers w "
        "JOIN users u ON u.id = w.user_id "
        "JOIN bets b ON b.id = w.bet_id "
        "LEFT JOIN bet_options bo ON bo.id = w.option_id "
        "WHERE b.status IN ('open', 'locked')"
    )
    stats: dict[int, list] = {}
    for r in rows:
        tid = r["telegram_id"]
        amount = float(r["amount"])
        if r["bet_type"] == "winner":
            payout = amount * float(r["option_odds"])
        else:
            odds = float(r["yes_odds"]) if r["side"] == "yes" else float(r["no_odds"])
            payout = amount * odds
        if tid not in stats:
            stats[tid] = [0, 0.0]
        stats[tid][0] += 1
        stats[tid][1] += payout
    return {tid: (v[0], v[1]) for tid, v in stats.items()}


async def has_resolved_bets():
    pool = await get_pool()
    val = await pool.fetchval("SELECT EXISTS(SELECT 1 FROM bets WHERE status = 'resolved')")
    return bool(val)


async def is_game_finished():
    pool = await get_pool()
    val = await pool.fetchval("SELECT value FROM settings WHERE key = 'game_finished'")
    return val == "true"


async def set_game_finished():
    pool = await get_pool()
    await pool.execute("UPDATE settings SET value = 'true' WHERE key = 'game_finished'")


async def get_resolved_bets_with_winners():
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT
            b.id AS bet_id, b.title, b.result, b.bet_type,
            b.yes_odds, b.no_odds,
            u.username,
            w.amount, w.side, w.option_id,
            bo.label AS option_label, bo.odds AS option_odds
        FROM bets b
        JOIN wagers w ON w.bet_id = b.id
        JOIN users u ON u.id = w.user_id
        LEFT JOIN bet_options bo ON bo.id = w.option_id
        WHERE b.status = 'resolved'
        ORDER BY b.id, u.username
    """)
    return [dict(r) for r in rows]


async def reset_game():
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "TRUNCATE TABLE wagers, bet_options, bets, users RESTART IDENTITY CASCADE"
            )
            await conn.execute("UPDATE settings SET value = 'false' WHERE key = 'game_finished'")
