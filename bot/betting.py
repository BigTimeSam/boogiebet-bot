"""Pure betting math shared by the handlers and the results exporter.

No telegram or database dependencies, so these can be unit-tested directly
(see tests/test_betting.py). They centralize the "which odds apply / did this
wager win / what is the P&L" rules that were previously copy-pasted across
several rendering functions.
"""
import math


def odds_for(bet_type, side, yes_odds, no_odds, option_odds) -> float:
    """The odds that apply to a wager.

    For a "winner" bet that's the chosen option's odds (0.0 if unknown); for a
    simple bet it's yes_odds or no_odds depending on the side.
    """
    if bet_type == "winner":
        return float(option_odds) if option_odds else 0.0
    return float(yes_odds) if side == "yes" else float(no_odds)


def is_winning(bet_type, side, option_id, result) -> bool:
    """Whether a wager matches the bet's result. Only meaningful once resolved
    (returns False while result is None)."""
    if result is None:
        return False
    if bet_type == "winner":
        return str(option_id) == str(result)
    return side == result


def wager_odds(row) -> float:
    """odds_for() over a combined wager+bet row (the handlers' query shape)."""
    return odds_for(
        row["bet_type"], row["side"], row.get("yes_odds"), row.get("no_odds"),
        row.get("option_odds"),
    )


def wager_is_winning(row) -> bool:
    """is_winning() over a combined wager+bet row."""
    return is_winning(row["bet_type"], row["side"], row.get("option_id"), row.get("result"))


def wager_pnl(row) -> float:
    """Realized profit/loss for a resolved wager (positive = profit)."""
    amount = float(row["amount"])
    return amount * wager_odds(row) - amount if wager_is_winning(row) else -amount


# Fraction of a stake returned on cashout; the rest is the house's cut.
CASHOUT_RATE = 0.95


def cashout_refund(amount) -> int:
    """Whole-euro refund for cancelling a wager before lock.

    Floored to an integer so the amount shown on the button, the amount in the
    confirmation, and the amount credited to the balance are the same number —
    the old round(x, 2) credited cents that no :.0f display ever showed.
    """
    return int(float(amount) * CASHOUT_RATE)


# Wager validation outcomes (returned by validate_wager).
WAGER_OK = "ok"
WAGER_BELOW_GLOBAL_MIN = "below_global_min"  # under the game-wide minimum
WAGER_BELOW_BET_MIN = "below_bet_min"        # under this bet's own minimum
WAGER_ABOVE_MAX = "above_max"                # accumulated stake exceeds bet max
WAGER_INSUFFICIENT = "insufficient"          # not enough balance


def validate_wager(amount, balance, existing_amount, bet_min, bet_max, global_min):
    """Validate a wager against the limits and the player's balance.

    ``amount`` is the new stake the player wants; a wager replaces (does not add
    to) any prior wager on the same bet, so the actual stake placed is
    ``existing_amount + amount`` and only ``amount`` is newly charged.

    Returns ``(status, new_total)`` where status is one of the WAGER_* constants.
    The distinct below-min statuses let callers show the game-wide vs per-bet
    limit message, matching the pre-refactor behaviour.
    """
    new_total = existing_amount + amount
    if amount < global_min:
        return WAGER_BELOW_GLOBAL_MIN, new_total
    if amount < bet_min:
        return WAGER_BELOW_BET_MIN, new_total
    if new_total > bet_max:
        return WAGER_ABOVE_MAX, new_total
    if amount > balance:
        return WAGER_INSUFFICIENT, new_total
    return WAGER_OK, new_total


def parse_wager_amount(text: str):
    """Parse an 'integer euros' wager input (comma or dot accepted).

    Returns the amount as a float, or None if it is not a positive whole number.

    The isfinite() check must come first: float() accepts "nan" and "inf", every
    comparison against NaN is False (so it would pass validate_wager untouched,
    and Postgres agrees that NaN >= 0), and int() raises on both.
    """
    try:
        amount = float(text.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None
    if not math.isfinite(amount) or amount != int(amount) or amount <= 0:
        return None
    return float(int(amount))
