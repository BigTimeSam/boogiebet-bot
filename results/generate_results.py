#!/usr/bin/env python3
"""
Generate results/data.json from the boogiebet database.

Usage (locally, with Docker DB exposed on port 5432):
    DATABASE_URL=postgresql://boogiebet:boogiebet@localhost:5432/boogiebet python results/generate_results.py

Usage (inside the bot container):
    docker compose exec bot python /app/results/generate_results.py

Usage (via SSH on the production server):
    ssh deploy@prod-docker-01.poggers.fi \
      "docker compose -f /srv/boogiebet-bot/docker-compose.yml exec -T bot python /app/results/generate_results.py"
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent

# Load .env from repo root; allow env override
load_dotenv(REPO_ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://boogiebet:boogiebet@localhost:5432/boogiebet")
OUTPUT = SCRIPT_DIR / "data.json"
STARTING_BALANCE = 1000.0


async def main():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ Tietokantayhteys epäonnistui: {e}", file=sys.stderr)
        print("   Varmista että DATABASE_URL on oikein tai Docker on käynnissä.", file=sys.stderr)
        sys.exit(1)

    try:
        # ── Game status ────────────────────────────────────────────────────────
        game_finished = (
            await conn.fetchval("SELECT value FROM settings WHERE key = 'game_finished'") == "true"
        )

        # ── Users (exclude kepulit – manually credited users) ─────────────────
        users = await conn.fetch(
            "SELECT id, telegram_id, username, balance, bonus_balance, created_at "
            "FROM users WHERE bonus_balance = 0 ORDER BY balance DESC"
        )
        user_id_map = {u["id"]: dict(u) for u in users}

        # ── Bets with options ──────────────────────────────────────────────────
        bets_raw = await conn.fetch(
            "SELECT b.*, "
            "  (SELECT json_agg("
            "    json_build_object('id', bo.id, 'label', bo.label, 'odds', bo.odds::float, 'position', bo.position)"
            "    ORDER BY bo.position"
            "  ) FROM bet_options bo WHERE bo.bet_id = b.id) AS options "
            "FROM bets b ORDER BY b.id"
        )

        # ── All wagers ─────────────────────────────────────────────────────────
        wagers_raw = await conn.fetch("""
            SELECT
                w.user_id, w.bet_id, w.side, w.amount, w.option_id,
                u.username,
                b.title AS bet_title, b.result AS bet_result, b.bet_type,
                b.yes_odds::float AS yes_odds, b.no_odds::float AS no_odds,
                b.status AS bet_status,
                bo.label AS option_label, bo.odds::float AS option_odds
            FROM wagers w
            JOIN users u ON u.id = w.user_id
            JOIN bets b ON b.id = w.bet_id
            LEFT JOIN bet_options bo ON bo.id = w.option_id
            ORDER BY b.id, u.username
        """)

    finally:
        await conn.close()

    wagers_by_bet: dict[int, list] = {}
    for w in wagers_raw:
        wagers_by_bet.setdefault(w["bet_id"], []).append(dict(w))

    # ── Process bets ───────────────────────────────────────────────────────────
    bets_data = []
    for b in bets_raw:
        b = dict(b)
        bet_id = b["id"]
        bet_wagers = wagers_by_bet.get(bet_id, [])
        options = json.loads(b["options"]) if b["options"] else []

        # Result label
        if b["status"] != "resolved":
            result_label = "—"
        elif b["bet_type"] == "winner":
            winning = next((o for o in options if str(o["id"]) == str(b["result"])), None)
            result_label = winning["label"] if winning else b["result"]
        else:
            result_label = "Kyllä ✅" if b["result"] == "yes" else "Ei ❌"

        # Per-wager details
        wager_details = []
        for w in bet_wagers:
            if b["status"] == "resolved":
                if b["bet_type"] == "winner":
                    won = str(w["option_id"]) == str(b["result"])
                    odds = w["option_odds"] or 0.0
                else:
                    won = (w["side"] == "yes" and b["result"] == "yes") or \
                          (w["side"] == "no" and b["result"] == "no")
                    odds = w["yes_odds"] if w["side"] == "yes" else w["no_odds"]
                payout = float(w["amount"]) * odds if won else 0.0
                pnl = payout - float(w["amount"])
            else:
                won = None
                payout = None
                pnl = None

            wager_details.append({
                "username": w["username"] or f"user{w['user_id']}",
                "side": w["side"],
                "option_label": w["option_label"] or ("Kyllä" if w["side"] == "yes" else "Ei"),
                "amount": float(w["amount"]),
                "won": won,
                "payout": round(payout, 2) if payout is not None else None,
                "pnl": round(pnl, 2) if pnl is not None else None,
            })

        bets_data.append({
            "id": bet_id,
            "title": b["title"],
            "type": b["bet_type"],
            "status": b["status"],
            "result": b["result"],
            "result_label": result_label,
            "yes_odds": b["yes_odds"] if b["bet_type"] == "simple" else None,
            "no_odds": b["no_odds"] if b["bet_type"] == "simple" else None,
            "options": options,
            "total_wagered": round(sum(float(w["amount"]) for w in bet_wagers), 2),
            "num_bettors": len(bet_wagers),
            "wagers": wager_details,
        })

    bet_by_id = {b["id"]: b for b in bets_data}

    # ── Leaderboard ────────────────────────────────────────────────────────────
    leaderboard = []
    for rank, u in enumerate(users, 1):
        u = dict(u)
        uid = u["id"]
        username = u["username"] or f"user{u['telegram_id']}"

        player_wagers_raw = wagers_by_bet_for_user(wagers_raw, uid)
        total_wagered = sum(float(w["amount"]) for w in player_wagers_raw)

        bets_won = bets_lost = bets_open = 0
        for w in player_wagers_raw:
            b = bet_by_id.get(w["bet_id"])
            if not b or b["status"] != "resolved":
                bets_open += 1
                continue
            wd = next((x for x in b["wagers"] if x["username"] == username), None)
            if wd:
                if wd["won"]:
                    bets_won += 1
                else:
                    bets_lost += 1

        leaderboard.append({
            "rank": rank,
            "username": username,
            "balance": float(u["balance"]),
            "pnl": round(float(u["balance"]) - STARTING_BALANCE, 2),
            "total_wagered": round(total_wagered, 2),
            "bets_won": bets_won,
            "bets_lost": bets_lost,
            "bets_open": bets_open,
            "bets_total": bets_won + bets_lost + bets_open,
        })

    # ── Global stats ───────────────────────────────────────────────────────────
    resolved_bets = [b for b in bets_data if b["status"] == "resolved"]
    all_wager_details = [w for b in resolved_bets for w in b["wagers"]]

    biggest_win = max(all_wager_details, key=lambda w: w["pnl"] or 0, default=None)
    biggest_loss = min(all_wager_details, key=lambda w: w["pnl"] or 0, default=None)
    most_active = max(leaderboard, key=lambda p: p["bets_total"], default=None)
    biggest_pot_bet = max(bets_data, key=lambda b: b["total_wagered"], default=None)
    total_wagers_count = sum(b["num_bettors"] for b in bets_data)

    def find_bet_title(wager_detail):
        for b in bets_data:
            if wager_detail in b["wagers"]:
                return b["title"]
        return ""

    stats = {
        "total_bets": len(bets_data),
        "resolved_bets": len(resolved_bets),
        "total_players": len(leaderboard),
        "total_wagers_count": total_wagers_count,
        "total_pot": round(sum(b["total_wagered"] for b in bets_data), 2),
        "avg_wager": round(
            sum(w["amount"] for b in bets_data for w in b["wagers"]) / max(1, total_wagers_count), 2
        ),
        "biggest_win": {
            "username": biggest_win["username"],
            "bet_title": find_bet_title(biggest_win),
            "pnl": biggest_win["pnl"],
        } if biggest_win and (biggest_win["pnl"] or 0) > 0 else None,
        "biggest_loss": {
            "username": biggest_loss["username"],
            "bet_title": find_bet_title(biggest_loss),
            "pnl": biggest_loss["pnl"],
        } if biggest_loss and (biggest_loss["pnl"] or 0) < 0 else None,
        "most_active": {
            "username": most_active["username"],
            "bet_count": most_active["bets_total"],
        } if most_active else None,
        "biggest_pot_bet": {
            "title": biggest_pot_bet["title"],
            "total_wagered": biggest_pot_bet["total_wagered"],
            "num_bettors": biggest_pot_bet["num_bettors"],
        } if biggest_pot_bet else None,
    }

    # ── Write output ───────────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now().isoformat(),
        "game_finished": game_finished,
        "starting_balance": STARTING_BALANCE,
        "leaderboard": leaderboard,
        "bets": bets_data,
        "stats": stats,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✅ Tulokset tallennettu: {OUTPUT}")
    print(f"   {len(leaderboard)} pelaajaa · {len(bets_data)} vetoa · {total_wagers_count} panosta")
    print(f"   Potti yhteensä: {stats['total_pot']:.0f} €")


def wagers_by_bet_for_user(wagers_raw, user_id: int) -> list:
    return [dict(w) for w in wagers_raw if w["user_id"] == user_id]


if __name__ == "__main__":
    asyncio.run(main())
