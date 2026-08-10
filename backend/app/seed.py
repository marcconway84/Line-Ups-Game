"""Load ``data/lineups.json`` into the database.

Seeding is idempotent: matches are keyed by their dataset ``id`` (stored as ``slug``) and
players by their normalised name, so starting the server repeatedly does not duplicate
rows, and editing the dataset updates the existing rows in place.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .matching import normalize
from .models import Appearance, League, Match, Player, Team

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "data" / "lineups.json"


def load_dataset(path: Path | None = None) -> dict:
    with open(path or DATASET_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def validate_dataset(dataset: dict) -> list[str]:
    """Return a list of problems with the dataset - empty means it is well formed."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for entry in dataset.get("lineups", []):
        lineup_id = entry.get("id", "<missing id>")
        if lineup_id in seen_ids:
            problems.append(f"{lineup_id}: duplicate id")
        seen_ids.add(lineup_id)

        players = entry.get("players", [])
        if len(players) != 11:
            problems.append(f"{lineup_id}: expected 11 players, found {len(players)}")

        formation = entry.get("formation", [])
        if sum(formation) != 10:
            problems.append(f"{lineup_id}: formation {formation} does not add up to 10")

        for field in ("team", "competition", "date", "source_url"):
            if not entry.get(field):
                problems.append(f"{lineup_id}: missing '{field}'")

        names = [normalize(p.get("name", "")) for p in players]
        if "" in names:
            problems.append(f"{lineup_id}: a player has an empty name")
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            problems.append(f"{lineup_id}: the same player appears twice: {sorted(duplicates)}")
    return problems


async def _get_or_create_team(session: AsyncSession, name: str, league_id: int | None) -> Team:
    team = (await session.execute(select(Team).where(Team.name == name))).scalar_one_or_none()
    if team is None:
        team = Team(name=name, league_id=league_id)
        session.add(team)
        await session.flush()
    return team


async def _get_or_create_player(session: AsyncSession, name: str, accepts: list[str]) -> Player:
    key = normalize(name)
    player = (
        await session.execute(select(Player).where(Player.normalized_name == key))
    ).scalar_one_or_none()
    if player is None:
        player = Player(name=name, normalized_name=key, notes={"accepts": accepts})
        session.add(player)
        await session.flush()
    else:
        # Keep aliases in sync when the dataset gains new ones.
        merged = sorted({*(player.notes or {}).get("accepts", []), *accepts})
        player.notes = {**(player.notes or {}), "accepts": merged}
    return player


async def seed_database(session: AsyncSession, dataset: dict | None = None) -> int:
    """Insert or refresh every lineup. Returns the number of lineups seeded."""
    dataset = dataset or load_dataset()
    problems = validate_dataset(dataset)
    if problems:
        raise ValueError("Invalid lineup dataset:\n  " + "\n  ".join(problems))

    for entry in dataset["lineups"]:
        league = (
            await session.execute(select(League).where(League.name == entry["competition"]))
        ).scalar_one_or_none()
        if league is None:
            league = League(name=entry["competition"], source="curated")
            session.add(league)
            await session.flush()

        team = await _get_or_create_team(session, entry["team"], league.id)
        opponent = (
            await _get_or_create_team(session, entry["opponent"], None)
            if entry.get("opponent")
            else None
        )

        match = (
            await session.execute(select(Match).where(Match.slug == entry["id"]))
        ).scalar_one_or_none()
        if match is None:
            match = Match(slug=entry["id"])
            session.add(match)

        match.utc_date = datetime.fromisoformat(entry["date"]) if entry.get("date") else None
        match.home_team_id = team.id
        match.away_team_id = opponent.id if opponent else None
        match.competition = entry["competition"]
        match.season = entry.get("season")
        match.venue = entry.get("venue")
        match.score = entry.get("score")
        match.formation = list(entry["formation"])
        match.blurb = entry.get("blurb")
        match.tags = list(entry.get("tags", []))
        match.source = "curated"
        match.source_url = entry.get("source_url")
        await session.flush()

        # Rewrite the XI wholesale - simpler and safer than diffing eleven slots.
        await session.execute(delete(Appearance).where(Appearance.match_id == match.id))
        for slot_index, raw_player in enumerate(entry["players"]):
            player = await _get_or_create_player(
                session, raw_player["name"], list(raw_player.get("accepts", []))
            )
            session.add(
                Appearance(
                    match_id=match.id,
                    team_id=team.id,
                    player_id=player.id,
                    position=raw_player.get("pos"),
                    slot_index=slot_index,
                    is_starting=True,
                    source="curated",
                    source_url=entry.get("source_url"),
                    confidence=1.0,
                )
            )

    await session.commit()
    return len(dataset["lineups"])


async def seed_if_empty(session: AsyncSession) -> int:
    """Seed on first run only, so a populated database is never rewritten at startup."""
    count = (await session.execute(select(func.count()).select_from(Match))).scalar_one()
    if count:
        return 0
    return await seed_database(session)


async def _main() -> int:
    """``python -m backend.app.seed`` - re-seed after editing the dataset."""
    from .db import AsyncSessionLocal, create_all

    problems = validate_dataset(load_dataset())
    if problems:
        print("Dataset is not valid:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    await create_all()
    async with AsyncSessionLocal() as session:
        print(f"Seeded {await seed_database(session)} lineups from {DATASET_PATH}")
    return 0


if __name__ == "__main__":
    import asyncio
    import sys

    sys.exit(asyncio.run(_main()))
