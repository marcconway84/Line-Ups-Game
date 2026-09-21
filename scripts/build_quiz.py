#!/usr/bin/env python3
"""Build Quick Fire: the quiz packs, the rules and the client in one HTML file.

The quiz has no server of its own. A pack is data, the rules are data, and the
game is a few hundred lines of browser JavaScript - so the build is one step:
read quiz/index.html, quiz/styles.css, quiz/engine.js and quiz/app.js, drop the
packs and the rules into the script, and write a single file that can be opened
from disk, mailed round, or served from GitHub Pages.

    python scripts/build_quiz.py                 -> dist/quickfire.html
    python scripts/build_quiz.py --site          -> dist/site/quiz/ for Pages

Validation happens here rather than at run time: a malformed pack fails the
build, which is the last moment anyone is watching. tests/test_quiz_packs.py
runs the same checks against everything in data/quizzes/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "data" / "quizzes"
RULES = REPO_ROOT / "data" / "quiz_rules.json"
LEADERBOARD = REPO_ROOT / "data" / "leaderboard.json"
SOURCE = REPO_ROOT / "quiz"
DEFAULT_OUT = REPO_ROOT / "dist" / "quickfire.html"

TITLE = "Quick Fire &mdash; the ten minute team quiz"
BLURB = ("Twelve questions, ten minutes, and a clue sheet you pay for out of your own "
         "score. A competitive ice breaker your team can play whenever suits them.")
SITE_URL = "https://marcconway84.github.io/Line-Ups-Game/quiz/"

#: Every key the game knows how to price. A pack cannot invent a new one, and a
#: rules file that forgets one would leave a clue the game cannot charge for.
CLUE_KEYS = {"letters", "first", "initials", "hint", "novowels", "anagram", "choices", "reveal"}

#: Below this the clue sheet stops being a ladder - an anagram of three letters
#: is the answer with extra steps.
MIN_ANSWER_LETTERS = 3
MIN_QUESTIONS = 4


class BadPack(Exception):
    """A pack that would make a broken game. Raised at build time, never at play time."""


def load_rules() -> dict:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    missing = CLUE_KEYS - set(rules.get("clueCosts", {}))
    if missing:
        raise BadPack(f"{RULES.name} has no price for: {', '.join(sorted(missing))}")
    unknown = set(rules["clueCosts"]) - CLUE_KEYS
    if unknown:
        raise BadPack(f"{RULES.name} prices clues the game does not offer: {', '.join(sorted(unknown))}")
    for key in ("secondsOnTheClock", "pointsPerQuestion", "finisherBonus",
                "pointsPerSecondRemaining", "cleanSweepBonus"):
        if not isinstance(rules.get(key), int):
            raise BadPack(f"{RULES.name} is missing a whole number for {key}")
    return {key: value for key, value in rules.items() if not key.startswith("_")}


def check_pack(pack: dict, source: str) -> dict:
    """Refuse a pack that would play badly, and say which one and why."""
    where = f"{source}: "
    for field in ("id", "title", "subject", "questions"):
        if not pack.get(field):
            raise BadPack(where + f"missing {field}")

    questions = pack["questions"]
    if len(questions) < MIN_QUESTIONS:
        raise BadPack(where + f"only {len(questions)} questions; {MIN_QUESTIONS} is the minimum")

    seen_prompts: set[str] = set()
    seen_answers: set[str] = set()
    for index, question in enumerate(questions, start=1):
        at = where + f"question {index}: "
        prompt = str(question.get("prompt") or "").strip()
        answer = str(question.get("answer") or "").strip()
        if not prompt:
            raise BadPack(at + "no prompt")
        if not answer:
            raise BadPack(at + "no answer")
        if len(answer.replace(" ", "")) < MIN_ANSWER_LETTERS:
            raise BadPack(at + f"the answer {answer!r} is too short to build clues from")
        if prompt.lower() in seen_prompts:
            raise BadPack(at + "the same question is already in this pack")
        seen_prompts.add(prompt.lower())

        # Two questions with one answer is a real trap: the wrong tile lights up
        # when the second is answered, and the multiple-choice clue can offer the
        # right answer twice.
        key = answer.lower()
        if key in seen_answers:
            raise BadPack(at + f"{answer!r} is already the answer to another question in this pack")
        seen_answers.add(key)

        decoys = question.get("decoys") or []
        if decoys and len(decoys) < 3:
            raise BadPack(at + f"{len(decoys)} decoys; give three or none at all")
        if key in {str(d).lower() for d in decoys}:
            raise BadPack(at + "the answer is one of its own decoys")

    return pack


def load_packs() -> list[dict]:
    if not PACK_DIR.is_dir():
        raise BadPack(f"no packs: {PACK_DIR} does not exist")
    packs: list[dict] = []
    ids: set[str] = set()
    for path in sorted(PACK_DIR.glob("*.json")):
        pack = check_pack(json.loads(path.read_text(encoding="utf-8")), path.name)
        if pack["id"] in ids:
            raise BadPack(f"{path.name}: the id {pack['id']!r} is used by another pack")
        ids.add(pack["id"])
        packs.append({
            "id": pack["id"],
            "title": pack["title"],
            "subject": pack["subject"],
            "blurb": pack.get("blurb", ""),
            "questions": [
                {
                    "prompt": q["prompt"],
                    "answer": q["answer"],
                    "accept": q.get("accept", []),
                    "hint": q.get("hint"),
                    "decoys": q.get("decoys", []),
                    "note": q.get("note"),
                }
                for q in pack["questions"]
            ],
        })
    if not packs:
        raise BadPack(f"no packs found in {PACK_DIR}")
    return packs


def leaderboard_payload() -> str:
    """Where the board lives, or null. Built in, so a board-less page makes no calls."""
    if not LEADERBOARD.exists():
        return "null"
    config = json.loads(LEADERBOARD.read_text(encoding="utf-8"))
    url = str(config.get("url") or "").strip()
    if not url:
        return "null"
    if not url.startswith("https://"):
        raise BadPack(f"leaderboard url must be https, got {url!r}")
    return json.dumps({"url": url.rstrip("/")})


def embed(value) -> str:
    """JSON for a <script> block: a literal </ would close the block early."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build() -> str:
    packs = load_packs()
    rules = load_rules()

    # The engine goes first: app.js reads the global it publishes.
    engine = (SOURCE / "engine.js").read_text(encoding="utf-8")
    script = engine + "\n" + (SOURCE / "app.js").read_text(encoding="utf-8")
    script = script.replace("__PACKS__", embed(packs))
    script = script.replace("__RULES__", embed(rules))
    script = script.replace("__LEADERBOARD__", leaderboard_payload())

    markup = (SOURCE / "index.html").read_text(encoding="utf-8")
    styles = (SOURCE / "styles.css").read_text(encoding="utf-8")

    # Stamped over the finished script, so the mark moves whenever anything in the
    # page does - a question, a price, the board's address, any of it.
    build_mark = hashlib.sha256(script.encode("utf-8")).hexdigest()[:8]
    markup = markup.replace("__BUILD__", f"build {build_mark}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="description" content="{BLURB}" />
<meta name="theme-color" content="#0a0f1a" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Quick Fire" />
<meta property="og:title" content="Quick Fire &mdash; the ten minute team quiz" />
<meta property="og:description" content="{BLURB}" />
<meta property="og:url" content="{SITE_URL}" />
<meta name="twitter:card" content="summary" />
<title>{TITLE}</title>
<style>
{styles}
</style>
</head>
<body>
{markup}
<script>
{script}
</script>
</body>
</html>
"""


def build_site(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(build(), encoding="utf-8")
    print(f"Wrote {out_dir}/index.html")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", action="store_true",
                        help="build into dist/site/quiz/ for publishing")
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()

    try:
        if args.site:
            build_site(args.out or (REPO_ROOT / "dist" / "site" / "quiz"))
            return 0
        out = args.out or DEFAULT_OUT
        out.parent.mkdir(parents=True, exist_ok=True)
        html = build()
        out.write_text(html, encoding="utf-8")
        print(f"Wrote {out} ({len(html) / 1024:.0f} KB)")
    except BadPack as err:
        print(f"error: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
