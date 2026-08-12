-- The leaderboard's storage. Small on purpose: a score table and a table of spent
-- round tokens, nothing else. No accounts, no email addresses, no IP addresses kept
-- beyond the hour they are needed for rate limiting.

CREATE TABLE IF NOT EXISTS scores (
  lineup       TEXT    NOT NULL,
  player       TEXT    NOT NULL,   -- a random id the browser keeps; not a login
  name         TEXT    NOT NULL,   -- the display name typed by the player
  score        INTEGER NOT NULL,
  guessed      INTEGER NOT NULL,
  completed    INTEGER NOT NULL,
  seconds_left INTEGER NOT NULL,
  difficulty   TEXT    NOT NULL,
  created_at   INTEGER NOT NULL,   -- unix ms

  -- The first-attempt rule, enforced here rather than in application code. A second
  -- run at the same XI cannot overwrite the first even if something upstream is
  -- wrong, which is what stops the board filling with ground-out perfect scores.
  PRIMARY KEY (lineup, player)
);

-- Ordering the board for one lineup is the only read this table does in anger.
CREATE INDEX IF NOT EXISTS scores_by_lineup ON scores (lineup, score DESC, created_at ASC);

CREATE TABLE IF NOT EXISTS spent_tokens (
  nonce      TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS spent_tokens_age ON spent_tokens (created_at);

-- Counts of rounds started per address per hour. Kept coarse so it cannot be used to
-- follow anyone around: an address appears here for an hour and is then swept.
CREATE TABLE IF NOT EXISTS rate (
  bucket     TEXT PRIMARY KEY,     -- hashed address + hour
  hits       INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
