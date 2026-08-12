"""Tests for the per-player clue sheet.

The whole point of these clues is that they are computed rather than recalled, so
they cannot be subtly wrong. These tests check that claim against every player in
the archive, not just a sample.
"""

from __future__ import annotations

import pytest

from backend.app.game import (
    CLUE_COSTS,
    anagram_of,
    available_clues,
    clue_length,
    forename,
    mask_vowels,
    surname_letters,
)
from backend.app.matching import normalize


@pytest.fixture(scope="module")
def players(dataset) -> list[dict]:
    return [p for lineup in dataset["lineups"] for p in lineup["players"]]


class TestPricing:
    def test_revealing_the_name_is_dearest(self):
        assert CLUE_COSTS["reveal"] == max(CLUE_COSTS.values())

    def test_one_letter_is_cheapest(self):
        assert CLUE_COSTS["letter"] == min(CLUE_COSTS.values())

    def test_offered_dearest_first(self):
        order = available_clues("Peter Schmeichel", also_appears=1,
                                has_nationality=True, has_career=True)
        costs = [CLUE_COSTS[key] for key in order]
        assert costs == sorted(costs, reverse=True)

    def test_the_anagram_is_second_dearest(self):
        """It hands over every letter of a short word, so it is nearly the answer."""
        ranked = sorted(CLUE_COSTS, key=lambda key: -CLUE_COSTS[key])
        assert ranked[0] == "reveal"
        assert ranked[1] == "anagram"

    def test_sourced_clues_are_withheld_when_the_lookup_found_nothing(self):
        offered = available_clues("Peter Schmeichel", also_appears=1)
        assert "nation" not in offered and "career" not in offered
        offered = available_clues("Peter Schmeichel", also_appears=1,
                                  has_nationality=True, has_career=True)
        assert "nation" in offered and "career" in offered

    def test_every_clue_has_a_distinct_price(self):
        assert len(set(CLUE_COSTS.values())) == len(CLUE_COSTS)


class TestAcrossTheArchive:
    """Every clue must hold for all 220 players, accents and one-name players included."""

    def test_length_matches_the_surname(self, players):
        for player in players:
            stated = int(clue_length(player["name"]).split()[0])
            assert stated == len(surname_letters(player["name"])), player["name"]

    def test_anagram_uses_exactly_the_surname_letters(self, players):
        for player in players:
            letters = anagram_of(player["name"]).replace(" ", "")
            assert sorted(letters) == sorted(surname_letters(player["name"]).upper()), player["name"]

    def test_anagram_is_never_the_surname_itself(self, players):
        for player in players:
            surname = surname_letters(player["name"]).upper()
            if len(surname) < 3:
                continue  # too short to scramble meaningfully
            assert anagram_of(player["name"]).replace(" ", "") != surname, player["name"]

    def test_anagram_is_stable(self, players):
        for player in players:
            assert anagram_of(player["name"]) == anagram_of(player["name"])

    def test_masked_surname_keeps_length_and_hides_vowels(self, players):
        for player in players:
            masked = mask_vowels(player["name"])
            assert len(masked) == len(surname_letters(player["name"])), player["name"]
            assert not set(masked.lower()) & set("aeiou"), player["name"]

    def test_forename_is_never_the_whole_name(self, players):
        for player in players:
            first = forename(player["name"])
            if first is not None:
                assert normalize(first) != normalize(player["name"]), player["name"]

    def test_single_name_players_are_not_offered_a_forename(self, players):
        for player in players:
            if forename(player["name"]) is None:
                assert "first" not in available_clues(player["name"])

    def test_every_player_gets_a_usable_sheet(self, players):
        for player in players:
            offered = available_clues(player["name"])
            # Even the sparsest player can be probed several ways before paying up.
            assert len(offered) >= 6, player["name"]
            assert "reveal" in offered and "initials" in offered


class TestElsewhere:
    def test_offered_only_when_he_appears_again(self):
        assert "elsewhere" not in available_clues("Peter Schmeichel", also_appears=0)
        assert "elsewhere" in available_clues("Peter Schmeichel", also_appears=2)

    def test_repeat_players_really_do_repeat(self, dataset):
        """The clue claims a player starts in another XI - check the data agrees."""
        seen: dict[str, list[str]] = {}
        for lineup in dataset["lineups"]:
            for player in lineup["players"]:
                seen.setdefault(normalize(player["name"]), []).append(lineup["id"])
        repeats = {name: ids for name, ids in seen.items() if len(ids) > 1}
        assert repeats, "the archive should contain some players more than once"
        for name, ids in repeats.items():
            assert len(set(ids)) == len(ids), f"{name} listed twice in one XI"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Peter Schmeichel", "SCHM··CH·L"),
        ("Xavi", "X·V·"),
        ("Gerard Piqué", "P·Q··"),          # accents folded before masking
        ("Edwin van der Sar", "V·ND·RS·R"),  # particles belong to the surname
    ],
)
def test_masking_examples(name, expected):
    assert mask_vowels(name) == expected


@pytest.mark.parametrize(
    "name, expected",
    [("Peter Schmeichel", "Peter"), ("Xavi", None), ("Trent Alexander-Arnold", "Trent")],
)
def test_forename_examples(name, expected):
    assert forename(name) == expected
