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
    yes_odds    NUMERIC(5,2) NOT NULL,
    no_odds     NUMERIC(5,2) NOT NULL,
    status      VARCHAR(20) DEFAULT 'open',   -- open | locked | resolved
    result      VARCHAR(3),                   -- yes | no | NULL
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wagers (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    bet_id      INTEGER REFERENCES bets(id),
    side        VARCHAR(3) NOT NULL,          -- yes | no
    amount      NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, bet_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key         VARCHAR(50) PRIMARY KEY,
    value       TEXT NOT NULL
);

INSERT INTO settings (key, value) VALUES ('game_finished', 'false') ON CONFLICT DO NOTHING;
