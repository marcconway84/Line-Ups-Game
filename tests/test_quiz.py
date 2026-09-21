"""Quick Fire's packs, its build, and the copy of its rules the leaderboard uses.

The game itself runs in the browser and is tested there - worker/test/quiz-engine.test.js
checks matching and the clue sheet against every question in every pack, and
worker/test/quiz.test.js checks the scoring. What is left for Python is the part
Python owns: that a pack cannot be malformed, that the page builds with everything
in it, and that the price list the browser is handed is the one the board charges.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = REPO_ROOT / "data" / "quizzes"
QUIZ_RULES = REPO_ROOT / "data" / "quiz_rules.json"
GENERATED = REPO_ROOT / "worker" / "src" / "quiz-rules.generated.json"


def _module(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_quiz():
    return _module("build_quiz")


@pytest.fixture(scope="module")
def packs() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(PACK_DIR.glob("*.json"))]


@pytest.fixture(scope="module")
def page(build_quiz) -> str:
    return build_quiz.build()


def _pack(**overrides) -> dict:
    """A minimal pack that passes, so each test can break exactly one thing."""
    base = {
        "id": "test-pack",
        "title": "Test Pack",
        "subject": "Testing",
        "questions": [
            {"prompt": f"Question {n}?", "answer": f"Answer{n}"} for n in range(1, 5)
        ],
    }
    base.update(overrides)
    return base


class TestTheShippedPacks:
    def test_there_are_some(self, packs):
        assert packs, "no packs in data/quizzes"

    def test_every_one_is_well_formed(self, build_quiz, packs):
        for pack in packs:
            build_quiz.check_pack(pack, pack.get("id", "?"))

    def test_ids_are_unique_across_packs(self, build_quiz):
        loaded = build_quiz.load_packs()
        ids = [pack["id"] for pack in loaded]
        assert len(ids) == len(set(ids))

    def test_a_pack_is_a_round_of_the_advertised_length(self, packs):
        # Ten minutes is the promise on the front of the box. Twelve questions is
        # what that works out to; a pack of thirty would be a different game.
        for pack in packs:
            assert 8 <= len(pack["questions"]) <= 15, f"{pack['id']} is {len(pack['questions'])} long"

    def test_answers_are_short_enough_to_type_under_pressure(self, packs):
        for pack in packs:
            for question in pack["questions"]:
                words = question["answer"].split()
                assert len(words) <= 4, f"{pack['id']}: {question['answer']!r} is a mouthful"

    def test_every_decoy_set_is_three_and_never_contains_the_answer(self, packs):
        for pack in packs:
            for question in pack["questions"]:
                decoys = question.get("decoys") or []
                if decoys:
                    assert len(decoys) == 3, f"{pack['id']}: {question['answer']!r}"
                    assert question["answer"] not in decoys


class TestABadPackFailsTheBuild:
    """Every one of these would otherwise be found by a player, mid-round."""

    @pytest.mark.parametrize(
        "broken, complaint",
        [
            (_pack(id=""), "missing id"),
            (_pack(title=""), "missing title"),
            (_pack(questions=[{"prompt": "Only one?", "answer": "Yes indeed"}]), "minimum"),
        ],
    )
    def test_a_malformed_pack_is_refused(self, build_quiz, broken, complaint):
        with pytest.raises(build_quiz.BadPack, match=complaint):
            build_quiz.check_pack(broken, "test.json")

    def test_a_question_with_no_answer_is_refused(self, build_quiz):
        pack = _pack()
        pack["questions"][0]["answer"] = ""
        with pytest.raises(build_quiz.BadPack, match="no answer"):
            build_quiz.check_pack(pack, "test.json")

    def test_an_answer_too_short_to_build_clues_from_is_refused(self, build_quiz):
        # An anagram of two letters is the answer with the letters the other way up.
        pack = _pack()
        pack["questions"][0]["answer"] = "Au"
        with pytest.raises(build_quiz.BadPack, match="too short"):
            build_quiz.check_pack(pack, "test.json")

    def test_two_questions_with_one_answer_are_refused(self, build_quiz):
        # The trap this catches: the matcher would light up the first of the two
        # whichever one the player was actually looking at.
        pack = _pack()
        pack["questions"][1]["answer"] = pack["questions"][0]["answer"]
        with pytest.raises(build_quiz.BadPack, match="already the answer"):
            build_quiz.check_pack(pack, "test.json")

    def test_the_same_question_twice_is_refused(self, build_quiz):
        pack = _pack()
        pack["questions"][1]["prompt"] = pack["questions"][0]["prompt"]
        with pytest.raises(build_quiz.BadPack, match="already in this pack"):
            build_quiz.check_pack(pack, "test.json")

    def test_a_half_written_decoy_set_is_refused(self, build_quiz):
        pack = _pack()
        pack["questions"][0]["decoys"] = ["One", "Two"]
        with pytest.raises(build_quiz.BadPack, match="three or none"):
            build_quiz.check_pack(pack, "test.json")

    def test_an_answer_listed_among_its_own_decoys_is_refused(self, build_quiz):
        pack = _pack()
        answer = pack["questions"][0]["answer"]
        pack["questions"][0]["decoys"] = [answer, "Two", "Three"]
        with pytest.raises(build_quiz.BadPack, match="its own decoys"):
            build_quiz.check_pack(pack, "test.json")


class TestThePageThatIsBuilt:
    def test_nothing_is_left_unfilled(self, page):
        for placeholder in ("__PACKS__", "__RULES__", "__LEADERBOARD__", "__BUILD__"):
            assert placeholder not in page, f"{placeholder} was never substituted"

    def test_every_pack_is_in_it(self, page, packs):
        for pack in packs:
            assert pack["title"] in page
            for question in pack["questions"]:
                assert question["prompt"] in page

    def test_it_is_one_file_with_nothing_to_fetch(self, page):
        # The whole point of the build: a page that plays from disk, from a share
        # sheet, or from anywhere a colleague opens it.
        assert "<script src=" not in page
        assert "<link rel=\"stylesheet\"" not in page

    def test_the_engine_is_loaded_before_the_game_that_reads_it(self, page):
        assert page.index("var QuickFireEngine") < page.index("QuickFireEngine.normalize")

    def test_a_script_tag_cannot_be_closed_early_by_the_data(self, page, build_quiz):
        # A question containing "</script>" would otherwise end the block and
        # spill the rest of the game onto the page as text.
        embedded = build_quiz.embed([{"prompt": "What about </script> then?"}])
        assert "</script>" not in embedded
        assert "<\\/script>" in embedded

    def test_the_build_mark_moves_when_the_game_does(self, build_quiz, monkeypatch, tmp_path):
        first = build_quiz.build()
        rules = json.loads(QUIZ_RULES.read_text(encoding="utf-8"))
        rules["pointsPerQuestion"] = 101
        changed = tmp_path / "quiz_rules.json"
        changed.write_text(json.dumps(rules), encoding="utf-8")
        monkeypatch.setattr(build_quiz, "RULES", changed)
        assert build_quiz.build() != first


class TestTheLeaderboardAddress:
    @staticmethod
    def payload(build_quiz, tmp_path, config, monkeypatch) -> str:
        target = tmp_path / "leaderboard.json"
        if config is not None:
            target.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(build_quiz, "LEADERBOARD", target)
        return build_quiz.leaderboard_payload()

    def test_no_config_means_no_board_and_no_network_calls(self, build_quiz, tmp_path, monkeypatch):
        assert self.payload(build_quiz, tmp_path, None, monkeypatch) == "null"

    def test_an_empty_url_means_no_board(self, build_quiz, tmp_path, monkeypatch):
        assert self.payload(build_quiz, tmp_path, {"url": "  "}, monkeypatch) == "null"

    def test_a_configured_url_is_built_in(self, build_quiz, tmp_path, monkeypatch):
        out = self.payload(build_quiz, tmp_path, {"url": "https://scores.example.dev/"}, monkeypatch)
        assert json.loads(out) == {"url": "https://scores.example.dev"}

    def test_plain_http_is_refused(self, build_quiz, tmp_path, monkeypatch):
        with pytest.raises(build_quiz.BadPack):
            self.payload(build_quiz, tmp_path, {"url": "http://scores.example.dev"}, monkeypatch)


class TestTheWorkersCopyOfTheRules:
    """The board recalculates every score. It can only be trusted while it agrees."""

    @staticmethod
    @pytest.fixture(scope="class")
    def generated() -> dict:
        return json.loads(GENERATED.read_text(encoding="utf-8"))

    @staticmethod
    @pytest.fixture(scope="class")
    def source() -> dict:
        return json.loads(QUIZ_RULES.read_text(encoding="utf-8"))

    def test_it_is_checked_in(self):
        assert GENERATED.exists(), "run scripts/generate_worker_rules.py"

    def test_regenerating_changes_nothing(self):
        import subprocess
        import sys

        before = GENERATED.read_text(encoding="utf-8")
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_worker_rules.py")],
            check=True,
            capture_output=True,
        )
        assert GENERATED.read_text(encoding="utf-8") == before, (
            "the worker's rules are stale - run scripts/generate_worker_rules.py"
        )

    def test_every_price_came_across(self, generated, source):
        assert generated["clueCosts"] == source["clueCosts"]

    def test_every_scoring_constant_came_across(self, generated, source):
        for key in ("secondsOnTheClock", "pointsPerQuestion", "finisherBonus",
                    "pointsPerSecondRemaining", "cleanSweepBonus"):
            assert generated[key] == source[key], key

    def test_the_worker_knows_how_big_every_pack_is(self, generated, packs):
        # Without this the board has nothing to measure "twenty right out of twelve"
        # against, and an impossible score walks straight onto it.
        assert generated["packs"] == {pack["id"]: len(pack["questions"]) for pack in packs}

    def test_no_clue_costs_more_than_a_question_is_worth(self, source):
        for key, cost in source["clueCosts"].items():
            assert 0 <= cost < source["pointsPerQuestion"], f"{key} is priced at {cost}"

    def test_reveal_is_free_because_it_already_costs_the_question(self, source):
        assert source["clueCosts"]["reveal"] == 0
