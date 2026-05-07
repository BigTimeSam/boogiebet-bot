from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from telegram.ext import ContextTypes
import db
import texts

# user_data state keys
AWAITING_AMOUNT = "awaiting_amount"
AWAITING_BET_TITLE = "awaiting_bet_title"
AWAITING_BET_ODDS = "awaiting_bet_odds"


def main_menu_keyboard(is_admin=False):
    rows = [
        [
            InlineKeyboardButton("📋 Kohteet", callback_data="nav:kohteet"),
            InlineKeyboardButton("🎯 Omat vedot", callback_data="nav:omat"),
        ],
        [
            InlineKeyboardButton("🏆 Tulostaulu", callback_data="nav:tulokset"),
            InlineKeyboardButton("💰 Saldo", callback_data="nav:saldo"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🔧 Admin-paneeli", callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")]])


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user, created = await db.get_or_create_user(tg.id, tg.username or tg.first_name)
    template = texts.WELCOME_NEW if created else texts.WELCOME_BACK
    await update.message.reply_text(
        template.format(name=tg.first_name, balance=float(user["balance"])),
        reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
    )


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    is_admin = user["is_admin"] if user else False
    await update.message.reply_text(
        texts.HELP_TEXT,
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def saldo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return
    await update.message.reply_text(texts.BALANCE.format(balance=float(user["balance"])))


async def kohteet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return
    text, keyboard = await _build_kohteet(user)
    await update.message.reply_text(text, reply_markup=keyboard)


async def omat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return
    text, keyboard = await _build_omat(user)
    await update.message.reply_text(text, reply_markup=keyboard)


async def tulokset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await _build_tulokset()
    await update.message.reply_text(text)


async def vetoa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Text command fallback: /vetoa <id> <kyllä|ei> <summa>"""
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return

    if await db.is_game_finished():
        await update.message.reply_text(texts.GAME_OVER_BLOCK)
        return

    args = ctx.args
    if len(args) != 3:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>"))
        return

    try:
        bet_id = int(args[0])
    except ValueError:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>"))
        return

    side_input = args[1].lower()
    if side_input not in ("kyllä", "kylla", "ei"):
        await update.message.reply_text(texts.INVALID_SIDE)
        return
    side = "yes" if side_input in ("kyllä", "kylla") else "no"

    try:
        amount = float(args[2].replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.INVALID_AMOUNT)
        return

    await _process_wager(update.message, user, bet_id, side, amount)


async def uusiveto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Text command: /uusiveto otsikko | kyllä_kerroin ei_kerroin"""
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return

    if await db.is_game_finished():
        await update.message.reply_text(texts.GAME_OVER_BLOCK)
        return

    text = " ".join(ctx.args)
    if "|" not in text:
        await update.message.reply_text(
            texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")
        )
        return

    parts = text.split("|", 1)
    title = parts[0].strip()
    odds_part = parts[1].strip().split()

    if not title or len(odds_part) != 2:
        await update.message.reply_text(
            texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")
        )
        return

    try:
        yes_odds = float(odds_part[0].replace(",", "."))
        no_odds = float(odds_part[1].replace(",", "."))
        if yes_odds <= 1.0 or no_odds <= 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.INVALID_ODDS)
        return

    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    await update.message.reply_text(texts.BET_CREATED.format(
        id=bet["id"], title=bet["title"],
        yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
    ))


async def poistakohde(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Text command: /poistakohde <id>"""
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Rekisteröidy ensin komennolla /start")
        return

    if await db.is_game_finished():
        await update.message.reply_text(texts.GAME_OVER_BLOCK)
        return

    if not ctx.args:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/poistakohde <id>"))
        return

    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.INVALID_COMMAND.format(usage="/poistakohde <id>"))
        return

    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.BET_NOT_FOUND.format(id=bet_id))
        return

    deleted = await db.delete_bet(bet_id)
    if deleted:
        await update.message.reply_text(texts.BET_DELETED.format(id=bet_id))
    else:
        await update.message.reply_text(texts.BET_DELETE_FORBIDDEN)


# ── Callback handlers ──────────────────────────────────────────────────────────

async def nav_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.message.reply_text("Rekisteröidy ensin komennolla /start")
        return

    action = query.data.split(":", 1)[1]

    if action == "main":
        await query.message.edit_text(
            texts.WELCOME_BACK.format(name=query.from_user.first_name, balance=float(user["balance"])),
            reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
        )
    elif action == "saldo":
        await query.message.edit_text(
            texts.BALANCE.format(balance=float(user["balance"])),
            reply_markup=back_keyboard(),
        )
    elif action == "kohteet":
        text, keyboard = await _build_kohteet(user)
        await query.message.edit_text(text, reply_markup=keyboard)
    elif action == "omat":
        text, keyboard = await _build_omat(user)
        await query.message.edit_text(text, reply_markup=keyboard)
    elif action == "tulokset":
        text = await _build_tulokset()
        await query.message.edit_text(text, reply_markup=back_keyboard())
    elif action == "new_bet":
        if await db.is_game_finished():
            await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
            return
        ctx.user_data["state"] = AWAITING_BET_TITLE
        await query.message.reply_text(
            texts.ASK_BET_TITLE,
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. Voittaako Suomi?"),
        )


async def bet_side_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.message.reply_text("Rekisteröidy ensin komennolla /start")
        return

    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    _, bet_id_str, side = query.data.split(":")
    bet_id = int(bet_id_str)

    bet = await db.get_bet(bet_id)
    if not bet:
        await query.message.reply_text(texts.BET_NOT_FOUND.format(id=bet_id))
        return
    if bet["status"] == "locked":
        await query.answer(texts.BET_LOCKED.format(id=bet_id), show_alert=True)
        return
    if bet["status"] == "resolved":
        await query.answer(texts.BET_RESOLVED.format(id=bet_id), show_alert=True)
        return

    odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
    side_fi = "kyllä" if side == "yes" else "ei"

    existing = await db.get_user_wager(user["id"], bet_id)
    existing_info = ""
    if existing:
        ex_side = "kyllä" if existing["side"] == "yes" else "ei"
        existing_info = f"\n(Nykyinen vetosi: {ex_side} {float(existing['amount']):.2f} €)"

    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": bet_id, "side": side}

    await query.message.reply_text(
        texts.ASK_AMOUNT.format(
            bet_id=bet_id, title=bet["title"], side=side_fi, odds=odds,
            balance=float(user["balance"]), existing=existing_info,
        ),
        reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 100"),
    )


async def delete_bet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user:
        return

    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    bet_id = int(query.data.split(":")[1])
    bet = await db.get_bet(bet_id)
    if not bet:
        await query.answer("Kohdetta ei löydy.", show_alert=True)
        return

    deleted = await db.delete_bet(bet_id)
    if deleted:
        await query.answer(f"Vetokohde #{bet_id} poistettu.")
        # Refresh the kohteet view
        text, keyboard = await _build_kohteet(user)
        await query.message.edit_text(text, reply_markup=keyboard)
    else:
        await query.answer(texts.BET_DELETE_FORBIDDEN, show_alert=True)


# ── Text message router ────────────────────────────────────────────────────────

async def text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state == AWAITING_AMOUNT:
        await _handle_amount(update, ctx)
    elif state == AWAITING_BET_TITLE:
        await _handle_bet_title(update, ctx)
    elif state == AWAITING_BET_ODDS:
        await _handle_bet_odds(update, ctx)


async def _handle_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = ctx.user_data.get(AWAITING_AMOUNT)
    if not pending:
        ctx.user_data.pop("state", None)
        return

    try:
        amount = float(update.message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.INVALID_AMOUNT)
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_AMOUNT, None)

    user = await db.get_user(update.effective_user.id)
    await _process_wager(update.message, user, pending["bet_id"], pending["side"], amount, is_admin=user["is_admin"])


async def _handle_bet_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text(texts.ASK_BET_TITLE,
            reply_markup=ForceReply(selective=True))
        return

    ctx.user_data["state"] = AWAITING_BET_ODDS
    ctx.user_data[AWAITING_BET_ODDS] = {"title": title}

    await update.message.reply_text(
        texts.ASK_BET_ODDS.format(title=title),
        reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 3.50 1.25"),
    )


async def _handle_bet_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = ctx.user_data.get(AWAITING_BET_ODDS, {})
    title = pending.get("title", "")

    parts = update.message.text.strip().replace(",", ".").split()
    try:
        if len(parts) != 2:
            raise ValueError
        yes_odds = float(parts[0])
        no_odds = float(parts[1])
        if yes_odds <= 1.0 or no_odds <= 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.INVALID_ODDS)
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_BET_ODDS, None)

    user = await db.get_user(update.effective_user.id)
    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    await update.message.reply_text(
        texts.BET_CREATED.format(
            id=bet["id"], title=bet["title"],
            yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
        ),
        reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
    )


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _process_wager(message, user, bet_id: int, side: str, amount: float, is_admin=False):
    bet = await db.get_bet(bet_id)
    if not bet:
        await message.reply_text(texts.BET_NOT_FOUND.format(id=bet_id))
        return
    if bet["status"] == "locked":
        await message.reply_text(texts.BET_LOCKED.format(id=bet_id))
        return
    if bet["status"] == "resolved":
        await message.reply_text(texts.BET_RESOLVED.format(id=bet_id))
        return

    existing = await db.get_user_wager(user["id"], bet_id)
    refund = float(existing["amount"]) if existing else 0.0
    available = float(user["balance"]) + refund

    if amount > available:
        await message.reply_text(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"])))
        return

    new_balance, updated = await db.place_wager(user["id"], bet_id, side, amount)
    odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
    side_fi = "kyllä" if side == "yes" else "ei"
    payout = amount * odds

    template = texts.WAGER_UPDATED if updated else texts.WAGER_PLACED
    await message.reply_text(
        template.format(bet_id=bet_id, side=side_fi, amount=amount, odds=odds, payout=payout, balance=new_balance),
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def _build_kohteet(user):
    game_done = await db.is_game_finished()
    bets = await db.get_active_bets()
    my_wagers = {w["bet_id"]: w for w in await db.get_user_wagers_with_bets(user["id"])}

    bottom_row = []
    if not game_done:
        bottom_row.append(InlineKeyboardButton("➕ Uusi kohde", callback_data="nav:new_bet"))
    bottom_row.append(InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main"))

    if not bets:
        return texts.NO_BETS, InlineKeyboardMarkup([bottom_row])

    msg = texts.BET_LIST_HEADER
    keyboard = []

    for b in bets:
        w = my_wagers.get(b["id"])
        is_open = b["status"] == "open"

        if is_open:
            if w:
                side_fi = "kyllä" if w["side"] == "yes" else "ei"
                msg += texts.BET_ROW_OPEN_WITH_WAGER.format(
                    id=b["id"], title=b["title"],
                    yes_odds=float(b["yes_odds"]), no_odds=float(b["no_odds"]),
                    side=side_fi, amount=float(w["amount"]),
                )
            else:
                msg += texts.BET_ROW_OPEN.format(
                    id=b["id"], title=b["title"],
                    yes_odds=float(b["yes_odds"]), no_odds=float(b["no_odds"]),
                )
            if not game_done:
                row = [
                    InlineKeyboardButton(f"✅ Kyllä {float(b['yes_odds']):.2f}", callback_data=f"bet:{b['id']}:yes"),
                    InlineKeyboardButton(f"❌ Ei {float(b['no_odds']):.2f}", callback_data=f"bet:{b['id']}:no"),
                    InlineKeyboardButton("🗑️", callback_data=f"del:{b['id']}"),
                ]
                keyboard.append(row)
        else:
            # locked
            if w:
                side_fi = "kyllä" if w["side"] == "yes" else "ei"
                msg += texts.BET_ROW_LOCKED_WITH_WAGER.format(
                    id=b["id"], title=b["title"],
                    yes_odds=float(b["yes_odds"]), no_odds=float(b["no_odds"]),
                    side=side_fi, amount=float(w["amount"]),
                )
            else:
                msg += texts.BET_ROW_LOCKED.format(
                    id=b["id"], title=b["title"],
                    yes_odds=float(b["yes_odds"]), no_odds=float(b["no_odds"]),
                )

    keyboard.append(bottom_row)
    return msg, InlineKeyboardMarkup(keyboard)


async def cancel_wager_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user:
        return

    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    bet_id = int(query.data.split(":")[2])
    refunded = await db.cancel_wager(user["id"], bet_id)
    if refunded is None:
        await query.answer("Vetoa ei voi peruuttaa — kohde ei ole enää auki.", show_alert=True)
        return

    await query.answer(f"Veto peruutettu, {refunded:.2f} € palautettu saldolle.")
    user = await db.get_user(query.from_user.id)
    text, keyboard = await _build_omat(user)
    await query.message.edit_text(text, reply_markup=keyboard)


async def _build_omat(user):
    wagers = await db.get_user_wagers_with_bets(user["id"])
    if not wagers:
        return texts.NO_WAGERS, back_keyboard()

    status_map = {"open": "avoinna", "locked": "lukittu", "resolved": "ratkaistu"}
    msg = texts.MY_WAGERS_HEADER
    keyboard = []
    for w in wagers:
        side_fi = "kyllä" if w["side"] == "yes" else "ei"
        odds = float(w["yes_odds"]) if w["side"] == "yes" else float(w["no_odds"])
        msg += texts.WAGER_ROW.format(
            bet_id=w["bet_id"], title=w["title"], side=side_fi,
            amount=float(w["amount"]), odds=odds,
            status=status_map.get(w["status"], w["status"]),
        )
        if w["status"] == "open":
            label = f"🗑️ Peruuta #{w['bet_id']} {w['title'][:25]}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"wager:cancel:{w['bet_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")])
    return msg, InlineKeyboardMarkup(keyboard)


async def _build_tulokset():
    rows = await db.get_leaderboard()
    if not rows:
        return "Ei pelaajia vielä."

    game_done = await db.is_game_finished()
    header = texts.GAME_FINISHED_HEADER if game_done else texts.LEADERBOARD_HEADER
    msg = header
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        msg += texts.LEADERBOARD_ROW.format(rank=i, username=name, balance=float(row["balance"]))
    if game_done:
        msg += texts.GAME_FINISHED_NOTICE
    return msg
