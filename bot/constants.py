"""Shared game constants.

Single source of truth for wager limits and game parameters, imported by the
handlers and by the test suite so the two can never silently drift.
"""

# Default per-bet wager limits (euros). Individual bets may tighten these via
# their own min_wager / max_wager columns, bounded by this range.
MIN_WAGER = 20.0
MAX_WAGER = 200.0

# Maximum number of options on a "winner" bet.
MAX_WINNER_OPTIONS = 6

# Odds must be > 1.0 and fit the NUMERIC(5,2) columns (max 999.99). Anything at
# or above this would overflow the column and surface as a raw DB error.
MAX_ODDS = 999.99

# Balance every player starts with (mirrors the users.balance DEFAULT in init.sql).
STARTING_BALANCE = 1000.0

# Telegram rejects any message body over 4096 characters. Views that can grow
# without bound (a player's whole wager history, the open-bets broadcast) must
# chunk or truncate against this; leave headroom for the HTML wrapper.
TELEGRAM_MAX_MESSAGE = 4096
MESSAGE_CHUNK_LIMIT = 3800
