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

#: One statement per fact, so a wrong answer can be traced to a single claim.
FACTS_QUERY = """
SELECT ?nationalityLabel ?teamLabel ?caps ?goals ?clubLabel ?start WHERE {
  OPTIONAL { wd:%(qid)s wdt:P27 ?nationality. }
  OPTIONAL {
    wd:%(qid)s p:P54 ?membership.
    ?membership ps:P54 ?team.
    ?team wdt:P31 wd:Q6979593.          # a national association football team
    OPTIONAL { ?membership pq:P1350 ?caps. }
    OPTIONAL { ?membership pq:P1351 ?goals. }
  }
  OPTIONAL {
    wd:%(qid)s p:P54 ?clubMembership.
    ?clubMembership ps:P54 ?club.
    FILTER NOT EXISTS { ?club wdt:P31 wd:Q6979593. }
    OPTIONAL { ?clubMembership pq:P580 ?start. }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


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
    payload = _get(SPARQL, {"query": FACTS_QUERY % {"qid": qid}, "format": "json"})
    rows = payload.get("results", {}).get("bindings", [])
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    """Fold repeated SPARQL rows into one record. Pure - covered by tests."""
    nationality = None
    national_team = None
    caps = goals = None
    clubs: dict[str, str | None] = {}

    for row in rows:
        if nationality is None and "nationalityLabel" in row:
            nationality = row["nationalityLabel"]["value"]
        if "teamLabel" in row and national_team is None:
            national_team = row["teamLabel"]["value"]
        if "caps" in row and caps is None:
            caps = int(float(row["caps"]["value"]))
        if "goals" in row and goals is None:
            goals = int(float(row["goals"]["value"]))
        if "clubLabel" in row:
            club = row["clubLabel"]["value"]
            start = row.get("start", {}).get("value")
            # Keep the earliest start date seen for each club, to order the career.
            if club not in clubs or (start and (clubs[club] is None or start < clubs[club])):
                clubs[club] = start

    career = [club for club, _ in sorted(clubs.items(), key=lambda kv: (kv[1] is None, kv[1] or ""))]
    return {
        "nationality": nationality,
        "national_team": national_team,
        "caps": caps,
        "goals": goals,
        "career": career,
    }


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
            print(
                f"  {name:<26} {found['qid']:<10} "
                f"{str(facts['nationality']):<18} "
                f"caps={facts['caps']} goals={facts['goals']} "
                f"clubs={len(facts['career'])}"
            )
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
