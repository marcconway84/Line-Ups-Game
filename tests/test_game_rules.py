"""Tests for the pure game rules: layout, freebies, scoring and the daily pick."""

from __future__ import annotations

from datetime import date

import pytest

from backend.app import game as rules


class TestLayout:
    def test_keeper_is_slot_zero_and_alone(self):
        slots = rules.layout_slots([4, 4, 2])
        assert len(slots) == 11
        assert slots[0] == {"slot": 0, "row": 0, "column": 0, "row_size": 1, "row_count": 4}

    def test_rows_follow_the_formation(self):
        slots = rules.layout_slots([4, 2, 3, 1])
        sizes = [s["row_size"] for s in slots]
        assert sizes == [1] + [4] * 4 + [2] * 2 + [3] * 3 + [1]
        assert [s["slot"] for s in slots] == list(range(11))

    @pytest.mark.parametrize("formation", [[4, 4, 3], [4, 4], [3, 5, 3]])
    def test_bad_formations_rejected(self, formation):
        with pytest.raises(ValueError):
            rules.layout_slots(formation)


class TestFreeSlots:
    def test_count_matches_difficulty(self):
        for key, difficulty in rules.DIFFICULTIES.items():
            free = rules.pick_free_slots(difficulty.freebies, seed=f"seed-{key}")
            assert len(free) == difficulty.freebies

    def test_keeper_is_never_given_away(self):
        for i in range(60):
            assert 0 not in rules.pick_free_slots(4, seed=f"seed-{i}")

    def test_no_duplicates(self):
        free = rules.pick_free_slots(4, seed="repeatable")
        assert len(set(free)) == len(free)

    def test_same_seed_gives_the_same_slots(self):
        assert rules.pick_free_slots(4, seed="abc") == rules.pick_free_slots(4, seed="abc")

    def test_different_seeds_generally_differ(self):
        variants = {tuple(rules.pick_free_slots(2, seed=f"s{i}")) for i in range(25)}
        assert len(variants) > 1

    def test_zero_and_oversized_requests(self):
        assert rules.pick_free_slots(0, seed="x") == []
        assert len(rules.pick_free_slots(99, seed="x")) == 10  # everyone but the keeper


class TestDailyPick:
    def test_stable_within_a_day(self):
        assert rules.daily_index(date(2026, 8, 10), 20) == rules.daily_index(date(2026, 8, 10), 20)

    def test_in_range(self):
        for day in range(1, 29):
            assert 0 <= rules.daily_index(date(2026, 2, day), 20) < 20

    def test_varies_across_a_month(self):
        picks = {rules.daily_index(date(2026, 3, d), 20) for d in range(1, 32)}
        assert len(picks) > 5

    def test_empty_archive_rejected(self):
        with pytest.raises(ValueError):
            rules.daily_index(date(2026, 1, 1), 0)


class TestInitials:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Peter Schmeichel", "P. S."),
            ("Trent Alexander-Arnold", "T. A. A."),
            ("Xavi", "X."),
            ("Edwin van der Sar", "E. V. D. S."),
        ],
    )
    def test_initials(self, name, expected):
        assert rules.initials_for(name) == expected


class TestScoring:
    hard = rules.DIFFICULTIES["hard"]
    easy = rules.DIFFICULTIES["easy"]

    def test_only_named_players_score(self):
        result = rules.score_round(
            guessed_slots=5, completed=False, seconds_remaining=60,
            hint_penalty=0, difficulty=self.easy,
        )
        assert result.guess_points == 500
        assert result.completion_bonus == 0
        # No time bonus unless the XI is finished.
        assert result.time_bonus == 0
        assert result.total == 500

    def test_completion_pays_bonus_and_leftover_time(self):
        result = rules.score_round(
            guessed_slots=11, completed=True, seconds_remaining=100,
            hint_penalty=0, difficulty=self.hard,
        )
        assert result.guess_points == 2200
        assert result.completion_bonus == 500
        assert result.time_bonus == 1000
        assert result.total == 3700

    def test_hints_are_deducted(self):
        result = rules.score_round(
            guessed_slots=3, completed=False, seconds_remaining=0,
            hint_penalty=160, difficulty=self.easy,
        )
        assert result.total == 300 - 160

    def test_score_never_goes_negative(self):
        result = rules.score_round(
            guessed_slots=0, completed=False, seconds_remaining=0,
            hint_penalty=500, difficulty=self.easy,
        )
        assert result.total == 0

    def test_harder_difficulty_pays_more(self):
        kwargs = dict(guessed_slots=6, completed=True, seconds_remaining=30, hint_penalty=0)
        easy = rules.score_round(**kwargs, difficulty=self.easy)
        hard = rules.score_round(**kwargs, difficulty=self.hard)
        assert hard.total > easy.total


def test_unknown_difficulty_falls_back_to_default():
    assert rules.get_difficulty("nonsense").key == rules.DEFAULT_DIFFICULTY
    assert rules.get_difficulty(None).key == rules.DEFAULT_DIFFICULTY
    assert rules.get_difficulty("HARD").key == "hard"


class TestTheDailyGivesNothingAway:
    """Eleven blanks, the same eleven for everyone who plays that day."""

    def test_the_daily_starts_with_no_names_shown(self):
        assert rules.get_difficulty(rules.DAILY_DIFFICULTY).freebies == 0

    def test_it_is_not_one_of_the_settings_a_player_picks(self):
        # Otherwise it would appear as a fourth chip next to Easy/Medium/Hard.
        assert rules.DAILY_DIFFICULTY not in rules.CHOOSABLE_DIFFICULTIES

    def test_the_choosable_settings_still_offer_a_head_start(self):
        # "Good to have the option on the other line ups" - easy and medium still do.
        assert rules.get_difficulty("easy").freebies == 4
        assert rules.get_difficulty("medium").freebies == 2
        assert rules.get_difficulty("hard").freebies == 0

    def test_the_daily_keeps_the_medium_clock_and_multiplier(self):
        daily, medium = rules.get_difficulty(rules.DAILY_DIFFICULTY), rules.get_difficulty("medium")
        assert (daily.seconds, daily.multiplier) == (medium.seconds, medium.multiplier)

    def test_all_eleven_are_worth_earning(self):
        """The leaderboard rejects a score claiming more players than were on offer.

        With no freebies the ceiling is eleven, not nine, and the worker has to know
        that or an honest full XI on the daily comes back refused.
        """
        daily = rules.get_difficulty(rules.DAILY_DIFFICULTY)
        result = rules.score_round(
            guessed_slots=11 - daily.freebies,
            completed=True,
            seconds_remaining=0,
            hint_penalty=0,
            difficulty=daily,
        )
        assert result.guess_points == 1650
