import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import db
import texts


def _password():
    return os.environ.get("ADMIN_PASSWORD", "")


def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Uusi kohde", callback_data="nav:new_bet"),
            InlineKeyboardButton("🔒 Lukitse kohde", callback_data="adm:lock_list"),
        ],
        [
            InlineKeyboardButton("✅ Ratkaise kohde", callback_data="adm:resolve_list"),
            InlineKeyboardButton("🏁 Lopeta peli", callback_data="adm:finish"),
        ],
        [InlineKeyboardButton("⬅️ Päävalikko", callback_data="nav:main")],
    ])


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
    await update.message.reply_text(texts.ADMIN_WELCOME, reply_markup=admin_panel_keyboard())


async def admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.NOT_ADMIN)
        return
    await update.message.reply_text(texts.ADMIN_PANEL, reply_markup=admin_panel_keyboard())


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


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user or not user["is_admin"]:
        await query.answer(texts.NOT_ADMIN, show_alert=True)
        return

    parts = query.data.split(":")
    action = parts[1]

    if action == "panel":
        await query.message.edit_text(texts.ADMIN_PANEL, reply_markup=admin_panel_keyboard())

    elif action == "lock_list":
        bets = await db.get_open_bets()
        if not bets:
            await query.message.edit_text(texts.ADMIN_NO_OPEN_BETS, reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(f"#{b['id']} {b['title']}", callback_data=f"adm:lock:{b['id']}")]
            for b in bets
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.ADMIN_LOCK_LIST, reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "lock":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] != "open":
            await query.answer(texts.BET_ALREADY_LOCKED, show_alert=True)
            return
        await db.lock_bet(bet_id)
        await query.answer(f"🔒 Kohde #{bet_id} lukittu!")
        await query.message.edit_text(texts.ADMIN_PANEL, reply_markup=admin_panel_keyboard())

    elif action == "resolve_list":
        all_bets = await db.get_active_bets()
        locked = [b for b in all_bets if b["status"] == "locked"]
        if not locked:
            await query.message.edit_text(texts.ADMIN_NO_LOCKED_BETS, reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(f"#{b['id']} {b['title']}", callback_data=f"adm:resolve:{b['id']}")]
            for b in locked
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.ADMIN_RESOLVE_LIST, reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "resolve" and len(parts) == 3:
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä", callback_data=f"adm:resolve:{bet_id}:yes"),
                InlineKeyboardButton("❌ Ei", callback_data=f"adm:resolve:{bet_id}:no"),
            ],
            [InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:resolve_list")],
        ])
        await query.message.edit_text(
            texts.ADMIN_RESOLVE_SIDE.format(id=bet_id, title=bet["title"]),
            reply_markup=keyboard,
        )

    elif action == "resolve" and len(parts) == 4:
        bet_id = int(parts[2])
        result = parts[3]
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "resolved":
            await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "open":
            await query.answer("Lukitse kohde ensin.", show_alert=True)
            return
        winners = await db.resolve_bet(bet_id, result)
        result_fi = "Kyllä ✅" if result == "yes" else "Ei ❌"
        winners_text = "".join(
            texts.WINNER_ROW.format(username=w["username"], profit=w["profit"], balance=w["balance"])
            for w in winners
        ) if winners else texts.NO_WINNERS
        msg = texts.BET_RESOLVED_MSG.format(
            id=bet_id, title=bet["title"], result=result_fi, winners=winners_text
        )
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Admin-paneeli", callback_data="adm:panel")]
        ]))

    elif action == "finish":
        if await db.is_game_finished():
            await query.answer("Peli on jo päättynyt.", show_alert=True)
            return
        all_bets = await db.get_active_bets()
        unresolved = [b for b in all_bets if b["status"] == "locked"]
        if unresolved:
            titles = "\n".join(f"  #{b['id']} {b['title']}" for b in unresolved)
            msg = f"⚠️ Ratkaisemattomia lukittuja kohteita:\n{titles}\n\nHaluatko silti lopettaa?"
        else:
            msg = texts.ADMIN_FINISH_CONFIRM
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä, lopeta", callback_data="adm:finish_confirm"),
                InlineKeyboardButton("❌ Peruuta", callback_data="adm:panel"),
            ]
        ])
        await query.message.edit_text(msg, reply_markup=keyboard)

    elif action == "finish_confirm":
        if await db.is_game_finished():
            await query.answer("Peli on jo päättynyt.", show_alert=True)
            return
        await db.set_game_finished()
        rows = await db.get_leaderboard()
        msg = texts.GAME_FINISHED_HEADER
        for i, row in enumerate(rows, 1):
            name = row["username"] or f"user{row['telegram_id']}"
            msg += texts.LEADERBOARD_ROW.format(rank=i, username=name, balance=float(row["balance"]))
        msg += texts.GAME_FINISHED_NOTICE
        await query.message.edit_text(msg)


async def _finish_game(update):
    await db.set_game_finished()

    rows = await db.get_leaderboard()
    msg = texts.GAME_FINISHED_HEADER
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        msg += texts.LEADERBOARD_ROW.format(rank=i, username=name, balance=float(row["balance"]))
    msg += texts.GAME_FINISHED_NOTICE

    await update.message.reply_text(msg)
