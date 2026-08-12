"""End-to-end tests over the HTTP API."""

from __future__ import annotations

import pytest

MAN_UTD_1999 = "ucl-1999-final-manutd"
ENGLAND_1966 = "wc-1966-final-england"

UNITED_XI = [
    "Peter Schmeichel", "Denis Irwin", "Ronny Johnsen", "Jaap Stam", "Gary Neville",
    "Jesper Blomqvist", "Nicky Butt", "David Beckham", "Ryan Giggs", "Dwight Yorke",
    "Andy Cole",
]

pytestmark = pytest.mark.asyncio


async def start(client, **body):
    body.setdefault("mode", "quick")
    response = await client.post("/api/games", json=body)
    assert response.status_code == 201, response.text
    return response.json()["state"]


async def test_health(client):
    assert (await client.get("/api/health")).json() == {"status": "ok"}


async def test_metadata_reports_the_archive(client):
    body = (await client.get("/api/metadata")).json()
    assert body["lineups_count"] >= 15
    assert body["players_count"] > 100
    # The daily has a setting of its own - eleven blanks - but it is not something a
    # player chooses, so it must not appear alongside the three that are.
    assert set(body["difficulties"]) == {"easy", "medium", "hard"}
    assert "daily" not in body["difficulties"]
    assert body["hint_costs"]["reveal"] > body["hint_costs"]["initials"]


async def test_lineup_catalogue_does_not_expose_players(client):
    payload = (await client.get("/api/lineups")).json()
    assert len(payload) >= 15
    flattened = str(payload)
    for name in ("Schmeichel", "Beckham", "Messi"):
        assert name not in flattened


class TestGameSetup:
    async def test_hard_mode_reveals_nothing(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        assert state["found"] == 0
        assert state["seconds_remaining"] > 0
        assert state["fixture"]["team"] == "Manchester United"
        assert state["fixture"]["formation_label"] == "4-4-2"

    async def test_easy_mode_gives_freebies_but_never_the_keeper(self, client):
        state = await start(client, difficulty="easy", lineup=MAN_UTD_1999)
        assert state["found"] == 4
        keeper = state["slots"][0]
        assert keeper["position"] == "GK"
        assert keeper["revealed"] is False

    async def test_hidden_players_are_not_sent_to_the_client(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        for slot in state["slots"]:
            assert slot["revealed"] is False
            assert slot["name"] is None
            assert slot["initials"] is None
        # And nothing leaks through the write-up either.
        assert state["fixture"]["blurb"] is None
        assert "Schmeichel" not in str(state)

    async def test_unknown_lineup_rejected(self, client):
        response = await client.post("/api/games", json={"lineup": "not-a-real-lineup"})
        assert response.status_code == 400

    async def test_unknown_game_is_404(self, client):
        assert (await client.get("/api/games/nope")).status_code == 404


class TestGuessing:
    async def test_correct_guess_reveals_exactly_one_slot(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(
                f"/api/games/{state['game_id']}/guesses", json={"text": "schmeichel"}
            )
        ).json()
        assert body["result"]["status"] == "correct"
        assert body["result"]["name"] == "Peter Schmeichel"
        assert body["state"]["found"] == 1
        revealed = [s for s in body["state"]["slots"] if s["revealed"]]
        assert [s["name"] for s in revealed] == ["Peter Schmeichel"]

    async def test_wrong_guess_counts_as_a_miss(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(
                f"/api/games/{state['game_id']}/guesses", json={"text": "Zinedine Zidane"}
            )
        ).json()
        assert body["result"]["status"] == "wrong"
        assert body["state"]["wrong_guesses"] == 1
        assert body["state"]["found"] == 0

    async def test_repeat_guess_is_reported_not_double_counted(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        game_id = state["game_id"]
        await client.post(f"/api/games/{game_id}/guesses", json={"text": "giggs"})
        body = (
            await client.post(f"/api/games/{game_id}/guesses", json={"text": "ryan giggs"})
        ).json()
        assert body["result"]["status"] == "already_found"
        assert body["state"]["found"] == 1
        assert body["state"]["wrong_guesses"] == 0

    async def test_shared_surname_asks_for_a_first_name(self, client):
        state = await start(client, difficulty="hard", lineup=ENGLAND_1966)
        game_id = state["game_id"]
        body = (
            await client.post(f"/api/games/{game_id}/guesses", json={"text": "charlton"})
        ).json()
        assert body["result"]["status"] == "ambiguous"
        assert body["state"]["found"] == 0

        body = (
            await client.post(f"/api/games/{game_id}/guesses", json={"text": "jack charlton"})
        ).json()
        assert body["result"]["status"] == "correct"
        assert body["result"]["name"] == "Jack Charlton"

    async def test_typos_are_forgiven(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(
                f"/api/games/{state['game_id']}/guesses", json={"text": "schmiechel"}
            )
        ).json()
        assert body["result"]["status"] == "correct"
        assert body["result"]["fuzzy"] is True

    async def test_naming_the_whole_xi_wins(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        game_id = state["game_id"]
        for name in UNITED_XI:
            body = (
                await client.post(f"/api/games/{game_id}/guesses", json={"text": name})
            ).json()
        assert body["state"]["status"] == "won"
        assert body["state"]["found"] == 11
        assert body["state"]["guessed"] == 11
        breakdown = body["state"]["score_breakdown"]
        assert breakdown["completion_bonus"] > 0
        assert breakdown["time_bonus"] > 0
        assert breakdown["total"] == body["state"]["score"]
        # The write-up and source only appear once the game is over.
        assert body["state"]["fixture"]["blurb"]
        assert body["state"]["fixture"]["source_url"].startswith("https://")

    async def test_guessing_after_the_final_whistle_is_rejected(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        game_id = state["game_id"]
        await client.post(f"/api/games/{game_id}/surrender")
        response = await client.post(f"/api/games/{game_id}/guesses", json={"text": "giggs"})
        assert response.status_code == 409

    async def test_empty_guess_rejected_by_validation(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        response = await client.post(
            f"/api/games/{state['game_id']}/guesses", json={"text": ""}
        )
        assert response.status_code == 422


class TestHints:
    async def test_initials_show_without_revealing(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(f"/api/games/{state['game_id']}/hints", json={"type": "initials"})
        ).json()
        slots = body["state"]["slots"]
        assert slots[0]["initials"] == "P. S."
        assert slots[0]["name"] is None
        assert body["state"]["found"] == 0
        assert body["state"]["hint_penalty"] == 40

    async def test_initials_cannot_be_bought_twice(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        game_id = state["game_id"]
        await client.post(f"/api/games/{game_id}/hints", json={"type": "initials"})
        again = await client.post(f"/api/games/{game_id}/hints", json={"type": "initials"})
        assert again.status_code == 409

    async def test_reveal_hands_over_a_player_without_scoring(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(f"/api/games/{state['game_id']}/hints", json={"type": "reveal"})
        ).json()
        assert body["state"]["found"] == 1
        assert body["state"]["guessed"] == 0
        revealed = [s for s in body["state"]["slots"] if s["revealed"]]
        assert revealed[0]["source"] == "hint"
        assert body["state"]["score"] == 0  # 0 earned, 120 spent, clamped at zero

    async def test_unknown_hint_rejected(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        response = await client.post(
            f"/api/games/{state['game_id']}/hints", json={"type": "telepathy"}
        )
        assert response.status_code == 422


class TestSurrender:
    async def test_surrender_reveals_everything(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        body = (
            await client.post(f"/api/games/{state['game_id']}/surrender")
        ).json()
        assert body["state"]["status"] == "gave_up"
        names = [s["name"] for s in body["state"]["slots"]]
        assert None not in names
        assert sorted(names) == sorted(UNITED_XI)
        assert all(s["source"] == "missed" for s in body["state"]["slots"])

    async def test_surrender_is_idempotent(self, client):
        state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
        game_id = state["game_id"]
        first = (await client.post(f"/api/games/{game_id}/surrender")).json()
        second = (await client.post(f"/api/games/{game_id}/surrender")).json()
        assert second["state"]["status"] == "gave_up"
        assert second["state"]["score"] == first["state"]["score"]


class TestDaily:
    async def test_daily_is_the_same_lineup_each_time(self, client):
        first = (await client.get("/api/daily")).json()["state"]
        second = (await client.get("/api/daily")).json()["state"]
        assert first["mode"] == "daily"
        assert first["fixture"] == second["fixture"]
        # Same puzzle means the same players given away.
        assert [s["revealed"] for s in first["slots"]] == [s["revealed"] for s in second["slots"]]
        assert first["game_id"] != second["game_id"]


async def test_game_state_survives_a_reload(client):
    state = await start(client, difficulty="hard", lineup=MAN_UTD_1999)
    game_id = state["game_id"]
    await client.post(f"/api/games/{game_id}/guesses", json={"text": "beckham"})
    reloaded = (await client.get(f"/api/games/{game_id}")).json()["state"]
    assert reloaded["found"] == 1
    assert [s["name"] for s in reloaded["slots"] if s["revealed"]] == ["David Beckham"]
