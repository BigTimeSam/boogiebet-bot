CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username    VARCHAR(255),
    balance     NUMERIC(10,2) DEFAULT 1000.00,
    is_admin    BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bets (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    yes_odds    NUMERIC(5,2) NOT NULL DEFAULT 0,
    no_odds     NUMERIC(5,2) NOT NULL DEFAULT 0,
    bet_type    VARCHAR(10) NOT NULL DEFAULT 'simple', -- simple | winner
    status      VARCHAR(20) DEFAULT 'open',            -- open | locked | resolved
    result      TEXT,                                  -- yes | no | option_id (winner)
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bet_options (
    id          SERIAL PRIMARY KEY,
    bet_id      INTEGER REFERENCES bets(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    odds        NUMERIC(5,2) NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wagers (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    bet_id      INTEGER REFERENCES bets(id),
    side        VARCHAR(3) NOT NULL,          -- yes | no | opt
    option_id   INTEGER REFERENCES bet_options(id),
    amount      NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, bet_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key         VARCHAR(50) PRIMARY KEY,
    value       TEXT NOT NULL
);

INSERT INTO settings (key, value) VALUES ('game_finished', 'false') ON CONFLICT DO NOTHING;
