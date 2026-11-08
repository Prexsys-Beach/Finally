-- FinAlly schema. Every statement is idempotent; applied on each startup.

CREATE TABLE IF NOT EXISTS users_profile (
    id TEXT PRIMARY KEY DEFAULT 'default',
    cash_balance REAL NOT NULL DEFAULT 10000.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    total_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_user_time
    ON portfolio_snapshots (user_id, recorded_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    actions TEXT,
    created_at TEXT NOT NULL
);

-- Market data, not user data, so no user_id. start_ts is Unix seconds (UTC) because
-- every query here is a time range. origin: recorded | synthetic | vendor.
CREATE TABLE IF NOT EXISTS price_bars (
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('1m', '1d')),
    start_ts INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('recorded', 'synthetic', 'vendor')),
    PRIMARY KEY (ticker, timeframe, start_ts)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Directional calls and how they turned out. Each assistant prediction is paired
-- with a coin-flip baseline on the same ticker and horizon.
CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    predictor TEXT NOT NULL CHECK (predictor IN ('assistant', 'baseline')),
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    confidence REAL NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    data_mode TEXT NOT NULL,
    made_at TEXT NOT NULL,
    resolves_at TEXT NOT NULL,
    resolved_price REAL,
    outcome TEXT CHECK (outcome IN ('hit', 'miss', 'void')),
    note TEXT,
    pair_id TEXT,
    chat_message_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_predictions_due
    ON predictions (user_id, outcome, resolves_at);
