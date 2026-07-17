"""Integration tests for the wager-placement handlers.

telegram is stubbed (see conftest), so we drive the handlers with fake Update /
Context / Bot objects and assert on the resulting database state and the
messages the handler tried to send. These cover the validation logic that the
two wager entry points share.
"""
import pytest
from fakes import FakeBot, FakeContext, FakeQuery, make_callback_update, make_update

import db
import handlers
import texts
from handlers import AWAITING_AMOUNT

# ── seed helpers ───────────────────────────────────────────────────────────────

async def _mk_user(conn, tid=1, username="alice", balance=1000):
    await conn.execute(
        "INSERT INTO users (telegram_id, username, balance) VALUES ($1, $2, $3)",
        tid, username, balance,
    )
    return await db.get_user(tid)


async def _mk_open_simple_bet(conn, yes=2.0, no=2.0, min_w=20, max_w=200):
    row = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status, min_wager, max_wager) "
        "VALUES ('Testikohde', $1, $2, 'simple', 'open', $3, $4) RETURNING *",
        yes, no, min_w, max_w,
    )
    return dict(row)


async def _mk_open_winner_bet(conn, options, min_w=20, max_w=200):
    bet = dict(await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status, min_wager, max_wager) "
        "VALUES ('Voittajaveto', 0, 0, 'winner', 'open', $1, $2) RETURNING *",
        min_w, max_w,
    ))
    bet["options"] = []
    for i, (label, odds) in enumerate(options):
        bet["options"].append(dict(await conn.fetchrow(
            "INSERT INTO bet_options (bet_id, label, odds, position) VALUES ($1, $2, $3, $4) RETURNING *",
            bet["id"], label, odds, i,
        )))
    return bet


# ── _process_wager (command / button flow) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_process_wager_happy_path(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    bot = FakeBot()

    rv = await handlers._process_wager(FakeContext(bot), 1, user, bet["id"], "yes", 100.0)

    assert rv is False  # success → caller stops
    w = await db.get_user_wager(user["id"], bet["id"])
    assert w is not None and float(w["amount"]) == 100.0
    assert float((await db.get_user(1))["balance"]) == 900.0
    assert bot.sent, "a confirmation message should have been sent"


@pytest.mark.asyncio
async def test_process_wager_below_min_rejected(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn, min_w=20, max_w=200)

    rv = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 10.0)

    assert rv is True  # validation failed → caller keeps awaiting
    assert await db.get_user_wager(user["id"], bet["id"]) is None
    assert float((await db.get_user(1))["balance"]) == 1000.0


@pytest.mark.asyncio
async def test_process_wager_above_max_rejected(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn, max_w=200)

    rv = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 250.0)

    assert rv is True
    assert await db.get_user_wager(user["id"], bet["id"]) is None


@pytest.mark.asyncio
async def test_process_wager_insufficient_balance_rejected(conn):
    user = await _mk_user(conn, balance=50)
    bet = await _mk_open_simple_bet(conn, min_w=20, max_w=200)

    rv = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)

    assert rv is True
    assert await db.get_user_wager(user["id"], bet["id"]) is None
    assert float((await db.get_user(1))["balance"]) == 50.0


@pytest.mark.asyncio
async def test_process_wager_locked_bet_rejected(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await conn.execute("UPDATE bets SET status = 'locked' WHERE id = $1", bet["id"])

    rv = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)

    assert rv is False  # locked → caller stops
    assert await db.get_user_wager(user["id"], bet["id"]) is None


@pytest.mark.asyncio
async def test_process_wager_accumulates_then_caps_at_max(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn, max_w=200)

    # First 150 succeeds.
    rv1 = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 150.0)
    assert rv1 is False
    # Adding 100 would total 250 > max 200 → rejected, original 150 stays.
    user = await db.get_user(1)
    rv2 = await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)
    assert rv2 is True
    assert float((await db.get_user_wager(user["id"], bet["id"]))["amount"]) == 150.0


# ── _handle_amount (interactive free-text flow) ─────────────────────────────────

def _pending(bet_id, side="yes", option_id=None, min_w=20, max_w=200):
    return {AWAITING_AMOUNT: {
        "bet_id": bet_id, "side": side, "option_id": option_id,
        "min_wager": min_w, "max_wager": max_w,
    }}


@pytest.mark.asyncio
async def test_handle_amount_places_wager_and_clears_state(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    ctx = FakeContext(FakeBot(), user_data=_pending(bet["id"]))

    await handlers._handle_amount(make_update("100"), ctx)

    w = await db.get_user_wager(user["id"], bet["id"])
    assert w is not None and float(w["amount"]) == 100.0
    assert AWAITING_AMOUNT not in ctx.user_data  # state cleared on success


@pytest.mark.asyncio
async def test_handle_amount_accepts_comma_decimal(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    ctx = FakeContext(FakeBot(), user_data=_pending(bet["id"]))

    await handlers._handle_amount(make_update("100,00"), ctx)

    w = await db.get_user_wager(user["id"], bet["id"])
    assert w is not None and float(w["amount"]) == 100.0


@pytest.mark.asyncio
async def test_handle_amount_rejects_fractional_and_keeps_state(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    ctx = FakeContext(FakeBot(), user_data=_pending(bet["id"]))

    await handlers._handle_amount(make_update("50.5"), ctx)

    assert await db.get_user_wager(user["id"], bet["id"]) is None
    assert AWAITING_AMOUNT in ctx.user_data  # retained so the user can retry


# ── bet_side_callback (simple bet button) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_bet_side_callback_sets_pending_amount_state(conn):
    await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    ctx = FakeContext()

    q = FakeQuery(f"bet:{bet['id']}:yes", user_id=1)
    await handlers.bet_side_callback(make_callback_update(q), ctx)

    pending = ctx.user_data.get(AWAITING_AMOUNT)
    assert pending is not None
    assert pending["bet_id"] == bet["id"] and pending["side"] == "yes"


@pytest.mark.asyncio
async def test_bet_side_callback_rejects_opposite_side(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await db.place_wager(user["id"], bet["id"], "yes", 100.0)
    ctx = FakeContext()

    q = FakeQuery(f"bet:{bet['id']}:no", user_id=1)
    await handlers.bet_side_callback(make_callback_update(q), ctx)

    assert any(a["show_alert"] for a in q.answers)  # rejected with an alert
    assert AWAITING_AMOUNT not in ctx.user_data
    assert (await db.get_user_wager(user["id"], bet["id"]))["side"] == "yes"


# ── winner_opt_callback + amount (end-to-end winner placement) ──────────────────

@pytest.mark.asyncio
async def test_winner_option_placement_end_to_end(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_winner_bet(conn, [("Tiimi A", 2.0), ("Tiimi B", 3.0)])
    opt_a = bet["options"][0]["id"]
    ctx = FakeContext()

    # Click option A → enters amount-entry, remembering the option.
    q = FakeQuery(f"opt:{bet['id']}:{opt_a}", user_id=1)
    await handlers.winner_opt_callback(make_callback_update(q), ctx)
    assert ctx.user_data[AWAITING_AMOUNT]["option_id"] == opt_a
    assert ctx.user_data[AWAITING_AMOUNT]["side"] == "opt"

    # Enter the amount → wager placed on that option.
    await handlers._handle_amount(make_update("100"), ctx)
    w = await db.get_user_wager(user["id"], bet["id"])
    assert w is not None
    assert float(w["amount"]) == 100.0
    assert w["option_id"] == opt_a
    assert w["side"] == "opt"
    assert float((await db.get_user(1))["balance"]) == 900.0


# ── cancel_wager_callback (cashout) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cashout_callback_refunds_95_percent(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await db.place_wager(user["id"], bet["id"], "yes", 200.0)  # balance → 800
    ctx = FakeContext()

    q = FakeQuery(f"wager:cancel:{bet['id']}", user_id=1)
    await handlers.cancel_wager_callback(make_callback_update(q), ctx)

    assert await db.get_user_wager(user["id"], bet["id"]) is None
    # 800 + 200 * 0.95 = 990
    assert float((await db.get_user(1))["balance"]) == pytest.approx(990.0)


@pytest.mark.asyncio
async def test_cashout_callback_rejects_locked_bet(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await db.place_wager(user["id"], bet["id"], "yes", 200.0)
    await conn.execute("UPDATE bets SET status = 'locked' WHERE id = $1", bet["id"])
    ctx = FakeContext()

    q = FakeQuery(f"wager:cancel:{bet['id']}", user_id=1)
    await handlers.cancel_wager_callback(make_callback_update(q), ctx)

    assert await db.get_user_wager(user["id"], bet["id"]) is not None  # unchanged
    assert any(a["show_alert"] for a in q.answers)


# ── cmd_place_bet input hardening ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_place_bet_rejects_nan_amount(conn):
    """The /vetoa path must reject non-finite input.

    NaN passes every limit check (all comparisons against it are False) and
    Postgres accepts it (NaN >= 0 is TRUE), so it used to land in the balance
    and corrupt it permanently — /lisaasaldo could not repair it, and NaN sorts
    highest, parking the player at the top of the leaderboard.
    """
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)

    for bad in ("nan", "inf", "1e400"):
        ctx = FakeContext(FakeBot(), args=[str(bet["id"]), "kyllä", bad])
        await handlers.cmd_place_bet(make_update(f"/vetoa {bet['id']} kyllä {bad}"), ctx)

        assert await db.get_user_wager(user["id"], bet["id"]) is None, bad
        balance = float((await db.get_user(1))["balance"])
        assert balance == 1000.0, f"{bad} must not touch the balance"

    corrupted = await conn.fetchval(
        "SELECT COUNT(*) FROM users WHERE balance <> balance"  # NaN <> NaN is TRUE
    )
    assert corrupted == 0


@pytest.mark.asyncio
async def test_cmd_place_bet_rejects_fractional_amount(conn):
    """/vetoa used to accept fractional euros while the button flow required
    whole ones; both now share parse_wager_amount()."""
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)

    ctx = FakeContext(FakeBot(), args=[str(bet["id"]), "kyllä", "50.5"])
    await handlers.cmd_place_bet(make_update(f"/vetoa {bet['id']} kyllä 50.5"), ctx)

    assert await db.get_user_wager(user["id"], bet["id"]) is None
    assert float((await db.get_user(1))["balance"]) == 1000.0


@pytest.mark.asyncio
async def test_cmd_place_bet_still_accepts_whole_euros(conn):
    """The hardening must not break the supported path, comma included."""
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)

    ctx = FakeContext(FakeBot(), args=[str(bet["id"]), "kyllä", "100,00"])
    await handlers.cmd_place_bet(make_update(f"/vetoa {bet['id']} kyllä 100,00"), ctx)

    w = await db.get_user_wager(user["id"], bet["id"])
    assert w is not None and float(w["amount"]) == 100.0
    assert float((await db.get_user(1))["balance"]) == 900.0


# ── navigation clears stale input state ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_nav_clears_pending_input_state(conn):
    """Leaving a wager-amount prompt by navigating must drop the state, or the
    next text message is consumed as an amount for the abandoned bet."""
    await _mk_user(conn)
    ctx = FakeContext(FakeBot())
    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": 1, "side": "yes"}
    query = FakeQuery("nav:kohteet", user_id=1)

    await handlers.nav_callback(make_callback_update(query), ctx)

    assert "state" not in ctx.user_data
    assert AWAITING_AMOUNT not in ctx.user_data


@pytest.mark.asyncio
async def test_nav_new_bet_keeps_and_sets_state(conn):
    """The new-bet entry is the one nav path that legitimately sets state."""
    await _mk_user(conn, username="admin")
    await conn.execute("UPDATE users SET is_admin = TRUE WHERE telegram_id = 1")
    ctx = FakeContext(FakeBot())
    query = FakeQuery("nav:new_bet", user_id=1)

    await handlers.nav_callback(make_callback_update(query), ctx)

    assert ctx.user_data.get("state") == handlers.AWAITING_BET_TITLE


@pytest.mark.asyncio
async def test_nav_new_bet_denied_for_non_admin_shows_alert(conn):
    await _mk_user(conn)  # not admin
    ctx = FakeContext(FakeBot())
    query = FakeQuery("nav:new_bet", user_id=1)

    await handlers.nav_callback(make_callback_update(query), ctx)

    # The alert must actually reach the user (not be swallowed by an early ack).
    assert any(a["show_alert"] and a["text"] == texts.NOT_ADMIN for a in query.answers)
    assert ctx.user_data.get("state") is None


# ── cashout toast is delivered (callback answered once, meaningfully) ────────────

@pytest.mark.asyncio
async def test_cashout_toast_is_delivered(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)

    query = FakeQuery("wager:cancel:" + str(bet["id"]), user_id=1)
    await handlers.cancel_wager_callback(make_callback_update(query), FakeContext(FakeBot()))

    # The success toast must be the answer shown, not swallowed by a blanket ack.
    assert any("Cashout" in (a["text"] or "") for a in query.answers)
    assert await db.get_user_wager(user["id"], bet["id"]) is None


@pytest.mark.asyncio
async def test_cashout_on_locked_bet_shows_alert(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)
    await conn.execute("UPDATE bets SET status = 'locked' WHERE id = $1", bet["id"])

    query = FakeQuery("wager:cancel:" + str(bet["id"]), user_id=1)
    await handlers.cancel_wager_callback(make_callback_update(query), FakeContext(FakeBot()))

    assert any(a["show_alert"] for a in query.answers), "the refusal must be shown as an alert"
    # Wager untouched, balance unchanged.
    assert await db.get_user_wager(user["id"], bet["id"]) is not None


# ── callback-data validation (finding #23) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_bet_side_callback_rejects_forged_side(conn):
    """side is written straight to wagers.side; a forged value must be refused."""
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    query = FakeQuery(f"bet:{bet['id']}:hax", user_id=1)

    await handlers.bet_side_callback(make_callback_update(query), FakeContext(FakeBot()))

    assert any(a["show_alert"] for a in query.answers)
    assert await db.get_user_wager(user["id"], bet["id"]) is None


# ── cashout confirmation step (finding #51) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_cashout_confirm_does_not_cash_out(conn):
    """The confirm step only shows a prompt — the wager must still be intact."""
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)

    query = FakeQuery(f"wager:cancel_confirm:{bet['id']}", user_id=1)
    await handlers.cancel_wager_confirm_callback(make_callback_update(query), FakeContext(FakeBot()))

    # Still there, still charged — nothing refunded yet.
    assert await db.get_user_wager(user["id"], bet["id"]) is not None
    assert float((await db.get_user(1))["balance"]) == 900.0


@pytest.mark.asyncio
async def test_cashout_confirm_then_execute_cashes_out(conn):
    user = await _mk_user(conn)
    bet = await _mk_open_simple_bet(conn)
    await handlers._process_wager(FakeContext(FakeBot()), 1, user, bet["id"], "yes", 100.0)

    # Confirm screen, then the actual cashout button.
    await handlers.cancel_wager_confirm_callback(
        make_callback_update(FakeQuery(f"wager:cancel_confirm:{bet['id']}", user_id=1)),
        FakeContext(FakeBot()),
    )
    await handlers.cancel_wager_callback(
        make_callback_update(FakeQuery(f"wager:cancel:{bet['id']}", user_id=1)),
        FakeContext(FakeBot()),
    )

    assert await db.get_user_wager(user["id"], bet["id"]) is None
    # 900 + 95 (whole-euro refund of 100) = 995.
    assert float((await db.get_user(1))["balance"]) == 995.0
