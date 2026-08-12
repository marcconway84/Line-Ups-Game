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


def row(kind, label, start=None, founded=None):
    """Build a typed SPARQL binding row the way the endpoint returns them."""
    binding = {"kind": {"value": kind}, "label": {"value": label}}
    if start:
        binding["start"] = {"value": start}
    if founded:
        binding["founded"] = {"value": founded}
    return binding


class TestSummarise:
    def test_empty_result_is_all_none(self):
        assert fetch.summarise([]) == {
            "nationality": None, "national_team": None, "born": None,
            "career": [], "rejected_spells": [],
        }

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


class TestImplausibleSpells:
    """Wikidata carries the odd bad claim; a career clue must not repeat it."""

    BORN = [{"kind": {"value": "born"}, "label": {"value": "1941"}}]

    def test_a_club_joined_after_a_plausible_career_is_rejected(self):
        # Bobby Moore, born 1941, came back with a club founded in 1999.
        facts = fetch.summarise(self.BORN + [
            row("club", "West Ham United F.C.", "1958-01-01T00:00:00Z"),
            row("club", "FC Midtjylland", "1999-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["West Ham United"]
        assert facts["rejected_spells"] == ["FC Midtjylland (joined aged 58)"]

    def test_an_academy_spell_is_kept(self):
        """Messi joined Newell's at six. A youth club is career history, not a bad claim."""
        facts = fetch.summarise(self.BORN + [row("club", "Youth Club", "1950-01-01T00:00:00Z")])
        assert facts["career"] == ["Youth Club"]

    def test_a_spell_beginning_before_birth_is_rejected(self):
        facts = fetch.summarise(self.BORN + [row("club", "Impossible", "1930-01-01T00:00:00Z")])
        assert facts["career"] == []

    def test_an_undated_spell_at_a_club_founded_too_late_is_rejected(self):
        """The real Bobby Moore case: no start date, so only the club's age catches it."""
        facts = fetch.summarise(self.BORN + [
            row("club", "West Ham United F.C.", "1958-01-01T00:00:00Z"),
            row("club", "FC Midtjylland", founded="1999-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["West Ham United"]
        assert facts["rejected_spells"] == ["FC Midtjylland (club founded 1999, player born 1941)"]

    def test_a_club_older_than_the_player_is_fine(self):
        facts = fetch.summarise(self.BORN + [
            row("club", "West Ham United F.C.", founded="1895-01-01T00:00:00Z"),
        ])
        assert facts["career"] == ["West Ham United"]

    def test_spells_are_kept_when_there_is_no_birth_year_to_judge_against(self):
        facts = fetch.summarise([row("club", "FC Midtjylland", "1999-01-01T00:00:00Z")])
        assert facts["career"] == ["FC Midtjylland"]

    def test_undated_spells_survive(self):
        facts = fetch.summarise(self.BORN + [row("club", "Seattle Sounders")])
        assert facts["career"] == ["Seattle Sounders"]


class TestLabelTidying:
    @pytest.mark.parametrize("team, expected", [
        ("England national football team", "England"),
        ("England men's national association football team", "England"),
        ("Denmark men's national association football team", "Denmark"),
        ("Brazil national association football team", "Brazil"),
        ("Wales national football team", "Wales"),
        ("Trinidad and Tobago national football team", "Trinidad and Tobago"),
    ])
    def test_country_from_team(self, team, expected):
        assert fetch.country_from_team(team) == expected

    @pytest.mark.parametrize("club, expected", [
        ("Manchester United F.C.", "Manchester United"),
        ("West Ham United F.C.", "West Ham United"),
        ("Arsenal F.C.", "Arsenal"),
        ("FC Barcelona", "FC Barcelona"),      # the prefix form is the real name
        ("AC Milan", "AC Milan"),
        ("Santos FC", "Santos"),
    ])
    def test_tidy_club(self, club, expected):
        assert fetch.tidy_club(club) == expected

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
    for token in ("?kind", "?label", "?start", "citizenship", "national", "club", "born"):
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


class TestReviewSummary:
    """The sweep's last words should be what a reviewer needs to act on."""

    RESULTS = {
        "Peter Schmeichel": {"nationality": "Denmark", "career": ["Brondby", "Manchester United"],
                             "rejected_spells": []},
        "Bobby Moore": {"nationality": "England", "career": ["West Ham United"],
                        "rejected_spells": ["FC Midtjylland (joined aged 58)"]},
        "Someone Obscure": {"nationality": None, "career": [], "rejected_spells": []},
    }
    NAMES = ["Peter Schmeichel", "Bobby Moore", "Someone Obscure", "Never Heard Of Him"]

    def summary(self, capsys):
        fetch.report(self.NAMES, self.RESULTS)
        return capsys.readouterr().out

    def test_counts_are_reported(self, capsys):
        out = self.summary(capsys)
        assert "looked up      4" in out
        assert "resolved       3" in out

    def test_unresolved_players_are_named(self, capsys):
        assert "Never Heard Of Him" in self.summary(capsys)

    def test_players_missing_facts_are_named(self, capsys):
        out = self.summary(capsys)
        assert "Resolved but no nationality" in out
        assert "Someone Obscure" in out

    def test_thin_careers_are_flagged_for_checking(self, capsys):
        # One club is usually a lookup that half-worked, worth a human glance.
        assert "Only one club" in self.summary(capsys)

    def test_rejected_claims_are_surfaced(self, capsys):
        out = self.summary(capsys)
        assert "FC Midtjylland" in out
        assert "rejected as implausible" in out


class TestFootballerDetection:
    """Occupation alone missed several single-name players in the full sweep."""

    def test_occupation_marks_a_footballer(self):
        claims = {"P106": [{"mainsnak": {"datavalue": {"value": {"id": fetch.ASSOCIATION_FOOTBALLER}}}}]}
        assert fetch.is_footballer(claims)

    def test_sport_alone_is_enough(self):
        claims = {"P641": [{"mainsnak": {"datavalue": {"value": {"id": fetch.ASSOCIATION_FOOTBALL}}}}]}
        assert fetch.is_footballer(claims)

    def test_someone_unrelated_is_not_a_footballer(self):
        claims = {"P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q177220"}}}}]}  # singer
        assert not fetch.is_footballer(claims)

    def test_no_claims_at_all(self):
        assert not fetch.is_footballer({})


class TestRejectionReasons:
    def test_reason_names_the_age(self):
        assert "58" in fetch.rejection_reason(1941, "1999-01-01T00:00:00Z")

    def test_reason_names_the_founding_year(self):
        reason = fetch.rejection_reason(1941, None, "1999-01-01T00:00:00Z")
        assert "1999" in reason and "1941" in reason

    def test_a_good_spell_has_no_reason(self):
        assert fetch.rejection_reason(1941, "1958-01-01T00:00:00Z", "1895-01-01T00:00:00Z") is None


class TestResolvingAName:
    """The first full sweep reported success while silently losing 28 players.

    Every one of them - Messi, Xavi, Kimmich among them - came back as "NOT FOUND"
    because the whole-entity request answered without the claims it was asked for.
    These tests pin the two things that let that happen: a request that treats an
    error body as an empty answer, and a lookup that cannot say why it gave up.
    """

    def test_an_error_body_is_raised_not_swallowed(self, monkeypatch):
        monkeypatch.setattr(
            fetch.urllib.request,
            "urlopen",
            lambda *a, **k: _FakeResponse('{"error": {"info": "too big"}}'),
        )
        with pytest.raises(RuntimeError, match="too big"):
            fetch._get(fetch.WIKIDATA_API, {})

    def test_one_property_is_asked_for_at_a_time(self, monkeypatch):
        asked = []

        def fake_get(url, params, **kwargs):
            asked.append(params)
            return {"claims": {"P106": [_occupation(fetch.ASSOCIATION_FOOTBALLER)]}}

        monkeypatch.setattr(fetch, "_get", fake_get)
        claims = fetch.footballer_claims("Q615")
        assert fetch.is_footballer(claims)
        assert asked[0]["action"] == "wbgetclaims"
        assert asked[0]["property"] == "P106"
        # Occupation settled it, so there was no need to ask about sport as well.
        assert len(asked) == 1

    def test_sport_is_only_asked_for_when_occupation_is_silent(self, monkeypatch):
        asked = []

        def fake_get(url, params, **kwargs):
            asked.append(params["property"])
            if params["property"] == "P641":
                return {"claims": {"P641": [_occupation(fetch.ASSOCIATION_FOOTBALL)]}}
            return {"claims": {}}

        monkeypatch.setattr(fetch, "_get", fake_get)
        assert fetch.is_footballer(fetch.footballer_claims("Q42"))
        assert asked == ["P106", "P641"]

    def test_a_failed_lookup_says_which_entities_it_turned_down(self, monkeypatch):
        def fake_get(url, params, **kwargs):
            if params.get("action") == "wbsearchentities":
                return {"search": [{"id": "Q1", "description": "a singer"}]}
            return {"claims": {}}

        monkeypatch.setattr(fetch, "_get", fake_get)
        trace = []
        assert fetch.find_player("Someone Else", trace) is None
        assert any("Q1" in line and "a singer" in line for line in trace)

    def test_a_search_with_no_hits_says_so(self, monkeypatch):
        monkeypatch.setattr(fetch, "_get", lambda url, params, **kw: {"search": []})
        trace = []
        assert fetch.find_player("Nobody At All", trace) is None
        assert trace == ["search returned nothing"]


class TestRetries:
    def test_a_rate_limit_is_retried(self, monkeypatch):
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) < 3:
                raise fetch.urllib.error.HTTPError("u", 429, "slow down", {}, None)
            return _FakeResponse('{"ok": true}')

        monkeypatch.setattr(fetch.urllib.request, "urlopen", flaky)
        monkeypatch.setattr(fetch.time, "sleep", lambda _: None)
        assert fetch._get(fetch.WIKIDATA_API, {}) == {"ok": True}
        assert len(calls) == 3

    def test_a_missing_page_is_not_retried(self, monkeypatch):
        calls = []

        def gone(*a, **k):
            calls.append(1)
            raise fetch.urllib.error.HTTPError("u", 404, "gone", {}, None)

        monkeypatch.setattr(fetch.urllib.request, "urlopen", gone)
        monkeypatch.setattr(fetch.time, "sleep", lambda _: None)
        with pytest.raises(fetch.urllib.error.HTTPError):
            fetch._get(fetch.WIKIDATA_API, {})
        assert len(calls) == 1


def _occupation(qid: str) -> dict:
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
