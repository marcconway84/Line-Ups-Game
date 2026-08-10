"""SQLAlchemy models for the tables sketched in ``db/schema.sql``.

The catalogue tables (leagues, teams, matches, players, appearances) hold the lineup
data. The play tables (games, rounds, round_guesses, hint_requests) record what a user
did in a session.

There is deliberately no "revealed slots" column: the visible state of a lineup is
derived from the game's seed (the free slots given at kick-off), the correct guesses and
any reveal hints. Storing it as well would be a second source of truth to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC.

    The timestamp columns are plain TIMESTAMPs, and SQLite hands values back without a
    timezone. Dropping the tzinfo on the way in keeps every comparison naive-to-naive
    instead of blowing up on a mix of the two.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base. Uses portable column types so the same models run on
    SQLite (the zero-setup default) and Postgres (via DATABASE_URL)."""


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    country: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("leagues.id"))
    wikidata_id: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)


class Match(Base):
    """One puzzle: a famous XI, with the context shown to the player."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Stable identifier from the dataset, used to re-seed without duplicating rows.
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    utc_date: Mapped[datetime | None] = mapped_column(DateTime)
    home_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    competition: Mapped[str | None] = mapped_column(Text)
    season: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(Text)
    score: Mapped[str | None] = mapped_column(Text)
    #: Formation rows for the outfield players, e.g. [4, 3, 3].
    formation: Mapped[list] = mapped_column(JSON, default=list)
    blurb: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Normalised name, so the same player seeded twice is recognised as one row.
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    wikidata_id: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[str | None] = mapped_column(Text)
    #: Curated aliases and nicknames: {"accepts": ["kdb", ...]}.
    notes: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("normalized_name", name="uq_players_normalized_name"),)


class Appearance(Base):
    """A player occupying one of the eleven slots in a match lineup."""

    __tablename__ = "appearances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    position: Mapped[str | None] = mapped_column(Text)
    #: 0-10, matching the order produced by ``game.layout_slots``.
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    shirt_number: Mapped[int | None] = mapped_column(Integer)
    is_starting: Mapped[bool] = mapped_column(Boolean, default=True)
    minute_in: Mapped[int | None] = mapped_column(Integer)
    minute_out: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)

    __table_args__ = (UniqueConstraint("match_id", "slot_index", name="uq_appearance_slot"),)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    #: "quick" or "daily".
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="quick")
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    #: "in_progress", "won", "lost" or "gave_up".
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    score: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Round(Base):
    """A game currently holds a single round; the table leaves room for more."""

    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), nullable=False, index=True)
    round_index: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RoundGuess(Base):
    __tablename__ = "round_guesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), nullable=False, index=True)
    #: What the user actually typed, kept for stats and for tuning the matcher.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    slot_index: Mapped[int | None] = mapped_column(Integer)
    team_position: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HintRequest(Base):
    __tablename__ = "hint_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[str] = mapped_column(ForeignKey("rounds.id"), nullable=False, index=True)
    appearance_id: Mapped[int | None] = mapped_column(ForeignKey("appearances.id"))
    slot_index: Mapped[int | None] = mapped_column(Integer)
    #: "initials" or "reveal".
    hint_type: Mapped[str] = mapped_column(String(20), nullable=False)
    hint_text: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
