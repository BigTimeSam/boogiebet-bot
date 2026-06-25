"""Cross-user push notifications: new-bet broadcasts and resolution announcements.

Self-contained leaf module (depends only on db and texts). Owns the process-local
``_notification_msgs`` cache used to edit each user's latest new-bet message in
place.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db
import texts

logger = logging.getLogger(__name__)

# Maps telegram_id -> (chat_id, message_id) of each user's latest "new bet"
# notification so it can be edited in place. NOTE: process-local and lost on
# restart; only correct for a single bot process. If the bot is ever scaled to
# more than one process, persist this (e.g. in the DB) instead.
_notification_msgs: dict[int, tuple[int, int]] = {}


def pop_notification(telegram_id: int):
    """Remove and return the cached (chat_id, message_id) for a user, or None."""
    return _notification_msgs.pop(telegram_id, None)


async def _build_open_bets_text(new_bet_id: int = None):
    bets = await db.get_active_bets()
    open_bets = [b for b in bets if b["status"] == "open"]
    if not open_bets:
        return None
    lines = ["🎰 Avatut vetokohteet\n"]
    for b in open_bets:
        marker = " 🆕" if b["id"] == new_bet_id else ""
        if b["bet_type"] == "winner":
            options = await db.get_bet_options(b["id"])
            opts = ", ".join(f"{o['label']} @ {float(o['odds']):.2f}" for o in options)
            lines.append(f"#{b['id']} {b['title']}{marker} — {opts}")
        else:
            lines.append(f"#{b['id']} {b['title']}{marker} — Kyllä @ {float(b['yes_odds']):.2f} | Ei @ {float(b['no_odds']):.2f}")
    return "\n".join(lines)


async def _broadcast_new_bet(bot, bet: dict, options: list = None):
    telegram_ids = await db.get_all_telegram_ids()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Katso kohteita", callback_data="nav:kohteet")]])
    if options:
        opts_text = "".join(f"🏅 {o['label']} @ {float(o['odds']):.2f}\n" for o in options)
        text = texts.NEW_BET_NOTIFICATION_WINNER.format(
            id=bet["id"], title=bet["title"], options=opts_text
        )
    else:
        text = texts.NEW_BET_NOTIFICATION_SIMPLE.format(
            id=bet["id"], title=bet["title"],
            yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
        )
    consolidated = await _build_open_bets_text(new_bet_id=bet["id"])
    for tid in telegram_ids:
        msg_text = consolidated if consolidated else text
        msg_kb = keyboard
        prev = _notification_msgs.get(tid)
        sent = False
        if prev:
            chat_id, msg_id = prev
            try:
                await bot.edit_message_text(text=msg_text, chat_id=chat_id, message_id=msg_id, reply_markup=msg_kb)
                sent = True
            except Exception:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
        if not sent:
            try:
                msg = await bot.send_message(chat_id=tid, text=msg_text, reply_markup=msg_kb)
                _notification_msgs[tid] = (tid, msg.message_id)
            except Exception as e:
                logger.warning("Could not send new-bet notification to %s: %s", tid, e)
                _notification_msgs.pop(tid, None)


async def _broadcast_bet_resolved(bot, bet: dict, result_fi: str, winners_text: str):
    telegram_ids = await db.get_all_telegram_ids()
    msg = texts.H(texts.BET_RESOLVED_MSG.format(
        id=bet["id"], title=bet["title"], result=result_fi, winners=winners_text
    ))
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Omat vedot", callback_data="nav:omat")]])
    for tid in telegram_ids:
        try:
            await bot.send_message(chat_id=tid, text=msg, reply_markup=keyboard)
        except Exception as e:
            logger.warning("Could not send resolution notification to %s: %s", tid, e)
