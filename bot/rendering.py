"""Read-model rendering: build the (text, keyboard) views shown to players.

Pure read → presentation; depends on db, texts, betting and the UI primitives,
but not on the dispatch layer, so handlers can import it without a cycle.
"""
import betting
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from ui import _option_rows, back_keyboard

import db
import texts


async def _build_bets(user):
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
        if b["status"] == "locked":
            continue
        w = my_wagers.get(b["id"])
        is_open = b["status"] == "open"

        if b["bet_type"] == "winner":
            options = await db.get_bet_options(b["id"])
            prefix = "" if is_open else "🔒 "
            title_text = f"{prefix}🏆 #{b['id']} {b['title']}"
            keyboard.append([InlineKeyboardButton(title_text, callback_data=f"noop:{b['id']}")])
            if not game_done:
                my_option_id = w.get("option_id") if w else None

                def _make_btn(o, _my_id=my_option_id, _bid=b["id"]):
                    return InlineKeyboardButton(
                        f"{'🎯 ' if o['id'] == _my_id else ''}{o['label']} @ {float(o['odds']):.2f}",
                        callback_data=f"opt:{_bid}:{o['id']}",
                    )

                for row in _option_rows(options, _make_btn):
                    keyboard.append(row)
        else:
            if not game_done:
                lock_prefix = "" if is_open else "🔒 "
                my_side = w["side"] if w else None
                keyboard.append([InlineKeyboardButton(f"{lock_prefix}⚖️ #{b['id']} {b['title']}", callback_data=f"noop:{b['id']}")])
                keyboard.append([
                    InlineKeyboardButton(f"{'🎯 ' if my_side == 'yes' else ''}Kyllä @ {float(b['yes_odds']):.2f}", callback_data=f"bet:{b['id']}:yes"),
                    InlineKeyboardButton(f"{'🎯 ' if my_side == 'no' else ''}Ei @ {float(b['no_odds']):.2f}", callback_data=f"bet:{b['id']}:no"),
                ])

    keyboard.append(bottom_row)
    if not keyboard[:-1]:
        msg += texts.ALL_BETS_LOCKED
    return msg, InlineKeyboardMarkup(keyboard)


async def _build_my_bets(user):
    wagers = await db.get_user_wagers_with_bets(user["id"])
    if not wagers:
        return texts.NO_WAGERS, back_keyboard()

    msg = texts.MY_WAGERS_HEADER
    keyboard = []
    for w in wagers:
        if w["bet_type"] == "winner":
            side_fi = w["option_label"] or "?"
        else:
            side_fi = "Kyllä" if w["side"] == "yes" else "Ei"
        odds = betting.wager_odds(w)
        won = w["status"] == "resolved" and betting.wager_is_winning(w)

        amount = float(w["amount"])
        payout = amount * odds
        if w["status"] == "open":
            icon, extra, title_suffix = "🎯", f" (mahdollinen voitto {payout:.0f} €)", ""
        elif w["status"] == "locked":
            icon, extra, title_suffix = "🎯", f" (mahdollinen voitto {payout:.0f} €)", " 🔒"
        elif won:
            # Net profit (payout − stake), matching the PnL view and results site;
            # the stake was already charged when the wager was placed.
            profit = betting.wager_pnl(w)
            icon, extra, title_suffix = "🏆", f" (+{profit:.0f} €)", ""
        else:
            icon, extra, title_suffix = "❌", f" (-{amount:.0f} €)", ""

        msg += texts.WAGER_ROW.format(
            bet_id=w["bet_id"], title=w["title"], title_suffix=title_suffix, side=side_fi,
            amount=amount, odds=odds, icon=icon, extra=extra,
        )
        if w["status"] == "open":
            # The whole-euro amount actually credited on cashout (see db.cancel_wager).
            refund = betting.cashout_refund(amount)
            label = f"💸 Cashout #{w['bet_id']} (+{refund:.0f} €)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"wager:cancel:{w['bet_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ Takaisin", callback_data="nav:main")])
    return msg, InlineKeyboardMarkup(keyboard)


async def _build_winners() -> list[str]:
    rows = await db.get_resolved_bets_with_winners()
    if not rows:
        return [texts.WINNERS_NO_RESOLVED]

    bets_seen: list[int] = []
    by_bet: dict[int, list] = {}
    for r in rows:
        bid = r["bet_id"]
        if bid not in by_bet:
            bets_seen.append(bid)
            by_bet[bid] = []
        by_bet[bid].append(r)

    blocks: list[str] = []
    for bid in bets_seen:
        wagers = by_bet[bid]
        first = wagers[0]
        if first["bet_type"] == "winner":
            winning_row = next((w for w in wagers if str(w["option_id"]) == str(first["result"])), None)
            result_label = winning_row["option_label"] if winning_row else f"#{first['result']}"
        else:
            result_label = "Kyllä" if first["result"] == "yes" else "Ei"
        block = texts.WINNERS_BET_SECTION.format(id=bid, title=first["title"], result=result_label)

        winners = []
        losers = []
        for w in wagers:
            name = w["username"] or f"user{bid}"
            amount = float(w["amount"])
            if betting.wager_is_winning(w):
                winners.append((name, amount * betting.wager_odds(w)))
            else:
                losers.append((name, amount))

        if winners:
            winners.sort(key=lambda x: x[0].lower())
            parts = [f"{name} (+{profit:,.0f} €)".replace(",", " ") for name, profit in winners]
            block += "\U0001f3c6 " + ", ".join(parts) + "\n"
        elif not losers:
            block += texts.WINNERS_NO_PLAYERS

        if losers:
            losers.sort(key=lambda x: x[0].lower())
            parts = [f"{name} (-{amount:,.0f} €)".replace(",", " ") for name, amount in losers]
            block += "\U0001f6ab " + ", ".join(parts) + "\n"

        blocks.append(block)

    limit = 3200
    chunks: list[str] = []
    current = texts.WINNERS_HEADER
    for block in blocks:
        if current != texts.WINNERS_HEADER and len(current) + len(block) + 1 > limit:
            chunks.append(current.rstrip())
            current = texts.WINNERS_HEADER
        current += block + "\n"
    if current.strip() != texts.WINNERS_HEADER.strip():
        chunks.append(current.rstrip())

    return chunks if chunks else [texts.WINNERS_NO_RESOLVED]


async def _build_realized_pnl_all() -> list[str]:
    PNL_HEADER = "📈 Realisoitunut PnL\n\n"
    rows = await db.get_resolved_bets_with_winners()
    if not rows:
        return [PNL_HEADER + "Ei vielä ratkaistuja vetoja."]

    by_player: dict[str, list[float]] = {}
    for r in rows:
        name = r["username"] or "?"
        by_player.setdefault(name, []).append(betting.wager_pnl(r))

    sorted_players = sorted(by_player.items(), key=lambda x: sum(x[1]), reverse=True)

    lines: list[str] = []
    for name, pnls in sorted_players:
        total = sum(pnls)
        parts = " ".join(
            f"+{p:.0f} €" if p >= 0 else f"{p:.0f} €"
            for p in pnls
        )
        sign = "+" if total >= 0 else ""
        lines.append(f"{name}: {parts} = {sign}{total:.0f} €")

    limit = 3200
    chunks: list[str] = []
    current = PNL_HEADER
    for line in lines:
        entry = line + "\n"
        if current != PNL_HEADER and len(current) + len(entry) > limit:
            chunks.append(current.rstrip())
            current = PNL_HEADER
        current += entry
    if current.strip() != PNL_HEADER.strip():
        chunks.append(current.rstrip())

    return chunks if chunks else [PNL_HEADER + "Ei vielä ratkaistuja vetoja."]


async def _build_leaderboard():
    rows = await db.get_leaderboard()
    if not rows:
        return "Ei pelaajia vielä."

    game_done = await db.is_game_finished()
    wager_stats = {} if game_done else await db.get_all_users_wager_stats()
    header = texts.GAME_FINISHED_HEADER if game_done else texts.LEADERBOARD_HEADER
    msg = header
    for i, row in enumerate(rows, 1):
        name = row["username"] or f"user{row['telegram_id']}"
        balance = float(row["balance"])
        if game_done:
            msg += texts.GAME_FINISHED_ROW.format(rank=i, username=name, balance=balance)
        else:
            count, payout = wager_stats.get(row["telegram_id"], (0, 0.0))
            if count == 0:
                msg += texts.LEADERBOARD_ROW_NO_WAGERS.format(rank=i, username=name, balance=balance)
            elif count == 1:
                msg += texts.LEADERBOARD_ROW_ONE_WAGER.format(rank=i, username=name, balance=balance, potential=balance + payout)
            else:
                msg += texts.LEADERBOARD_ROW_MANY_WAGERS.format(rank=i, username=name, balance=balance, count=count, potential=balance + payout)
    if game_done:
        msg += texts.GAME_FINISHED_NOTICE

    kepulit = await db.get_kepulit()
    if kepulit:
        msg += texts.KEPULIT_HEADER
        for i, row in enumerate(kepulit, 1):
            name = row["username"] or f"user{row['telegram_id']}"
            balance = float(row["balance"])
            bonus = float(row["bonus_balance"])
            if game_done:
                msg += texts.KEPULIT_ROW.format(rank=i, username=name, balance=balance, bonus=bonus)
            else:
                count, payout = wager_stats.get(row["telegram_id"], (0, 0.0))
                if count == 0:
                    msg += texts.KEPULIT_ROW_NO_WAGERS.format(rank=i, username=name, balance=balance, bonus=bonus)
                elif count == 1:
                    msg += texts.KEPULIT_ROW_ONE_WAGER.format(rank=i, username=name, balance=balance, bonus=bonus, potential=balance + payout)
                else:
                    msg += texts.KEPULIT_ROW_MANY_WAGERS.format(rank=i, username=name, balance=balance, bonus=bonus, count=count, potential=balance + payout)
    return msg
