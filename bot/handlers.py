from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from telegram.ext import ContextTypes
import db
import texts

# user_data state keys
AWAITING_AMOUNT = "awaiting_amount"
AWAITING_BET_TITLE = "awaiting_bet_title"
AWAITING_BET_TYPE = "awaiting_bet_type"
AWAITING_BET_ODDS = "awaiting_bet_odds"
AWAITING_WINNER_OPTIONS = "awaiting_winner_options"

MIN_WAGER = 20.0
MAX_WAGER = 200.0


def main_menu_keyboard(is_admin=False):
    rows = [
        [
            InlineKeyboardButton("📋 Kohteet", callback_data="nav:kohteet"),
            InlineKeyboardButton("🎯 Omat vedot", callback_data="nav:omat"),
        ],
        [
            InlineKeyboardButton("🏆 Tulostaulu", callback_data="nav:tulokset"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("🔧 Admin-paneeli", callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")]])


def _bet_type_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⚖️ Kyllä / Ei", callback_data="bet_type:simple"),
        InlineKeyboardButton("🏆 Voittajaveto", callback_data="bet_type:winner"),
    ]])


async def _main_text(user, name: str = None, is_new: bool = False) -> str:
    balance = float(user["balance"])
    if is_new and name:
        base = texts.WELCOME_NEW.format(name=name, balance=balance)
    else:
        base = texts.WELCOME_BACK.format(balance=balance)
    wagered, payout = await db.get_user_open_wager_stats(user["id"])
    if wagered > 0:
        base += "\n" + texts.WAGER_STATS.format(wagered=wagered, potential=balance + payout)
    return base


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    user, created = await db.get_or_create_user(tg.id, tg.username or tg.first_name)
    await update.message.reply_text(
        texts.H(await _main_text(user, name=tg.first_name, is_new=created)),
        reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
    )


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    is_admin = user["is_admin"] if user else False
    await update.message.reply_text(
        texts.H(texts.HELP_TEXT),
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def saldo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    await update.message.reply_text(texts.H(texts.BALANCE.format(balance=float(user["balance"]))))


async def kohteet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    text, keyboard = await _build_kohteet(user)
    await update.message.reply_text(texts.H(text), reply_markup=keyboard)


async def omat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    text, keyboard = await _build_omat(user)
    await update.message.reply_text(texts.H(text), reply_markup=keyboard)


async def tulokset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await _build_tulokset()
    await update.message.reply_text(texts.H(text))


async def vetoa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    if await db.is_game_finished():
        await update.message.reply_text(texts.H(texts.GAME_OVER_BLOCK))
        return
    args = ctx.args
    if len(args) != 3:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>")))
        return
    try:
        bet_id = int(args[0])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/vetoa <id> <kyllä|ei> <summa>")))
        return
    side_input = args[1].lower()
    if side_input not in ("kyllä", "kylla", "ei"):
        await update.message.reply_text(texts.H(texts.INVALID_SIDE))
        return
    side = "yes" if side_input in ("kyllä", "kylla") else "no"
    try:
        amount = float(args[2].replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_AMOUNT))
        return
    await _process_wager(update.message, user, bet_id, side, amount)


async def uusiveto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    if not user["is_admin"]:
        await update.message.reply_text(texts.H(texts.NOT_ADMIN))
        return
    if await db.is_game_finished():
        await update.message.reply_text(texts.H(texts.GAME_OVER_BLOCK))
        return
    text = " ".join(ctx.args)
    if "|" not in text:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")))
        return
    parts = text.split("|", 1)
    title = parts[0].strip()
    odds_part = parts[1].strip().split()
    if not title or len(odds_part) != 2:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/uusiveto <otsikko> | <kyllä_kerroin> <ei_kerroin>")))
        return
    try:
        yes_odds = float(odds_part[0].replace(",", "."))
        no_odds = float(odds_part[1].replace(",", "."))
        if yes_odds <= 1.0 or no_odds <= 1.0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_ODDS))
        return
    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    await update.message.reply_text(texts.H(texts.BET_CREATED.format(
        id=bet["id"], title=bet["title"],
        yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
    )))


async def poistakohde(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    if await db.is_game_finished():
        await update.message.reply_text(texts.H(texts.GAME_OVER_BLOCK))
        return
    if not ctx.args:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/poistakohde <id>")))
        return
    try:
        bet_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text(texts.H(texts.INVALID_COMMAND.format(usage="/poistakohde <id>")))
        return
    bet = await db.get_bet(bet_id)
    if not bet:
        await update.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
        return
    deleted = await db.delete_bet(bet_id)
    if deleted:
        await update.message.reply_text(texts.H(texts.BET_DELETED.format(id=bet_id)))
    else:
        await update.message.reply_text(texts.H(texts.BET_DELETE_FORBIDDEN))


# ── Callback handlers ──────────────────────────────────────────────────────────

async def noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def nav_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return

    action = query.data.split(":", 1)[1]

    if action == "main":
        await query.message.edit_text(
            texts.H(await _main_text(user)),
            reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
        )
    elif action == "saldo":
        await query.message.edit_text(
            texts.H(texts.BALANCE.format(balance=float(user["balance"]))),
            reply_markup=back_keyboard(),
        )
    elif action == "kohteet":
        text, keyboard = await _build_kohteet(user)
        await query.message.edit_text(texts.H(text), reply_markup=keyboard)
    elif action == "omat":
        text, keyboard = await _build_omat(user)
        await query.message.edit_text(texts.H(text), reply_markup=keyboard)
    elif action == "tulokset":
        text = await _build_tulokset()
        await query.message.edit_text(texts.H(text), reply_markup=back_keyboard())
    elif action == "new_bet":
        if not user["is_admin"]:
            await query.answer(texts.NOT_ADMIN, show_alert=True)
            return
        if await db.is_game_finished():
            await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
            return
        ctx.user_data["state"] = AWAITING_BET_TITLE
        await query.message.reply_text(
            texts.H(texts.ASK_BET_TITLE),
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. Lanimestaruuden voittava kapteenipari?"),
        )


async def bet_type_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending = ctx.user_data.pop(AWAITING_BET_TYPE, {})
    title = pending.get("title", "")
    ctx.user_data.pop("state", None)

    bet_type = query.data.split(":")[1]

    if bet_type == "simple":
        ctx.user_data["state"] = AWAITING_BET_ODDS
        ctx.user_data[AWAITING_BET_ODDS] = {"title": title}
        await query.message.reply_text(
            texts.H(texts.ASK_BET_ODDS.format(title=title)),
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 3.50 1.25"),
        )
    elif bet_type == "winner":
        ctx.user_data["state"] = AWAITING_WINNER_OPTIONS
        ctx.user_data[AWAITING_WINNER_OPTIONS] = {"title": title}
        await query.message.reply_text(
            texts.H(texts.ASK_WINNER_OPTIONS.format(title=title)),
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. Osmo & Markulov @ 2.80 | Zyrk & Kipe @ 2.50 | Damu & Koala @ 3.00 | Johkis & Winkzi @ 2.75"),
        )


async def bet_side_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        await query.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
        return
    if await db.is_game_finished():
        await query.answer(texts.GAME_OVER_BLOCK, show_alert=True)
        return

    _, bet_id_str, side = query.data.split(":")
    bet_id = int(bet_id_str)

    bet = await db.get_bet(bet_id)
    if not bet:
        await query.answer()
        await query.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
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
    remaining = int(MAX_WAGER) - existing_amount
    if existing and remaining <= 0:
        await query.answer(f"Olet jo panostanut maksimin ({int(MAX_WAGER)} €) tähän kohteeseen.", show_alert=True)
        return
    existing_info = f"\n(Nykyinen panoksesi: {existing_amount} €, voit lisätä enintään {remaining} €)" if existing else ""

    await query.answer()
    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": bet_id, "side": side}

    await query.message.reply_text(
        texts.H(texts.ASK_AMOUNT.format(
            bet_id=bet_id, title=bet["title"], side=side_fi, odds=odds,
            balance=float(user["balance"]), existing=existing_info,
            min=MIN_WAGER, max=MAX_WAGER,
        )),
        reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 100"),
    )


async def winner_opt_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    user = await db.get_user(query.from_user.id)
    if not user:
        await query.answer()
        await query.message.reply_text(texts.H("Rekisteröidy ensin komennolla /start"))
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
        await query.message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
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
    remaining = int(MAX_WAGER) - existing_amount
    if existing and remaining <= 0:
        await query.answer(f"Olet jo panostanut maksimin ({int(MAX_WAGER)} €) tähän kohteeseen.", show_alert=True)
        return
    existing_info = f"\n(Nykyinen panoksesi: {existing_amount} €, voit lisätä enintään {remaining} €)" if existing else ""

    await query.answer()
    ctx.user_data["state"] = AWAITING_AMOUNT
    ctx.user_data[AWAITING_AMOUNT] = {"bet_id": bet_id, "side": "opt", "option_id": option_id}

    await query.message.reply_text(
        texts.H(texts.ASK_AMOUNT.format(
            bet_id=bet_id, title=bet["title"], side=option["label"],
            odds=float(option["odds"]), balance=float(user["balance"]),
            existing=existing_info, min=MIN_WAGER, max=MAX_WAGER,
        )),
        reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 100"),
    )



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

    await query.answer(f"Cashout! {refunded:.2f} € palautettu saldolle (5% maksu pidätetty).")
    user = await db.get_user(query.from_user.id)
    text, keyboard = await _build_omat(user)
    await query.message.edit_text(texts.H(text), reply_markup=keyboard)


# ── Text message router ────────────────────────────────────────────────────────

async def text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    if state == AWAITING_AMOUNT:
        await _handle_amount(update, ctx)
    elif state == AWAITING_BET_TITLE:
        await _handle_bet_title(update, ctx)
    elif state == AWAITING_BET_ODDS:
        await _handle_bet_odds(update, ctx)
    elif state == AWAITING_WINNER_OPTIONS:
        await _handle_winner_options(update, ctx)


async def _handle_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = ctx.user_data.get(AWAITING_AMOUNT)
    if not pending:
        ctx.user_data.pop("state", None)
        return
    try:
        amount = float(update.message.text.strip().replace(",", "."))
        if amount != int(amount) or amount <= 0:
            raise ValueError
        amount = float(int(amount))
    except ValueError:
        await update.message.reply_text(
            texts.H(texts.INVALID_AMOUNT),
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 100"),
        )
        return

    user = await db.get_user(update.effective_user.id)
    option_id = pending.get("option_id")
    retryable = await _process_wager(
        update.message, user, pending["bet_id"], pending["side"], amount,
        is_admin=user["is_admin"], option_id=option_id,
    )
    if retryable:
        await update.message.reply_text(
            reply_markup=ForceReply(selective=True, input_field_placeholder="esim. 100"),
            text=texts.H(f"Syötä vetosumma euroissa ({int(MIN_WAGER)}–{int(MAX_WAGER)} €):"),
        )
    else:
        ctx.user_data.pop("state", None)
        ctx.user_data.pop(AWAITING_AMOUNT, None)


async def _handle_bet_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text(
            texts.H(texts.ASK_BET_TITLE),
            reply_markup=ForceReply(selective=True),
        )
        return

    ctx.user_data["state"] = AWAITING_BET_TYPE
    ctx.user_data[AWAITING_BET_TYPE] = {"title": title}

    await update.message.reply_text(
        texts.H(texts.ASK_BET_TYPE.format(title=title)),
        reply_markup=_bet_type_keyboard(),
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
        await update.message.reply_text(texts.H(texts.INVALID_ODDS))
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_BET_ODDS, None)

    user = await db.get_user(update.effective_user.id)
    bet = await db.create_bet(title, yes_odds, no_odds, user["id"])
    await update.message.reply_text(
        texts.H(texts.BET_CREATED.format(
            id=bet["id"], title=bet["title"],
            yes_odds=float(bet["yes_odds"]), no_odds=float(bet["no_odds"]),
        )),
        reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
    )


async def _handle_winner_options(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = ctx.user_data.get(AWAITING_WINNER_OPTIONS, {})
    title = pending.get("title", "")

    lines = [l.strip() for l in update.message.text.strip().split("|") if l.strip()]
    options = []
    for line in lines:
        if "@" not in line:
            await update.message.reply_text(texts.H(texts.INVALID_WINNER_OPTIONS))
            return
        parts = line.rsplit("@", 1)
        label = parts[0].strip()
        try:
            odds = float(parts[1].strip().replace(",", "."))
            if odds <= 1.0 or not label:
                raise ValueError
        except ValueError:
            await update.message.reply_text(texts.H(texts.INVALID_WINNER_OPTIONS))
            return
        options.append({"label": label, "odds": odds})

    if len(options) < 2:
        await update.message.reply_text(texts.H(texts.INVALID_WINNER_OPTIONS))
        return

    ctx.user_data.pop("state", None)
    ctx.user_data.pop(AWAITING_WINNER_OPTIONS, None)

    user = await db.get_user(update.effective_user.id)
    bet = await db.create_winner_bet(title, options, user["id"])
    options_text = "".join(f"🏅 {o['label']} @ {float(o['odds']):.2f}\n" for o in bet["options"])
    await update.message.reply_text(
        texts.H(texts.WINNER_BET_CREATED.format(id=bet["id"], title=bet["title"], options=options_text)),
        reply_markup=main_menu_keyboard(is_admin=user["is_admin"]),
    )


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _process_wager(message, user, bet_id: int, side: str, amount: float,
                         is_admin=False, option_id: int = None):
    """Returns True if a retryable validation error occurred, False otherwise."""
    bet = await db.get_bet(bet_id)
    if not bet:
        await message.reply_text(texts.H(texts.BET_NOT_FOUND.format(id=bet_id)))
        return False
    if bet["status"] == "locked":
        await message.reply_text(texts.H(texts.BET_LOCKED.format(id=bet_id)))
        return False
    if bet["status"] == "resolved":
        await message.reply_text(texts.H(texts.BET_RESOLVED.format(id=bet_id)))
        return False

    if amount < MIN_WAGER:
        await message.reply_text(texts.H(texts.MAX_WAGER_EXCEEDED.format(min=MIN_WAGER, max=MAX_WAGER)))
        return True

    existing = await db.get_user_wager(user["id"], bet_id)
    existing_amount = float(existing["amount"]) if existing else 0.0
    new_total = existing_amount + amount

    if new_total > MAX_WAGER:
        remaining = int(MAX_WAGER - existing_amount)
        await message.reply_text(texts.H(
            f"❌ Panosten maksimi on {int(MAX_WAGER)} € per kohde. "
            f"Sinulla on jo {int(existing_amount)} € panostettuna — voit lisätä enintään {remaining} €."
        ))
        return True

    if amount > float(user["balance"]):
        await message.reply_text(texts.H(texts.NOT_ENOUGH_BALANCE.format(balance=float(user["balance"]))))
        return True

    new_balance, updated = await db.place_wager(user["id"], bet_id, side, new_total, option_id=option_id)

    if option_id is not None:
        options = await db.get_bet_options(bet_id)
        option = next((o for o in options if o["id"] == option_id), None)
        odds = float(option["odds"]) if option else 0
        side_fi = option["label"] if option else side
    else:
        odds = float(bet["yes_odds"]) if side == "yes" else float(bet["no_odds"])
        side_fi = "Kyllä" if side == "yes" else "Ei"

    payout = new_total * odds
    template = texts.WAGER_UPDATED if updated else texts.WAGER_PLACED
    await message.reply_text(
        texts.H(template.format(bet_id=bet_id, side=side_fi, amount=new_total, odds=odds, payout=payout, balance=new_balance)),
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )
    return False


async def _build_kohteet(user):
    game_done = await db.is_game_finished()
    bets = await db.get_active_bets()
    my_wagers = {w["bet_id"]: w for w in await db.get_user_wagers_with_bets(user["id"])}

    bottom_row = []
    if not game_done and user["is_admin"]:
        bottom_row.append(InlineKeyboardButton("➕ Uusi kohde", callback_data="nav:new_bet"))
    bottom_row.append(InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main"))

    if not bets:
        return texts.NO_BETS, InlineKeyboardMarkup([bottom_row])

    msg = texts.BET_LIST_HEADER
    keyboard = []

    for b in bets:
        w = my_wagers.get(b["id"])
        is_open = b["status"] == "open"

        if b["bet_type"] == "winner":
            options = await db.get_bet_options(b["id"])
            my_label = next((o["label"] for o in options if w and w.get("option_id") == o["id"]), None)
            prefix = "" if is_open else "🔒 "
            title_text = f"{prefix}🏆 #{b['id']} {b['title']}"
            keyboard.append([InlineKeyboardButton(title_text, callback_data=f"noop:{b['id']}")])
            if is_open and not game_done:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{o['label']} @ {float(o['odds']):.2f}",
                        callback_data=f"opt:{b['id']}:{o['id']}",
                    )
                    for o in options[:4]
                ])
        else:
            if is_open:
                if not game_done:
                    keyboard.append([InlineKeyboardButton(f"⚖️ #{b['id']} {b['title']}", callback_data=f"noop:{b['id']}")])
                    keyboard.append([
                        InlineKeyboardButton(f"✅ Kyllä @ {float(b['yes_odds']):.2f}", callback_data=f"bet:{b['id']}:yes"),
                        InlineKeyboardButton(f"❌ Ei @ {float(b['no_odds']):.2f}", callback_data=f"bet:{b['id']}:no"),
                    ])
            else:
                keyboard.append([InlineKeyboardButton(f"🔒 ⚖️ #{b['id']} {b['title']}", callback_data=f"noop:{b['id']}")])

    keyboard.append(bottom_row)
    return msg, InlineKeyboardMarkup(keyboard)


async def _build_omat(user):
    wagers = await db.get_user_wagers_with_bets(user["id"])
    if not wagers:
        return texts.NO_WAGERS, back_keyboard()

    status_map = {"open": "avoinna", "locked": "lukittu", "resolved": "ratkaistu"}
    msg = texts.MY_WAGERS_HEADER
    keyboard = []
    for w in wagers:
        if w["bet_type"] == "winner":
            side_fi = w["option_label"] or "?"
            odds = float(w["option_odds"]) if w["option_odds"] else 0.0
        else:
            side_fi = "Kyllä" if w["side"] == "yes" else "Ei"
            odds = float(w["yes_odds"]) if w["side"] == "yes" else float(w["no_odds"])
        msg += texts.WAGER_ROW.format(
            bet_id=w["bet_id"], title=w["title"], side=side_fi,
            amount=float(w["amount"]), odds=odds,
            status=status_map.get(w["status"], w["status"]),
        )
        if w["status"] == "open":
            refund = float(w["amount"]) * 0.95
            label = f"💸 Cashout #{w['bet_id']} (+{refund:.0f} €)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"wager:cancel:{w['bet_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")])
    return msg, InlineKeyboardMarkup(keyboard)


async def _build_tulokset():
    rows = await db.get_leaderboard()
    if not rows:
        return "Ei pelaajia vielä."

    game_done = await db.is_game_finished()
    payouts = {} if game_done else await db.get_all_users_potential_winnings()
    header = texts.GAME_FINISHED_HEADER if game_done else texts.LEADERBOARD_HEADER
    msg = header
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        balance = float(row["balance"])
        potential = balance + payouts.get(row["telegram_id"], 0.0)
        msg += texts.LEADERBOARD_ROW.format(rank=i, username=name, balance=balance, potential=potential)
    if game_done:
        msg += texts.GAME_FINISHED_NOTICE
    return msg
