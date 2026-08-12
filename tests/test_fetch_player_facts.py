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


def row(**values):
    """Build a SPARQL binding row the way the endpoint returns them."""
    return {key: {"value": str(value)} for key, value in values.items()}


class TestSummarise:
    def test_empty_result_is_all_none(self):
        facts = fetch.summarise([])
        assert facts == {
            "nationality": None,
            "national_team": None,
            "caps": None,
            "goals": None,
            "career": [],
        }

    def test_reads_the_headline_facts(self):
        facts = fetch.summarise([
            row(nationalityLabel="Denmark", teamLabel="Denmark national football team",
                caps="129", goals="1"),
        ])
        assert facts["nationality"] == "Denmark"
        assert facts["national_team"] == "Denmark national football team"
        assert facts["caps"] == 129
        assert facts["goals"] == 1

    def test_caps_arriving_as_a_decimal(self):
        # SPARQL returns numeric literals as strings, sometimes "129.0".
        assert fetch.summarise([row(caps="129.0")])["caps"] == 129

    def test_career_is_ordered_by_start_date(self):
        facts = fetch.summarise([
            row(clubLabel="Manchester United", start="1991-01-01T00:00:00Z"),
            row(clubLabel="Hvidovre", start="1984-01-01T00:00:00Z"),
            row(clubLabel="Brondby", start="1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Hvidovre", "Brondby", "Manchester United"]

    def test_clubs_without_a_date_go_last_and_are_not_dropped(self):
        facts = fetch.summarise([
            row(clubLabel="Aston Villa"),
            row(clubLabel="Brondby", start="1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Brondby", "Aston Villa"]

    def test_repeated_rows_do_not_duplicate_a_club(self):
        facts = fetch.summarise([
            row(clubLabel="Liverpool", start="1999-01-01T00:00:00Z"),
            row(clubLabel="Liverpool", start="1999-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Liverpool"]

    def test_a_club_rejoined_later_keeps_its_first_spell(self):
        facts = fetch.summarise([
            row(clubLabel="Atletico Madrid", start="2007-01-01T00:00:00Z"),
            row(clubLabel="Atletico Madrid", start="2002-01-01T00:00:00Z"),
            row(clubLabel="Liverpool", start="2004-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Atletico Madrid", "Liverpool"]

    def test_national_team_is_not_listed_as_a_club(self):
        """The query excludes national sides; the fold must not reintroduce one."""
        facts = fetch.summarise([
            row(teamLabel="Denmark national football team", caps="129"),
            row(clubLabel="Brondby", start="1987-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["Brondby"]
        assert facts["national_team"] == "Denmark national football team"


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
    for token in ("nationalityLabel", "teamLabel", "?caps", "?goals", "clubLabel", "?start"):
        assert token.lstrip("?") in fetch.FACTS_QUERY


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
