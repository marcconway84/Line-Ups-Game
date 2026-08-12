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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "data" / "lineups.json"

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
# Wikidata asks for a descriptive agent so it can contact you about heavy use.
USER_AGENT = "LineUpsGame/1.0 (https://github.com/marcconway84/Line-Ups-Game) python-urllib"

#: Rate limiting and short outages, not "this does not exist" - worth another go.
RETRY_CODES = frozenset({429, 500, 502, 503, 504})

ASSOCIATION_FOOTBALLER = "Q937857"
ASSOCIATION_FOOTBALL = "Q2736"
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
    # "Country for sport". For a British player this is England, Scotland, Wales or
    # Northern Ireland - the distinction citizenship cannot make, and the one that
    # matters here. It is recorded for players who never won a cap, which is exactly
    # where the national-side route runs out.
    wd:%(qid)s wdt:P1532 ?item.
    BIND("sportcountry" AS ?kind)
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

#: States that field no football team. "United Kingdom" is the one that matters:
#: it is what citizenship returns for every English, Scottish, Welsh and Northern
#: Irish player, and it tells a quizzer nothing.
NOT_A_FOOTBALLING_NATION = frozenset({"United Kingdom", "Kingdom of Great Britain",
                                      "United Kingdom of Great Britain and Ireland",
                                      "Great Britain", "Soviet Union", "Yugoslavia",
                                      "Czechoslovakia"})

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


#: Bounds on a club spell. The floor is deliberately low: academy signings are real
#: career history - Messi joined Newell's at six - and a floor of 15 threw those out
#: as bad claims. The ceiling and the club-inception check are what actually catch
#: the bad ones.
FIRST_PLAUSIBLE_AGE = 6
LAST_PLAUSIBLE_AGE = 45


def _year(value: str | None) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def rejection_reason(born_year: int | None, start: str | None,
                     founded: str | None = None) -> str | None:
    """Why this club spell cannot belong to this player, or None if it can."""
    if born_year is None:
        return None  # nothing to judge against; review is the backstop

    start_year = _year(start)
    if start_year is not None:
        age = start_year - born_year
        if age < FIRST_PLAUSIBLE_AGE:
            return f"joined aged {age}"
        if age > LAST_PLAUSIBLE_AGE:
            return f"joined aged {age}"

    founded_year = _year(founded)
    if founded_year is not None and founded_year > born_year + LAST_PLAUSIBLE_AGE:
        return f"club founded {founded_year}, player born {born_year}"

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
    return rejection_reason(born_year, start, founded) is None


def is_senior_side(label: str) -> bool:
    lowered = label.lower()
    return not any(marker in lowered for marker in NOT_A_SENIOR_SIDE)


def _get(url: str, params: dict, attempts: int = 4) -> dict:
    """One request, retried on the failures that are worth retrying.

    Wikidata rate-limits and occasionally 503s under a sweep of several hundred
    players. Those are temporary, so back off and try again rather than losing the
    player. A 404 or a bad query is not temporary, so it is raised at once.
    """
    target = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        target, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_CODES or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == attempts - 1:
                raise
        time.sleep(2**attempt)

    # The API answers 200 with an error body. Left unchecked this reads as "no data"
    # and quietly drops a player, which is how the first sweep lost Messi and Xavi.
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"wikidata: {payload['error'].get('info', payload['error'])}")
    return payload


def claims_for(qid: str, prop: str) -> list:
    """The statements one entity holds for one property.

    Asking for a single property rather than the whole item matters: wbgetentities on
    a well-documented player returns a very large response, and the API can answer
    without the claims it was asked for. The caller then sees an entity with no
    occupation and concludes it is not a footballer - which is exactly how Messi,
    Xavi, Kimmich and twenty-five others vanished from a sweep that reported success.
    """
    payload = _get(
        WIKIDATA_API,
        {"action": "wbgetclaims", "entity": qid, "property": prop, "format": "json"},
    )
    return payload.get("claims", {}).get(prop, [])


def footballer_claims(qid: str) -> dict:
    """The two claims that identify a footballer, fetched one small call at a time."""
    claims = {"P106": claims_for(qid, "P106")}
    if not is_footballer(claims):
        claims["P641"] = claims_for(qid, "P641")
    return claims


def labels_and_aliases(qid: str) -> set[str]:
    """Every English name an entity answers to, folded for comparison."""
    payload = _get(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "labels|aliases",
            "languages": "en",
            "format": "json",
        },
    )
    entity = payload.get("entities", {}).get(qid, {})
    names = {entity.get("labels", {}).get("en", {}).get("value", "")}
    names |= {alias.get("value", "") for alias in entity.get("aliases", {}).get("en", [])}
    return {fold(n) for n in names if n}


def fold(text: str) -> str:
    """Strip accents and case so "Félix" and "Felix" compare equal."""
    stripped = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in stripped if not unicodedata.combining(ch)).casefold().strip()


def search_among_footballers(name: str, hint: str | None) -> list[str]:
    """Full-text search restricted to people whose occupation is footballer.

    The plain entity search ranks by how well a string matches a label, which is no
    help for a player who goes by one common word: searching "Leonardo" offers the
    painter long before the full-back. Filtering the search itself to footballers, and
    adding the club from the lineup as an ordinary search term, puts the right person
    in reach without anybody having to hand-pick an id.
    """
    terms = [name]
    if hint:
        terms.append(hint)
    terms.append(f"haswbstatement:P106={ASSOCIATION_FOOTBALLER}")
    payload = _get(
        WIKIDATA_API,
        {
            "action": "query",
            "list": "search",
            "srsearch": " ".join(terms),
            "srlimit": 10,
            "format": "json",
        },
    )
    return [row["title"] for row in payload.get("query", {}).get("search", [])]


#: A starting XI in a final is not filled with children or pensioners. The window is
#: wide on purpose - it is there to catch a different person, not to referee an
#: unusually young debutant.
YOUNGEST_STARTER = 15
OLDEST_STARTER = 45


def plausible_starter(born: int | None, match_year: int | None) -> str | None:
    """Why this cannot be the man who started that match, or None if it could be.

    The archive knows the date of every match, so the age of whoever is resolved can
    be checked against it. That check is what separates Leonardo of Brazil 1998 from
    the other Brazilian footballer called Leonardo who was twelve at the time - a
    name and a nationality match both of them, and only one of them played.
    """
    if born is None or match_year is None:
        return None
    age = match_year - born
    if age < YOUNGEST_STARTER:
        return f"would have been {age} on the day"
    if age > OLDEST_STARTER:
        return f"would have been {age} on the day"
    return None


def candidate_players(name: str, trace: list | None = None, hint: str | None = None):
    """Yield Wikidata ids that could be this footballer, best guess first.

    Yields rather than returns because being a footballer of the right name is not
    enough - the caller checks each one's age against the match before accepting it,
    and needs to be able to ask for the next.
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
    hits = payload.get("search", [])
    if trace is not None and not hits:
        trace.append("search returned nothing")
    for hit in hits:
        qid = hit["id"]
        claims = footballer_claims(qid)
        if is_footballer(claims):
            yield {"qid": qid, "label": hit.get("label"), "description": hit.get("description")}
        elif trace is not None:
            trace.append(f"{qid} ({hit.get('description') or 'no description'}) - not a footballer")

    # Nothing in the name search was a footballer. Try again among footballers only,
    # with the club he lined up for as a hint.
    for qid in search_among_footballers(name, hint):
        # This path is looser than the one above, so the entity has to actually answer
        # to the name being looked for. Without that check, "Gabi" plus "Atletico
        # Madrid" would cheerfully return whichever Atletico player ranked highest.
        if fold(name) not in labels_and_aliases(qid):
            if trace is not None:
                trace.append(f"{qid} - a footballer, but does not go by '{name}'")
            continue
        if is_footballer(footballer_claims(qid)):
            yield {"qid": qid, "label": name, "description": f"found via {hint or 'search'}"}


def ids_for(claims: dict, prop: str) -> set:
    return {
        claim["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
        for claim in claims.get(prop, [])
    }


def is_footballer(claims: dict) -> bool:
    """Two independent markers, because one alone misses people.

    Occupation (P106) is the obvious one, but several single-name players - Xavi,
    Pelé's team-mate Félix, Piazza - did not resolve on it alone. Sport (P641) set to
    association football is a second, equally strong signal.
    """
    return (ASSOCIATION_FOOTBALLER in ids_for(claims, "P106")
            or ASSOCIATION_FOOTBALL in ids_for(claims, "P641"))


def player_facts(qid: str) -> dict:
    payload = _get(
        SPARQL,
        {"query": FACTS_QUERY % {"qid": qid, "national": NATIONAL_TEAM}, "format": "json"},
    )
    rows = payload.get("results", {}).get("bindings", [])
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    """Fold typed SPARQL rows into one record. Pure - covered by tests.

    Nationality is taken from three sources in order: the senior national side he
    actually played for, then his "country for sport", then citizenship.

    The order is the whole point. Citizenship says "United Kingdom" for an Englishman
    and cannot tell England from Scotland or Wales - the one distinction a football
    clue needs. Country for sport can, and unlike a national side it exists for
    players who never won a cap: Clint Hill played 500-odd games and none for
    England, and citizenship was all that was left for him.

    "United Kingdom" is refused outright at the end. It is not a footballing
    nationality, and no clue is better than a useless one.

    Caps and goals are deliberately absent. The probe showed Wikidata's qualifiers on
    these statements are patchy and easy to misread - Piqué came back with 5 caps -
    and a confidently wrong number is worse than no number at all.
    """
    citizenships: list[str] = []
    sport_countries: list[str] = []
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
        elif kind == "sportcountry":
            if label not in sport_countries:
                sport_countries.append(label)
        elif kind == "national":
            if is_senior_side(label) and label not in national_sides:
                national_sides.append(label)
        elif kind == "club":
            start = row.get("start", {}).get("value")
            founded = row.get("founded", {}).get("value")
            reason = rejection_reason(born_year, start, founded)
            if reason:
                note = f"{label} ({reason})"
                if note not in rejected:
                    rejected.append(note)
                continue
            club = tidy_club(label)
            # Keep the earliest start seen, so a player who rejoins a club keeps his
            # first spell's place in the order.
            if club_is_new_or_earlier(clubs, club, start):
                clubs[club] = start

    if national_sides:
        nationality = country_from_team(national_sides[0])
    elif sport_countries:
        nationality = tidy_country(sport_countries[0])
    elif citizenships:
        nationality = tidy_country(citizenships[0])
    else:
        nationality = None
    if nationality in NOT_A_FOOTBALLING_NATION:
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
    return [name for name, _, _ in dataset_entries()]


def dataset_entries() -> list[tuple[str, str, int | None]]:
    """Every player, with the side he lines up for and the year he did it.

    The side breaks ties a name alone cannot - the difference between finding Wilson
    Piazza and finding a square in Rome. The year is the stronger check of the two:
    whoever is resolved has to have been the right age on the day.
    """
    doc = json.loads(DATASET.read_text(encoding="utf-8"))
    seen: set[str] = set()
    entries: list[tuple[str, str, int | None]] = []
    for lineup in doc["lineups"]:
        year = _year(lineup.get("date"))
        for player in lineup["players"]:
            if player["name"] not in seen:
                seen.add(player["name"])
                entries.append((player["name"], lineup["team"], year))
    return entries


PROBE_NAMES = [
    "Peter Schmeichel",
    "Bobby Moore",
    "Pelé",
    "Gerard Piqué",
    "N'Golo Kanté",
    "Dwight Yorke",
]


def run(names: list[str], pause: float = 0.4) -> dict:
    context = {name: (team, year) for name, team, year in dataset_entries()}
    out: dict[str, dict] = {}
    for name in names:
        try:
            trace: list[str] = []
            team, match_year = context.get(name, (None, None))
            resolved = None
            for found in candidate_players(name, trace, team):
                facts = player_facts(found["qid"])
                # Being a footballer of the right name is not enough. Check the man
                # against the match: if he was twelve that year, he is not the one.
                wrong = plausible_starter(facts.get("born"), match_year)
                if wrong:
                    trace.append(f"{found['qid']} - born {facts.get('born')}, {wrong}")
                    continue
                resolved = (found, facts)
                break

            if not resolved:
                # Say which entities were looked at and why each was turned down. A bare
                # "NOT FOUND" cannot be told apart from a bug, and once was one.
                print(f"  {name:<26} NOT FOUND after {len(trace)} candidates")
                for line in trace[:5]:
                    print(f"      {line}")
                continue

            found, facts = resolved
            out[name] = {**facts, "wikidata_id": found["qid"]}
            career = ", ".join(facts["career"][:5]) + ("…" if len(facts["career"]) > 5 else "")
            print(f"  {name:<26} {found['qid']:<10} {str(facts['nationality']):<20} {career}")
        except Exception as exc:  # noqa: BLE001 - a probe should report, not crash
            print(f"  {name:<26} ERROR {type(exc).__name__}: {exc}")
        time.sleep(pause)
    return out


def report(names: list[str], results: dict) -> None:
    """Print what a reviewer needs, last, so it survives a truncated log.

    A sweep prints a line per player; the things worth acting on - who could not be
    found, who came back thin, which source claims were thrown out - would otherwise
    be scattered through hundreds of lines.
    """
    missing = [name for name in names if name not in results]
    no_nationality = sorted(n for n, f in results.items() if not f.get("nationality"))
    no_career = sorted(n for n, f in results.items() if not f.get("career"))
    thin_career = sorted(n for n, f in results.items() if 0 < len(f.get("career", [])) < 2)
    rejected = {n: f["rejected_spells"] for n, f in results.items() if f.get("rejected_spells")}

    def show(title: str, items, limit: int = 25) -> None:
        print(f"\n{title}: {len(items)}")
        for item in list(items)[:limit]:
            print(f"    {item}")
        if len(items) > limit:
            print(f"    ... and {len(items) - limit} more")

    print("\n" + "=" * 68)
    print("REVIEW SUMMARY")
    print("=" * 68)
    print(f"  looked up      {len(names)}")
    print(f"  resolved       {len(results)}")
    print(f"  with country   {len(results) - len(no_nationality)}")
    print(f"  with a career  {len(results) - len(no_career)}")

    show("NOT FOUND on Wikidata (no clue data for these)", missing)
    show("Resolved but no nationality", no_nationality)
    show("Resolved but no club career", no_career)
    show("Only one club - check these by hand", thin_career)
    show("Source claims rejected as implausible",
         [f"{name}: {', '.join(spells)}" for name, spells in sorted(rejected.items())])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="look up a few known players")
    parser.add_argument("--all", action="store_true", help="look up every player in the dataset")
    parser.add_argument(
        "--missing",
        action="store_true",
        help="look up only the players --merge does not already have",
    )
    parser.add_argument(
        "--merge",
        type=Path,
        default=None,
        help="existing facts file to start from and write back into",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not (args.probe or args.all or args.missing):
        parser.error("choose --probe, --all or --missing")
    if args.missing and not args.merge:
        parser.error("--missing needs --merge to know what is already held")

    existing: dict[str, dict] = {}
    if args.merge and args.merge.exists():
        existing = json.loads(args.merge.read_text(encoding="utf-8"))
        print(f"Starting from {len(existing)} players already looked up")

    if args.probe:
        names = PROBE_NAMES
    elif args.missing:
        # Only the stragglers. A sweep of the whole archive takes half an hour, which
        # is too slow a loop for chasing down the last few dozen.
        names = [name for name in dataset_names() if name not in existing]
    else:
        names = dataset_names()

    print(f"Looking up {len(names)} players on Wikidata\n")
    results = run(names)

    out_path = args.out or args.merge
    if out_path:
        merged = {**existing, **results}
        # Written in archive order so the file reads like the dataset and diffs cleanly.
        ordered = {name: merged[name] for name in dataset_names() if name in merged}
        ordered.update({name: facts for name, facts in merged.items() if name not in ordered})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {out_path} ({len(ordered)} players)")

    report(names, results)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
