"""Shared UI primitives: keyboard builders and the menu-message display helpers.

Leaf module — depends only on db and texts, so handlers / rendering /
notifications can all import it without creating an import cycle.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import db
import texts
from constants import TELEGRAM_MAX_MESSAGE

logger = logging.getLogger(__name__)

_TRUNCATION_NOTICE = "\n\n… (viesti katkaistu — se oli liian pitkä)"


def _fit(text: str) -> str:
    """Keep a message under Telegram's hard limit.

    A body over 4096 chars is rejected outright; without this the caller would
    log a debug line no one sees and then resend the same too-long text, turning
    any oversized view into a dead end. Truncating degrades gracefully instead.
    """
    if len(text) <= TELEGRAM_MAX_MESSAGE:
        return text
    keep = TELEGRAM_MAX_MESSAGE - len(_TRUNCATION_NOTICE)
    return text[:keep] + _TRUNCATION_NOTICE


async def _show(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    text = _fit(text)
    # Reuse the cached menu message only if it belongs to THIS chat. user_data is
    # per-user, not per-chat, so a message id stored from another chat would edit
    # the wrong message — menu_chat_id was written for this check but never read.
    msg_id = (
        ctx.user_data.get("menu_message_id")
        if ctx.user_data.get("menu_chat_id") == chat_id
        else None
    )
    if msg_id:
        try:
            await ctx.bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=msg_id, reply_markup=reply_markup,
            )
            return
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            logger.debug("Could not edit menu message %s: %s", msg_id, e)
        except Exception as e:
            logger.debug("Could not edit menu message %s: %s", msg_id, e)
    msg = await ctx.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    ctx.user_data["menu_chat_id"] = chat_id
    ctx.user_data["menu_message_id"] = msg.message_id


async def _delete_msg(bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _show_callback(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text: str, reply_markup=None):
    ctx.user_data["menu_chat_id"] = chat_id
    ctx.user_data["menu_message_id"] = message_id
    await _show(ctx, chat_id, text, reply_markup)


def _option_rows(options, btn_maker):
    rows = []
    for i in range(0, len(options), 2):
        rows.append([btn_maker(o) for o in options[i:i + 2]])
    return rows


def main_menu_keyboard(is_admin=False, game_done=False, has_winners=False):
    top_row = []
    if not game_done:
        top_row.append(InlineKeyboardButton("📋 Kohteet", callback_data="nav:kohteet"))
    top_row.append(InlineKeyboardButton("🎯 Omat vedot", callback_data="nav:omat"))
    results_row = [InlineKeyboardButton("🏆 Tulostaulu", callback_data="nav:tulokset")]
    if has_winners:
        results_row.append(InlineKeyboardButton("🥇 Voittajat", callback_data="nav:voittajat"))
    results_row.append(InlineKeyboardButton("📈 PnL", callback_data="nav:pnl"))
    rows = [top_row, results_row]
    if is_admin:
        rows.append([InlineKeyboardButton("🔧 Admin-paneeli", callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


async def _main_keyboard(user):
    game_done = await db.is_game_finished()
    has_winners = await db.has_resolved_bets()
    return main_menu_keyboard(is_admin=user["is_admin"], game_done=game_done, has_winners=has_winners)


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")]])


def _cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Peruuta", callback_data="input:cancel")]])


def _bet_type_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚖️ Kyllä / Ei", callback_data="bet_type:simple"),
            InlineKeyboardButton("🏆 Voittajaveto", callback_data="bet_type:winner"),
        ],
        [InlineKeyboardButton("❌ Peruuta", callback_data="input:cancel")],
    ])


async def _main_text(user, name: str = None, is_new: bool = False) -> str:
    if await db.is_game_finished():
        leaderboard = await db.get_leaderboard()
        total = len(leaderboard)
        rank = next(
            (i for i, r in enumerate(leaderboard, 1) if r["telegram_id"] == user["telegram_id"]),
            None,
        )
        if rank is None:
            # Not on the leaderboard (a kepuli, excluded from the ranking). Don't
            # show a made-up "last" rank; say plainly they're out of the running.
            return texts.GAME_FINISHED_PERSONAL_KEPULI.format(balance=float(user["balance"]))
        return texts.GAME_FINISHED_PERSONAL.format(
            balance=float(user["balance"]), rank=rank, total=total
        )
    balance = float(user["balance"])
    if is_new and name:
        base = texts.WELCOME_NEW.format(name=name, balance=balance)
    else:
        base = texts.WELCOME_BACK.format(balance=balance)
    wagered, payout = await db.get_user_open_wager_stats(user["id"])
    if wagered > 0:
        base += "\n" + texts.WAGER_STATS.format(wagered=wagered, potential=balance + payout)
    return base
