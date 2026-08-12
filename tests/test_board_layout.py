"""The leaderboard table has to actually look like a table.

This exists because of a bug no other test could have caught. The leaderboard was
given the class names `board`, then `tally`, then `points` - each of which already
meant something else in this page: the pitch, the stats strip, and the big score
readout on the result panel. Nothing errored. The table simply inherited a grid
layout, a border and a 3rem font, and came out as 120px-tall rows with the names
scattered across them.

Every other test in the suite passed throughout. Only a browser can see this, so a
browser is what checks it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "dist" / "lineups.html"
CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

pytestmark = pytest.mark.skipif(
    not CHROMIUM.exists(), reason="no browser available in this environment"
)

SAMPLE = {
    "lineup": "pl-2012-qpr-mancity",
    "players": 4,
    "you": {"name": "Marc", "score": 90, "rank": 4},
    "top": [
        {"name": "Ada", "score": 2295},
        {"name": "Ben", "score": 1800},
        {"name": "Cara", "score": 1200},
        {"name": "Marc", "score": 90},
    ],
}


@pytest.fixture(scope="module")
def rendered() -> dict:
    """Build the page, paint a board into it, and measure what the browser did."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    subprocess.run(
        [sys.executable, "scripts/build_standalone.py"],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(CHROMIUM))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(PAGE.as_uri())
        page.evaluate(
            """(sample) => {
                 document.getElementById('dlg-board').showModal();
                 window.__paint(document.getElementById('board-table'), sample, {});
               }""",
            SAMPLE,
        )
        page.wait_for_timeout(200)
        measurements = page.evaluate(
            """() => {
                 const table = document.getElementById('board-table');
                 const rows = [...table.rows];
                 const dialog = document.getElementById('dlg-board');
                 return {
                   rowCount: rows.length,
                   rowHeights: rows.map(r => r.getBoundingClientRect().height),
                   cellText: rows.map(r => [...r.cells].map(c => c.textContent)),
                   fontSizes: rows.map(r => [...r.cells]
                     .map(c => parseFloat(getComputedStyle(c).fontSize))),
                   youRows: rows.filter(r => r.className === 'you').length,
                   dialogOverflows:
                     dialog.scrollHeight > Math.ceil(dialog.getBoundingClientRect().height) + 1,
                 };
               }"""
        )
        browser.close()
        measurements["errors"] = errors
        return measurements


class TestTheBoardLooksLikeATable:
    def test_it_renders_without_errors(self, rendered):
        assert rendered["errors"] == []

    def test_one_row_per_player(self, rendered):
        assert rendered["rowCount"] == len(SAMPLE["top"])

    def test_rows_are_a_sensible_height(self, rendered):
        """The collision produced 120px rows. A line of small text is nearer 25."""
        for height in rendered["rowHeights"]:
            assert 16 <= height <= 48, f"row is {height}px tall: {rendered['rowHeights']}"

    def test_rows_are_all_the_same_height(self, rendered):
        heights = rendered["rowHeights"]
        assert max(heights) - min(heights) < 2, heights

    def test_no_cell_is_shouting(self, rendered):
        """`points` meant the 3rem result-panel score, so 2295 rendered enormous."""
        for row in rendered["fontSizes"]:
            for size in row:
                assert size <= 18, f"cell font-size {size}px: {rendered['fontSizes']}"

    def test_each_row_reads_place_name_score(self, rendered):
        assert rendered["cellText"][0] == ["1st", "Ada", "2295"]
        assert rendered["cellText"][3] == ["4th", "Marc", "90"]

    def test_your_own_row_is_marked_once(self, rendered):
        assert rendered["youRows"] == 1

    def test_a_full_board_does_not_overflow_its_dialog(self, rendered):
        # The dialog is the one place a scrollbar is allowed, but a four-row board
        # on a phone should not need one.
        assert not rendered["dialogOverflows"]


def test_the_sample_matches_what_the_service_returns():
    """Guards against the test drifting from the shape the worker actually sends."""
    worker = (REPO_ROOT / "worker" / "src" / "index.js").read_text(encoding="utf-8")
    assert "return { lineup, players: total.n, top: top.results || [], you };" in worker
    assert set(SAMPLE) == {"lineup", "players", "top", "you"}
    assert set(SAMPLE["you"]) >= {"name", "score", "rank"}
    assert all(set(row) == {"name", "score"} for row in SAMPLE["top"])
    json.dumps(SAMPLE)  # must survive the trip through page.evaluate
