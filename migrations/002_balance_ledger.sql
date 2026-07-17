-- Append-only money ledger + resolution audit columns.
--
-- Before this, a balance was a bare mutable number and no money movement was
-- recorded anywhere, so a wrong balance could not be explained after the fact.
-- balance_events records every delta with its reason and (for admin actions) who
-- caused it; the bets.resolved_by/at columns answer "who resolved this bet".

CREATE TABLE IF NOT EXISTS balance_events (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    delta         NUMERIC(10,2) NOT NULL,
    balance_after NUMERIC(10,2) NOT NULL,
    reason        TEXT NOT NULL,   -- wager | cashout | payout | payout_revert | admin_adjust
    actor_id      INTEGER REFERENCES users(id),  -- who caused it; NULL = the user / the system
    bet_id        INTEGER,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_balance_events_user_id ON balance_events (user_id);
CREATE INDEX IF NOT EXISTS idx_balance_events_bet_id ON balance_events (bet_id);

ALTER TABLE bets ADD COLUMN IF NOT EXISTS resolved_by INTEGER REFERENCES users(id);
ALTER TABLE bets ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;

-- Reject non-positive or NaN stakes at the database, not just in the handler.
-- NOT VALID applies the check to new rows only, so any legacy row can't fail the
-- migration (and thus the deploy) on an existing production database.
-- NB: Postgres NUMERIC treats NaN as greater than every number and equal to
-- itself, so `amount > 0` passes NaN and `amount = amount` does NOT catch it
-- (unlike IEEE floats) — NaN must be excluded explicitly.
DO $$ BEGIN
    ALTER TABLE wagers
        ADD CONSTRAINT wagers_amount_positive
        CHECK (amount > 0 AND amount <> 'NaN'::numeric) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
