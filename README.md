# Line-Ups

A football trivia game that tests your knowledge of famous starting XIs.

You are shown a lineup from a well-known match with the names blanked out — the
formation and positions are there, the players are not. Type everyone you recognise
before the clock runs out.

```
                          Manchester United vs Bayern Munich
                       UEFA Champions League Final · 1998-99 · 4-4-2

                              [ST] Dwight Yorke   [ST] ?
                    [LM] Blomqvist  [CM] Butt  [CM] ?  [RM] Giggs
              [LB] Irwin  [CB] Johnsen  [CB] Jaap Stam  [RB] G. Neville
                                    [GK] ?
```

## Running it

Nothing to set up beyond Python — the game ships with a SQLite database that seeds
itself on first launch.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

Then open <http://localhost:8000>. The API docs are at `/docs`.

To use Postgres instead, point `DATABASE_URL` at it before starting — plain and
`+asyncpg` URLs both work, and the tables are created on startup:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/lineups_db
```

## How the game works

- **Guessing.** Surnames are enough (`Beckham`), accents are optional (`Pique` finds
  `Piqué`), apostrophes and hyphens are flexible (`Etoo`, `Alexander-Arnold`), and small
  typos are forgiven on longer names. Where two players in the same XI share a surname —
  the Charltons in 1966 — you are asked for a first name rather than being credited with
  a coin flip.
- **Difficulty.** Easy shows 4 players at kick-off and gives you 4 minutes; medium shows
  2 in 3 minutes; hard shows nothing in 2:30 and pays double. The goalkeeper is never
  given away.
- **Hints.** *Initials* shows the initials of everyone still hidden (−40). *Give me one*
  hands over a player (−120). Hinted players earn no points.
- **Scoring.** 100 per player you name, multiplied by the difficulty, plus a completion
  bonus and whatever time is left if you get all eleven.
- **Daily challenge.** One lineup a day, the same puzzle and the same free players for
  everyone.
- **Sharing a lineup.** `/?lineup=ucl-1999-final-manutd&difficulty=hard` starts that
  exact XI. The ids are listed by `GET /api/lineups`.

## Layout

```
backend/app/
  main.py       app setup, seeding on first run, serves the frontend
  routes.py     HTTP API
  service.py    game orchestration and state rendering
  game.py       rules: difficulty, layout, hints, scoring, daily pick  (pure)
  matching.py   guess matching: accents, surnames, typos, ambiguity     (pure)
  models.py     SQLAlchemy models
  seed.py       loads and validates data/lineups.json
data/lineups.json   the lineup archive
db/schema.sql       Postgres reference schema
frontend/           the browser client (no build step, no dependencies)
tests/              pytest suite
```

The rules and the matcher are deliberately free of database and clock access, so they
can be tested directly and reasoned about on their own.

**Hidden players never leave the server.** Unrevealed slots are serialised with
`name: null`, so the answers cannot be read out of the network tab or the page source.
Guesses are resolved server-side, and the clock is enforced server-side too.

## The API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/metadata` | Archive counts, difficulty settings, hint costs |
| `GET` | `/api/lineups` | Catalogue of puzzles (no player names) |
| `POST` | `/api/games` | Start a game (`mode`, `difficulty`, optional `lineup`) |
| `GET` | `/api/games/{id}` | Current state |
| `POST` | `/api/games/{id}/guesses` | Submit a guess |
| `POST` | `/api/games/{id}/hints` | Buy a hint (`initials` or `reveal`) |
| `POST` | `/api/games/{id}/surrender` | End the round and reveal the XI |
| `GET` | `/api/daily` | Today's challenge |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers the matcher, the scoring rules, the dataset and the API end to end —
including a check that every player in the archive can be found by typing their own
name, and that no hidden name appears in any response. CI runs it on Python 3.11 and
3.12 against SQLite, and again against Postgres.

## The lineup archive

`data/lineups.json` holds 20 hand-curated XIs, from England 1966 to Manchester City in
2023, each with a `source_url` for verification. Adding one means appending an entry —
the seeder validates it (11 players, a formation adding up to 10, no duplicates) and
refuses to start if anything is malformed.

Lineups are keyed by `id`, so editing an entry updates it in place. After changing the
dataset, re-seed an existing database with:

```bash
python -m backend.app.seed
```

It validates the file first and refuses to write anything if a lineup is malformed.

## Ideas for later

- Ingest lineups from Wikipedia/Wikidata instead of curating by hand, using
  `matches.source_url` and `appearances.confidence` to track provenance.
- Alembic migrations, generated from `backend/app/models.py`.
- Accounts and a shared leaderboard — the `games`/`rounds` tables already record enough
  to rank players.
- More game modes: name the XI from a photo, or guess the season from the lineup.
