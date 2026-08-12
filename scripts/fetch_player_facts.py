#!/usr/bin/env python3
"""Fetch verifiable player facts from Wikidata.

Why this exists: clues like a player's nationality, his caps or his club career must
come from a source, not from anyone's memory. Wikidata is structured, public, and
carries an id per player so a fact can be traced back and re-checked.

Two modes:

    python scripts/fetch_player_facts.py --probe
        Look up a handful of known players and print what comes back, with the
        Wikidata id for each so the result can be spot-checked by hand.

    python scripts/fetch_player_facts.py --all --out data/player_facts.json
        Look up every player in data/lineups.json and write the results.

Network note: the development sandbox blocks Wikidata, so this is designed to run in
CI (see .github/workflows/enrich.yml), where the network is open. Everything that
does not need the network - name matching, claim parsing, output shape - is covered
by tests/test_fetch_player_facts.py and runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "data" / "lineups.json"

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
# Wikidata asks for a descriptive agent so it can contact you about heavy use.
USER_AGENT = "LineUpsGame/1.0 (https://github.com/marcconway84/Line-Ups-Game) python-urllib"

ASSOCIATION_FOOTBALLER = "Q937857"
NATIONAL_TEAM = "Q6979593"

#: Typed rows via UNION rather than nested OPTIONALs: an OPTIONAL join multiplies
#: rows together and makes it hard to tell which fact came from which statement.
FACTS_QUERY = """
SELECT ?kind ?label ?start ?founded WHERE {
  {
    wd:%(qid)s wdt:P569 ?born.
    BIND("born" AS ?kind)
    BIND(STR(YEAR(?born)) AS ?label)
  } UNION {
    wd:%(qid)s wdt:P27 ?item.
    BIND("citizenship" AS ?kind)
  } UNION {
    wd:%(qid)s p:P54 ?statement.
    ?statement ps:P54 ?item.
    ?item wdt:P31/wdt:P279* wd:%(national)s.
    OPTIONAL { ?statement pq:P580 ?start. }
    BIND("national" AS ?kind)
  } UNION {
    wd:%(qid)s p:P54 ?statement.
    ?statement ps:P54 ?item.
    FILTER NOT EXISTS { ?item wdt:P31/wdt:P279* wd:%(national)s. }
    OPTIONAL { ?statement pq:P580 ?start. }
    OPTIONAL { ?item wdt:P571 ?founded. }
    BIND("club" AS ?kind)
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". ?item rdfs:label ?label. }
}
"""

#: Wikidata's citizenship values are the formal state names. A football game wants
#: the everyday one.
COUNTRY_TIDY = {
    "Kingdom of Denmark": "Denmark",
    "Kingdom of the Netherlands": "Netherlands",
    "Kingdom of Norway": "Norway",
    "Kingdom of Spain": "Spain",
    "Kingdom of Sweden": "Sweden",
    "Federal Republic of Germany": "Germany",
    "Italian Republic": "Italy",
    "French Republic": "France",
    "Portuguese Republic": "Portugal",
    "Argentine Republic": "Argentina",
    "Federative Republic of Brazil": "Brazil",
    "Republic of Poland": "Poland",
    "Republic of Finland": "Finland",
    "Czechia": "Czech Republic",
    "Republic of Ireland": "Republic of Ireland",
    "Commonwealth of Australia": "Australia",
}

#: Youth, B and Olympic sides are not what "he played for X" means.
NOT_A_SENIOR_SIDE = ("under-", "under ", "u21", "u-21", "u23", "u-23", "olympic",
                     "b team", " b national", "youth", "amateur")


def tidy_country(label: str) -> str:
    return COUNTRY_TIDY.get(label, label)


def country_from_team(label: str) -> str:
    """"England men's national association football team" -> "England"."""
    out = label
    for suffix in (" national association football team", " national football team",
                   " national soccer team", " national team"):
        if out.endswith(suffix):
            out = out[: -len(suffix)]
            break
    # Wikidata labels these "X men's ..."; the possessive is left behind by the strip.
    for tail in (" men's", " women's", " men", " women"):
        if out.endswith(tail):
            out = out[: -len(tail)]
            break
    return out.strip()


#: Club labels carry their legal form. "Manchester United" reads better than
#: "Manchester United F.C.". Only trailing forms are stripped - "FC Barcelona" and
#: "AC Milan" are how those clubs are actually known.
CLUB_SUFFIXES = (" F.C.", " FC", " A.F.C.", " AFC", " S.C.", " SC", " C.F.", " CF",
                 " S.A.D.", " B.C.", " F.C", " Football Club")


def tidy_club(label: str) -> str:
    out = label.strip()
    for suffix in CLUB_SUFFIXES:
        if out.endswith(suffix):
            out = out[: -len(suffix)].strip()
            break
    return out


#: A footballer's club career runs roughly between these ages. Anything outside is a
#: bad claim, not a transfer - Bobby Moore came back from Wikidata with a club founded
#: six years after he died.
FIRST_PLAUSIBLE_AGE = 15
LAST_PLAUSIBLE_AGE = 45


def _year(value: str | None) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def plausible_spell(born_year: int | None, start: str | None,
                    founded: str | None = None) -> bool:
    """Whether a club spell could belong to this player.

    Two independent checks, because a bad claim often carries no date at all:

    * the spell must start within a playing age, and
    * the club must have existed by the time his career ended. Bobby Moore's
      spurious Midtjylland claim has no start date, so only the second catches it -
      the club was founded in 1999 and he was born in 1941.
    """
    if born_year is None:
        return True  # nothing to judge against; review is the backstop

    start_year = _year(start)
    if start_year is not None:
        age = start_year - born_year
        if not (FIRST_PLAUSIBLE_AGE <= age <= LAST_PLAUSIBLE_AGE):
            return False

    founded_year = _year(founded)
    if founded_year is not None and founded_year > born_year + LAST_PLAUSIBLE_AGE:
        return False

    return True


def is_senior_side(label: str) -> bool:
    lowered = label.lower()
    return not any(marker in lowered for marker in NOT_A_SENIOR_SIDE)


def _get(url: str, params: dict) -> dict:
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def find_player(name: str) -> dict | None:
    """Resolve a name to a Wikidata id, rejecting anyone who is not a footballer.

    Returns None rather than a guess when nothing matches - a wrong player is far
    worse than a missing one, because it produces a confident, wrong clue.
    """
    payload = _get(
        WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "format": "json",
            "limit": 10,
            "type": "item",
        },
    )
    for hit in payload.get("search", []):
        qid = hit["id"]
        entity = _get(
            WIKIDATA_API,
            {"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"},
        )
        claims = entity.get("entities", {}).get(qid, {}).get("claims", {})
        occupations = {
            claim["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
            for claim in claims.get("P106", [])
        }
        if ASSOCIATION_FOOTBALLER in occupations:
            return {"qid": qid, "label": hit.get("label"), "description": hit.get("description")}
    return None


def player_facts(qid: str) -> dict:
    payload = _get(
        SPARQL,
        {"query": FACTS_QUERY % {"qid": qid, "national": NATIONAL_TEAM}, "format": "json"},
    )
    rows = payload.get("results", {}).get("bindings", [])
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    """Fold typed SPARQL rows into one record. Pure - covered by tests.

    Nationality comes from the senior national side a player actually turned out for,
    falling back to citizenship. That order matters: citizenship says "United Kingdom"
    for an Englishman and cannot tell England from Scotland or Wales, which is exactly
    the distinction a football clue needs.

    Caps and goals are deliberately absent. The probe showed Wikidata's qualifiers on
    these statements are patchy and easy to misread - Piqué came back with 5 caps -
    and a confidently wrong number is worse than no number at all.
    """
    citizenships: list[str] = []
    national_sides: list[str] = []
    clubs: dict[str, str | None] = {}
    born_year: int | None = None
    rejected: list[str] = []

    for row in rows:
        if row.get("kind", {}).get("value") == "born":
            try:
                born_year = int(row["label"]["value"])
            except (KeyError, ValueError):
                pass

    for row in rows:
        kind = row.get("kind", {}).get("value")
        label = row.get("label", {}).get("value")
        if not kind or not label or kind == "born":
            continue
        if kind == "citizenship":
            if label not in citizenships:
                citizenships.append(label)
        elif kind == "national":
            if is_senior_side(label) and label not in national_sides:
                national_sides.append(label)
        elif kind == "club":
            start = row.get("start", {}).get("value")
            founded = row.get("founded", {}).get("value")
            if not plausible_spell(born_year, start, founded):
                if label not in rejected:
                    rejected.append(label)
                continue
            club = tidy_club(label)
            # Keep the earliest start seen, so a player who rejoins a club keeps his
            # first spell's place in the order.
            if club_is_new_or_earlier(clubs, club, start):
                clubs[club] = start

    if national_sides:
        nationality = country_from_team(national_sides[0])
    elif citizenships:
        nationality = tidy_country(citizenships[0])
    else:
        nationality = None

    career = [club for club, _ in sorted(clubs.items(), key=lambda kv: (kv[1] is None, kv[1] or ""))]
    return {
        "nationality": nationality,
        "national_team": national_sides[0] if national_sides else None,
        "born": born_year,
        "career": career,
        # Surfaced rather than silently dropped, so a bad source claim is visible.
        "rejected_spells": rejected,
    }


def club_is_new_or_earlier(clubs: dict, label: str, start: str | None) -> bool:
    if label not in clubs:
        return True
    existing = clubs[label]
    return bool(start) and (existing is None or start < existing)


def dataset_names() -> list[str]:
    doc = json.loads(DATASET.read_text(encoding="utf-8"))
    seen, names = set(), []
    for lineup in doc["lineups"]:
        for player in lineup["players"]:
            if player["name"] not in seen:
                seen.add(player["name"])
                names.append(player["name"])
    return names


PROBE_NAMES = [
    "Peter Schmeichel",
    "Bobby Moore",
    "Pelé",
    "Gerard Piqué",
    "N'Golo Kanté",
    "Dwight Yorke",
]


def run(names: list[str], pause: float = 0.4) -> dict:
    out: dict[str, dict] = {}
    for name in names:
        try:
            found = find_player(name)
            if not found:
                print(f"  {name:<26} NOT FOUND")
                continue
            facts = player_facts(found["qid"])
            out[name] = {**facts, "wikidata_id": found["qid"]}
            career = ", ".join(facts["career"][:5]) + ("…" if len(facts["career"]) > 5 else "")
            print(f"  {name:<26} {found['qid']:<10} {str(facts['nationality']):<20} {career}")
        except Exception as exc:  # noqa: BLE001 - a probe should report, not crash
            print(f"  {name:<26} ERROR {type(exc).__name__}: {exc}")
        time.sleep(pause)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="look up a few known players")
    parser.add_argument("--all", action="store_true", help="look up every player in the dataset")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not (args.probe or args.all):
        parser.error("choose --probe or --all")

    names = dataset_names() if args.all else PROBE_NAMES
    print(f"Looking up {len(names)} players on Wikidata\n")
    results = run(names)
    print(f"\nResolved {len(results)}/{len(names)}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
