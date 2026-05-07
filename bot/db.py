import asyncpg
import os

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
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
    """Return open and locked bets (everything visible to users)."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT b.*, u.username AS creator_name "
        "FROM bets b LEFT JOIN users u ON u.id = b.created_by "
        "WHERE b.status IN ('open', 'locked') ORDER BY b.id"
    )
    return [dict(r) for r in rows]


async def get_open_bets():
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM bets WHERE status = 'open' ORDER BY id")
    return [dict(r) for r in rows]


async def get_bet(bet_id: int):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM bets WHERE id = $1", bet_id)
    return dict(row) if row else None


async def create_bet(title: str, yes_odds: float, no_odds: float, created_by: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, created_by) VALUES ($1, $2, $3, $4) RETURNING *",
        title, yes_odds, no_odds, created_by,
    )
    return dict(row)


async def delete_bet(bet_id: int):
    """Delete an open bet and refund all wagers on it."""
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


async def get_user_wager(user_id: int, bet_id: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM wagers WHERE user_id = $1 AND bet_id = $2", user_id, bet_id
    )
    return dict(row) if row else None


async def place_wager(user_id: int, bet_id: int, side: str, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
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
                    "UPDATE wagers SET side = $1, amount = $2 WHERE user_id = $3 AND bet_id = $4",
                    side, amount, user_id, bet_id,
                )
            else:
                await conn.execute(
                    "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, $3, $4)",
                    user_id, bet_id, side, amount,
                )
            return float(balance), existing is not None


async def get_user_wagers_with_bets(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT w.*, b.title, b.yes_odds, b.no_odds, b.status, b.result "
        "FROM wagers w JOIN bets b ON b.id = w.bet_id "
        "WHERE w.user_id = $1 ORDER BY w.bet_id",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_leaderboard():
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT telegram_id, username, balance FROM users ORDER BY balance DESC"
    )
    return [dict(r) for r in rows]


async def is_game_finished():
    pool = await get_pool()
    val = await pool.fetchval("SELECT value FROM settings WHERE key = 'game_finished'")
    return val == "true"


async def set_game_finished():
    pool = await get_pool()
    await pool.execute("UPDATE settings SET value = 'true' WHERE key = 'game_finished'")
