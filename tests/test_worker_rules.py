"""The leaderboard worker must score a round exactly as the game does.

The worker recalculates every score it is sent instead of trusting the browser. That
is only worth doing if the two agree: a worker that scores differently would mark
honest players down for points they really earned, and the board would quietly stop
matching what anyone saw on their own screen.

So the constants live in backend/app/game.py and are copied into a file the worker
imports. These tests fail if that copy has gone stale, and if the rounding rule the
two sides use ever parts company again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.game import (
    CLUE_COSTS,
    COMPLETION_BONUS,
    DIFFICULTIES,
    POINTS_PER_PLAYER,
    POINTS_PER_SECOND_REMAINING,
    get_difficulty,
    round_half_up,
    score_round,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED = REPO_ROOT / "worker" / "src" / "rules.generated.json"
GENERATOR = REPO_ROOT / "scripts" / "generate_worker_rules.py"


@pytest.fixture(scope="module")
def rules() -> dict:
    return json.loads(GENERATED.read_text(encoding="utf-8"))


class TestTheCopyIsCurrent:
    def test_the_file_is_checked_in(self):
        assert GENERATED.exists(), "run scripts/generate_worker_rules.py"

    def test_regenerating_changes_nothing(self):
        """Catches a price changed in game.py and not carried across to the worker."""
        before = GENERATED.read_text(encoding="utf-8")
        subprocess.run([sys.executable, str(GENERATOR)], check=True, capture_output=True)
        after = GENERATED.read_text(encoding="utf-8")
        assert before == after, "worker rules are stale - run scripts/generate_worker_rules.py"

    def test_every_clue_price_came_across(self, rules):
        assert rules["clueCosts"] == CLUE_COSTS

    def test_every_difficulty_came_across(self, rules):
        for key, difficulty in DIFFICULTIES.items():
            assert rules["difficulties"][key]["seconds"] == difficulty.seconds
            assert rules["difficulties"][key]["multiplier"] == difficulty.multiplier
            assert rules["difficulties"][key]["freebies"] == difficulty.freebies

    def test_the_scoring_constants_came_across(self, rules):
        assert rules["pointsPerPlayer"] == POINTS_PER_PLAYER
        assert rules["completionBonus"] == COMPLETION_BONUS
        assert rules["pointsPerSecondRemaining"] == POINTS_PER_SECOND_REMAINING


class TestRounding:
    """A second is worth 7.5 points at medium, so halves are the common case."""

    @pytest.mark.parametrize(
        "value, expected",
        [(22.5, 23), (23.5, 24), (52.5, 53), (0.5, 1), (7.4, 7), (7.6, 8), (0.0, 0)],
    )
    def test_halves_go_up_like_javascript(self, value, expected):
        assert round_half_up(value) == expected

    def test_the_builtin_would_have_disagreed(self):
        # Python's round() sends a half to the nearest even number. Pinned here so the
        # difference is on the record rather than rediscovered as a one-point bug.
        assert round(22.5) == 22
        assert round_half_up(22.5) == 23

    def test_an_odd_clock_scores_the_same_as_the_browser(self):
        # The browser does Math.round(7 * 5 * 1.5) = Math.round(52.5) = 53.
        result = score_round(
            guessed_slots=0,
            completed=True,
            seconds_remaining=7,
            hint_penalty=0,
            difficulty=get_difficulty("medium"),
        )
        assert result.time_bonus == 53


class TestAgreementWithTheWorker:
    """A worked example both sides are pinned to, so neither can drift alone."""

    def test_a_full_medium_round(self):
        result = score_round(
            guessed_slots=9,
            completed=True,
            seconds_remaining=180,
            hint_penalty=0,
            difficulty=get_difficulty("medium"),
        )
        # The same 3075 the worker's end-to-end tests assert on.
        assert (result.guess_points, result.completion_bonus, result.time_bonus) == (1350, 375, 1350)
        assert result.total == 3075

    def test_a_conceded_round_earns_guesses_only(self):
        result = score_round(
            guessed_slots=4,
            completed=False,
            seconds_remaining=180,
            hint_penalty=0,
            difficulty=get_difficulty("medium"),
        )
        assert result.total == 600
