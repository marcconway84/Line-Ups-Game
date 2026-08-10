"""Game orchestration: create games, apply guesses and hints, and render state.

The single most important rule in this module: a lineup slot that has not been revealed
must never appear in a payload with its player's name attached. Every response is built
by :func:`render_state`, which only attaches a name to slots that are actually visible,
so there is one place to get that right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import game as rules
from .matching import Candidate, match_guess
from .models import (
    Appearance,
    Game,
    HintRequest,
    Match,
    Player,
    Round,
    RoundGuess,
    Team,
    new_uuid,
    utcnow,
)


class GameError(Exception):
    """Raised for a request the rules do not allow (unknown hint, finished game, ...)."""


@dataclass
class Bundle:
    """A match with its eleven players, plus the teams involved."""

    match: Match
    appearances: list[Appearance]
    players: dict[int, Player]
    team: Team | None
    opponent: Team | None

    def player_for(self, appearance: Appearance) -> Player:
        return self.players[appearance.player_id]

    def candidates(self, slots: Sequence[int] | None = None) -> list[Candidate]:
        wanted = set(slots) if slots is not None else None
        out = []
        for appearance in self.appearances:
            if wanted is not None and appearance.slot_index not in wanted:
                continue
            player = self.player_for(appearance)
            accepts = (player.notes or {}).get("accepts", [])
            out.append(Candidate.build(appearance.slot_index, player.name, accepts))
        return out


async def load_bundle(session: AsyncSession, match_id: int) -> Bundle:
    match = (await session.execute(select(Match).where(Match.id == match_id))).scalar_one()
    appearances = list(
        (
            await session.execute(
                select(Appearance)
                .where(Appearance.match_id == match_id)
                .order_by(Appearance.slot_index)
            )
        )
        .scalars()
        .all()
    )
    player_ids = [a.player_id for a in appearances]
    players = {
        p.id: p
        for p in (await session.execute(select(Player).where(Player.id.in_(player_ids))))
        .scalars()
        .all()
    }
    teams: dict[int, Team] = {}
    wanted_teams = [tid for tid in (match.home_team_id, match.away_team_id) if tid]
    if wanted_teams:
        teams = {
            t.id: t
            for t in (await session.execute(select(Team).where(Team.id.in_(wanted_teams))))
            .scalars()
            .all()
        }
    return Bundle(
        match=match,
        appearances=appearances,
        players=players,
        team=teams.get(match.home_team_id) if match.home_team_id else None,
        opponent=teams.get(match.away_team_id) if match.away_team_id else None,
    )


@dataclass
class Progress:
    """Everything derived about a game in flight."""

    round: Round
    free_slots: set[int]
    guessed_slots: set[int]
    hint_slots: set[int]
    initials_bought: bool
    hint_penalty: int
    wrong_guesses: int
    seconds_remaining: int

    @property
    def visible_slots(self) -> set[int]:
        return self.free_slots | self.guessed_slots | self.hint_slots

    @property
    def hidden_slots(self) -> set[int]:
        return set(range(11)) - self.visible_slots

    @property
    def completed(self) -> bool:
        return not self.hidden_slots


async def load_progress(session: AsyncSession, game_obj: Game) -> Progress:
    round_obj = (
        await session.execute(select(Round).where(Round.game_id == game_obj.id))
    ).scalar_one()
    guesses = list(
        (await session.execute(select(RoundGuess).where(RoundGuess.round_id == round_obj.id)))
        .scalars()
        .all()
    )
    hints = list(
        (await session.execute(select(HintRequest).where(HintRequest.round_id == round_obj.id)))
        .scalars()
        .all()
    )
    difficulty = rules.get_difficulty(game_obj.difficulty)
    seed = (game_obj.settings or {}).get("seed", game_obj.id)

    elapsed = (utcnow() - round_obj.started_at).total_seconds()
    remaining = int(max(0, round(difficulty.seconds - elapsed)))

    return Progress(
        round=round_obj,
        free_slots=set(rules.pick_free_slots(difficulty.freebies, seed=seed)),
        guessed_slots={g.slot_index for g in guesses if g.is_correct and g.slot_index is not None},
        hint_slots={
            h.slot_index for h in hints if h.hint_type == "reveal" and h.slot_index is not None
        },
        initials_bought=any(h.hint_type == "initials" for h in hints),
        hint_penalty=sum(h.cost for h in hints),
        wrong_guesses=sum(1 for g in guesses if not g.is_correct),
        seconds_remaining=remaining if game_obj.status == "in_progress" else 0,
    )


def render_state(game_obj: Game, bundle: Bundle, progress: Progress) -> dict:
    """Build the client payload for a game.

    Names are attached only to revealed slots while the game is live; once it is over
    everything is shown.
    """
    over = game_obj.status != "in_progress"
    difficulty = rules.get_difficulty(game_obj.difficulty)
    layout = rules.layout_slots(bundle.match.formation)
    by_slot = {a.slot_index: a for a in bundle.appearances}

    slots = []
    for cell in layout:
        index = cell["slot"]
        appearance = by_slot[index]
        player = bundle.player_for(appearance)

        if index in progress.guessed_slots:
            source = "guessed"
        elif index in progress.free_slots:
            source = "free"
        elif index in progress.hint_slots:
            source = "hint"
        else:
            source = None

        revealed = source is not None
        slots.append(
            {
                **cell,
                "position": appearance.position,
                "revealed": revealed,
                "source": source if revealed else ("missed" if over else None),
                # The one place a name is allowed onto the wire.
                "name": player.name if (revealed or over) else None,
                "initials": (
                    rules.initials_for(player.name)
                    if (not revealed and not over and progress.initials_bought)
                    else None
                ),
            }
        )

    if over:
        # Use the breakdown frozen when the game closed, so the numbers on the result
        # screen add up to the score that was actually awarded.
        final_breakdown = (game_obj.settings or {}).get("breakdown")
    else:
        final_breakdown = None
    live_breakdown = rules.score_round(
        guessed_slots=len(progress.guessed_slots),
        completed=progress.completed,
        seconds_remaining=progress.seconds_remaining,
        hint_penalty=progress.hint_penalty,
        difficulty=difficulty,
    )

    match = bundle.match
    return {
        "game_id": game_obj.id,
        "mode": game_obj.mode,
        "difficulty": difficulty.key,
        "status": game_obj.status,
        "seconds_remaining": 0 if over else progress.seconds_remaining,
        "seconds_total": difficulty.seconds,
        "found": len(progress.visible_slots),
        "guessed": len(progress.guessed_slots),
        "total": len(slots),
        "wrong_guesses": progress.wrong_guesses,
        "hints_used": {
            "initials": progress.initials_bought,
            "revealed": len(progress.hint_slots),
        },
        "hint_penalty": progress.hint_penalty,
        "hint_costs": rules.HINT_COSTS,
        "score": game_obj.score if over else live_breakdown.total,
        "score_breakdown": (final_breakdown or vars(live_breakdown)) if over else None,
        "fixture": {
            "team": bundle.team.name if bundle.team else None,
            "opponent": bundle.opponent.name if bundle.opponent else None,
            "score": match.score,
            "competition": match.competition,
            "season": match.season,
            "venue": match.venue,
            "date": match.utc_date.date().isoformat() if match.utc_date else None,
            "formation": match.formation,
            "formation_label": "-".join(str(row) for row in match.formation),
            # Held back until the game is over so the write-up cannot spoil the answers.
            "blurb": match.blurb if over else None,
            "source_url": match.source_url if over else None,
        },
        "slots": slots,
    }


async def _pick_match_id(
    session: AsyncSession, mode: str, lineup_slug: str | None, day: date | None
) -> int:
    if lineup_slug:
        match = (
            await session.execute(select(Match).where(Match.slug == lineup_slug))
        ).scalar_one_or_none()
        if match is None:
            raise GameError(f"unknown lineup '{lineup_slug}'")
        return match.id

    ids = list(
        (await session.execute(select(Match.id).order_by(Match.slug))).scalars().all()
    )
    if not ids:
        raise GameError("no lineups have been seeded")

    if mode == "daily":
        return ids[rules.daily_index(day or date.today(), len(ids))]

    # Quick play: any lineup, chosen by the database.
    random_id = (
        await session.execute(select(Match.id).order_by(func.random()).limit(1))
    ).scalar_one()
    return random_id


async def create_game(
    session: AsyncSession,
    *,
    mode: str = "quick",
    difficulty: str | None = None,
    lineup_slug: str | None = None,
    day: date | None = None,
) -> Game:
    mode = (mode or "quick").lower()
    if mode not in {"quick", "daily"}:
        raise GameError(f"unknown mode '{mode}'")

    if mode == "daily":
        # One puzzle a day for everyone, with identical free slots.
        day = day or date.today()
        difficulty_key = rules.DAILY_DIFFICULTY
        seed = f"daily:{day.isoformat()}"
    else:
        difficulty_key = rules.get_difficulty(difficulty).key
        seed = None

    match_id = await _pick_match_id(session, mode, lineup_slug, day)
    # The id is needed as the free-slot seed for quick games, so mint it here rather
    # than letting the column default fill it in at flush time.
    game_obj = Game(
        id=new_uuid(),
        mode=mode,
        difficulty=difficulty_key,
        match_id=match_id,
        status="in_progress",
    )
    game_obj.settings = {"seed": seed or game_obj.id, "day": day.isoformat() if day else None}
    session.add(game_obj)
    await session.flush()
    session.add(Round(game_id=game_obj.id, round_index=0))
    await session.commit()
    return game_obj


async def get_game(session: AsyncSession, game_id: str) -> Game:
    game_obj = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
    if game_obj is None:
        raise GameError(f"unknown game '{game_id}'")
    return game_obj


async def _finalize(
    session: AsyncSession, game_obj: Game, progress: Progress, status: str
) -> None:
    """Close a game and freeze its score."""
    difficulty = rules.get_difficulty(game_obj.difficulty)
    breakdown = rules.score_round(
        guessed_slots=len(progress.guessed_slots),
        completed=progress.completed,
        seconds_remaining=progress.seconds_remaining,
        hint_penalty=progress.hint_penalty,
        difficulty=difficulty,
    )
    game_obj.status = status
    game_obj.score = breakdown.total
    game_obj.finished_at = utcnow()
    progress.round.finished_at = game_obj.finished_at
    # Freeze the breakdown that produced the score. Recomputing it later would report a
    # time bonus of zero, because by then the clock has stopped.
    game_obj.settings = {**(game_obj.settings or {}), "breakdown": vars(breakdown)}
    await session.commit()


async def refresh(session: AsyncSession, game_obj: Game) -> tuple[Bundle, Progress]:
    """Load state, closing the game first if the clock has run out."""
    bundle = await load_bundle(session, game_obj.match_id)
    progress = await load_progress(session, game_obj)
    if game_obj.status == "in_progress" and progress.seconds_remaining <= 0:
        await _finalize(session, game_obj, progress, "won" if progress.completed else "lost")
    return bundle, progress


async def submit_guess(session: AsyncSession, game_obj: Game, text: str) -> dict:
    bundle, progress = await refresh(session, game_obj)
    if game_obj.status != "in_progress":
        raise GameError("this game has finished")

    hidden = sorted(progress.hidden_slots)
    result = match_guess(text, bundle.candidates(hidden))

    outcome = {"status": result.status, "slot": None, "name": None, "message": ""}

    if result.status == "match":
        slot = result.slot
        appearance = next(a for a in bundle.appearances if a.slot_index == slot)
        player = bundle.player_for(appearance)
        session.add(
            RoundGuess(
                round_id=progress.round.id,
                text=text,
                player_id=player.id,
                slot_index=slot,
                team_position=appearance.position,
                is_correct=True,
            )
        )
        progress.guessed_slots.add(slot)
        outcome.update(
            status="correct",
            slot=slot,
            name=player.name,
            message=f"{player.name} - {appearance.position}",
            fuzzy=result.fuzzy,
        )
    elif result.status == "ambiguous":
        # Several hidden players answer to that name; ask for more.
        outcome.update(
            status="ambiguous",
            message="More than one player in this XI goes by that name - add a first name.",
        )
    elif result.status in {"empty", "too_short"}:
        outcome.update(status=result.status, message="Type at least three letters.")
    else:
        # Was it someone already on the pitch, or simply wrong?
        already = match_guess(text, bundle.candidates())
        if already.status in {"match", "ambiguous"}:
            outcome.update(status="already_found", message="Already on the pitch.")
        else:
            session.add(
                RoundGuess(
                    round_id=progress.round.id, text=text, is_correct=False, slot_index=None
                )
            )
            progress.wrong_guesses += 1
            outcome.update(status="wrong", message="Not in this lineup.")

    await session.commit()

    if progress.completed:
        await _finalize(session, game_obj, progress, "won")

    state = render_state(game_obj, bundle, progress)
    return {"result": outcome, "state": state}


async def buy_hint(session: AsyncSession, game_obj: Game, hint_type: str) -> dict:
    bundle, progress = await refresh(session, game_obj)
    if game_obj.status != "in_progress":
        raise GameError("this game has finished")
    if hint_type not in rules.HINT_COSTS:
        raise GameError(f"unknown hint '{hint_type}'")

    cost = rules.HINT_COSTS[hint_type]
    hidden = sorted(progress.hidden_slots)
    if not hidden:
        raise GameError("the whole XI is already revealed")

    if hint_type == "initials":
        if progress.initials_bought:
            raise GameError("initials have already been bought for this round")
        session.add(
            HintRequest(
                round_id=progress.round.id,
                hint_type="initials",
                hint_text="initials shown for all hidden players",
                cost=cost,
            )
        )
        progress.initials_bought = True
    else:
        # Give away the slot nearest the goalkeeper - predictable, and usually the
        # least valuable player to hand over.
        slot = hidden[0]
        appearance = next(a for a in bundle.appearances if a.slot_index == slot)
        player = bundle.player_for(appearance)
        session.add(
            HintRequest(
                round_id=progress.round.id,
                appearance_id=appearance.id,
                slot_index=slot,
                hint_type="reveal",
                hint_text=player.name,
                cost=cost,
            )
        )
        progress.hint_slots.add(slot)

    progress.hint_penalty += cost
    await session.commit()

    if progress.completed:
        await _finalize(session, game_obj, progress, "won")

    return {"state": render_state(game_obj, bundle, progress)}


async def give_up(session: AsyncSession, game_obj: Game) -> dict:
    bundle, progress = await refresh(session, game_obj)
    if game_obj.status == "in_progress":
        await _finalize(session, game_obj, progress, "gave_up")
    return {"state": render_state(game_obj, bundle, progress)}


async def game_state(session: AsyncSession, game_obj: Game) -> dict:
    bundle, progress = await refresh(session, game_obj)
    return {"state": render_state(game_obj, bundle, progress)}
