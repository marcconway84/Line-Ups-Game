"""Tests for guess matching - the part players notice most when it is wrong."""

from __future__ import annotations

import pytest

from backend.app.matching import (
    Candidate,
    alias_keys,
    edit_distance,
    match_guess,
    normalize,
    surname_of,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Gerard Piqué", "gerard pique"),
        ("Milan Baroš", "milan baros"),
        ("N'Golo Kanté", "ngolo kante"),
        ("Samuel Eto'o", "samuel etoo"),
        ("Stéphane Guivarc'h", "stephane guivarch"),
        ("Trent Alexander-Arnold", "trent alexander arnold"),
        ("  MESSI  ", "messi"),
        ("İlkay Gündoğan", "ilkay gundogan"),
        ("Peter Schmeichel!!", "peter schmeichel"),
        ("CR7", "cr7"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("David Beckham", "beckham"),
        ("Edwin van der Sar", "van der sar"),
        ("Kevin De Bruyne", "de bruyne"),
        ("Alexis Mac Allister", "mac allister"),
        ("Xavi", "xavi"),
        ("Roberto Carlos", "carlos"),
    ],
)
def test_surname_keeps_particles(name, expected):
    assert surname_of(name) == expected


def test_alias_keys_cover_the_obvious_answers():
    keys = alias_keys("Virgil van Dijk", ["vvd"])
    assert {"virgil van dijk", "van dijk", "dijk", "vvd"} <= keys


def test_edit_distance_gives_up_early():
    assert edit_distance("beckham", "beckham", 1) == 0
    assert edit_distance("beckam", "beckham", 1) == 1
    assert edit_distance("totally-different", "beckham", 1) == 2


class TestMatchGuess:
    @staticmethod
    def xi():
        # A trimmed England 1966 side: two Charltons, to exercise ambiguity.
        return [
            Candidate.build(0, "Gordon Banks"),
            Candidate.build(1, "Jack Charlton"),
            Candidate.build(2, "Bobby Charlton"),
            Candidate.build(3, "Geoff Hurst"),
            Candidate.build(4, "Nobby Stiles", ["norbert stiles"]),
        ]

    def test_surname_alone_is_enough(self):
        assert match_guess("banks", self.xi()).slot == 0

    def test_full_name_works(self):
        assert match_guess("Gordon Banks", self.xi()).slot == 0

    def test_shared_surname_is_ambiguous(self):
        result = match_guess("charlton", self.xi())
        assert result.status == "ambiguous"
        assert result.slots == (1, 2)
        assert result.slot is None

    def test_first_name_disambiguates(self):
        assert match_guess("bobby charlton", self.xi()).slot == 2
        assert match_guess("jack charlton", self.xi()).slot == 1

    def test_nickname_alias(self):
        assert match_guess("norbert stiles", self.xi()).slot == 4

    def test_small_typo_forgiven(self):
        result = match_guess("gordan banks", self.xi())
        assert result.slot == 0
        assert result.fuzzy is True

    def test_unrelated_guess_rejected(self):
        assert match_guess("cristiano ronaldo", self.xi()).status == "no_match"

    def test_short_and_empty_guesses(self):
        assert match_guess("", self.xi()).status == "empty"
        assert match_guess("ba", self.xi()).status == "too_short"

    def test_short_names_require_exact_spelling(self):
        # "Xavi" is too short to forgive a typo without matching half the squad.
        xi = [Candidate.build(0, "Xavi"), Candidate.build(1, "Pelé")]
        assert match_guess("xavi", xi).slot == 0
        assert match_guess("pele", xi).slot == 1
        assert match_guess("xavr", xi).status == "no_match"

    def test_accents_are_optional(self):
        xi = [Candidate.build(0, "Gerard Piqué"), Candidate.build(1, "Milan Baroš")]
        assert match_guess("pique", xi).slot == 0
        assert match_guess("Piqué", xi).slot == 0
        assert match_guess("baros", xi).slot == 1

    def test_result_is_deterministic_across_candidate_order(self):
        forwards = list(reversed(self.xi()))
        assert match_guess("gordan banks", forwards).slots == (0,)

    def test_double_barrelled_surname_accepted_whole(self):
        xi = [Candidate.build(0, "Trent Alexander-Arnold", ["trent", "taa"])]
        for guess in ["Alexander-Arnold", "alexander arnold", "arnold", "taa"]:
            assert match_guess(guess, xi).slot == 0, guess

    def test_short_curated_alias_beats_the_length_guard(self):
        xi = [Candidate.build(0, "Ronaldo", ["r9"]), Candidate.build(1, "Rivaldo")]
        assert match_guess("r9", xi).slot == 0
        # A short guess that is not a curated alias is still turned away.
        assert match_guess("ri", xi).status == "too_short"
