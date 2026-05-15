import os
from html import escape
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import db
import texts
from handlers import AWAITING_WAGER_LIMITS, _cancel_keyboard, _broadcast_new_bet, _broadcast_bet_resolved


def _password():
    return os.environ.get("ADMIN_PASSWORD", "")


def admin_panel_keyboard(game_finished: bool = False):
    if game_finished:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Resetoi kaikki", callback_data="adm:reset")],
            [InlineKeyboardButton("⬅️ Päävalikko", callback_data="nav:main")],
        ])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Uusi kohde", callback_data="nav:new_bet"),
            InlineKeyboardButton("❌ Poista kohde", callback_data="adm:delete_list"),
        ],
        [
            InlineKeyboardButton("🔒 Lukitse/vapauta kohde", callback_data="adm:lock_list"),
            InlineKeyboardButton("✅ Ratkaise kohde", callback_data="adm:resolve_list"),
        ],
        [
            InlineKeyboardButton("✏️ Muuta kertoimia", callback_data="adm:odds_list"),
            InlineKeyboardButton("💰 Aseta panosrajat", callback_data="adm:limits_list"),
        ],
        [
            InlineKeyboardButton("↩️ Peruuta ratkaisu", callback_data="adm:revert_list"),
        ],
        [
            InlineKeyboardButton("🏁 Lopeta peli", callback_data="adm:finish"),
            InlineKeyboardButton("🔄 Resetoi kaikki", callback_data="adm:reset"),
        ],
        [InlineKeyboardButton("⬅️ Päävalikko", callback_data="nav:main")],
    ])


async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, _ = await db.get_or_create_user(
        update.effective_user.id,
        update.effective_user.username or update.effective_user.first_name,
    )
    if user["is_admin"]:
        await update.message.reply_text(texts.H(texts.ADMIN_ALREADY))
        return
    if not ctx.args or ctx.args[0] != _password():
        await update.message.reply_text(texts.H(texts.WRONG_PASSWORD))
        return
    await db.set_admin(update.effective_user.id)
    game_done = await db.is_game_finished()
    await update.message.reply_text(texts.H(texts.ADMIN_WELCOME), reply_markup=admin_panel_keyboard(game_done))


async def admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    game_done = await db.is_game_finished()
    await update.message.reply_text(texts.H(texts.ADMIN_PANEL), reply_markup=admin_panel_keyboard(game_done))


async def cmd_lock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if not ctx.args:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/lukitse <id>")))
        return
    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/lukitse <id>")))
        return
    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
        return
    if bet["status"] != "open":
        await update.message.reply_text(texts.H(texts.BET_ALREADY_LOCKED))
        return
    await db.lock_bet(bet_id)
    await update.message.reply_text(texts.H(texts.BET_LOCKED_OK.format(id=bet_id)))


async def cmd_resolve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if len(ctx.args) != 2:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/ratkaise <id> <kyllä|ei>")))
        return
    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/ratkaise <id> <kyllä|ei>")))
        return
    result_input = ctx.args[1].lower()
    if result_input not in ("kyllä", "kylla", "ei"):
        await update.message.reply_text(texts.H(texts.INVALID_SIDE))
        return
    result = "yes" if result_input in ("kyllä", "kylla") else "no"
    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
        return
    if bet["status"] == "resolved":
        await update.message.reply_text(texts.H(texts.BET_RESOLVED.format(id=bet_id)))
        return
    winners = await db.resolve_bet(bet_id, result)
    result_fi = "Kyllä ✅" if result == "yes" else "Ei ❌"
    winners_text = "".join(
        texts.WINNER_ROW.format(username=w["username"], profit=w["profit"])
        for w in winners
    ) if winners else texts.NO_WINNERS
    await _broadcast_bet_resolved(update.get_bot(), bet, result_fi, winners_text)


async def cmd_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if await db.is_game_finished():
        await update.message.reply_text(texts.H("Peli on jo päättynyt."))
        return
    pool_bets = await db.get_active_bets()
    unresolved = [b for b in pool_bets if b["status"] in ("open", "locked")]
    if unresolved:
        titles = "\n".join(f"  #{b['id']} {b['title']}" for b in unresolved)
        await update.message.reply_text(texts.H(
            f"❌ Ratkaisemattomia kohteita:\n{titles}\n\nRatkaise kaikki kohteet ennen pelin lopettamista."
        ))
        return
    await _finish_game(update)


async def cmd_finish_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_finish(update, ctx)


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
        game_done = await db.is_game_finished()
        await query.message.edit_text(texts.H(texts.ADMIN_PANEL), reply_markup=admin_panel_keyboard(game_done))

    elif action == "delete_list":
        bets = await db.get_active_bets()
        if not bets:
            await query.message.edit_text(texts.H("Ei poistettavia kohteita."), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"🗑️ {'🔒 ' if b['status'] == 'locked' else ''}#{b['id']} {b['title']}",
                callback_data=f"adm:delete_confirm:{b['id']}",
            )]
            for b in bets
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H("🗑️ Valitse poistettava kohde:\n\nVedot palautetaan täysimääräisesti."), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "delete_confirm":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "resolved":
            await query.answer(texts.BET_DELETE_FORBIDDEN, show_alert=True)
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä, poista", callback_data=f"adm:delete:{bet_id}"),
                InlineKeyboardButton("❌ Peruuta", callback_data="adm:delete_list"),
            ]
        ])
        await query.message.edit_text(
            texts.H(f"⚠️ Poistetaanko kohde #{bet_id} {bet['title']}?\n\nKaikki vedot palautetaan täysimääräisesti."),
            reply_markup=keyboard,
        )

    elif action == "delete":
        bet_id = int(parts[2])
        deleted = await db.delete_bet(bet_id)
        if deleted:
            await query.answer(f"🗑️ Kohde #{bet_id} poistettu.")
        else:
            await query.answer(texts.BET_DELETE_FORBIDDEN, show_alert=True)
        game_done = await db.is_game_finished()
        await query.message.edit_text(texts.H(texts.ADMIN_PANEL), reply_markup=admin_panel_keyboard(game_done))

    elif action == "lock_list":
        all_bets = await db.get_active_bets()
        toggleable = [b for b in all_bets if b["status"] in ("open", "locked")]
        if not toggleable:
            await query.message.edit_text(texts.H(texts.ADMIN_NO_OPEN_BETS), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"{'🔒 ' if b['status'] == 'locked' else ''}#{b['id']} {b['title']}",
                callback_data=f"adm:lock:{b['id']}",
            )]
            for b in toggleable
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H(texts.ADMIN_LOCK_LIST), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "lock":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "resolved":
            await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "locked":
            success, is_first_open = await db.unlock_bet(bet_id)
            await query.answer(f"🔓 Kohde #{bet_id} vapautettu!")
            if is_first_open:
                bet = await db.get_bet(bet_id)
                if bet["bet_type"] == "winner":
                    options = await db.get_bet_options(bet_id)
                    await _broadcast_new_bet(query.message.get_bot(), bet, options=options)
                else:
                    await _broadcast_new_bet(query.message.get_bot(), bet)
        else:
            await db.lock_bet(bet_id)
            await query.answer(f"🔒 Kohde #{bet_id} lukittu!")
        all_bets = await db.get_active_bets()
        toggleable = [b for b in all_bets if b["status"] in ("open", "locked")]
        keyboard = [
            [InlineKeyboardButton(
                f"{'🔒 ' if b['status'] == 'locked' else ''}#{b['id']} {b['title']}",
                callback_data=f"adm:lock:{b['id']}",
            )]
            for b in toggleable
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "resolve_list":
        locked_bets = await db.get_locked_bets_with_totals()
        if not locked_bets:
            await query.message.edit_text(texts.H(texts.ADMIN_NO_LOCKED_BETS), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"#{b['id']} {b['title']} ({float(b['total_wagered']):.0f} €)",
                callback_data=f"adm:resolve:{b['id']}",
            )]
            for b in locked_bets
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H(texts.ADMIN_RESOLVE_LIST), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "resolve" and len(parts) == 3:
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["bet_type"] == "winner":
            options = await db.get_bet_options(bet_id)
            rows = [
                [InlineKeyboardButton(
                    f"{o['label']} @ {float(o['odds']):.2f}",
                    callback_data=f"adm:resolve:{bet_id}:{o['id']}",
                )]
                for o in options
            ]
            rows.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:resolve_list")])
            await query.message.edit_text(
                texts.H(texts.ADMIN_RESOLVE_SIDE.format(id=bet_id, title=bet["title"])),
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Kyllä", callback_data=f"adm:resolve:{bet_id}:yes"),
                    InlineKeyboardButton("❌ Ei", callback_data=f"adm:resolve:{bet_id}:no"),
                ],
                [InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:resolve_list")],
            ])
            await query.message.edit_text(
                texts.H(texts.ADMIN_RESOLVE_SIDE.format(id=bet_id, title=bet["title"])),
                reply_markup=keyboard,
            )

    elif action == "resolve" and len(parts) == 4:
        bet_id = int(parts[2])
        value = parts[3]
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] == "resolved":
            await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
            return
        if bet["bet_type"] == "winner":
            winning_option_id = int(value)
            winners = await db.resolve_winner_bet(bet_id, winning_option_id)
            if winners is None:
                await query.answer("❌ Virheellinen vaihtoehto tälle vedolle.", show_alert=True)
                return
            options = await db.get_bet_options(bet_id)
            winning = next((o for o in options if o["id"] == winning_option_id), None)
            result_fi = f"🏆 {winning['label']}" if winning else f"Option {winning_option_id}"
        else:
            winners = await db.resolve_bet(bet_id, value)
            result_fi = "Kyllä ✅" if value == "yes" else "Ei ❌"
        winners_text = "".join(
            texts.WINNER_ROW.format(username=w["username"], profit=w["profit"])
            for w in winners
        ) if winners else texts.NO_WINNERS
        await _broadcast_bet_resolved(query.message.get_bot(), bet, result_fi, winners_text)
        await query.message.edit_text(texts.H(texts.BET_RESOLVED_MSG.format(
            id=bet_id, title=bet["title"], result=result_fi, winners=winners_text
        )), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Peruuta ratkaisu", callback_data=f"adm:revert:{bet_id}")],
            [InlineKeyboardButton("⬅️ Admin-paneeli", callback_data="adm:panel")],
        ]))

    elif action == "revert_list":
        resolved_bets = await db.get_resolved_bets()
        if not resolved_bets:
            await query.message.edit_text(texts.H(texts.ADMIN_NO_RESOLVED_BETS), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"↩️ #{b['id']} {b['title']}",
                callback_data=f"adm:revert:{b['id']}",
            )]
            for b in resolved_bets
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H(texts.ADMIN_REVERT_LIST), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "revert" and len(parts) == 3:
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet or bet["status"] != "resolved":
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["bet_type"] == "winner":
            options = await db.get_bet_options(bet_id)
            winning = next((o for o in options if str(o["id"]) == bet["result"]), None)
            result_fi = f"🏆 {winning['label']}" if winning else f"Option {bet['result']}"
        else:
            result_fi = "Kyllä ✅" if bet["result"] == "yes" else "Ei ❌"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä, peruuta", callback_data=f"adm:revert_confirm:{bet_id}"),
                InlineKeyboardButton("❌ Peruuta", callback_data="adm:revert_list"),
            ]
        ])
        await query.message.edit_text(
            texts.H(texts.ADMIN_REVERT_CONFIRM.format(id=bet_id, title=bet["title"], result=result_fi)),
            reply_markup=keyboard,
        )

    elif action == "revert_confirm":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet or bet["status"] != "resolved":
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        success = await db.revert_resolved_bet(bet_id)
        if success:
            await query.answer(f"↩️ Kohteen #{bet_id} ratkaisu peruutettu.")
            game_done = await db.is_game_finished()
            await query.message.edit_text(
                texts.H(texts.BET_REVERTED.format(id=bet_id)),
                reply_markup=admin_panel_keyboard(game_done),
            )
        else:
            await query.answer("❌ Peruutus epäonnistui.", show_alert=True)

    elif action == "odds_list":
        all_bets = await db.get_active_bets()
        locked_bets = [b for b in all_bets if b["status"] == "locked"]
        eligible = []
        for b in locked_bets:
            count = await db.get_bet_wager_count(b["id"])
            if count == 0:
                eligible.append(b)
        if not eligible:
            await query.message.edit_text(texts.H(texts.ADMIN_NO_ODDS_BETS), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(f"✏️ #{b['id']} {b['title']}", callback_data=f"adm:odds_show:{b['id']}")]
            for b in eligible
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H(texts.ADMIN_ODDS_LIST), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "odds_show":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet or bet["status"] != "locked":
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        wager_count = await db.get_bet_wager_count(bet_id)
        if wager_count > 0:
            await query.answer(texts.ODDS_UPDATE_FORBIDDEN, show_alert=True)
            return
        if bet["bet_type"] == "winner":
            options = await db.get_bet_options(bet_id)
            opts_str = " | ".join(f"{escape(o['label'])} @ {float(o['odds']):.2f}" for o in options)
            msg = texts.ODDS_COPY_PASTE_WINNER.format(id=bet_id, title=escape(bet["title"]), options=opts_str)
        else:
            msg = texts.ODDS_COPY_PASTE_SIMPLE.format(
                id=bet_id, title=escape(bet["title"]),
                yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
            )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:odds_list")]])
        await query.message.edit_text(texts.H(msg), reply_markup=keyboard, parse_mode="HTML")

    elif action == "limits_list":
        all_bets = await db.get_active_bets()
        bets = [b for b in all_bets if b["status"] in ("open", "locked")]
        if not bets:
            await query.message.edit_text(texts.H("Ei avoimia tai lukittuja kohteita."), reply_markup=admin_panel_keyboard())
            return
        keyboard = [
            [InlineKeyboardButton(
                f"{'🔒 ' if b['status'] == 'locked' else ''}#{b['id']} {b['title']} ({int(float(b['min_wager']))}–{int(float(b['max_wager']))} €)",
                callback_data=f"adm:limits_set:{b['id']}",
            )]
            for b in bets
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")])
        await query.message.edit_text(texts.H("💰 Valitse kohde jonka panosrajat haluat muuttaa:"), reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "limits_set":
        bet_id = int(parts[2])
        bet = await db.get_bet(bet_id)
        if not bet:
            await query.answer(texts.BET_NOT_FOUND.format(id=bet_id), show_alert=True)
            return
        if bet["status"] not in ("open", "locked"):
            await query.answer("Vain avoimien tai lukittujen kohteiden rajoja voi muuttaa.", show_alert=True)
            return
        ctx.user_data["state"] = AWAITING_WAGER_LIMITS
        ctx.user_data[AWAITING_WAGER_LIMITS] = {"bet_id": bet_id}
        await query.message.reply_text(
            texts.H(texts.ASK_WAGER_LIMITS.format(
                id=bet_id, title=bet["title"],
                min=float(bet["min_wager"]), max=float(bet["max_wager"]),
            )),
            reply_markup=_cancel_keyboard(),
        )

    elif action == "finish":
        if await db.is_game_finished():
            await query.answer("Peli on jo päättynyt.", show_alert=True)
            return
        all_bets = await db.get_active_bets()
        unresolved = [b for b in all_bets if b["status"] in ("open", "locked")]
        if unresolved:
            titles = "\n".join(f"  #{b['id']} {b['title']}" for b in unresolved)
            msg = f"❌ Ratkaisemattomia kohteita:\n{titles}\n\nRatkaise kaikki kohteet ennen pelin lopettamista."
            await query.message.edit_text(texts.H(msg), reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Takaisin", callback_data="adm:panel")]
            ]))
            return
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä, lopeta", callback_data="adm:finish_confirm"),
                InlineKeyboardButton("❌ Peruuta", callback_data="adm:panel"),
            ]
        ])
        await query.message.edit_text(texts.H(texts.ADMIN_FINISH_CONFIRM), reply_markup=keyboard)

    elif action == "finish_confirm":
        if await db.is_game_finished():
            await query.answer("Peli on jo päättynyt.", show_alert=True)
            return
        await db.set_game_finished()
        rows = await db.get_leaderboard()
        msg = texts.GAME_FINISHED_HEADER
        for i, row in enumerate(rows, 1):
            name = row["username"] or f"user{row['telegram_id']}"
            msg += texts.GAME_FINISHED_ROW.format(rank=i, username=name, balance=float(row["balance"]))
        msg += texts.GAME_FINISHED_NOTICE
        kepulit = await db.get_kepulit()
        if kepulit:
            msg += texts.KEPULIT_HEADER
            for i, row in enumerate(kepulit, 1):
                name = row["username"] or f"user{row['telegram_id']}"
                msg += texts.KEPULIT_ROW.format(
                    rank=i, username=name,
                    balance=float(row["balance"]),
                    bonus=float(row["bonus_balance"]),
                )
        await query.message.edit_text(texts.H(msg))

    elif action == "reset":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Kyllä, nollaa", callback_data="adm:reset_confirm"),
                InlineKeyboardButton("❌ Peruuta", callback_data="adm:panel"),
            ]
        ])
        await query.message.edit_text(texts.H(texts.ADMIN_RESET_CONFIRM), reply_markup=keyboard)

    elif action == "reset_confirm":
        await db.reset_game()
        await query.message.edit_text(texts.H(texts.ADMIN_RESET_DONE), reply_markup=admin_panel_keyboard())


async def cmd_list_weights(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    bets = await db.get_active_bets()
    if not bets:
        await update.message.reply_text(texts.H(texts.WEIGHT_NO_BETS))
        return
    msg = texts.WEIGHT_LIST_HEADER
    msg += "".join(
        texts.WEIGHT_ROW.format(id=b["id"], title=b["title"], weight=b["weight"])
        for b in bets
    )
    msg += "\nMuuta painoa: /weight <id> <paino>"
    await update.message.reply_text(texts.H(msg))


async def cmd_set_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if len(ctx.args) != 2:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/weight <id> <paino>")))
        return
    try:
        bet_id = int(ctx.args[0])
        weight = int(ctx.args[1])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/weight <id> <paino>")))
        return
    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
        return
    ok = await db.set_bet_weight(bet_id, weight)
    if not ok:
        await update.message.reply_text(texts.H(texts.WEIGHT_SET_FORBIDDEN))
        return
    await update.message.reply_text(texts.H(texts.WEIGHT_SET.format(
        id=bet_id, title=bet["title"], weight=weight,
    )))


async def cmd_update_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(texts.H(texts.INVALID_ODDS_CMD_SIMPLE))
        return
    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_ODDS_CMD_SIMPLE))
        return

    bet = await db.get_bet(bet_id)
    if not bet or bet["status"] != "locked":
        await update.message.reply_text(texts.H(texts.ODDS_UPDATE_BET_NOT_FOUND.format(id=bet_id)))
        return
    wager_count = await db.get_bet_wager_count(bet_id)
    if wager_count > 0:
        await update.message.reply_text(texts.H(texts.ODDS_UPDATE_FORBIDDEN))
        return

    rest = " ".join(ctx.args[1:])

    if bet["bet_type"] == "winner":
        raw_options = [o.strip() for o in rest.split("|") if o.strip()]
        existing_options = await db.get_bet_options(bet_id)
        if len(raw_options) != len(existing_options):
            await update.message.reply_text(texts.H(texts.INVALID_ODDS_CMD_WINNER))
            return
        option_odds = []
        new_odds_list = []
        try:
            for i, raw in enumerate(raw_options):
                at_pos = raw.rfind("@")
                if at_pos == -1:
                    raise ValueError
                new_odds = float(raw[at_pos + 1:].strip().replace(",", "."))
                if new_odds <= 1.0:
                    raise ValueError
                option_odds.append((existing_options[i]["position"], new_odds))
                new_odds_list.append((existing_options[i]["label"], new_odds))
        except ValueError:
            await update.message.reply_text(texts.H(texts.INVALID_ODDS_CMD_WINNER))
            return
        ok = await db.update_winner_bet_option_odds(bet_id, option_odds)
        if not ok:
            await update.message.reply_text(texts.H(texts.ODDS_UPDATE_FORBIDDEN))
            return
        opts_display = "\n".join(f"  {label} @ {odds:.2f}" for label, odds in new_odds_list)
        await update.message.reply_text(texts.H(texts.ODDS_UPDATED_WINNER.format(
            id=bet_id, title=bet["title"], options=opts_display,
        )))
    else:
        parts = rest.split()
        if len(parts) != 2:
            await update.message.reply_text(texts.H(texts.INVALID_ODDS_CMD_SIMPLE))
            return
        try:
            yes_odds = float(parts[0].replace(",", "."))
            no_odds = float(parts[1].replace(",", "."))
            if yes_odds <= 1.0 or no_odds <= 1.0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(texts.H(texts.INVALID_ODDS))
            return
        ok = await db.update_simple_bet_odds(bet_id, yes_odds, no_odds)
        if not ok:
            await update.message.reply_text(texts.H(texts.ODDS_UPDATE_FORBIDDEN))
            return
        await update.message.reply_text(texts.H(texts.ODDS_UPDATED_SIMPLE.format(
            id=bet_id, title=bet["title"], yes_odds=yes_odds, no_odds=no_odds,
        )))


async def _finish_game(update):
    await db.set_game_finished()
    rows = await db.get_leaderboard()
    msg = texts.GAME_FINISHED_HEADER
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        msg += texts.GAME_FINISHED_ROW.format(rank=i, username=name, balance=float(row["balance"]))
    msg += texts.GAME_FINISHED_NOTICE
    kepulit = await db.get_kepulit()
    if kepulit:
        msg += texts.KEPULIT_HEADER
        for i, row in enumerate(kepulit, 1):
            name = row["username"] or f"user{row['telegram_id']}"
            msg += texts.KEPULIT_ROW.format(
                rank=i, username=name,
                balance=float(row["balance"]),
                bonus=float(row["bonus_balance"]),
            )
    await update.message.reply_text(texts.H(msg))


async def cmd_add_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/lisaasaldo <handle> <summa>")))
        return
    handle = ctx.args[0].lstrip("@")
    try:
        amount = float(ctx.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/lisaasaldo <handle> <summa>")))
        return
    target = await db.get_user_by_username(handle)
    if not target:
        await update.message.reply_text(texts.H(f"❌ Käyttäjää '{handle}' ei löydy."))
        return
    await db.add_balance(target["id"], amount)
    sign = "+" if amount >= 0 else ""
    await update.message.reply_text(texts.H(
        f"✅ Saldo päivitetty!\n{target['username']}: {sign}{amount:.0f} € → uusi saldo {float(target['balance']) + amount:.0f} €"
    ))


async def cmd_set_kepuli(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mark a user as having received bonus balance (kepuli), without touching real balance.
    Usage: /kepuli <handle> <summa>   — set bonus marking
           /kepuli <handle> 0         — clear the marking
    """
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/kepuli <handle> <summa>")))
        return
    handle = ctx.args[0].lstrip("@")
    try:
        amount = float(ctx.args[1].replace(",", "."))
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/kepuli <handle> <summa>")))
        return
    target = await db.get_user_by_username(handle)
    if not target:
        await update.message.reply_text(texts.H(f"❌ Käyttäjää '{handle}' ei löydy."))
        return
    await db.set_bonus_balance(target["id"], amount)
    if amount == 0:
        await update.message.reply_text(texts.H(texts.KEPULI_CLEARED.format(username=target["username"])))
    else:
        await update.message.reply_text(texts.H(texts.KEPULI_SET.format(
            username=target["username"], bonus=amount,
        )))


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Lähetä viesti kaikille rekisteröityneille pelaajille.
    Käyttö: /broadcast <viesti>
    """
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if not ctx.args:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/broadcast <viesti>")))
        return

    message = escape(" ".join(ctx.args))
    broadcast_text = f"📢 <b>Tiedote adminilta:</b>\n\n{message}"

    telegram_ids = await db.get_all_telegram_ids()
    sent, failed = 0, 0
    bot = update.get_bot()
    for tid in telegram_ids:
        try:
            await bot.send_message(chat_id=tid, text=broadcast_text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        texts.H(f"✅ Tiedote lähetetty!\nLähetettiin: {sent} | Epäonnistui: {failed}")
    )
