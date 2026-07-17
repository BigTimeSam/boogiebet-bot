import logging

import betting
from notifications import pop_notification
from rendering import (
    _build_bets,
    _build_leaderboard,
    _build_my_bets,
    _build_realized_pnl_all,
    _build_winners,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from ui import (
    _bet_type_keyboard,
    _cancel_keyboard,
    _delete_msg,
    _main_keyboard,
    _main_text,
    _show,
    _show_callback,
    back_keyboard,
    main_menu_keyboard,
)

import db
import texts
from constants import MAX_ODDS, MAX_WAGER, MAX_WINNER_OPTIONS, MIN_WAGER

logger = logging.getLogger(__name__)

AWAITING_AMOUNT = "awaiting_amount"
AWAITING_BET_TITLE = "awaiting_bet_title"
AWAITING_BET_TYPE = "awaiting_bet_type"
AWAITING_BET_ODDS = "awaiting_bet_odds"
AWAITING_WINNER_OPTIONS = "awaiting_winner_options"
AWAITING_WAGER_LIMITS = "awaiting_wager_limits"

_INPUT_STATE_KEYS = (
    AWAITING_AMOUNT, AWAITING_BET_TITLE, AWAITING_BET_ODDS, AWAITING_BET_TYPE,
    AWAITING_WINNER_OPTIONS, AWAITING_WAGER_LIMITS, "state",
)


def _clear_input_state(ctx: ContextTypes.DEFAULT_TYPE):
    """Drop any pending free-text input flow.

    Without this, "state" survives navigation and a text message typed later is
    consumed as a wager amount / bet title for a flow the user already left.
    """
    for key in _INPUT_STATE_KEYS:
        ctx.user_data.pop(key, None)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user, created = await db.get_or_create_user(tg.id, tg.username or tg.first_name)
    _clear_input_state(ctx)
    text = texts.H(await _main_text(user, name=tg.first_name, is_new=created))
    keyboard = await _main_keyboard(user)
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, text, keyboard)


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    keyboard = await _main_keyboard(user) if user else main_menu_keyboard()
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, texts.H(texts.HELP_TEXT), keyboard)


async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    _clear_input_state(ctx)
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, texts.H(texts.BALANCE.format(balance=float(user["balance"]))), back_keyboard())


async def cmd_bets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    _clear_input_state(ctx)
    text, keyboard = await _build_bets(user)
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, texts.H(text), keyboard)


async def cmd_my_bets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    _clear_input_state(ctx)
    text, keyboard = await _build_my_bets(user)
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, texts.H(text), keyboard)


async def cmd_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    text = await _build_leaderboard()
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    await _show(ctx, update.effective_chat.id, texts.H(text), back_keyboard())


async def cmd_place_bet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    if await db.is_game_finished():
        await _show(ctx, update.effective_chat.id, texts.H(texts.GAME_OVER_BLOCK), await _main_keyboard(user))
        return
    args = ctx.args
    if len(args) != 3:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>")), back_keyboard())
        return
    try:
        bet_id = int(args[0])
    except ValueError:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>")), back_keyboard())
        return
    side_input = args[1].lower()
    if side_input not in ("kyllä", "kylla", "ei"):
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_SIDE), back_keyboard())
        return
    side = "yes" if side_input in ("kyllä", "kylla") else "no"
    # Same parser as the button flow: whole euros only, and non-finite input
    # rejected before it can reach the balance.
    amount = betting.parse_wager_amount(args[2])
    if amount is None:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_AMOUNT), back_keyboard())
        return
    await _process_wager(ctx, update.effective_chat.id, user, bet_id, side, amount)


async def cmd_new_bet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    if not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        return
    if await db.is_game_finished():
        await _show(ctx, update.effective_chat.id, texts.H(texts.GAME_OVER_BLOCK), await _main_keyboard(user))
        return
    text = " ".join(ctx.args)
    if "|" not in text:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")), await _main_keyboard(user))
        return
    parts = text.split("|", 1)
    title = parts[0].strip()
    odds_part = parts[1].strip().split()
    if not title or len(odds_part) != 2:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")), await _main_keyboard(user))
        return
    try:
        yes_odds = float(odds_part[0].replace(",", "."))
        no_odds = float(odds_part[1].replace(",", "."))
        if not (1.0 < yes_odds <= MAX_ODDS) or not (1.0 < no_odds <= MAX_ODDS):
            raise ValueError
    except ValueError:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_ODDS), await _main_keyboard(user))
        return
    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    # No broadcast here: create_bet makes the bet 'locked', and players are
    # notified only when it is first opened (the panel's unlock, which alone
    # checks is_first_open). Broadcasting now would announce an un-bettable bet
    # and then announce it a second time on open.
    await _show(ctx, update.effective_chat.id, texts.H(texts.BET_CREATED.format(
        id=bet["id"], title=bet["title"],
        yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
    )), await _main_keyboard(user))


async def cmd_delete_bet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await _show(ctx, update.effective_chat.id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    if not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        return
    if await db.is_game_finished():
        await _show(ctx, update.effective_chat.id, texts.H(texts.GAME_OVER_BLOCK), await _main_keyboard(user))
        return
    if not ctx.args:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/poistakohde <id>")), await _main_keyboard(user))
        return
    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_COMMAND.format(usage="/poistakohde <id>")), await _main_keyboard(user))
        return
    bet = await db.get_bet(bet_id)
    if not bet:
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_NOT_FOUND.format(id=bet_id)), await _main_keyboard(user))
        return
    deleted = await db.delete_bet(bet_id)
    if deleted:
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_DELETED.format(id=bet_id)), await _main_keyboard(user))
    else:
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_DELETE_FORBIDDEN), await _main_keyboard(user))


# ── Callback handlers ──────────────────────────────────────────────────────────

async def noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def nav_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                             texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return

    action = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id

    # Alert-showing guards must run before the silent answer() below: a callback
    # query can be answered only once, so a prior answer() would swallow these.
    if action == "new_bet":
        if not user["is_admin"]:
            await query.answer(texts.NOT_ADMIN, show_alert=True)
            return
        if await db.is_game_finished():
            await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
            return

    # Leaving input state on every navigation stops a later text message from
    # being consumed as a stale wager amount (see _clear_input_state).
    if action != "new_bet":
        _clear_input_state(ctx)

    await query.answer()

    if action == "main":
        await _show_callback(ctx, chat_id, query.message.message_id,
                             texts.H(await _main_text(user)), await _main_keyboard(user))
    elif action == "saldo":
        await _show_callback(ctx, chat_id, query.message.message_id,
                             texts.H(texts.BALANCE.format(balance=float(user["balance"]))), back_keyboard())
    elif action == "kohteet":
        prev = pop_notification(user["telegram_id"])
        if prev:
            try:
                await ctx.bot.delete_message(chat_id=prev[0], message_id=prev[1])
            except Exception:
                pass
        text, keyboard = await _build_bets(user)
        await _show_callback(ctx, chat_id, query.message.message_id, texts.H(text), keyboard)
    elif action == "omat":
        text, keyboard = await _build_my_bets(user)
        await _show_callback(ctx, chat_id, query.message.message_id, texts.H(text), keyboard)
    elif action == "tulokset":
        text = await _build_leaderboard()
        await _show_callback(ctx, chat_id, query.message.message_id, texts.H(text), back_keyboard())
    elif action == "voittajat":
        chunks = await _build_winners()
        keyboard = back_keyboard() if len(chunks) == 1 else None
        await _show_callback(ctx, chat_id, query.message.message_id, texts.H(chunks[0]), keyboard)
        for i, chunk in enumerate(chunks[1:], 1):
            is_last = i == len(chunks) - 1
            await query.message.reply_text(texts.H(chunk), reply_markup=back_keyboard() if is_last else None)
    elif action == "pnl":
        chunks = await _build_realized_pnl_all()
        keyboard = back_keyboard() if len(chunks) == 1 else None
        await _show_callback(ctx, chat_id, query.message.message_id, texts.H(chunks[0]), keyboard)
        for i, chunk in enumerate(chunks[1:], 1):
            is_last = i == len(chunks) - 1
            await query.message.reply_text(texts.H(chunk), reply_markup=back_keyboard() if is_last else None)
    elif action == "new_bet":
        # Guards already ran and answered above; here we only enter the flow.
        ctx.user_data["state"] = AWAITING_BET_TITLE
        await _show_callback(ctx, chat_id, query.message.message_id,
                             texts.H(texts.ASK_BET_TITLE), _cancel_keyboard())


async def bet_type_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = await db.get_user(query.from_user.id)
    if not user or not user["is_admin"]:
        await query.answer(texts.NOT_ADMIN, show_alert=True)
        return
    await query.answer()

    pending = ctx.user_data.pop(AWAITING_BET_TYPE, {})
    title = pending.get("title", "")
    ctx.user_data.pop("state", None)

    bet_type = query.data.split(":")[1]
    chat_id = query.message.chat_id

    if bet_type == "simple":
        ctx.user_data["state"] = AWAITING_BET_ODDS
        ctx.user_data[AWAITING_BET_ODDS] = {"title": title}
        await _show_callback(ctx, chat_id, query.message.message_id,
                             texts.H(texts.ASK_BET_ODDS.format(title=title)), _cancel_keyboard())
    elif bet_type == "winner":
        ctx.user_data["state"] = AWAITING_WINNER_OPTIONS
        ctx.user_data[AWAITING_WINNER_OPTIONS] = {"title": title}
        await _show_callback(ctx, chat_id, query.message.message_id,
                             texts.H(texts.ASK_WINNER_OPTIONS.format(title=title)), _cancel_keyboard())


async def bet_side_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        await _show(ctx, query.message.chat_id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    parts = query.data.split(":")
    # Reject anything but the two expected sides: callback_data is client-supplied
    # and 'side' is written straight to wagers.side, so an allowlist keeps a
    # forged button from storing an arbitrary value.
    if len(parts) != 3 or parts[2] not in ("yes", "no") or not parts[1].isdigit():
        await query.answer("Virheellinen valinta.", show_alert=True)
        return
    _, bet_id_str, side = parts
    bet_id = int(bet_id_str)

    bet = await db.get_bet(bet_id)
    if not bet:
        await query.answer()
        await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                             texts.H(texts.BET_NOT_FOUND.format(id=bet_id)), await _main_keyboard(user))
        return
    if bet["status"] == "locked":
        await query.answer(texts.BET_LOCKED.format(id=bet_id), show_alert=True)
        return
    if bet["status"] == "resolved":
        await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
        return

    odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
    side_fi = "Kyllä" if side == "yes" else "Ei"

    existing = await db.get_user_wager(user["id"], bet_id)
    if existing and existing["side"] != side:
        await query.answer(
            "Sinulla on jo veto eri puolelle. Tee cashout ensin Omat vedot -sivulla.",
            show_alert=True,
        )
        return

    existing_amount = int(float(existing["amount"])) if existing else 0
    bet_max = int(float(bet["max_wager"]))
    bet_min = float(bet["min_wager"])
    remaining = bet_max - existing_amount
    if existing and remaining <= 0:
        await query.answer(f"Olet jo panostanut maksimin ({bet_max} €) tähän kohteeseen.", show_alert=True)
        return
    if not existing and float(user["balance"]) < bet_min:
        await query.answer(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"])), show_alert=True)
        return
    existing_info = f"\n(Nykyinen panoksesi: {existing_amount} €, voit lisätä enintään {remaining} €)" if existing else ""

    await query.answer()
    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": bet_id, "side": side, "min_wager": bet_min, "max_wager": float(bet_max)}

    amount_hint = f"vain {int(bet_min)} € vedot sallittu" if bet_min == bet_max else f"{int(bet_min)}–{int(bet_max)} €"
    await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                        texts.H(texts.ASK_AMOUNT.format(
                            bet_id=bet_id, title=bet["title"], side=side_fi, odds=odds,
                            balance=float(user["balance"]), existing=existing_info,
                            amount_hint=amount_hint,
                        )), _cancel_keyboard())


async def winner_opt_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        await _show(ctx, query.message.chat_id, texts.H("Rekisteröidy ensin komennolla /start"), main_menu_keyboard())
        return
    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    _, bet_id_str, option_id_str = query.data.split(":")
    bet_id = int(bet_id_str)
    option_id = int(option_id_str)

    bet = await db.get_bet(bet_id)
    if not bet:
        await query.answer()
        await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                             texts.H(texts.BET_NOT_FOUND.format(id=bet_id)), await _main_keyboard(user))
        return
    if bet["status"] == "locked":
        await query.answer(texts.BET_LOCKED.format(id=bet_id), show_alert=True)
        return
    if bet["status"] == "resolved":
        await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
        return

    options = await db.get_bet_options(bet_id)
    option = next((o for o in options if o["id"] == option_id), None)
    if not option:
        await query.answer("Vaihtoehtoa ei löydy.", show_alert=True)
        return

    existing = await db.get_user_wager(user["id"], bet_id)
    if existing and existing.get("option_id") != option_id:
        await query.answer(
            "Sinulla on jo veto eri vaihtoehtoon. Tee cashout ensin Omat vedot -sivulla.",
            show_alert=True,
        )
        return

    existing_amount = int(float(existing["amount"])) if existing else 0
    bet_max = int(float(bet["max_wager"]))
    bet_min = float(bet["min_wager"])
    remaining = bet_max - existing_amount
    if existing and remaining <= 0:
        await query.answer(f"Olet jo panostanut maksimin ({bet_max} €) tähän kohteeseen.", show_alert=True)
        return
    if not existing and float(user["balance"]) < bet_min:
        await query.answer(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"])), show_alert=True)
        return
    existing_info = f"\n(Nykyinen panoksesi: {existing_amount} €, voit lisätä enintään {remaining} €)" if existing else ""

    await query.answer()
    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": bet_id, "side": "opt", "option_id": option_id, "min_wager": bet_min, "max_wager": float(bet_max)}

    amount_hint = f"vain {int(bet_min)} € vedot sallittu" if bet_min == bet_max else f"{int(bet_min)}–{int(bet_max)} €"
    await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                        texts.H(texts.ASK_AMOUNT.format(
                            bet_id=bet_id, title=bet["title"], side=option["label"],
                            odds=float(option["odds"]), balance=float(user["balance"]),
                            existing=existing_info, amount_hint=amount_hint,
                        )), _cancel_keyboard())


async def cancel_wager_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show a confirmation before the irreversible cashout."""
    query = update.callback_query
    await query.answer()
    user = await db.get_user(query.from_user.id)
    if not user:
        return
    bet_id = int(query.data.split(":")[2])
    wager = await db.get_user_wager(user["id"], bet_id)
    bet = await db.get_bet(bet_id)
    if not wager or not bet or bet["status"] != "open":
        await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                             texts.H("Vetoa ei voi enää perua — kohde ei ole auki."),
                             await _main_keyboard(user))
        return
    amount = int(float(wager["amount"]))
    refund = betting.cashout_refund(amount)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Kyllä, cashout", callback_data=f"wager:cancel:{bet_id}")],
        [InlineKeyboardButton("❌ Peruuta", callback_data="nav:omat")],
    ])
    await _show_callback(
        ctx, query.message.chat_id, query.message.message_id,
        texts.H(texts.CASHOUT_CONFIRM.format(
            bet_id=bet_id, title=bet["title"], amount=amount, refund=refund,
        )),
        keyboard,
    )


async def cancel_wager_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # No early answer(): answerCallbackQuery fires once, so consuming it up front
    # would swallow every alert and the cashout toast below. Each path answers.
    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        return
    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    bet_id = int(query.data.split(":")[2])
    refunded = await db.cancel_wager(user["id"], bet_id)
    if refunded is None:
        await query.answer("Vetoa ei voi peruuttaa — kohde ei ole enää auki.", show_alert=True)
        return

    await query.answer(f"Cashout! {refunded:.0f} € palautettu saldolle (5% maksu pidätetty).")
    user = await db.get_user(query.from_user.id)
    text, keyboard = await _build_my_bets(user)
    await _show_callback(ctx, query.message.chat_id, query.message.message_id, texts.H(text), keyboard)


async def cancel_input_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    state = ctx.user_data.get("state")
    _clear_input_state(ctx)

    creation_states = (AWAITING_BET_TITLE, AWAITING_BET_ODDS, AWAITING_BET_TYPE, AWAITING_WINNER_OPTIONS)
    msg = texts.CANCEL_CREATION if state in creation_states else "❌ Peruutettu."

    user = await db.get_user(query.from_user.id)
    await _show_callback(ctx, query.message.chat_id, query.message.message_id,
                         texts.H(msg), await _main_keyboard(user))


# ── Text message router ────────────────────────────────────────────────────────

async def text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state is None:
        return
    await _delete_msg(ctx.bot, update.effective_chat.id, update.message.message_id)
    if state == AWAITING_AMOUNT:
        await _handle_amount(update, ctx)
    elif state == AWAITING_BET_TITLE:
        await _handle_bet_title(update, ctx)
    elif state == AWAITING_BET_ODDS:
        await _handle_bet_odds(update, ctx)
    elif state == AWAITING_WINNER_OPTIONS:
        await _handle_winner_options(update, ctx)
    elif state == AWAITING_WAGER_LIMITS:
        await _handle_wager_limits(update, ctx)


async def _handle_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = ctx.user_data.get(AWAITING_AMOUNT)
    if not pending:
        ctx.user_data.pop("state", None)
        return
    bet_min = pending.get("min_wager", MIN_WAGER)
    bet_max = pending.get("max_wager", MAX_WAGER)
    amount_hint = f"vain {int(bet_min)} € vedot sallittu" if bet_min == bet_max else f"{int(bet_min)}–{int(bet_max)} €"

    amount = betting.parse_wager_amount(update.message.text)
    if amount is None:
        user = await db.get_user(update.effective_user.id)
        await _show(ctx, update.effective_chat.id, texts.H(
            f"❌ Syötä kokonaisluku euroissa ({amount_hint}):\n\nSaldosi: {float(user['balance']):.0f} €"
        ), _cancel_keyboard())
        return

    user = await db.get_user(update.effective_user.id)
    option_id = pending.get("option_id")
    bet_id = pending["bet_id"]
    side = pending["side"]

    bet = await db.get_bet(bet_id)
    if not bet:
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_NOT_FOUND.format(id=bet_id)), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        ctx.user_data.pop(AWAITING_AMOUNT, None)
        return
    if bet["status"] == "locked":
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_LOCKED.format(id=bet_id)), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        ctx.user_data.pop(AWAITING_AMOUNT, None)
        return
    if bet["status"] == "resolved":
        await _show(ctx, update.effective_chat.id, texts.H(texts.BET_RESOLVED.format(id=bet_id)), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        ctx.user_data.pop(AWAITING_AMOUNT, None)
        return
    if bet["bet_type"] == "winner" and option_id is None:
        await _show(ctx, update.effective_chat.id, texts.H("❌ Tämä on voittajaveto — käytä painikkeita panostamiseen."), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        ctx.user_data.pop(AWAITING_AMOUNT, None)
        return

    bet_min = float(bet["min_wager"])
    bet_max = float(bet["max_wager"])
    min_wager = max(MIN_WAGER, bet_min)

    existing = await db.get_user_wager(user["id"], bet_id)
    existing_amount = float(existing["amount"]) if existing else 0.0

    status, new_total = betting.validate_wager(
        amount, float(user["balance"]), existing_amount, bet_min, bet_max, MIN_WAGER,
    )
    if status in (betting.WAGER_BELOW_GLOBAL_MIN, betting.WAGER_BELOW_BET_MIN):
        await _show(ctx, update.effective_chat.id, texts.H(
            f"❌ Vetosumman täytyy olla {int(min_wager):.0f}–{int(bet_max):.0f} €.\n\n"
            f"Syötä vetosumma uudelleen ({amount_hint}):\n\nSaldosi: {float(user['balance']):.0f} €"
        ), _cancel_keyboard())
        return
    if status == betting.WAGER_ABOVE_MAX:
        remaining = int(bet_max - existing_amount)
        await _show(ctx, update.effective_chat.id, texts.H(
            f"❌ Panosten maksimi on {int(bet_max)} € per kohde. "
            f"Sinulla on jo {int(existing_amount)} € panostettuna — voit lisätä enintään {remaining} €.\n\n"
            f"Syötä vetosumma uudelleen ({amount_hint}):\n\nSaldosi: {float(user['balance']):.0f} €"
        ), _cancel_keyboard())
        return
    if status == betting.WAGER_INSUFFICIENT:
        await _show(ctx, update.effective_chat.id, texts.H(
            f"{texts.NOT_ENOUGH_BALANCE.format(balance=float(user['balance']))}\n\n"
            f"Syötä vetosumma uudelleen ({amount_hint}):"
        ), _cancel_keyboard())
        return

    result = await db.place_wager(user["id"], bet_id, side, new_total, option_id=option_id)
    if result[0] is None:
        user = await db.get_user(user["telegram_id"])
        await _show(ctx, update.effective_chat.id, texts.H(
            f"{texts.NOT_ENOUGH_BALANCE.format(balance=float(user['balance']))}\n\n"
            f"Syötä vetosumma uudelleen ({amount_hint}):"
        ), _cancel_keyboard())
        return
    new_balance, updated = result

    if option_id is not None:
        options = await db.get_bet_options(bet_id)
        option = next((o for o in options if o["id"] == option_id), None)
        odds = float(option["odds"]) if option else 0
        side_fi = option["label"] if option else side
        side_icon = "🏅"
    else:
        odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
        side_fi = "Kyllä" if side == "yes" else "Ei"
        side_icon = "✅" if side == "yes" else "❌"

    payout = new_total * odds
    template = texts.WAGER_UPDATED if updated else texts.WAGER_PLACED
    user = await db.get_user(user["telegram_id"])
    await _show(ctx, update.effective_chat.id, texts.H(template.format(
        bet_id=bet_id, title=bet["title"], side=side_fi, side_icon=side_icon,
        amount=new_total, odds=odds, payout=payout, balance=new_balance,
    )), await _main_keyboard(user))
    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_AMOUNT, None)


async def _handle_bet_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        return

    title = update.message.text.strip()
    if not title:
        await _show(ctx, update.effective_chat.id, texts.H(texts.ASK_BET_TITLE), _cancel_keyboard())
        return

    ctx.user_data["state"] = AWAITING_BET_TYPE
    ctx.user_data[AWAITING_BET_TYPE] = {"title": title}

    await _show(ctx, update.effective_chat.id, texts.H(texts.ASK_BET_TYPE.format(title=title)), _bet_type_keyboard())


async def _handle_bet_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        return

    pending = ctx.user_data.get(AWAITING_BET_ODDS, {})
    title = pending.get("title", "")

    parts = update.message.text.strip().replace(",", ".").split()
    try:
        if len(parts) != 2:
            raise ValueError
        yes_odds = float(parts[0])
        no_odds = float(parts[1])
        if not (1.0 < yes_odds <= MAX_ODDS) or not (1.0 < no_odds <= MAX_ODDS):
            raise ValueError
    except ValueError:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_ODDS), _cancel_keyboard())
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_BET_ODDS, None)

    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    await _show(ctx, update.effective_chat.id, texts.H(texts.BET_CREATED.format(
        id=bet["id"], title=bet["title"],
        yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
    )), await _main_keyboard(user))


async def _handle_winner_options(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        return

    pending = ctx.user_data.get(AWAITING_WINNER_OPTIONS, {})
    title = pending.get("title", "")

    lines = [ln.strip() for ln in update.message.text.strip().split("|") if ln.strip()]
    options = []
    for line in lines:
        if "@" not in line:
            await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_WINNER_OPTIONS), _cancel_keyboard())
            return
        parts = line.rsplit("@", 1)
        label = parts[0].strip()
        try:
            odds = float(parts[1].strip().replace(",", "."))
            if not (1.0 < odds <= MAX_ODDS) or not label:
                raise ValueError
        except ValueError:
            await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_WINNER_OPTIONS), _cancel_keyboard())
            return
        options.append({"label": label, "odds": odds})

    if len(options) < 2:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_WINNER_OPTIONS), _cancel_keyboard())
        return

    if len(options) > MAX_WINNER_OPTIONS:
        await _show(ctx, update.effective_chat.id, texts.H(texts.TOO_MANY_WINNER_OPTIONS.format(max=MAX_WINNER_OPTIONS)), _cancel_keyboard())
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_WINNER_OPTIONS, None)

    bet = await db.create_winner_bet(title, options, user["id"])
    options_text = "".join(f"🏅 {o['label']} @ {float(o['odds']):.2f}\n" for o in bet["options"])
    await _show(ctx, update.effective_chat.id, texts.H(texts.WINNER_BET_CREATED.format(id=bet["id"], title=bet["title"], options=options_text)), await _main_keyboard(user))


async def _handle_wager_limits(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user or not user["is_admin"]:
        await _show(ctx, update.effective_chat.id, texts.H(texts.NOT_ADMIN), await _main_keyboard(user))
        ctx.user_data.pop("state", None)
        return

    pending = ctx.user_data.get(AWAITING_WAGER_LIMITS)
    if not pending:
        ctx.user_data.pop("state", None)
        return

    parts = update.message.text.strip().replace(",", ".").split()
    try:
        if len(parts) != 2:
            raise ValueError
        new_min = float(parts[0])
        new_max = float(parts[1])
        if new_min != int(new_min) or new_max != int(new_max):
            raise ValueError
        new_min = float(int(new_min))
        new_max = float(int(new_max))
        if new_min < MIN_WAGER or new_max > MAX_WAGER or new_min > new_max:
            raise ValueError
    except ValueError:
        await _show(ctx, update.effective_chat.id, texts.H(texts.INVALID_WAGER_LIMITS), _cancel_keyboard())
        return

    bet_id = pending["bet_id"]
    updated = await db.set_bet_wager_limits(bet_id, new_min, new_max)

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_WAGER_LIMITS, None)

    bet = await db.get_bet(bet_id)
    if not updated or not bet:
        await _show(ctx, update.effective_chat.id, texts.H("❌ Panosrajojen asetus epäonnistui. Kohde ei ehkä ole enää muokattavissa."), await _main_keyboard(user))
        return

    await _show(ctx, update.effective_chat.id, texts.H(texts.WAGER_LIMITS_SET.format(id=bet_id, title=bet["title"], min=new_min, max=new_max)), await _main_keyboard(user))


async def _process_wager(ctx, chat_id, user, bet_id: int, side: str, amount: float,
                         is_admin=False, option_id=None):
    bet = await db.get_bet(bet_id)
    if not bet:
        await _show(ctx, chat_id, texts.H(texts.BET_NOT_FOUND.format(id=bet_id)), await _main_keyboard(user))
        return False
    if bet["status"] == "locked":
        await _show(ctx, chat_id, texts.H(texts.BET_LOCKED.format(id=bet_id)), await _main_keyboard(user))
        return False
    if bet["status"] == "resolved":
        await _show(ctx, chat_id, texts.H(texts.BET_RESOLVED.format(id=bet_id)), await _main_keyboard(user))
        return False
    if bet["bet_type"] == "winner" and option_id is None:
        await _show(ctx, chat_id, texts.H("❌ Tämä on voittajaveto — käytä painikkeita panostamiseen."), await _main_keyboard(user))
        return False

    bet_min = float(bet["min_wager"])
    bet_max = float(bet["max_wager"])
    existing = await db.get_user_wager(user["id"], bet_id)
    existing_amount = float(existing["amount"]) if existing else 0.0

    status, new_total = betting.validate_wager(
        amount, float(user["balance"]), existing_amount, bet_min, bet_max, MIN_WAGER,
    )
    if status == betting.WAGER_BELOW_GLOBAL_MIN:
        await _show(ctx, chat_id, texts.H(texts.MAX_WAGER_EXCEEDED.format(min=MIN_WAGER, max=MAX_WAGER)), _cancel_keyboard())
        return True
    if status == betting.WAGER_BELOW_BET_MIN:
        await _show(ctx, chat_id, texts.H(texts.MAX_WAGER_EXCEEDED.format(min=bet_min, max=bet_max)), _cancel_keyboard())
        return True
    if status == betting.WAGER_ABOVE_MAX:
        remaining = int(bet_max - existing_amount)
        await _show(ctx, chat_id, texts.H(
            f"❌ Panosten maksimi on {int(bet_max)} € per kohde. "
            f"Sinulla on jo {int(existing_amount)} € panostettuna — voit lisätä enintään {remaining} €."
        ), _cancel_keyboard())
        return True
    if status == betting.WAGER_INSUFFICIENT:
        await _show(ctx, chat_id, texts.H(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"]))), _cancel_keyboard())
        return True

    result = await db.place_wager(user["id"], bet_id, side, new_total, option_id=option_id)
    if result[0] is None:
        user = await db.get_user(user["telegram_id"])
        await _show(ctx, chat_id, texts.H(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"]))), _cancel_keyboard())
        return True
    new_balance, updated = result

    if option_id is not None:
        options = await db.get_bet_options(bet_id)
        option = next((o for o in options if o["id"] == option_id), None)
        odds = float(option["odds"]) if option else 0
        side_fi = option["label"] if option else side
        side_icon = "🏅"
    else:
        odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
        side_fi = "Kyllä" if side == "yes" else "Ei"
        side_icon = "✅" if side == "yes" else "❌"

    payout = new_total * odds
    template = texts.WAGER_UPDATED if updated else texts.WAGER_PLACED
    user = await db.get_user(user["telegram_id"])
    await _show(ctx, chat_id, texts.H(template.format(
        bet_id=bet_id, title=bet["title"], side=side_fi, side_icon=side_icon,
        amount=new_total, odds=odds, payout=payout, balance=new_balance,
    )), await _main_keyboard(user))
    return False


