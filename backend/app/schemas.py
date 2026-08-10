"""Request and response models for the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class NewGameRequest(BaseModel):
    mode: Literal["quick", "daily"] = "quick"
    difficulty: Literal["easy", "medium", "hard"] | None = None
    #: Ask for a specific lineup by its dataset id - handy for sharing and debugging.
    lineup: str | None = None


class GuessRequest(BaseModel):
    text: str = Field(min_length=1, max_length=80)


class HintRequestBody(BaseModel):
    type: Literal["initials", "reveal"]


class GuessOutcome(BaseModel):
    status: str
    slot: int | None = None
    name: str | None = None
    message: str = ""
    fuzzy: bool = False


class GameStateResponse(BaseModel):
    """Rendered by ``service.render_state``; kept loose so the shape can evolve."""

    state: dict[str, Any]


class GuessResponse(BaseModel):
    result: GuessOutcome
    state: dict[str, Any]


class LineupSummary(BaseModel):
    id: str
    team: str | None
    opponent: str | None
    competition: str | None
    season: str | None
    date: str | None
    formation: str


class MetadataResponse(BaseModel):
    lineups_count: int
    teams_count: int
    players_count: int
    leagues_count: int
    date_range: list[str | None]
    difficulties: dict[str, Any]
    hint_costs: dict[str, int]
