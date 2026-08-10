# Contributing

## Getting set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn backend.app.main:app --reload --port 8000
```

The default SQLite database (`lineups.db`) is created and seeded on first launch. Delete
it to start over.

## Adding a lineup

Append an entry to `data/lineups.json` and run `python -m backend.app.seed`.

- Players are listed **row by row**: goalkeeper first, then each outfield row from the
  back forwards, left to right as seen by a viewer with the team attacking up the screen.
- `formation` covers the ten outfield players and must add up to 10.
- Include a `source_url` — the dataset tests check for one, and it is shown to the player
  after the whistle.
- Use the player's real name with its diacritics (`Piqué`, not `Pique`). The matcher
  strips accents when comparing, so correct spelling costs nothing.
- `accepts` is for nicknames and alternative spellings (`kdb`, `dibu`). Full names and
  surnames are handled automatically — you do not need to list them.

`pytest tests/test_dataset.py` checks that every player in your entry can be found by
typing their own name, that aliases resolve to the right player, and that shared
surnames are reported as ambiguous rather than being credited to whoever comes first.

## Where things live

- `backend/app/matching.py` and `backend/app/game.py` are pure — no database, no clock,
  no hidden randomness. Keep them that way; it is what makes the rules testable.
- `backend/app/service.py` is the only place that decides what a client is allowed to
  see. If you add a field to a response, check it cannot expose a hidden player.
- `frontend/` has no build step and no dependencies. It is plain HTML, CSS and ES5-ish
  JavaScript served straight from disk.

## House rules

- Anything a player can type goes through `matching.py`. Do not add a second, ad-hoc
  comparison somewhere else.
- The server owns the clock and the answers. The client renders state; it never decides
  whether a guess was right.
- New behaviour needs a test. The suite runs in under two seconds — there is no excuse.

## Roadmap

- Wikipedia/Wikidata ingestion to grow the archive beyond hand-curated entries.
- Alembic migrations generated from `backend/app/models.py`.
- Accounts, shared leaderboards and streaks that survive clearing browser storage.
