"""Integration tests for admin command handlers (telegram stubbed via conftest)."""
import pytest
from fakes import FakeBot, FakeContext, make_update

import admin
import db
import texts


async def _mk_user(conn, tid=1, username="admin", is_admin=False, balance=1000):
    await conn.execute(
        "INSERT INTO users (telegram_id, username, balance, is_admin) VALUES ($1, $2, $3, $4)",
        tid, username, balance, is_admin,
    )
    return await db.get_user(tid)


async def _mk_bet(conn, status="open"):
    return dict(await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status) "
        "VALUES ('Kohde', 2.0, 2.0, 'simple', $1) RETURNING *",
        status,
    ))


# ── register ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_with_correct_password_grants_admin(conn, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    await _mk_user(conn, tid=1, username="alice", is_admin=False)
    ctx = FakeContext(args=["secret"])

    await admin.register(make_update("", user_id=1, username="alice"), ctx)

    assert (await db.get_user(1))["is_admin"] is True


@pytest.mark.asyncio
async def test_register_with_wrong_password_denied(conn, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    await _mk_user(conn, tid=1, username="alice", is_admin=False)
    ctx = FakeContext(args=["wrong"])

    await admin.register(make_update("", user_id=1, username="alice"), ctx)

    assert (await db.get_user(1))["is_admin"] is False


# ── lock ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_lock_locks_open_bet(conn):
    await _mk_user(conn, tid=1, is_admin=True)
    bet = await _mk_bet(conn, status="open")
    ctx = FakeContext(args=[str(bet["id"])])

    await admin.cmd_lock(make_update("", user_id=1), ctx)

    assert (await db.get_bet(bet["id"]))["status"] == "locked"


@pytest.mark.asyncio
async def test_cmd_lock_requires_admin(conn):
    await _mk_user(conn, tid=1, is_admin=False)
    bet = await _mk_bet(conn, status="open")
    ctx = FakeContext(args=[str(bet["id"])])

    await admin.cmd_lock(make_update("", user_id=1), ctx)

    assert (await db.get_bet(bet["id"]))["status"] == "open"  # unchanged


# ── resolve ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_resolve_pays_winner(conn):
    await _mk_user(conn, tid=1, is_admin=True)
    await conn.execute("INSERT INTO users (telegram_id, username, balance) VALUES (2, 'bob', 1000)")
    player = await db.get_user(2)
    bet = await _mk_bet(conn, status="open")
    await db.place_wager(player["id"], bet["id"], "yes", 200.0)  # bob → 800
    await db.lock_bet(bet["id"])
    ctx = FakeContext(args=[str(bet["id"]), "kyllä"])

    await admin.cmd_resolve(make_update("", user_id=1), ctx)

    assert (await db.get_bet(bet["id"]))["status"] == "resolved"
    # bob: 800 + 200 * 2.0 = 1200
    assert float((await db.get_user(2))["balance"]) == pytest.approx(1200.0)


@pytest.mark.asyncio
async def test_cmd_resolve_rejects_unlocked_bet(conn):
    await _mk_user(conn, tid=1, is_admin=True)
    bet = await _mk_bet(conn, status="open")  # never locked
    ctx = FakeContext(args=[str(bet["id"]), "kyllä"])

    await admin.cmd_resolve(make_update("", user_id=1), ctx)

    assert (await db.get_bet(bet["id"]))["status"] == "open"  # not resolved


# ── cmd_resolve type guard ─────────────────────────────────────────────────────

async def _mk_locked_winner_bet(conn):
    bet = dict(await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status) "
        "VALUES ('Voittajaveto', 0, 0, 'winner', 'locked') RETURNING *"
    ))
    bet["options"] = [dict(await conn.fetchrow(
        "INSERT INTO bet_options (bet_id, label, odds, position) "
        "VALUES ($1, 'A', 2.0, 0) RETURNING *",
        bet["id"],
    ))]
    return bet


@pytest.mark.asyncio
async def test_cmd_resolve_refuses_winner_bet(conn):
    """/ratkaise is the simple-bet path; the panel handles winner bets.

    Without the guard the bet resolved to 'yes', matching none of its 'opt'
    wagers: every stake lost, no winners, and revert could not undo it.
    """
    admin_user = await _mk_user(conn, tid=1, username="admin", is_admin=True)
    player = await _mk_user(conn, tid=2, username="alice")
    bet = await _mk_locked_winner_bet(conn)
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, option_id, amount) "
        "VALUES ($1, $2, 'opt', $3, 100)",
        player["id"], bet["id"], bet["options"][0]["id"],
    )
    update = make_update(f"/ratkaise {bet['id']} kyllä", user_id=1, username="admin")
    ctx = FakeContext(args=[str(bet["id"]), "kyllä"])

    await admin.cmd_resolve(update, ctx)

    unchanged = await db.get_bet(bet["id"])
    assert unchanged["status"] == "locked", "winner bet must not resolve via /ratkaise"
    assert unchanged["result"] is None
    assert any("voittajaveto" in r.lower() for r in update.message.replies), \
        f"admin should be told why, got: {update.message.replies}"
    assert admin_user["is_admin"] is True


@pytest.mark.asyncio
async def test_cmd_resolve_still_resolves_simple_bet(conn):
    """The guard must not block the supported path."""
    await _mk_user(conn, tid=1, username="admin", is_admin=True)
    player = await _mk_user(conn, tid=2, username="alice")
    bet = await _mk_bet(conn, status="locked")
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'yes', 100)",
        player["id"], bet["id"],
    )
    ctx = FakeContext(args=[str(bet["id"]), "kyllä"])

    await admin.cmd_resolve(make_update("", user_id=1, username="admin"), ctx)

    resolved = await db.get_bet(bet["id"])
    assert resolved["status"] == "resolved"
    assert resolved["result"] == "yes"
    # 1000 (never charged: wager inserted directly) + 100 × 2.0 payout
    assert float((await db.get_user(2))["balance"]) == pytest.approx(1200.0)


# ── handle resolution (username is not unique) ──────────────────────────────────

@pytest.mark.asyncio
async def test_add_balance_refuses_ambiguous_handle(conn):
    await _mk_user(conn, tid=1, username="admin", is_admin=True)
    # Two players share the handle "dupe".
    await _mk_user(conn, tid=2, username="dupe")
    await _mk_user(conn, tid=3, username="dupe")

    update = make_update("", user_id=1, username="admin")
    ctx = FakeContext(args=["dupe", "100"])
    await admin.cmd_add_balance(update, ctx)

    # Neither duplicate is credited; the admin is told to use a telegram_id.
    assert float((await db.get_user(2))["balance"]) == 1000.0
    assert float((await db.get_user(3))["balance"]) == 1000.0
    assert any("telegram-id" in r.lower() for r in update.message.replies)


@pytest.mark.asyncio
async def test_add_balance_by_telegram_id_is_unambiguous(conn):
    await _mk_user(conn, tid=1, username="admin", is_admin=True)
    await _mk_user(conn, tid=2, username="dupe")
    await _mk_user(conn, tid=3, username="dupe")

    ctx = FakeContext(args=["3", "100"])  # target by telegram_id
    await admin.cmd_add_balance(make_update("", user_id=1, username="admin"), ctx)

    assert float((await db.get_user(3))["balance"]) == 1100.0
    assert float((await db.get_user(2))["balance"]) == 1000.0


@pytest.mark.asyncio
async def test_add_balance_reports_real_new_balance(conn):
    await _mk_user(conn, tid=1, username="admin", is_admin=True)
    await _mk_user(conn, tid=2, username="bob")
    update = make_update("", user_id=1, username="admin")
    ctx = FakeContext(args=["bob", "250"])

    await admin.cmd_add_balance(update, ctx)

    assert float((await db.get_user(2))["balance"]) == 1250.0
    assert any("1250" in r for r in update.message.replies)


# ── /admin brute-force throttle ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_admin_attempts():
    admin._admin_attempts.clear()
    yield
    admin._admin_attempts.clear()


@pytest.mark.asyncio
async def test_admin_locks_out_after_repeated_failures(conn, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    await _mk_user(conn, tid=1, username="attacker", is_admin=False)

    for _ in range(admin._ADMIN_MAX_ATTEMPTS):
        ctx = FakeContext(args=["wrong"])
        await admin.register(make_update("", user_id=1, username="attacker"), ctx)

    # Even the CORRECT password is refused once locked out.
    ctx = FakeContext(args=["secret"])
    await admin.register(make_update("", user_id=1, username="attacker"), ctx)
    assert (await db.get_user(1))["is_admin"] is False


@pytest.mark.asyncio
async def test_admin_deletes_the_password_message(conn, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    await _mk_user(conn, tid=1, username="alice", is_admin=False)

    bot = FakeBot()
    update = make_update("/admin secret", user_id=1, username="alice")
    update.get_bot = lambda: bot
    ctx = FakeContext(bot, args=["secret"])

    await admin.register(update, ctx)

    assert bot.deleted, "the /admin message must be deleted so the password does not linger"
    assert (await db.get_user(1))["is_admin"] is True


# ── admin_callback dispatcher (ack wrapper + a money path) ──────────────────────

@pytest.mark.asyncio
async def test_admin_callback_delete_resolved_bet_is_refused_and_acked(conn):
    """adm:delete on a resolved bet must not destroy its wagers, and the callback
    must still be answered (the finally in admin_callback) so the button stops
    spinning."""
    from fakes import FakeQuery, make_callback_update

    admin_user = await _mk_user(conn, tid=1, username="admin", is_admin=True)
    player = await _mk_user(conn, tid=2, username="alice")
    bet = dict(await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status, result) "
        "VALUES ('Done', 2.0, 2.0, 'simple', 'resolved', 'yes') RETURNING *"
    ))
    await conn.execute(
        "INSERT INTO wagers (user_id, bet_id, side, amount) VALUES ($1, $2, 'yes', 100)",
        player["id"], bet["id"],
    )

    query = FakeQuery(f"adm:delete:{bet['id']}", user_id=1)
    await admin.admin_callback(make_callback_update(query), FakeContext(query.get_bot()))

    # Wager survives; the callback was answered exactly (at least once).
    assert await conn.fetchval("SELECT COUNT(*) FROM wagers WHERE bet_id = $1", bet["id"]) == 1
    assert query.answers, "the callback must be answered so the button stops spinning"
    assert admin_user["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_callback_non_admin_gets_alert(conn):
    from fakes import FakeQuery, make_callback_update

    await _mk_user(conn, tid=1, username="alice", is_admin=False)
    query = FakeQuery("adm:panel", user_id=1)
    await admin.admin_callback(make_callback_update(query), FakeContext(query.get_bot()))

    assert any(a["show_alert"] and a["text"] == texts.NOT_ADMIN for a in query.answers)
