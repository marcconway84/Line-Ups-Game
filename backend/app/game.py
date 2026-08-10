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
