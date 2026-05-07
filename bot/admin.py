import os
from telegram import Update
from telegram.ext import ContextTypes
import db
import texts


def _password():
    return os.environ.get("ADMIN_PASSWORD", "lanijatkot")


async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, _ = await db.get_or_create_user(
        update.effective_user.id,
        update.effective_user.username or update.effective_user.first_name,
    )
    if user["is_admin"]:
        await update.message.reply_text(texts.ADMIN_ALREADY)
        return
    if not ctx.args or ctx.args[0] != _password():
        await update.message.reply_text(texts.WRONG_PASSWORD)
        return
    await db.set_admin(update.effective_user.id)
    await update.message.reply_text(texts.ADMIN_WELCOME)


async def admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.NOT_ADMIN)
        return
    await update.message.reply_text(texts.ADMIN_HELP)


async def lukitse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.NOT_ADMIN)
        return

    if not ctx.args:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/lukitse <id>"))
        return

    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/lukitse <id>"))
        return

    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.BET_NOT_FOUND.format(id=bet_id))
        return
    if bet["status"] != "open":
        await update.message.reply_text(texts.BET_ALREADY_LOCKED)
        return

    await db.lock_bet(bet_id)
    await update.message.reply_text(texts.BET_LOCKED_OK.format(id=bet_id))


async def ratkaise(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.NOT_ADMIN)
        return

    if len(ctx.args) != 2:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/ratkaise <id> <kyllä|ei>"))
        return

    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/ratkaise <id> <kyllä|ei>"))
        return

    result_input = ctx.args[1].lower()
    if result_input not in ("kyllä", "kylla", "ei"):
        await update.message.reply_text(texts.INVALID_SIDE)
        return
    result = "yes" if result_input in ("kyllä", "kylla") else "no"

    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.BET_NOT_FOUND.format(id=bet_id))
        return
    if bet["status"] == "resolved":
        await update.message.reply_text(texts.BET_RESOLVED.format(id=bet_id))
        return
    if bet["status"] == "open":
        await update.message.reply_text("❌ Lukitse kohde ensin komennolla /lukitse " + str(bet_id))
        return

    winners = await db.resolve_bet(bet_id, result)
    result_fi = "Kyllä ✅" if result == "yes" else "Ei ❌"
    winners_text = "".join(
        texts.WINNER_ROW.format(username=w["username"], profit=w["profit"], balance=w["balance"])
        for w in winners
    ) if winners else texts.NO_WINNERS

    await update.message.reply_text(texts.BET_RESOLVED_MSG.format(
        id=bet_id, title=bet["title"], result=result_fi, winners=winners_text
    ))


async def lopeta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.NOT_ADMIN)
        return

    if await db.is_game_finished():
        await update.message.reply_text("Peli on jo päättynyt.")
        return

    # Warn if there are unresolved locked bets
    pool_bets = await db.get_active_bets()
    unresolved = [b for b in pool_bets if b["status"] == "locked"]
    if unresolved:
        titles = "\n".join(f"  #{b['id']} {b['title']}" for b in unresolved)
        await update.message.reply_text(
            f"⚠️ Ratkaisemattomia lukittuja kohteita:\n{titles}\n\n"
            "Ratkaise ne ensin komennolla /ratkaise tai lähetä /lopeta uudelleen hyväksyäksesi."
        )
        ctx.user_data["lopeta_confirm"] = True
        return

    await _finish_game(update)


async def lopeta_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Second /lopeta call confirms finishing with unresolved bets."""
    if not ctx.user_data.pop("lopeta_confirm", False):
        await lopeta(update, ctx)
        return
    await _finish_game(update)


async def _finish_game(update):
    await db.set_game_finished()

    rows = await db.get_leaderboard()
    msg = texts.GAME_FINISHED_HEADER
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        msg += texts.LEADERBOARD_ROW.format(rank=i, username=name, balance=float(row["balance"]))
    msg += texts.GAME_FINISHED_NOTICE

    await update.message.reply_text(msg)
