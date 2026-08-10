#!/usr/bin/env python3
"""Build a single-file, no-server version of the game.

The full game keeps the answers on the server. This build inlines the lineup data into
one HTML file so it can be opened straight from disk or hosted as a static page - handy
for sharing, at the cost that a determined player could read the answers out of the page
source. The server version remains the real thing.

    python scripts/build_standalone.py                 -> dist/lineups.html
    python scripts/build_standalone.py --fragment      -> body-only, for embedding

The game rules here mirror backend/app/game.py and backend/app/matching.py. If you
change the rules there, change them here too - tests/test_standalone.py checks that the
headline numbers still agree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "data" / "lineups.json"
DEFAULT_OUT = REPO_ROOT / "dist" / "lineups.html"

TITLE = "Line-Ups &mdash; name the missing players"

STYLE = """
<style>
/* ---------------------------------------------------------------------------
   The manager's tactics board: board green, chalk markings, brass discs.
   Deliberately a single visual world - there is no light variant of a tactics
   board - so every colour is painted explicitly rather than inherited.
   --------------------------------------------------------------------------- */
:root {
  --board:      #0e2a20;
  --board-deep: #0a1f18;
  --panel:      #123c2c;
  --panel-2:    #174835;
  --chalk:      #eaf2ec;
  --chalk-dim:  #8fa89a;
  --chalk-line: rgba(234, 242, 236, 0.22);
  --brass:      #e8b04b;
  --brass-deep: #b9821f;
  --flag:       #e2574c;

  --display: "Haettenschweiler", "Arial Narrow", "Helvetica Neue", Impact, sans-serif;
  --body: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --data: ui-monospace, "SF Mono", Menlo, Consolas, monospace;

  --rule: 1px solid var(--chalk-line);
  --pad: clamp(0.9rem, 3vw, 1.4rem);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0 0 3rem;
  background: var(--board-deep);
  color: var(--chalk);
  font-family: var(--body);
  line-height: 1.55;
  -webkit-text-size-adjust: 100%;
}

.wrap { max-width: 33rem; margin: 0 auto; padding: 0 var(--pad); }

/* -------------------------------------------------------------- masthead */
.masthead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem var(--pad) 0.85rem;
  max-width: 33rem;
  margin: 0 auto;
  border-bottom: var(--rule);
}
.wordmark {
  font-family: var(--display);
  font-size: 1.6rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: none;
  border: 0;
  color: var(--chalk);
  padding: 0;
  cursor: pointer;
  line-height: 1;
}
.wordmark span { color: var(--brass); }
.masthead nav { display: flex; gap: 0.9rem; }

.textlink {
  background: none;
  border: 0;
  color: var(--chalk-dim);
  font: 600 0.78rem/1 var(--body);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  padding: 0.3rem 0;
  border-bottom: 1px solid transparent;
}
.textlink:hover, .textlink:focus-visible { color: var(--brass); border-bottom-color: var(--brass); }

/* ----------------------------------------------------------------- views */
.view { display: none; }
.view.on { display: block; }

.eyebrow {
  font: 700 0.7rem/1 var(--body);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--brass);
  margin: 1.6rem 0 0.5rem;
}

h1 {
  font-family: var(--display);
  font-size: clamp(2.4rem, 11vw, 3.6rem);
  line-height: 0.95;
  letter-spacing: 0.01em;
  text-transform: uppercase;
  margin: 0 0 0.6rem;
  text-wrap: balance;
}
.standfirst { color: var(--chalk-dim); margin: 0 0 1.6rem; max-width: 34ch; }

/* ------------------------------------------------------------ team sheet */
.sheet {
  border: var(--rule);
  background: var(--panel);
  padding: 1rem;
  margin-bottom: 0.9rem;
}
.sheet h2 {
  font-family: var(--display);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 1.15rem;
  margin: 0 0 0.35rem;
}
.sheet p { margin: 0 0 0.85rem; color: var(--chalk-dim); font-size: 0.88rem; }

.grades { display: flex; gap: 0; border: var(--rule); margin-bottom: 0.6rem; }
.grade {
  flex: 1;
  background: none;
  border: 0;
  border-right: var(--rule);
  color: var(--chalk-dim);
  font: 700 0.75rem/1 var(--body);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 0.6rem 0.2rem;
  cursor: pointer;
}
.grade:last-child { border-right: 0; }
.grade[aria-checked="true"] { background: var(--brass); color: var(--board-deep); }

.terms {
  font-family: var(--data);
  font-size: 0.72rem;
  color: var(--chalk-dim);
  margin: 0 0 0.9rem;
  min-height: 1.2em;
}

.btn {
  display: inline-block;
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--brass);
  background: var(--brass);
  color: var(--board-deep);
  font: 700 0.82rem/1 var(--body);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.btn:hover:not(:disabled) { background: var(--brass-deep); border-color: var(--brass-deep); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-quiet { background: none; color: var(--chalk); border-color: var(--chalk-line); }
.btn-quiet:hover:not(:disabled) { background: var(--panel-2); border-color: var(--chalk-dim); color: var(--chalk); }
.btn-flag { background: none; color: var(--flag); border-color: rgba(226, 87, 76, 0.45); }
.btn-flag:hover:not(:disabled) { background: rgba(226, 87, 76, 0.12); border-color: var(--flag); color: var(--flag); }

/* ------------------------------------------------------------- scoreline */
.record {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border: var(--rule);
  border-bottom: 0;
  margin: 1.4rem 0 0.5rem;
}
.record div {
  border-bottom: var(--rule);
  border-right: var(--rule);
  padding: 0.55rem 0.4rem;
  text-align: center;
}
.record div:nth-child(3n) { border-right: 0; }
.record dt {
  font: 700 0.62rem/1 var(--body);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--chalk-dim);
}
.record dd {
  margin: 0.25rem 0 0;
  font-family: var(--data);
  font-size: 1.15rem;
  font-variant-numeric: tabular-nums;
}
.footnote { color: var(--chalk-dim); font-size: 0.75rem; text-align: center; margin: 0.6rem 0 0; }

/* --------------------------------------------------------------- fixture */
.fixture { padding: 1.1rem 0 0.7rem; text-align: center; }
.fixture .teams {
  font-family: var(--display);
  font-size: clamp(1.35rem, 5.5vw, 1.8rem);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  line-height: 1.05;
}
.fixture .teams em { font-style: normal; color: var(--chalk-dim); }
.fixture .meta {
  font-family: var(--data);
  font-size: 0.7rem;
  color: var(--chalk-dim);
  margin-top: 0.35rem;
  letter-spacing: 0.02em;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0 0.9rem;
}
/* Keep "4-2-3-1" and the like from breaking across lines. */
.fixture .meta b { font-weight: 400; white-space: nowrap; }

.fixture .badge {
  display: inline-block;
  margin-top: 0.4rem;
  padding: 0.14rem 0.5rem;
  border: 1px solid var(--brass);
  color: var(--brass);
  font: 700 0.58rem/1.4 var(--body);
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

/* -------------------------------------------------------------- the board */
.tally {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border: var(--rule);
  border-bottom: 0;
}
.tally div { border-right: var(--rule); border-bottom: var(--rule); padding: 0.4rem 0.3rem; text-align: center; }
.tally div:last-child { border-right: 0; }
.tally span {
  display: block;
  font: 700 0.58rem/1 var(--body);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--chalk-dim);
}
.tally strong {
  display: block;
  font-family: var(--data);
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
  margin-top: 0.2rem;
  font-weight: 500;
}
.tally .late strong { color: var(--flag); }

.whistle { height: 3px; background: rgba(234, 242, 236, 0.1); overflow: hidden; }
.whistle i { display: block; height: 100%; width: 100%; background: var(--brass); transition: width 0.95s linear; }
.whistle i.late { background: var(--flag); }

.board {
  position: relative;
  aspect-ratio: 68 / 95;
  border: var(--rule);
  border-top: 0;
  background:
    repeating-linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.028) 0 6.25%,
      transparent 6.25% 12.5%
    ),
    var(--board);
  overflow: hidden;
}
.marks { position: absolute; inset: 0; }
.marks > i { position: absolute; border: 1px solid var(--chalk-line); display: block; }
.marks .circle { width: 30%; aspect-ratio: 1; border-radius: 50%; left: 35%; top: 50%; transform: translateY(-50%); }
.marks .half { left: 0; right: 0; top: 50%; border-width: 0 0 1px; }
.marks .area { left: 21%; width: 58%; height: 14%; }
.marks .area.own { bottom: 0; border-bottom: 0; }
.marks .area.opp { top: 0; border-top: 0; }
.marks .six { left: 34%; width: 32%; height: 6%; }
.marks .six.own { bottom: 0; border-bottom: 0; }
.marks .six.opp { top: 0; border-top: 0; }

.man {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 22%;
  min-width: 60px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.22rem;
  text-align: center;
}
.disc {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font: 700 0.6rem/1 var(--body);
  letter-spacing: 0.04em;
  border: 1px solid var(--chalk-line);
  background: rgba(10, 31, 24, 0.72);
  color: var(--chalk-dim);
  transition: transform 0.2s;
}
.tag {
  font-size: 0.66rem;
  font-weight: 600;
  line-height: 1.15;
  padding: 0.1rem 0.28rem;
  background: rgba(10, 31, 24, 0.82);
  color: var(--chalk-dim);
  max-width: 100%;
  overflow-wrap: break-word;
}
.man.named .disc { background: var(--brass); border-color: var(--brass); color: var(--board-deep); }
.man.named .tag { color: var(--chalk); }
.man.spotted .disc { background: var(--chalk-dim); border-color: var(--chalk); color: var(--board-deep); }
.man.spotted .tag { color: var(--chalk); }
.man.told .disc { background: var(--brass-deep); border-color: var(--brass); color: var(--board-deep); }
.man.told .tag { color: var(--chalk); }
.man.gone .disc { background: rgba(226, 87, 76, 0.85); border-color: var(--flag); color: var(--board-deep); }
.man.gone .tag { color: #f6cfcb; }
.man.new .disc { animation: place 0.4s ease-out; }
@keyframes place { 0% { transform: scale(0.5); } 60% { transform: scale(1.22); } 100% { transform: scale(1); } }

/* --------------------------------------------------------------- the call */
.call { display: flex; gap: 0.5rem; margin-top: 0.8rem; }
.call input {
  flex: 1;
  min-width: 0;
  padding: 0.7rem 0.8rem;
  border: var(--rule);
  background: var(--panel);
  color: var(--chalk);
  font: 400 1rem var(--body);
}
.call input::placeholder { color: var(--chalk-dim); }
.call input:focus-visible { outline: 2px solid var(--brass); outline-offset: 1px; }
.call .btn { width: auto; padding-inline: 1.1rem; }

.verdict { min-height: 1.5em; margin: 0.5rem 0 0.7rem; font-size: 0.88rem; font-weight: 600; }
.verdict.good { color: var(--brass); }
.verdict.bad { color: var(--flag); }
.verdict.note { color: var(--chalk-dim); }

.bench { display: flex; gap: 0.5rem; }
.bench .btn { flex: 1; font-size: 0.68rem; letter-spacing: 0.08em; padding: 0.6rem 0.3rem; }

/* ---------------------------------------------------------------- result */
.final { text-align: center; padding-top: 1.2rem; }
.final .outcome {
  font-family: var(--display);
  font-size: clamp(1.8rem, 8vw, 2.6rem);
  text-transform: uppercase;
  letter-spacing: 0.02em;
  margin: 0 0 0.1rem;
  text-wrap: balance;
}
.final .points {
  font-family: var(--data);
  font-size: 3rem;
  font-variant-numeric: tabular-nums;
  color: var(--brass);
  line-height: 1;
  margin: 0.3rem 0 0.1rem;
}
.final .points small { font-family: var(--body); font-size: 0.72rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--chalk-dim); display: block; margin-top: 0.35rem; }

.ledger { width: 100%; border-collapse: collapse; margin: 1.2rem 0; font-size: 0.85rem; }
.ledger td { padding: 0.4rem 0.1rem; border-bottom: var(--rule); color: var(--chalk-dim); text-align: left; }
.ledger td:last-child { text-align: right; color: var(--chalk); font-family: var(--data); font-variant-numeric: tabular-nums; }
.ledger tr.sum td { color: var(--chalk); font-weight: 700; border-bottom: 0; }

.report { text-align: left; color: var(--chalk-dim); font-size: 0.88rem; }
.report a { color: var(--brass); }

.sheetlist { list-style: none; padding: 0; margin: 0.5rem 0 1.4rem; text-align: left; }
.sheetlist li { display: flex; align-items: center; gap: 0.7rem; padding: 0.42rem 0.1rem; border-bottom: var(--rule); font-size: 0.9rem; }
.sheetlist .slot {
  font-family: var(--data);
  font-size: 0.62rem;
  color: var(--chalk-dim);
  min-width: 2.6rem;
  letter-spacing: 0.06em;
}
.sheetlist .mark { margin-left: auto; font: 700 0.62rem/1 var(--body); letter-spacing: 0.1em; text-transform: uppercase; }
.mark.named { color: var(--brass); }
.mark.spotted { color: var(--chalk-dim); }
.mark.told { color: var(--brass-deep); }
.mark.gone { color: var(--flag); }

.again { display: flex; gap: 0.5rem; }

/* ---------------------------------------------------------------- dialog */
dialog {
  border: var(--rule);
  background: var(--panel);
  color: var(--chalk);
  max-width: 30rem;
  width: calc(100% - 2rem);
  padding: 1.25rem;
}
dialog::backdrop { background: rgba(6, 18, 14, 0.78); }
dialog h2 {
  font-family: var(--display);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 0.7rem;
  font-size: 1.3rem;
}
dialog ul { padding-left: 1.1rem; color: var(--chalk-dim); font-size: 0.88rem; }
dialog li { margin-bottom: 0.45rem; }
dialog strong { color: var(--chalk); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
</style>
"""

MARKUP = """
<header class="masthead">
  <button class="wordmark" id="home-link" type="button">Line<span>&middot;</span>Ups</button>
  <nav>
    <button class="textlink" type="button" data-dialog="rules">Rules</button>
    <button class="textlink" type="button" data-dialog="record">Record</button>
  </nav>
</header>

<main class="wrap">
  <section class="view on" id="v-home">
    <p class="eyebrow">The football lineup quiz</p>
    <h1>Name the eleven</h1>
    <p class="standfirst">
      A famous starting XI, blanked out. The shape is there, the names are not.
      Fill in everyone you recognise before the whistle.
    </p>

    <div class="sheet">
      <h2>Kick off</h2>
      <p>A lineup drawn at random from the archive.</p>
      <div class="grades" role="radiogroup" aria-label="Difficulty">
        <button class="grade" type="button" role="radio" aria-checked="false" data-grade="easy">Easy</button>
        <button class="grade" type="button" role="radio" aria-checked="true" data-grade="medium">Medium</button>
        <button class="grade" type="button" role="radio" aria-checked="false" data-grade="hard">Hard</button>
      </div>
      <p class="terms" id="terms"></p>
      <button class="btn" type="button" id="go-quick">Start a lineup</button>
    </div>

    <div class="sheet">
      <h2>Today's XI</h2>
      <p id="daily-note">One lineup a day, the same for everyone who plays it.</p>
      <button class="btn btn-quiet" type="button" id="go-daily">Play today's lineup</button>
    </div>

    <dl class="record" id="home-record"></dl>
    <p class="footnote" id="archive-note"></p>
  </section>

  <section class="view" id="v-game">
    <div class="fixture" id="fixture"></div>
    <dl class="tally">
      <div><span>Named</span><strong id="t-found">0/11</strong></div>
      <div id="t-clock-cell"><span>Clock</span><strong id="t-clock">0:00</strong></div>
      <div><span>Points</span><strong id="t-points">0</strong></div>
      <div><span>Misses</span><strong id="t-misses">0</strong></div>
    </dl>
    <div class="whistle"><i id="whistle-bar"></i></div>

    <div class="board" id="board">
      <div class="marks" aria-hidden="true">
        <i class="circle"></i><i class="half"></i>
        <i class="area own"></i><i class="area opp"></i>
        <i class="six own"></i><i class="six opp"></i>
      </div>
    </div>

    <form class="call" id="call-form" autocomplete="off">
      <input id="call-input" type="text" placeholder="Name a player&hellip;" aria-label="Name a player"
             maxlength="80" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" />
      <button class="btn" type="submit">Call</button>
    </form>
    <p class="verdict" id="verdict" role="status" aria-live="polite"></p>

    <div class="bench">
      <button class="btn btn-quiet" type="button" id="hint-initials">Initials</button>
      <button class="btn btn-quiet" type="button" id="hint-reveal">Name one</button>
      <button class="btn btn-flag" type="button" id="concede">Concede</button>
    </div>
  </section>

  <section class="view" id="v-final">
    <div class="final">
      <p class="outcome" id="outcome"></p>
      <p class="points"><span id="final-points">0</span><small>points</small></p>
      <table class="ledger" id="ledger"></table>
      <div class="report" id="report"></div>
      <p class="eyebrow">The full eleven</p>
      <ol class="sheetlist" id="full-xi"></ol>
      <div class="again">
        <button class="btn" type="button" id="go-again">Another lineup</button>
        <button class="btn btn-quiet" type="button" id="go-home">Menu</button>
      </div>
    </div>
  </section>
</main>

<dialog id="dlg-rules">
  <h2>Rules</h2>
  <ul>
    <li>You get a famous starting XI with the names hidden. Type whoever you recognise &mdash; any order.</li>
    <li>Surnames are enough (<strong>Beckham</strong>). Accents are optional &mdash; <strong>Pique</strong> finds Piqu&eacute;.</li>
    <li>Small typos are forgiven on longer names.</li>
    <li>If two players in the same XI share a surname, you'll be asked for a first name.</li>
    <li><strong>Initials</strong> shows the initials of everyone still missing. <strong>Name one</strong> hands a player over. Both cost points.</li>
    <li>Get all eleven before the whistle for a bonus, plus whatever time is left.</li>
  </ul>
  <button class="btn" type="button" data-close>Close</button>
</dialog>

<dialog id="dlg-record">
  <h2>Your record</h2>
  <dl class="record" id="dlg-record-body"></dl>
  <div class="again" style="margin-top:1rem">
    <button class="btn btn-flag" type="button" id="wipe-record">Wipe</button>
    <button class="btn" type="button" data-close>Close</button>
  </div>
</dialog>
"""

SCRIPT = r"""
<script>
(function () {
  "use strict";

  var LINEUPS = __LINEUPS_DATA__;

  /* ===================================================================== rules
     Mirrors backend/app/game.py. */
  var GRADES = {
    easy:   { label: "Easy",   free: 4, seconds: 240, mult: 1.0 },
    medium: { label: "Medium", free: 2, seconds: 180, mult: 1.5 },
    hard:   { label: "Hard",   free: 0, seconds: 150, mult: 2.0 }
  };
  var PER_PLAYER = 100, FINISH_BONUS = 250, PER_SECOND = 5;
  var HINT_COST = { initials: 40, reveal: 120 };

  /* ================================================================== matching
     Mirrors backend/app/matching.py. */
  var PARTICLES = {
    van:1, von:1, de:1, der:1, den:1, di:1, da:1, das:1, dos:1, del:1,
    della:1, la:1, le:1, el:1, mac:1, mc:1, ten:1, ter:1, bin:1, al:1, st:1
  };
  var TRANSLIT = { "ø":"o", "đ":"d", "ð":"d", "ß":"ss",
                   "æ":"ae", "œ":"oe", "ł":"l", "þ":"th", "ı":"i" };
  var MIN_LEN = 3;

  function normalize(text) {
    if (!text) return "";
    var s = String(text).toLowerCase().replace(/[øđðßæœłþı]/g,
      function (ch) { return TRANSLIT[ch] || ch; });
    s = s.replace(/['’ʼ`]/g, "");
    s = s.normalize("NFD").replace(/[̀-ͯ]/g, "");
    return s.replace(/[^a-z0-9]+/g, " ").trim();
  }

  function surnameOf(name) {
    var t = normalize(name).split(" ").filter(Boolean);
    if (!t.length) return "";
    var i = t.length - 1;
    while (i > 0 && PARTICLES[t[i - 1]]) i--;
    return t.slice(i).join(" ");
  }

  function aliasKeys(name, accepts) {
    var t = normalize(name).split(" ").filter(Boolean);
    var keys = {};
    if (t.length) {
      keys[t.join(" ")] = 1;
      keys[surnameOf(name)] = 1;
      keys[t[t.length - 1]] = 1;
      var rawParts = String(name).split(/\s+/);
      var lastRaw = rawParts[rawParts.length - 1] || "";
      if (lastRaw.indexOf("-") !== -1) keys[normalize(lastRaw)] = 1;
    }
    (accepts || []).forEach(function (a) { var n = normalize(a); if (n) keys[n] = 1; });
    delete keys[""];
    return Object.keys(keys);
  }

  function editDistance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    if (a === b) return 0;
    var prev = [], cur = [], i, j;
    for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      cur = [i];
      var best = i;
      for (j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0));
        if (cur[j] < best) best = cur[j];
      }
      if (best > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }

  function allowance(key) { return key.length >= 10 ? 2 : (key.length >= 6 ? 1 : 0); }

  // Returns { status, slots, fuzzy }. status: match | ambiguous | no_match | too_short | empty
  function matchGuess(guess, cands) {
    var needle = normalize(guess);
    if (!needle) return { status: "empty", slots: [] };

    var exact = cands.filter(function (c) { return c.keys.indexOf(needle) !== -1; })
                     .map(function (c) { return c.slot; });
    if (exact.length) {
      return { status: exact.length === 1 ? "match" : "ambiguous", slots: exact.sort(), fuzzy: false };
    }
    if (needle.replace(/ /g, "").length < MIN_LEN) return { status: "too_short", slots: [] };

    var best = null, near = [];
    cands.forEach(function (c) {
      var closest = null;
      c.keys.slice().sort().forEach(function (key) {
        var allow = allowance(key);
        if (!allow) return;
        var d = editDistance(needle, key, allow);
        if (d <= allow && (closest === null || d < closest)) closest = d;
      });
      if (closest === null) return;
      if (best === null || closest < best) { best = closest; near = [c.slot]; }
      else if (closest === best) near.push(c.slot);
    });
    if (near.length) {
      return { status: near.length === 1 ? "match" : "ambiguous", slots: near.sort(), fuzzy: true };
    }
    return { status: "no_match", slots: [] };
  }

  /* ================================================================== layout */
  function layoutSlots(formation) {
    var rows = [1].concat(formation), out = [], slot = 0;
    rows.forEach(function (size, rowIndex) {
      for (var col = 0; col < size; col++) {
        out.push({ slot: slot++, row: rowIndex, column: col, rowSize: size, rowCount: rows.length });
      }
    });
    return out;
  }

  function initialsFor(name) {
    return String(name).replace(/-/g, " ").split(/\s+/).filter(Boolean)
      .map(function (p) { return p[0].toUpperCase() + "."; }).join(" ");
  }

  /* Deterministic seeding, so the daily lineup matches for everyone. */
  function hashSeed(str) {
    var h = 2166136261 >>> 0;
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0;
  }
  function rngFrom(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // The keeper is never given away - it is the easiest slot to guess.
  function pickFreeSlots(count, seed) {
    count = Math.max(0, Math.min(count, 10));
    if (!count) return [];
    var pool = [1,2,3,4,5,6,7,8,9,10], rnd = rngFrom(hashSeed(seed)), chosen = [];
    while (chosen.length < count && pool.length) {
      chosen.push(pool.splice(Math.floor(rnd() * pool.length), 1)[0]);
    }
    return chosen.sort(function (x, y) { return x - y; });
  }

  function scoreRound(named, complete, secondsLeft, penalty, grade) {
    var pts = Math.round(named * PER_PLAYER * grade.mult);
    var bonus = complete ? Math.round(FINISH_BONUS * grade.mult) : 0;
    var time = complete ? Math.round(Math.max(0, secondsLeft) * PER_SECOND * grade.mult) : 0;
    return {
      named: named, points: pts, bonus: bonus, time: time, penalty: penalty,
      total: Math.max(0, pts + bonus + time - penalty)
    };
  }

  function today() { return new Date().toISOString().slice(0, 10); }

  /* ==================================================================== state */
  var grade = "medium";
  var game = null;
  var tick = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function clock(s) {
    s = Math.max(0, Math.floor(s));
    return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
  }

  function newGame(lineup, gradeKey, seed, mode) {
    var g = GRADES[gradeKey];
    var free = pickFreeSlots(g.free, seed);
    return {
      lineup: lineup, grade: g, gradeKey: gradeKey, mode: mode,
      free: free, named: [], told: [],
      initialsBought: false, penalty: 0, misses: 0,
      secondsLeft: g.seconds, over: null, result: null
    };
  }

  function visible(g) { return g.free.concat(g.named, g.told); }
  function hidden(g) {
    var seen = visible(g), out = [];
    for (var i = 0; i < 11; i++) if (seen.indexOf(i) === -1) out.push(i);
    return out;
  }
  function candidates(g, slots) {
    return g.lineup.players.map(function (p, i) {
      return { slot: i, keys: aliasKeys(p.name, p.accepts) };
    }).filter(function (c) { return !slots || slots.indexOf(c.slot) !== -1; });
  }
  function sourceOf(g, i) {
    if (g.named.indexOf(i) !== -1) return "named";
    if (g.free.indexOf(i) !== -1) return "spotted";
    if (g.told.indexOf(i) !== -1) return "told";
    return null;
  }

  /* =================================================================== record */
  var KEY = "lineups.record.v1";
  function blankRecord() {
    return { played: 0, complete: 0, best: 0, namedTotal: 0, streak: 0, bestStreak: 0, lastDaily: null };
  }
  function readRecord() {
    try { return JSON.parse(localStorage.getItem(KEY)) || blankRecord(); }
    catch (e) { return blankRecord(); }
  }
  function writeRecord(r) { try { localStorage.setItem(KEY, JSON.stringify(r)); } catch (e) {} }

  function logResult(g) {
    var r = readRecord();
    r.played += 1;
    r.namedTotal += g.named.length;
    r.best = Math.max(r.best, g.result.total);
    if (g.over === "won") {
      r.complete += 1; r.streak += 1;
      r.bestStreak = Math.max(r.bestStreak, r.streak);
    } else { r.streak = 0; }
    if (g.mode === "daily") r.lastDaily = today();
    writeRecord(r);
  }

  function paintRecord(node) {
    var r = readRecord();
    var rate = r.played ? Math.round((r.complete / r.played) * 100) + "%" : "–";
    var avg = r.played ? (r.namedTotal / r.played).toFixed(1) : "–";
    node.innerHTML = "";
    [["Played", r.played], ["Full XIs", r.complete], ["Win rate", rate],
     ["Avg named", avg], ["Best", r.best], ["Streak", r.streak + "/" + r.bestStreak]
    ].forEach(function (pair) {
      var box = el("div");
      box.appendChild(el("dt", null, pair[0]));
      box.appendChild(el("dd", null, String(pair[1])));
      node.appendChild(box);
    });
  }

  /* ==================================================================== views */
  function show(name) {
    ["home", "game", "final"].forEach(function (v) {
      $("v-" + v).classList.toggle("on", v === name);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function paintTerms() {
    var g = GRADES[grade];
    $("terms").textContent =
      (g.free ? g.free + " shown at kick-off" : "nothing shown") +
      "  ·  " + clock(g.seconds) + " on the clock  ·  ×" + g.mult + " points";
  }

  function paintHome() {
    paintRecord($("home-record"));
    paintTerms();
    var r = readRecord();
    $("daily-note").textContent = r.lastDaily === today()
      ? "You've played today's lineup already — go again for practice."
      : "One lineup a day, the same for everyone who plays it.";
    var years = LINEUPS.map(function (l) { return l.date.slice(0, 4); }).sort();
    $("archive-note").textContent =
      LINEUPS.length + " lineups in the archive, " + years[0] + "–" + years[years.length - 1] + ".";
  }

  var MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];

  function longDate(iso) {
    if (!iso) return "";
    var bits = iso.split("-");
    return Number(bits[2]) + " " + MONTHS[Number(bits[1]) - 1] + " " + bits[0];
  }

  // A lineup with no opponent is not a single match - it is the XI a side fielded
  // most of a season. Saying so beats leaving the fixture looking half-missing.
  function paintFixture(l) {
    var box = $("fixture");
    box.innerHTML = "";
    var seasonSide = !l.opponent;

    var teams = el("div", "teams");
    teams.appendChild(document.createTextNode(l.team));
    if (l.opponent) teams.appendChild(el("em", null, " v " + l.opponent));
    box.appendChild(teams);

    if (seasonSide) box.appendChild(el("div", "badge", "Season XI"));

    var meta = el("div", "meta");
    [
      l.competition,
      seasonSide ? l.season + " season" : longDate(l.date),
      l.venue,
      l.formation.join("-")
    ].filter(Boolean).forEach(function (part) {
      meta.appendChild(el("b", null, part));
    });
    box.appendChild(meta);
  }

  function paintBoard(g, justPlaced) {
    var board = $("board");
    Array.prototype.slice.call(board.querySelectorAll(".man")).forEach(function (n) { n.remove(); });

    layoutSlots(g.lineup.formation).forEach(function (cell) {
      var i = cell.slot;
      var player = g.lineup.players[i];
      var src = sourceOf(g, i);
      var done = g.over !== null;

      var man = el("div", "man");
      // Row 0 is the keeper, at the foot of the board; the last row attacks the top.
      man.style.top = (cell.rowCount > 1 ? 93 - (cell.row / (cell.rowCount - 1)) * 86 : 50) + "%";
      man.style.left = (((cell.column + 1) / (cell.rowSize + 1)) * 100) + "%";
      if (src) man.classList.add(src);
      else if (done) man.classList.add("gone");
      if (justPlaced === i) man.classList.add("new");

      man.appendChild(el("span", "disc", player.pos));
      var label = (src || done) ? player.name : (g.initialsBought ? initialsFor(player.name) : "–");
      man.appendChild(el("span", "tag", label));
      board.appendChild(man);
    });
  }

  function paintTally(g) {
    var live = scoreRound(g.named.length, hidden(g).length === 0, g.secondsLeft, g.penalty, g.grade);
    $("t-found").textContent = visible(g).length + "/11";
    $("t-clock").textContent = clock(g.secondsLeft);
    $("t-points").textContent = g.over ? g.result.total : live.total;
    $("t-misses").textContent = g.misses;

    var late = g.secondsLeft <= 30 && !g.over;
    $("t-clock-cell").classList.toggle("late", late);
    $("whistle-bar").classList.toggle("late", late);
    $("whistle-bar").style.width = Math.max(0, (g.secondsLeft / g.grade.seconds) * 100) + "%";

    $("hint-initials").disabled = g.initialsBought || !!g.over;
    $("hint-initials").textContent = g.initialsBought ? "Initials shown" : "Initials −" + HINT_COST.initials;
    $("hint-reveal").disabled = !!g.over;
    $("hint-reveal").textContent = "Name one −" + HINT_COST.reveal;
    $("call-input").disabled = !!g.over;
  }

  function say(msg, tone) {
    var n = $("verdict");
    n.textContent = msg || "";
    n.className = "verdict" + (tone ? " " + tone : "");
  }

  function stopClock() { if (tick) { clearInterval(tick); tick = null; } }

  function startClock() {
    stopClock();
    tick = setInterval(function () {
      if (!game || game.over) { stopClock(); return; }
      game.secondsLeft -= 1;
      if (game.secondsLeft <= 0) {
        game.secondsLeft = 0;
        finish(hidden(game).length === 0 ? "won" : "lost");
        return;
      }
      paintTally(game);
    }, 1000);
  }

  function begin(lineup, gradeKey, seed, mode) {
    game = newGame(lineup, gradeKey, seed, mode);
    show("game");
    paintFixture(lineup);
    paintBoard(game);
    paintTally(game);
    say("");
    $("call-input").value = "";
    startClock();
    $("call-input").focus();
  }

  function startQuick() {
    var l = LINEUPS[Math.floor(Math.random() * LINEUPS.length)];
    begin(l, grade, "quick:" + Math.random(), "quick");
  }

  function startDaily() {
    var day = today();
    begin(LINEUPS[hashSeed(day) % LINEUPS.length], "medium", "daily:" + day, "daily");
  }

  function finish(how) {
    stopClock();
    game.over = how;
    game.result = scoreRound(game.named.length, hidden(game).length === 0,
                             game.secondsLeft, game.penalty, game.grade);
    logResult(game);
    paintBoard(game);
    paintTally(game);
    paintFinal(game);
    show("final");
  }

  function call(event) {
    event.preventDefault();
    if (!game || game.over) return;
    var input = $("call-input");
    var text = input.value.trim();
    if (!text) return;
    input.value = "";

    var open = hidden(game);
    var res = matchGuess(text, candidates(game, open));

    if (res.status === "match") {
      var slot = res.slots[0];
      game.named.push(slot);
      var p = game.lineup.players[slot];
      say("✓  " + p.name + " — " + p.pos, "good");
      if (hidden(game).length === 0) { finish("won"); return; }
      paintBoard(game, slot);
      paintTally(game);
    } else if (res.status === "ambiguous") {
      say("Two players here go by that name — add a first name.", "note");
    } else if (res.status === "too_short" || res.status === "empty") {
      say("Type at least three letters.", "note");
    } else {
      // Already on the board, or simply not in this XI?
      var anywhere = matchGuess(text, candidates(game, null));
      if (anywhere.status === "match" || anywhere.status === "ambiguous") {
        say("Already on the board.", "note");
      } else {
        game.misses += 1;
        say("✗  " + text + " — not in this lineup.", "bad");
        paintTally(game);
      }
    }
    input.focus();
  }

  function buyHint(type) {
    if (!game || game.over) return;
    var open = hidden(game);
    if (!open.length) return;

    if (type === "initials") {
      if (game.initialsBought) return;
      game.initialsBought = true;
      game.penalty += HINT_COST.initials;
      say("Initials shown.", "note");
    } else {
      var slot = open[0];
      game.told.push(slot);
      game.penalty += HINT_COST.reveal;
      say(game.lineup.players[slot].name + " — handed to you.", "note");
      if (hidden(game).length === 0) { finish("won"); return; }
    }
    paintBoard(game);
    paintTally(game);
    $("call-input").focus();
  }

  var OUTCOMES = { won: "All eleven", lost: "Time up", conceded: "Lineup revealed" };
  var MARKS = { named: "named", spotted: "given", told: "hinted", gone: "missed" };

  function paintFinal(g) {
    $("outcome").textContent = OUTCOMES[g.over] || "Round over";
    $("final-points").textContent = g.result.total;

    var table = $("ledger");
    table.innerHTML = "";
    [["Players named (" + g.result.named + ")", g.result.points],
     ["Completed the XI", g.result.bonus],
     ["Time left", g.result.time],
     ["Hints", g.result.penalty ? -g.result.penalty : 0]
    ].forEach(function (row) {
      if (!row[1]) return;
      var tr = table.insertRow();
      tr.insertCell().textContent = row[0];
      tr.insertCell().textContent = (row[1] > 0 ? "+" : "") + row[1];
    });
    var sum = table.insertRow();
    sum.className = "sum";
    sum.insertCell().textContent = "Total";
    sum.insertCell().textContent = String(g.result.total);

    var l = g.lineup;
    var report = $("report");
    report.innerHTML = "";
    var head = el("p");
    head.appendChild(el("strong", null, l.team + (l.opponent ? " " + (l.score || "v") + " " + l.opponent : "")));
    report.appendChild(head);
    var line = el("p");
    line.appendChild(document.createTextNode(
      [l.competition, l.venue, l.date].filter(Boolean).join("  ·  ")));
    report.appendChild(line);
    if (l.blurb) {
      var b = el("p", null, l.blurb + " ");
      if (l.source_url) {
        var a = el("a", null, "Source");
        a.href = l.source_url; a.target = "_blank"; a.rel = "noopener noreferrer";
        b.appendChild(a);
      }
      report.appendChild(b);
    }

    var list = $("full-xi");
    list.innerHTML = "";
    l.players.forEach(function (p, i) {
      var src = sourceOf(g, i) || "gone";
      var li = el("li");
      li.appendChild(el("span", "slot", p.pos));
      li.appendChild(el("span", null, p.name));
      li.appendChild(el("span", "mark " + src, MARKS[src]));
      list.appendChild(li);
    });
  }

  /* =================================================================== wiring */
  function openDialog(name) {
    if (name === "record") paintRecord($("dlg-record-body"));
    var dlg = $("dlg-" + name);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }

  $("go-quick").addEventListener("click", startQuick);
  $("go-again").addEventListener("click", startQuick);
  $("go-daily").addEventListener("click", startDaily);
  $("go-home").addEventListener("click", function () { paintHome(); show("home"); });
  $("home-link").addEventListener("click", function () { stopClock(); paintHome(); show("home"); });

  Array.prototype.slice.call(document.querySelectorAll("[data-grade]")).forEach(function (btn) {
    btn.addEventListener("click", function () {
      grade = btn.dataset.grade;
      document.querySelectorAll("[data-grade]").forEach(function (o) {
        o.setAttribute("aria-checked", String(o === btn));
      });
      paintTerms();
    });
  });

  $("call-form").addEventListener("submit", call);
  $("hint-initials").addEventListener("click", function () { buyHint("initials"); });
  $("hint-reveal").addEventListener("click", function () { buyHint("reveal"); });
  $("concede").addEventListener("click", function () {
    if (game && !game.over && window.confirm("Concede and see the full XI?")) finish("conceded");
  });

  Array.prototype.slice.call(document.querySelectorAll("[data-dialog]")).forEach(function (b) {
    b.addEventListener("click", function () { openDialog(b.dataset.dialog); });
  });
  Array.prototype.slice.call(document.querySelectorAll("[data-close]")).forEach(function (b) {
    b.addEventListener("click", function () { b.closest("dialog").close(); });
  });
  $("wipe-record").addEventListener("click", function () {
    if (!window.confirm("Wipe your saved record?")) return;
    writeRecord(blankRecord());
    paintRecord($("dlg-record-body"));
    paintRecord($("home-record"));
  });

  paintHome();
})();
</script>
"""


def build(fragment: bool = False) -> str:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    lineups = [
        {
            "id": entry["id"],
            "team": entry["team"],
            "opponent": entry.get("opponent"),
            "score": entry.get("score"),
            "competition": entry.get("competition"),
            "season": entry.get("season"),
            "venue": entry.get("venue"),
            "date": entry.get("date"),
            "formation": entry["formation"],
            "blurb": entry.get("blurb"),
            "source_url": entry.get("source_url"),
            "players": [
                {"name": p["name"], "pos": p.get("pos"), "accepts": p.get("accepts", [])}
                for p in entry["players"]
            ],
        }
        for entry in dataset["lineups"]
    ]
    # </script> inside a string literal would close the block early.
    payload = json.dumps(lineups, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = SCRIPT.replace("__LINEUPS_DATA__", payload)

    if fragment:
        # Artifact hosting supplies the doctype/head/body wrapper itself.
        return f"<title>{TITLE}</title>\n{STYLE}\n{MARKUP}\n{script}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="description" content="Name the missing players from famous starting XIs." />
<meta name="theme-color" content="#0a1f18" />
<link rel="manifest" href="manifest.webmanifest" />
<link rel="icon" href="icon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="icon-180.png" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="Line-Ups" />
<title>{TITLE}</title>
{STYLE}
</head>
<body>
{MARKUP}
{script}
<script>
if ("serviceWorker" in navigator) {{
  window.addEventListener("load", function () {{
    navigator.serviceWorker.register("sw.js").catch(function () {{ /* offline play unavailable */ }});
  }});
}}
</script>
</body>
</html>
"""


def build_site(out_dir: Path) -> None:
    """Assemble a static, installable site: the game plus its app manifest and icons."""
    import shutil

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(build(), encoding="utf-8")
    for asset in sorted((REPO_ROOT / "web").iterdir()):
        if asset.is_file():
            shutil.copy2(asset, out_dir / asset.name)
    # Pages otherwise runs the upload through Jekyll, which ignores some files.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Wrote {out_dir}/ ({sum(1 for _ in out_dir.iterdir())} files)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fragment", action="store_true",
                        help="emit body content only, without the html/head wrapper")
    parser.add_argument("--site", action="store_true",
                        help="build the installable static site into dist/site/")
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()

    if args.site:
        build_site(args.out or (DEFAULT_OUT.parent / "site"))
        return 0

    out = args.out or (DEFAULT_OUT.with_name("lineups-fragment.html") if args.fragment else DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build(fragment=args.fragment)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(html) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
