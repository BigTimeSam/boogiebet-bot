"""Integration tests for the cross-user broadcast logic in bot/notifications.py.

telegram is stubbed (see conftest); a FakeBot records what was sent/edited so we
can assert on the broadcast behaviour, including the in-place edit and the
4096-char cap that used to fail silently for everyone.
"""
import notifications
import pytest
from fakes import FakeBot


async def _mk_user(conn, tid, username="p"):
    await conn.execute(
        "INSERT INTO users (telegram_id, username) VALUES ($1, $2)", tid, f"{username}{tid}"
    )


async def _open_bet(conn, title="Bet"):
    row = await conn.fetchrow(
        "INSERT INTO bets (title, yes_odds, no_odds, bet_type, status) "
        "VALUES ($1, 2.0, 2.0, 'simple', 'open') RETURNING *", title,
    )
    return dict(row)


@pytest.fixture(autouse=True)
def _clear_notification_cache():
    notifications._notification_msgs.clear()
    yield
    notifications._notification_msgs.clear()


@pytest.mark.asyncio
async def test_broadcast_sends_to_every_user_and_caches(conn):
    for tid in (1, 2, 3):
        await _mk_user(conn, tid)
    bet = await _open_bet(conn)
    bot = FakeBot()

    await notifications._broadcast_new_bet(bot, bet)

    assert len(bot.sent) == 3, "every registered user gets the notification"
    assert set(notifications._notification_msgs) == {1, 2, 3}


@pytest.mark.asyncio
async def test_second_broadcast_edits_in_place(conn):
    await _mk_user(conn, 1)
    bet1 = await _open_bet(conn, "First")
    bot = FakeBot()

    await notifications._broadcast_new_bet(bot, bet1)
    assert len(bot.sent) == 1
    bot.sent.clear()

    bet2 = await _open_bet(conn, "Second")
    await notifications._broadcast_new_bet(bot, bet2)

    # The existing message is edited, not re-sent.
    assert bot.sent == []
    assert len(bot.edited) == 1


@pytest.mark.asyncio
async def test_broadcast_text_capped_below_telegram_limit(conn):
    await _mk_user(conn, 1)
    # Many bets with long titles so the consolidated text would exceed 4096.
    for i in range(60):
        await _open_bet(conn, f"Pitkä otsikko numero {i} " + "x" * 60)
    bet = await _open_bet(conn, "Uusin")
    bot = FakeBot()

    await notifications._broadcast_new_bet(bot, bet)

    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert len(text) <= 4096, "the broadcast must never exceed Telegram's limit"
    assert "muuta" in text, "the truncation notice should point to the full list"


@pytest.mark.asyncio
async def test_broadcast_open_bets_text_none_when_no_open_bets(conn):
    assert await notifications._build_open_bets_text() is None
