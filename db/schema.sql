-- Postgres schema for Line-Ups Game.
--
-- This mirrors the SQLAlchemy models in backend/app/models.py, which are the source of
-- truth at runtime: the app calls Base.metadata.create_all() on startup and will create
-- these tables itself on SQLite or Postgres. Keep this file in step with the models -
-- it exists so the intended Postgres shape can be read (and reviewed) in one place, and
-- as the starting point for the first Alembic migration.
--
--   createdb lineups_db && psql lineups_db -f db/schema.sql
--   export DATABASE_URL=postgresql://user:pass@localhost:5432/lineups_db

-- ------------------------------------------------------------------ catalogue

CREATE TABLE leagues (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  country TEXT,
  source TEXT
);

CREATE TABLE teams (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  league_id INT REFERENCES leagues(id),
  wikidata_id TEXT,
  wikipedia_url TEXT
);

-- One puzzle: a famous XI plus the context shown to the player.
CREATE TABLE matches (
  id SERIAL PRIMARY KEY,
  -- Stable id from data/lineups.json, so re-seeding updates rather than duplicates.
  slug VARCHAR(120) NOT NULL UNIQUE,
  utc_date TIMESTAMP,
  home_team_id INT REFERENCES teams(id),
  away_team_id INT REFERENCES teams(id),
  competition TEXT,
  season TEXT,
  venue TEXT,
  score TEXT,
  -- Outfield rows, e.g. [4, 3, 3]; must add up to 10.
  formation JSONB NOT NULL DEFAULT '[]'::jsonb,
  blurb TEXT,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  source TEXT,
  source_url TEXT
);
CREATE INDEX idx_matches_slug ON matches(slug);

CREATE TABLE players (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  -- Accent- and punctuation-free form used to deduplicate players across lineups.
  normalized_name VARCHAR(160) NOT NULL UNIQUE,
  wikidata_id TEXT,
  wikipedia_url TEXT,
  nationality TEXT,
  -- Curated aliases: {"accepts": ["kdb", "de bruyne"]}
  notes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_players_normalized_name ON players(normalized_name);

-- A player occupying one of the eleven slots of a lineup.
CREATE TABLE appearances (
  id SERIAL PRIMARY KEY,
  match_id INT NOT NULL REFERENCES matches(id),
  team_id INT REFERENCES teams(id),
  player_id INT NOT NULL REFERENCES players(id),
  position TEXT,
  -- 0-10; slot 0 is always the goalkeeper.
  slot_index INT NOT NULL,
  shirt_number INT,
  is_starting BOOLEAN DEFAULT TRUE,
  minute_in INT,
  minute_out INT,
  source TEXT,
  source_url TEXT,
  confidence DOUBLE PRECISION DEFAULT 0.8,
  CONSTRAINT uq_appearance_slot UNIQUE (match_id, slot_index)
);
CREATE INDEX idx_appearances_match ON appearances(match_id);

-- ----------------------------------------------------------------------- play

-- Which slots are visible is NOT stored: it is derived from the game's seed (the slots
-- given away at kick-off), the correct guesses and the reveal hints.
CREATE TABLE games (
  id VARCHAR(36) PRIMARY KEY,
  mode VARCHAR(20) NOT NULL DEFAULT 'quick',        -- 'quick' | 'daily'
  difficulty VARCHAR(20) NOT NULL DEFAULT 'medium', -- 'easy' | 'medium' | 'hard'
  match_id INT NOT NULL REFERENCES matches(id),
  status VARCHAR(20) NOT NULL DEFAULT 'in_progress',-- 'in_progress' | 'won' | 'lost' | 'gave_up'
  score INT DEFAULT 0,
  -- {"seed": ..., "day": ..., "breakdown": {...}} - the frozen final score breakdown.
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMP DEFAULT now(),
  finished_at TIMESTAMP
);

CREATE TABLE rounds (
  id VARCHAR(36) PRIMARY KEY,
  game_id VARCHAR(36) NOT NULL REFERENCES games(id),
  round_index INT DEFAULT 0,
  started_at TIMESTAMP DEFAULT now(),
  finished_at TIMESTAMP
);
CREATE INDEX idx_rounds_game ON rounds(game_id);

CREATE TABLE round_guesses (
  id SERIAL PRIMARY KEY,
  round_id VARCHAR(36) NOT NULL REFERENCES rounds(id),
  -- Exactly what the user typed, kept for stats and for tuning the matcher.
  text TEXT NOT NULL,
  player_id INT REFERENCES players(id),
  slot_index INT,
  team_position TEXT,
  is_correct BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_round_guesses_round ON round_guesses(round_id);

CREATE TABLE hint_requests (
  id SERIAL PRIMARY KEY,
  round_id VARCHAR(36) NOT NULL REFERENCES rounds(id),
  appearance_id INT REFERENCES appearances(id),
  slot_index INT,
  hint_type VARCHAR(20) NOT NULL,  -- 'initials' | 'reveal'
  hint_text TEXT,
  cost INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_hint_requests_round ON hint_requests(round_id);
