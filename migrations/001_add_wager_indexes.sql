-- wagers.bet_id and wagers.user_id are filtered/joined constantly, but Postgres
-- does not auto-index foreign keys. Add indexes to keep those lookups fast.
CREATE INDEX IF NOT EXISTS idx_wagers_bet_id ON wagers (bet_id);
CREATE INDEX IF NOT EXISTS idx_wagers_user_id ON wagers (user_id);
CREATE INDEX IF NOT EXISTS idx_bet_options_bet_id ON bet_options (bet_id);
