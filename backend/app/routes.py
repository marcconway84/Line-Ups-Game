"""HTTP API for the Line-Ups game."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import game as rules
from . import service
from .db import get_db
from .models import League, Match, Player, Team
from .schemas import (
    GameStateResponse,
    GuessRequest,
    GuessResponse,
    HintRequestBody,
    LineupSummary,
    MetadataResponse,
    NewGameRequest,
)

router = APIRouter()


def _not_found(exc: service.GameError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/metadata", response_model=MetadataResponse)
async def metadata(db: AsyncSession = Depends(get_db)):
    """Counts and rules, so the client does not hard-code any of them."""
    lineups = (await db.execute(select(func.count()).select_from(Match))).scalar_one()
    teams = (await db.execute(select(func.count()).select_from(Team))).scalar_one()
    players = (await db.execute(select(func.count()).select_from(Player))).scalar_one()
    leagues = (await db.execute(select(func.count()).select_from(League))).scalar_one()
    earliest = (await db.execute(select(func.min(Match.utc_date)))).scalar_one()
    latest = (await db.execute(select(func.max(Match.utc_date)))).scalar_one()

    return MetadataResponse(
        lineups_count=lineups,
        teams_count=teams,
        players_count=players,
        leagues_count=leagues,
        date_range=[
            earliest.date().isoformat() if earliest else None,
            latest.date().isoformat() if latest else None,
        ],
        difficulties={
            key: {
                "label": d.label,
                "revealed_at_kickoff": d.freebies,
                "seconds": d.seconds,
                "multiplier": d.multiplier,
            }
            # Only the settings a player can pick. The daily has its own, which comes
            # with the puzzle rather than being offered as a fourth option.
            for key, d in ((k, rules.DIFFICULTIES[k]) for k in rules.CHOOSABLE_DIFFICULTIES)
        },
        hint_costs=rules.HINT_COSTS,
    )


@router.get("/lineups", response_model=list[LineupSummary])
async def list_lineups(db: AsyncSession = Depends(get_db)):
    """The catalogue of puzzles.

    Deliberately free of player names - this endpoint is public and listing the XIs
    would hand over every answer in the game.
    """
    matches = (await db.execute(select(Match).order_by(Match.utc_date))).scalars().all()
    teams = {t.id: t.name for t in (await db.execute(select(Team))).scalars().all()}
    return [
        LineupSummary(
            id=m.slug,
            team=teams.get(m.home_team_id),
            opponent=teams.get(m.away_team_id),
            competition=m.competition,
            season=m.season,
            date=m.utc_date.date().isoformat() if m.utc_date else None,
            formation="-".join(str(row) for row in m.formation),
        )
        for m in matches
    ]


@router.post("/games", response_model=GameStateResponse, status_code=status.HTTP_201_CREATED)
async def create_game(body: NewGameRequest, db: AsyncSession = Depends(get_db)):
    try:
        game_obj = await service.create_game(
            db, mode=body.mode, difficulty=body.difficulty, lineup_slug=body.lineup
        )
    except service.GameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await service.game_state(db, game_obj)


@router.get("/games/{game_id}", response_model=GameStateResponse)
async def read_game(game_id: str, db: AsyncSession = Depends(get_db)):
    try:
        game_obj = await service.get_game(db, game_id)
    except service.GameError as exc:
        raise _not_found(exc) from exc
    return await service.game_state(db, game_obj)


@router.post("/games/{game_id}/guesses", response_model=GuessResponse)
async def guess(game_id: str, body: GuessRequest, db: AsyncSession = Depends(get_db)):
    try:
        game_obj = await service.get_game(db, game_id)
    except service.GameError as exc:
        raise _not_found(exc) from exc
    try:
        return await service.submit_guess(db, game_obj, body.text)
    except service.GameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/games/{game_id}/hints", response_model=GameStateResponse)
async def hint(game_id: str, body: HintRequestBody, db: AsyncSession = Depends(get_db)):
    try:
        game_obj = await service.get_game(db, game_id)
    except service.GameError as exc:
        raise _not_found(exc) from exc
    try:
        return await service.buy_hint(db, game_obj, body.type)
    except service.GameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/games/{game_id}/surrender", response_model=GameStateResponse)
async def surrender(game_id: str, db: AsyncSession = Depends(get_db)):
    """End the round and show the full XI."""
    try:
        game_obj = await service.get_game(db, game_id)
    except service.GameError as exc:
        raise _not_found(exc) from exc
    return await service.give_up(db, game_obj)


@router.get("/daily", response_model=GameStateResponse, status_code=status.HTTP_201_CREATED)
async def daily(db: AsyncSession = Depends(get_db)):
    """Today's puzzle - the same lineup, and the same free slots, for everyone."""
    try:
        game_obj = await service.create_game(db, mode="daily", day=date.today())
    except service.GameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await service.game_state(db, game_obj)
