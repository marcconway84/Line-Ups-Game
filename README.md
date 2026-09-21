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
- **Clues.** Stuck on one player? Tap his shirt for a clue sheet of his own, priced by how
  much each clue gives away: the name itself (−150), another XI in the archive he also
  starts in (−100), his forename (−80), the surname with its vowels blanked out (−60), an
  anagram of the surname (−45), his initials (−40), the length of the surname (−25), its
  first letter (−20). Hinted players earn no points.

  Every clue is **computed from the archive**, never recalled — an anagram is generated, a
  repeat appearance is looked up. So they are exact by construction, they exist for all 220
  players without anyone hand-writing them, and they cannot quietly rot. `tests/test_clues.py`
  checks each one against every player in the dataset.
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

quiz/               Quick Fire: the team quiz (engine.js is the tested half)
data/quizzes/       one file per quiz pack
data/quiz_rules.json   its scoring, written once and copied to the worker
worker/             the leaderboard both games share
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

## Quick Fire &mdash; the ten minute team quiz

A second game in the same repository, built for a work team rather than a football
one. Twelve questions on one ten minute clock, a clue sheet you pay for out of your
own score, and a leaderboard the team shares. People play whenever suits them and
turn up to the meeting with a number to argue about.

```
QUICK FIRE                           TIME 7:42   SCORE 480   RIGHT 5/12
[1][2][3][4][5][6][7][8][9][10][11][12]

QUESTION 6 OF 12                                    100 POINTS, 30 SPENT
Which gas do plants absorb from the air?

  How long is it?       13 letters across two words (6, 7).      -10
  The first letter      Begins with C.                           -20
  The initials                                                   -30
  A clue in words                                                -45
  Vowels removed                                                 -55
  An anagram                                                     -65
  Four to choose from                                            -75
  Just tell me                                        free, scores 0
```

**Playing.** `python scripts/build_quiz.py` writes `dist/quickfire.html` &mdash; one
file, no server, no build step, opens from disk. Published to
[`/quiz/`](https://marcconway84.github.io/Line-Ups-Game/quiz/) alongside Line-Ups by
the same Pages workflow.

**Scoring.** 100 a question. Clues come off the top, priced by how much they give
away. All twelve right earns 250, plus 2 a second for what is left on the clock,
plus another 250 if you did it without buying a single clue. Every bonus wants a
clean sheet, which is why revealing an answer is free: it costs you the question and
the bonuses, and so cannot be played as a strategy.

**Clues are computed, not written.** An anagram is generated, the vowels are taken
out, the initials are read off. Writing a pack is a list of questions and answers,
and the whole clue sheet comes with it &mdash; it cannot go stale, and
`worker/test/quiz-engine.test.js` checks every clue against every answer in every
pack. A clue that would say nothing is left off: no initials on a one word answer.

**Answers are matched generously.** Case, accents and punctuation are optional
(`Pique` finds `Piqué`), a leading "the" is ignored either way, and a typo or two is
forgiven on anything long enough to mistype. Short answers must be exact.

### Writing a pack

One file in `data/quizzes/`. The id is the filename you want in the leaderboard, and
everything past `prompt` and `answer` is optional:

```json
{
  "id": "your-subject",
  "title": "Your Subject",
  "subject": "What it is about",
  "blurb": "One line for the pack list.",
  "questions": [
    {
      "prompt": "Which gas do plants absorb from the air?",
      "answer": "Carbon dioxide",
      "accept": ["co2"],
      "hint": "Two words. You breathe it out.",
      "decoys": ["Oxygen", "Nitrogen", "Methane"],
      "note": "Shown on the results page, for the 'ah, of course' moment."
    }
  ]
}
```

`accept` adds aliases, `hint` adds the one clue that cannot be computed, `decoys`
supply the three wrong options (without them the game borrows other answers from the
pack, which works but reads oddly), and `note` is the bit of colour shown afterwards.

Aim for answers of one to four words, and avoid bare numbers &mdash; "begins with F"
is a poor clue for `Four`. The build refuses a pack that would play badly: too few
questions, a repeated question, two questions sharing an answer, an answer too short
to make clues from, or a half-written decoy set. After adding a pack, re-run
`python scripts/generate_worker_rules.py` so the leaderboard knows how long it is.

```bash
python scripts/build_quiz.py          # rebuild the page
python scripts/generate_worker_rules.py
pytest tests/test_quiz.py
cd worker && npm test
```

## Ideas for later

- Ingest lineups from Wikipedia/Wikidata instead of curating by hand, using
  `matches.source_url` and `appearances.confidence` to track provenance.
- Alembic migrations, generated from `backend/app/models.py`.
- Accounts and a shared leaderboard — the `games`/`rounds` tables already record enough
  to rank players.
- More game modes: name the XI from a photo, or guess the season from the lineup.
