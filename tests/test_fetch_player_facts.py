"""Tests for the Wikidata fetcher's offline half.

The network call itself cannot run in the development sandbox (Wikidata is blocked by
the egress proxy), so it is exercised in CI. Everything around it - folding the query
rows into one record, ordering a career, reading the dataset - is pure and is tested
here, against recorded response shapes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_player_facts.py"
spec = importlib.util.spec_from_file_location("fetch_player_facts", MODULE_PATH)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def row(kind, label, start=None):
    """Build a typed SPARQL binding row the way the endpoint returns them."""
    binding = {"kind": {"value": kind}, "label": {"value": label}}
    if start:
        binding["start"] = {"value": start}
    return binding


class TestSummarise:
    def test_empty_result_is_all_none(self):
        assert fetch.summarise([]) == {"nationality": None, "national_team": None, "career": []}

    def test_nationality_comes_from_the_national_side(self):
        facts = fetch.summarise([
            row("citizenship", "United Kingdom"),
            row("national", "England national football team"),
        ])
        # Citizenship cannot tell England from Scotland; the national side can.
        assert facts["nationality"] == "England"

    def test_citizenship_is_the_fallback_and_is_tidied(self):
        facts = fetch.summarise([row("citizenship", "Kingdom of Denmark")])
        assert facts["nationality"] == "Denmark"

    def test_youth_and_olympic_sides_are_ignored(self):
        facts = fetch.summarise([
            row("national", "Spain national under-21 football team"),
            row("national", "Spain Olympic football team"),
            row("national", "Spain national football team"),
        ])
        assert facts["nationality"] == "Spain"

    def test_a_youth_cap_alone_does_not_set_nationality(self):
        facts = fetch.summarise([
            row("citizenship", "French Republic"),
            row("national", "France national under-21 football team"),
        ])
        assert facts["nationality"] == "France"        # from citizenship, tidied
        assert facts["national_team"] is None

    def test_caps_are_not_reported_at_all(self):
        """The probe proved these are unreliable, so they must not leak back in."""
        assert "caps" not in fetch.summarise([row("national", "Denmark national football team")])
        assert "goals" not in fetch.summarise([])

    def test_career_is_ordered_by_start_date(self):
        facts = fetch.summarise([
            row("club", "Manchester United", "1991-01-01T00:00:00Z"),
            row("club", "Hvidovre", "1984-01-01T00:00:00Z"),
            row("club", "Brondby", "1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Hvidovre", "Brondby", "Manchester United"]

    def test_clubs_without_a_date_go_last_and_are_not_dropped(self):
        facts = fetch.summarise([
            row("club", "Aston Villa"),
            row("club", "Brondby", "1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Brondby", "Aston Villa"]

    def test_repeated_rows_do_not_duplicate_a_club(self):
        facts = fetch.summarise([
            row("club", "Liverpool", "1999-01-01T00:00:00Z"),
            row("club", "Liverpool", "1999-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Liverpool"]

    def test_a_club_rejoined_later_keeps_its_first_spell(self):
        facts = fetch.summarise([
            row("club", "Atletico Madrid", "2007-01-01T00:00:00Z"),
            row("club", "Atletico Madrid", "2002-01-01T00:00:00Z"),
            row("club", "Liverpool", "2004-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Atletico Madrid", "Liverpool"]

    def test_national_sides_never_appear_in_the_club_career(self):
        facts = fetch.summarise([
            row("national", "Denmark national football team"),
            row("club", "Brondby", "1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Brondby"]
        assert facts["national_team"] == "Denmark national football team"


class TestLabelTidying:
    @pytest.mark.parametrize("team, expected", [
        ("England national football team", "England"),
        ("Brazil national association football team", "Brazil"),
        ("Wales national football team", "Wales"),
        ("Trinidad and Tobago national football team", "Trinidad and Tobago"),
    ])
    def test_country_from_team(self, team, expected):
        assert fetch.country_from_team(team) == expected

    @pytest.mark.parametrize("label, senior", [
        ("England national football team", True),
        ("England national under-21 football team", False),
        ("Spain Olympic football team", False),
        ("Germany youth national football team", False),
    ])
    def test_senior_side_detection(self, label, senior):
        assert fetch.is_senior_side(label) is senior


class TestNameList:
    def test_every_dataset_player_is_offered_once(self, dataset):
        names = fetch.dataset_names()
        assert len(names) == len(set(names)), "the lookup list should be deduplicated"
        every = {p["name"] for lineup in dataset["lineups"] for p in lineup["players"]}
        assert set(names) == every

    def test_probe_names_are_really_in_the_archive(self, dataset):
        every = {p["name"] for lineup in dataset["lineups"] for p in lineup["players"]}
        for name in fetch.PROBE_NAMES:
            assert name in every, f"{name} is not in the archive, so it is a poor probe"


def test_query_asks_for_the_fields_we_parse():
    """Guard against the query and the parser drifting apart."""
    for token in ("?kind", "?label", "?start", "citizenship", "national", "club"):
        assert token.lstrip("?") in fetch.FACTS_QUERY


def test_query_no_longer_asks_for_caps():
    """Caps were dropped as unreliable; the query should not fetch them either."""
    assert "P1350" not in fetch.FACTS_QUERY and "P1351" not in fetch.FACTS_QUERY


def test_user_agent_identifies_the_project():
    # Wikidata blocks anonymous default agents; this must stay descriptive.
    assert "Line-Ups-Game" in fetch.USER_AGENT


def test_cli_refuses_to_run_without_a_mode(monkeypatch, capsys):
    """Running it bare should explain itself, not silently hit the network."""
    monkeypatch.setattr(fetch.sys, "argv", ["fetch_player_facts.py"])
    with pytest.raises(SystemExit) as exit_info:
        fetch.main()
    assert exit_info.value.code != 0
    assert "--probe" in capsys.readouterr().err
