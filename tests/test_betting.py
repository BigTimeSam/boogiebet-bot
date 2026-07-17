"""Unit tests for the pure betting math in bot/betting.py (no DB, no telegram)."""
import betting

# ── odds_for ───────────────────────────────────────────────────────────────────

def test_odds_for_simple_yes():
    assert betting.odds_for("simple", "yes", 2.5, 1.8, None) == 2.5


def test_odds_for_simple_no():
    assert betting.odds_for("simple", "no", 2.5, 1.8, None) == 1.8


def test_odds_for_winner_uses_option_odds():
    assert betting.odds_for("winner", "opt", None, None, 3.0) == 3.0


def test_odds_for_winner_missing_option_odds_is_zero():
    assert betting.odds_for("winner", "opt", None, None, None) == 0.0


# ── is_winning ─────────────────────────────────────────────────────────────────

def test_is_winning_simple_match():
    assert betting.is_winning("simple", "yes", None, "yes") is True
    assert betting.is_winning("simple", "no", None, "no") is True


def test_is_winning_simple_mismatch():
    assert betting.is_winning("simple", "yes", None, "no") is False


def test_is_winning_winner_match_by_string():
    # option_id may be int while result is the stringified id.
    assert betting.is_winning("winner", "opt", 7, "7") is True


def test_is_winning_winner_mismatch():
    assert betting.is_winning("winner", "opt", 7, "8") is False


def test_is_winning_unresolved_is_false():
    assert betting.is_winning("simple", "yes", None, None) is False
    assert betting.is_winning("winner", "opt", 7, None) is False


# ── row helpers ────────────────────────────────────────────────────────────────

def _simple_row(side, result, amount=100):
    return {"bet_type": "simple", "side": side, "result": result,
            "yes_odds": 2.0, "no_odds": 3.0, "amount": amount}


def _winner_row(option_id, result, odds, amount=100):
    return {"bet_type": "winner", "side": "opt", "option_id": option_id,
            "result": result, "option_odds": odds, "amount": amount}


def test_wager_odds_and_winning_row():
    row = _simple_row("yes", "yes")
    assert betting.wager_odds(row) == 2.0
    assert betting.wager_is_winning(row) is True


def test_wager_pnl_simple_win():
    # 100 @ 2.0 → payout 200, profit 100
    assert betting.wager_pnl(_simple_row("yes", "yes")) == 100.0


def test_wager_pnl_simple_loss():
    assert betting.wager_pnl(_simple_row("yes", "no")) == -100.0


def test_wager_pnl_winner_win():
    # 100 @ 3.5 → payout 350, profit 250
    assert betting.wager_pnl(_winner_row(7, "7", 3.5)) == 250.0


def test_wager_pnl_winner_loss():
    assert betting.wager_pnl(_winner_row(7, "8", 3.5)) == -100.0


# ── parse_wager_amount ─────────────────────────────────────────────────────────

def test_parse_wager_amount_integer():
    assert betting.parse_wager_amount("50") == 50.0


def test_parse_wager_amount_comma_decimal_whole():
    assert betting.parse_wager_amount("50,00") == 50.0


def test_parse_wager_amount_strips_whitespace():
    assert betting.parse_wager_amount("  200 ") == 200.0


def test_parse_wager_amount_rejects_fractional():
    assert betting.parse_wager_amount("50.5") is None


def test_parse_wager_amount_rejects_zero_and_negative():
    assert betting.parse_wager_amount("0") is None
    assert betting.parse_wager_amount("-20") is None


def test_parse_wager_amount_rejects_nonnumeric():
    assert betting.parse_wager_amount("abc") is None
    assert betting.parse_wager_amount("") is None


def test_parse_wager_amount_rejects_non_finite():
    """float() happily parses these; every comparison against NaN is False, so a
    NaN that reaches validate_wager passes every limit and lands in the DB
    (Postgres: NaN >= 0 is TRUE), permanently corrupting the balance."""
    for text in ("nan", "NaN", "inf", "-inf", "infinity", "1e400"):
        assert betting.parse_wager_amount(text) is None, text


# ── validate_wager ─────────────────────────────────────────────────────────────

def test_validate_wager_ok():
    status, new_total = betting.validate_wager(
        amount=100, balance=1000, existing_amount=0, bet_min=20, bet_max=200, global_min=20)
    assert status == betting.WAGER_OK
    assert new_total == 100


def test_validate_wager_below_global_min():
    status, _ = betting.validate_wager(
        amount=10, balance=1000, existing_amount=0, bet_min=20, bet_max=200, global_min=20)
    assert status == betting.WAGER_BELOW_GLOBAL_MIN


def test_validate_wager_below_bet_min_but_above_global():
    # amount 30 clears the global min (20) but not this bet's min (50).
    status, _ = betting.validate_wager(
        amount=30, balance=1000, existing_amount=0, bet_min=50, bet_max=200, global_min=20)
    assert status == betting.WAGER_BELOW_BET_MIN


def test_validate_wager_above_max_uses_accumulated_total():
    # 150 already staked + 100 new = 250 > 200 max.
    status, new_total = betting.validate_wager(
        amount=100, balance=1000, existing_amount=150, bet_min=20, bet_max=200, global_min=20)
    assert status == betting.WAGER_ABOVE_MAX
    assert new_total == 250


def test_validate_wager_insufficient_balance():
    status, _ = betting.validate_wager(
        amount=100, balance=50, existing_amount=0, bet_min=20, bet_max=200, global_min=20)
    assert status == betting.WAGER_INSUFFICIENT


def test_validate_wager_replacement_charges_only_delta():
    # Already 100 staked, balance 50. Replacing with 120 (new_total 220>max) is
    # caught by the max rule first; balance is only checked on `amount`.
    status, new_total = betting.validate_wager(
        amount=120, balance=50, existing_amount=100, bet_min=20, bet_max=300, global_min=20)
    # amount 120 > balance 50 → insufficient (max 300 not exceeded by 220).
    assert status == betting.WAGER_INSUFFICIENT
    assert new_total == 220
