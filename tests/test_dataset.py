"""Checks on data/lineups.json.

The dataset is hand-curated, so these guard the shape of it and the properties the game
depends on - not the football facts, which are covered by each entry's source_url.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.app.game import layout_slots
from backend.app.matching import Candidate, match_guess, normalize
from backend.app.seed import validate_dataset


def test_dataset_is_valid(dataset):
    assert validate_dataset(dataset) == []


def test_has_a_decent_archive(dataset):
    assert len(dataset["lineups"]) >= 15


def test_every_lineup_lays_out_on_the_pitch(dataset):
    for lineup in dataset["lineups"]:
        slots = layout_slots(lineup["formation"])
        assert len(slots) == len(lineup["players"]) == 11


def test_first_player_is_the_keeper(dataset):
    for lineup in dataset["lineups"]:
        assert lineup["players"][0]["pos"] == "GK", lineup["id"]


def test_only_the_keeper_is_a_keeper(dataset):
    for lineup in dataset["lineups"]:
        keepers = [p for p in lineup["players"] if p["pos"] == "GK"]
        assert len(keepers) == 1, lineup["id"]


def test_dates_are_real_and_ordered_sensibly(dataset):
    for lineup in dataset["lineups"]:
        parsed = date.fromisoformat(lineup["date"])
        assert date(1950, 1, 1) < parsed <= date.today(), lineup["id"]


def test_every_lineup_is_one_specific_match(dataset):
    """The point of the game is a particular team sheet on a particular night.

    A "most-used XI of the season" is not something a player can picture, so an
    opponent and a date are required of every entry.
    """
    for lineup in dataset["lineups"]:
        assert lineup.get("opponent"), f"{lineup['id']} has no opponent"
        assert lineup.get("date"), f"{lineup['id']} has no date"
        assert lineup.get("venue"), f"{lineup['id']} has no venue"


def test_a_lineup_without_an_opponent_is_rejected(dataset):
    """The validator must catch it, not just the curator."""
    from copy import deepcopy

    broken = deepcopy(dataset)
    broken["lineups"] = [deepcopy(dataset["lineups"][0])]
    broken["lineups"][0]["opponent"] = None
    problems = validate_dataset(broken)
    assert any("opponent" in problem for problem in problems)


def test_sources_are_links(dataset):
    for lineup in dataset["lineups"]:
        assert lineup["source_url"].startswith("https://"), lineup["id"]


def test_every_player_can_be_guessed_by_their_own_name(dataset):
    """The whole game rests on this: typing a player's name must find them."""
    failures = []
    for lineup in dataset["lineups"]:
        candidates = [
            Candidate.build(i, p["name"], p.get("accepts", []))
            for i, p in enumerate(lineup["players"])
        ]
        for index, player in enumerate(lineup["players"]):
            result = match_guess(player["name"], candidates)
            if result.slot != index:
                failures.append(f"{lineup['id']}: {player['name']} -> {result.status}")
    assert failures == []


def test_every_player_can_be_guessed_by_surname_or_flagged_ambiguous(dataset):
    """A surname should either identify one player or be reported as ambiguous.

    Two players sharing a surname in the same XI (the Charltons in 1966) is fine - being
    silently credited to the wrong one would not be.
    """
    failures = []
    for lineup in dataset["lineups"]:
        candidates = [
            Candidate.build(i, p["name"], p.get("accepts", []))
            for i, p in enumerate(lineup["players"])
        ]
        for index, player in enumerate(lineup["players"]):
            surname = player["name"].split()[-1]
            result = match_guess(surname, candidates)
            if result.status == "match" and result.slot != index:
                failures.append(f"{lineup['id']}: '{surname}' credited to the wrong player")
            elif result.status == "no_match":
                failures.append(f"{lineup['id']}: '{surname}' matched nobody")
    assert failures == []


def test_curated_aliases_resolve_to_their_own_player(dataset):
    failures = []
    for lineup in dataset["lineups"]:
        candidates = [
            Candidate.build(i, p["name"], p.get("accepts", []))
            for i, p in enumerate(lineup["players"])
        ]
        for index, player in enumerate(lineup["players"]):
            for alias in player.get("accepts", []):
                result = match_guess(alias, candidates)
                if result.slot != index:
                    failures.append(f"{lineup['id']}: alias '{alias}' -> {result.status}")
    assert failures == []


def test_ids_and_names_are_normalised_consistently(dataset):
    for lineup in dataset["lineups"]:
        assert lineup["id"] == lineup["id"].lower()
        for player in lineup["players"]:
            assert normalize(player["name"]), lineup["id"]


@pytest.mark.parametrize("field", ["team", "competition", "formation", "players", "source_url"])
def test_required_fields_present(dataset, field):
    for lineup in dataset["lineups"]:
        assert lineup.get(field), f"{lineup['id']} is missing {field}"


class TestTheDailySchedule:
    """A chosen daily must name a lineup that exists, or the day silently breaks."""

    @staticmethod
    def schedule() -> dict:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "data" / "daily.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")).get("schedule", {})

    def test_every_chosen_day_names_a_real_lineup(self, dataset):
        known = {entry["id"] for entry in dataset["lineups"]}
        for day, lineup_id in self.schedule().items():
            assert lineup_id in known, f"{day} names an unknown lineup: {lineup_id}"

    def test_every_key_is_an_iso_date(self):
        from datetime import date

        for day in self.schedule():
            date.fromisoformat(day)  # raises if it is not a real yyyy-mm-dd
