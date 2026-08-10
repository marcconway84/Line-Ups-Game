-- name=01_schema.sql
-- Initial Postgres schema for Line-Ups Game (minimal)

CREATE TABLE leagues (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT,
  source TEXT
);

CREATE TABLE teams (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  league_id INT REFERENCES leagues(id),
  wikidata_id TEXT,
  wikipedia_url TEXT
);

CREATE TABLE matches (
  id BIGINT PRIMARY KEY,
  utc_date TIMESTAMP,
  home_team_id INT REFERENCES teams(id),
  away_team_id INT REFERENCES teams(id),
  competition TEXT,
  source TEXT,
  source_url TEXT
);

CREATE TABLE players (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  wikidata_id TEXT,
  wikipedia_url TEXT,
  nationality TEXT,
  dob DATE,
  notes JSONB
);

CREATE TABLE appearances (
  id BIGSERIAL PRIMARY KEY,
  match_id BIGINT REFERENCES matches(id),
  team_id INT REFERENCES teams(id),
  player_id BIGINT REFERENCES players(id),
  position TEXT,
  shirt_number INT,
  is_starting BOOLEAN,
  minute_in INT,
  minute_out INT,
  source TEXT,
  source_url TEXT,
  confidence NUMERIC DEFAULT 0.8
);

CREATE TABLE games (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  mode TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT now(),
  match_id BIGINT REFERENCES matches(id),
  settings JSONB
);

CREATE TABLE rounds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id UUID REFERENCES games(id),
  round_index INT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP
);

CREATE TABLE round_guesses (
  id BIGSERIAL PRIMARY KEY,
  round_id UUID REFERENCES rounds(id),
  player_id BIGINT REFERENCES players(id),
  team_position TEXT,
  is_correct BOOLEAN,
  created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE hint_requests (
  id BIGSERIAL PRIMARY KEY,
  round_id UUID REFERENCES rounds(id),
  appearance_id BIGINT REFERENCES appearances(id),
  hint_type INT,
  hint_text TEXT,
  created_at TIMESTAMP DEFAULT now()
);
