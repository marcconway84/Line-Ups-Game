"""Rules of the game: difficulty, pitch layout, hints, scoring and the daily pick.

Everything here is deliberately pure - no database, no clock, no randomness that isn't
passed in. That keeps the rules testable and lets the API layer stay thin.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class Difficulty:
    key: str
    label: str
    #: How many of the eleven are shown for free at kick-off.
    freebies: int
    seconds: int
    multiplier: float


DIFFICULTIES: dict[str, Difficulty] = {
    "easy": Difficulty("easy", "Easy", freebies=4, seconds=240, multiplier=1.0),
    "medium": Difficulty("medium", "Medium", freebies=2, seconds=180, multiplier=1.5),
    "hard": Difficulty("hard", "Hard", freebies=0, seconds=150, multiplier=2.0),
}
DEFAULT_DIFFICULTY = "medium"

#: Difficulty used by the daily challenge, so every player gets the same puzzle.
DAILY_DIFFICULTY = "medium"

POINTS_PER_PLAYER = 100
COMPLETION_BONUS = 250
POINTS_PER_SECOND_REMAINING = 5

HINT_COSTS = {"initials": 40, "reveal": 120}
#: "initials" applies to the whole XI at once, so it is only worth buying once.
MAX_INITIALS_HINTS = 1


def get_difficulty(key: str | None) -> Difficulty:
    return DIFFICULTIES.get((key or DEFAULT_DIFFICULTY).lower(), DIFFICULTIES[DEFAULT_DIFFICULTY])


def layout_slots(formation: Sequence[int]) -> list[dict]:
    """Map a formation such as [4, 3, 3] onto pitch positions for the eleven slots.

    Slot 0 is always the goalkeeper. The remaining slots follow the formation rows,
    back to front, left to right - matching the order players appear in the dataset.
    Rows are returned with their size so the client can space them evenly.
    """
    if sum(formation) != 10:
        raise ValueError(f"formation must account for 10 outfield players, got {list(formation)}")
    rows = [1, *formation]
    slots: list[dict] = []
    slot = 0
    for row_index, row_size in enumerate(rows):
        for column in range(row_size):
            slots.append(
                {
                    "slot": slot,
                    "row": row_index,
                    "column": column,
                    "row_size": row_size,
                    "row_count": len(rows),
                }
            )
            slot += 1
    return slots


def initials_for(name: str) -> str:
    """"Peter Schmeichel" -> "P. S." - enough of a nudge without giving it away."""
    parts = [part for part in str(name).replace("-", " ").split() if part]
    return " ".join(f"{part[0].upper()}." for part in parts)


def pick_free_slots(count: int, seed: str, total: int = 11) -> list[int]:
    """Choose which slots start revealed, deterministically for a given seed.

    The goalkeeper is never given away for free - it is usually the easiest slot to
    guess, so donating it would waste the freebie.
    """
    count = max(0, min(count, total - 1))
    if count == 0:
        return []
    pool = list(range(1, total))
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    chosen: list[int] = []
    # Fisher-Yates style selection driven by the digest, extended if we run out of bytes.
    for index in range(count):
        block = digest[index % len(digest)] + index * 7
        pick = pool.pop(block % len(pool))
        chosen.append(pick)
    return sorted(chosen)


def daily_index(day: date, total: int) -> int:
    """Pick one lineup per calendar day, the same one for everybody."""
    if total <= 0:
        raise ValueError("no lineups available")
    digest = hashlib.sha256(day.isoformat().encode("utf-8")).hexdigest()
    return int(digest, 16) % total


#: Clues a player can buy about one team-mate, dearest first. Price tracks how much
#: each gives away. Every one is computed from the archive rather than recalled, so
#: they are exact by construction and exist for every player without hand-authoring.
#: An anagram is second only to the name itself: it hands over every letter, and a
#: surname is short enough that a football supporter will usually unscramble it.
CLUE_COSTS = {
    "reveal": 150,
    "anagram": 130,
    "career": 110,
    "elsewhere": 90,
    "first": 75,
    "novowels": 60,
    "nation": 50,
    "initials": 40,
    "length": 25,
    "letter": 20,
}

#: Clues that come from the Wikidata sweep rather than from the archive itself, and
#: so are only offered where the lookup found something.
SOURCED_CLUES = ("nation", "career")

VOWELS = frozenset("aeiou")


def surname_letters(name: str) -> str:
    """The surname reduced to bare letters - the basis of the letter clues."""
    from .matching import surname_of

    return "".join(ch for ch in surname_of(name) if ch.isalpha())


def forename(name: str) -> str | None:
    """The forename, or None for a player who goes by a single name (Xavi, Pelé)."""
    parts = str(name).strip().split()
    return parts[0] if len(parts) > 1 else None


def mask_vowels(name: str) -> str:
    """"Schmeichel" -> "SCH·M·CH·L": consonants kept, vowels shown as gaps."""
    return "".join("·" if ch in VOWELS else ch.upper() for ch in surname_letters(name))


def anagram_of(name: str) -> str:
    """A deterministic scramble of the surname that is never the surname itself."""
    letters = list(surname_letters(name).upper())
    if len(letters) < 3:
        return " ".join(letters)
    original = "".join(letters)
    seed = int(hashlib.sha256(original.encode("utf-8")).hexdigest(), 16)
    for _ in range(8):
        # Fisher-Yates driven by the seed, so the same name always scrambles alike.
        for i in range(len(letters) - 1, 0, -1):
            seed = (seed * 6364136223846793005 + 1442695040888963407) % (2**64)
            j = seed % (i + 1)
            letters[i], letters[j] = letters[j], letters[i]
        if "".join(letters) != original:
            break
    return " ".join(letters)


def clue_length(name: str) -> str:
    count = len(surname_letters(name))
    tail = ", not counting the forename." if forename(name) else ", and he goes by one name only."
    return f"{count} letters{tail}"


def available_clues(
    name: str,
    also_appears: int = 0,
    has_nationality: bool = False,
    has_career: bool = False,
) -> list[str]:
    """Clue keys worth offering for this player, dearest first.

    A clue is withheld when it would say nothing: no forename for a single-name
    player, no "elsewhere" unless he really does start in another XI, and none of the
    sourced clues unless the lookup found the fact.
    """
    order = sorted(CLUE_COSTS, key=lambda key: -CLUE_COSTS[key])
    out = []
    for key in order:
        if key == "first" and not forename(name):
            continue
        if key == "elsewhere" and also_appears <= 0:
            continue
        if key == "nation" and not has_nationality:
            continue
        if key == "career" and not has_career:
            continue
        out.append(key)
    return out


@dataclass(frozen=True)
class ScoreBreakdown:
    guessed: int
    guess_points: int
    completion_bonus: int
    time_bonus: int
    hint_penalty: int
    total: int


def score_round(
    *,
    guessed_slots: int,
    completed: bool,
    seconds_remaining: int,
    hint_penalty: int,
    difficulty: Difficulty,
) -> ScoreBreakdown:
    """Score a finished round.

    Only players named by the user count - those handed over by a "reveal" hint or shown
    for free at kick-off earn nothing. Finishing the XI pays a bonus plus whatever time
    was left on the clock.
    """
    guess_points = int(round(guessed_slots * POINTS_PER_PLAYER * difficulty.multiplier))
    completion = int(round(COMPLETION_BONUS * difficulty.multiplier)) if completed else 0
    time_bonus = (
        int(round(max(0, seconds_remaining) * POINTS_PER_SECOND_REMAINING * difficulty.multiplier))
        if completed
        else 0
    )
    total = max(0, guess_points + completion + time_bonus - hint_penalty)
    return ScoreBreakdown(
        guessed=guessed_slots,
        guess_points=guess_points,
        completion_bonus=completion,
        time_bonus=time_bonus,
        hint_penalty=hint_penalty,
        total=total,
    )
