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
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "data" / "lineups.json"
#: Optional. Produced by scripts/fetch_player_facts.py; absent until a sweep has run,
#: in which case the sourced clues simply are not offered.
PLAYER_FACTS = REPO_ROOT / "data" / "player_facts.json"
LEADERBOARD = REPO_ROOT / "data" / "leaderboard.json"
DAILY = REPO_ROOT / "data" / "daily.json"
DEFAULT_OUT = REPO_ROOT / "dist" / "lineups.html"

TITLE = "Line-Ups &mdash; name the missing players"
BLURB = ("Name the missing players from 20 famous starting XIs, against the clock. "
         "England 1966 to Manchester City 2023.")
#: Where the game is published. Used for the link preview that messaging apps show
#: when someone pastes the address - those need absolute URLs, not relative ones.
SITE_URL = "https://marcconway84.github.io/Line-Ups-Game/"

STYLE = """
<style>
/* ---------------------------------------------------------------------------
   The manager's tactics board: board green, chalk markings, brass discs.
   Deliberately a single visual world - there is no light variant of a tactics
   board - so every colour is painted explicitly rather than inherited.

   Layout rule for the whole file: the page never scrolls. The body is exactly
   one viewport tall, every screen is a flex/grid column inside it, and the
   pitch takes whatever height is left over. Nothing is sized in a way that can
   push the controls off the bottom.
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
  --gap: clamp(0.35rem, 1.2vh, 0.7rem);
}

* { box-sizing: border-box; }

html, body {
  height: 100%;
  margin: 0;
  overflow: hidden;             /* the page itself never scrolls */
  overscroll-behavior: none;
}

body {
  height: 100dvh;
  display: flex;
  flex-direction: column;
  background: var(--board-deep);
  color: var(--chalk);
  font-family: var(--body);
  line-height: 1.45;
  -webkit-text-size-adjust: 100%;
}

/* -------------------------------------------------------------- masthead */
.masthead {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.5rem clamp(0.7rem, 3vw, 1.2rem);
  border-bottom: var(--rule);
}
.wordmark {
  font-family: var(--display);
  font-size: clamp(1.1rem, 3.4vh, 1.45rem);
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
.masthead nav { display: flex; gap: 0.8rem; }

.textlink {
  background: none;
  border: 0;
  color: var(--chalk-dim);
  font: 600 0.72rem/1 var(--body);
  letter-spacing: 0.09em;
  text-transform: uppercase;
  cursor: pointer;
  padding: 0.3rem 0;
  border-bottom: 1px solid transparent;
}
.textlink:hover, .textlink:focus-visible { color: var(--brass); border-bottom-color: var(--brass); }
.textlink[hidden] { display: none; }
.install {
  color: var(--board-deep);
  background: var(--brass);
  padding: 0.3rem 0.55rem;
  border-bottom: 0;
}
.install:hover, .install:focus-visible { background: var(--brass-deep); color: var(--board-deep); border-bottom-color: transparent; }
.steps { counter-reset: step; list-style: none; padding: 0; }
.steps li { counter-increment: step; position: relative; padding-left: 1.6rem; }
.steps li::before {
  content: counter(step);
  position: absolute;
  left: 0;
  color: var(--brass);
  font-family: var(--data);
  font-weight: 700;
}
.steps b { color: var(--chalk); }

/* ----------------------------------------------------------------- stage */
.stage {
  flex: 1 1 auto;
  min-height: 0;                /* lets children shrink instead of overflowing */
  padding: var(--gap) clamp(0.7rem, 3vw, 1.2rem);
}

.view { display: none; height: 100%; min-height: 0; }
.view.on { display: flex; flex-direction: column; }

/* ------------------------------------------------------------------ home */
#v-home {
  justify-content: center;
  gap: var(--gap);
  max-width: 34rem;
  margin: 0 auto;
  width: 100%;
  text-align: center;
}
.eyebrow {
  font: 700 0.64rem/1 var(--body);
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--brass);
  margin: 0;
}
h1 {
  font-family: var(--display);
  font-size: clamp(1.8rem, 7vh, 3rem);
  line-height: 0.95;
  text-transform: uppercase;
  margin: 0;
  text-wrap: balance;
}
.standfirst {
  color: var(--chalk-dim);
  margin: 0 auto;
  max-width: 36ch;
  font-size: clamp(0.8rem, 1.9vh, 0.95rem);
}

.decks { display: grid; gap: var(--gap); grid-template-columns: 1fr; }
@media (min-width: 34rem) { .decks { grid-template-columns: 1fr 1fr; } }

.deck {
  border: var(--rule);
  background: var(--panel);
  padding: clamp(0.55rem, 1.6vh, 0.9rem);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  text-align: left;
}
.deck h2 {
  font-family: var(--display);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 1rem;
  margin: 0;
}
.deck p { margin: 0; color: var(--chalk-dim); font-size: 0.76rem; }
.deck .btn { margin-top: auto; }

.grades { display: flex; border: var(--rule); }
.grade {
  flex: 1;
  background: none;
  border: 0;
  border-right: var(--rule);
  color: var(--chalk-dim);
  font: 700 0.68rem/1 var(--body);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 0.45rem 0.2rem;
  cursor: pointer;
}
.grade:last-child { border-right: 0; }
.grade[aria-checked="true"] { background: var(--brass); color: var(--board-deep); }

.terms { font-family: var(--data); font-size: 0.64rem; color: var(--chalk-dim); margin: 0; }

.btn {
  width: 100%;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--brass);
  background: var(--brass);
  color: var(--board-deep);
  font: 700 0.75rem/1 var(--body);
  letter-spacing: 0.11em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.btn:hover:not(:disabled) { background: var(--brass-deep); border-color: var(--brass-deep); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-quiet { background: none; color: var(--chalk); border-color: var(--chalk-line); }
.btn-quiet:hover:not(:disabled) { background: var(--panel-2); border-color: var(--chalk-dim); }
.btn-flag { background: none; color: var(--flag); border-color: rgba(226, 87, 76, 0.45); }
.btn-flag:hover:not(:disabled) { background: rgba(226, 87, 76, 0.12); border-color: var(--flag); }

.record { display: grid; grid-template-columns: repeat(3, 1fr); border: var(--rule); border-bottom: 0; margin: 0; }
.record div { border-bottom: var(--rule); border-right: var(--rule); padding: 0.35rem 0.3rem; text-align: center; }
.record div:nth-child(3n) { border-right: 0; }
.record dt { font: 700 0.55rem/1 var(--body); letter-spacing: 0.11em; text-transform: uppercase; color: var(--chalk-dim); }
.record dd { margin: 0.15rem 0 0; font-family: var(--data); font-size: 0.95rem; font-variant-numeric: tabular-nums; }
.footnote { color: var(--chalk-dim); font-size: 0.66rem; margin: 0; }

/* A landscape phone has barely any height. Drop the scene-setting copy and put
   the record on a single row so the menu still fits without scrolling. */
@media (max-height: 30rem) {
  #v-home .eyebrow, #v-home .standfirst, #v-home .footnote { display: none; }
  #v-home .deck p { display: none; }
  .record { grid-template-columns: repeat(6, 1fr); }
  .record div:nth-child(3n) { border-right: var(--rule); }
  .record div:last-child { border-right: 0; }
}

/* -------------------------------------------------------------- pitchside
   Narrow: one column, board takes the slack (the dugout dissolves into the
   grid so its parts can sit above and below the pitch).
   Wide: pitch on the left at full height, everything else in a side column. */
.pitchside {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  gap: var(--gap);
}
.dugout { display: contents; }
.fixture { order: 1; }
.tally   { order: 2; }
.whistle { order: 3; }
.board-cell { order: 4; }
.controls, .result { order: 5; }

/* Two columns whenever the viewport is wide, and always in landscape - a short
   landscape phone is exactly the case where stacking cannot fit. */
@media (min-width: 52rem), (min-aspect-ratio: 1 / 1) and (min-width: 34rem) {
  .pitchside {
    grid-template-columns: minmax(0, 1fr) clamp(17rem, 26vw, 22rem);
    grid-template-rows: minmax(0, 1fr);
    gap: clamp(0.8rem, 2vw, 1.6rem);
    align-items: stretch;
  }
  .dugout {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--gap);
    min-height: 0;
  }
  .board-cell { order: 0; }
}

/* --------------------------------------------------------------- fixture */
.fixture { text-align: center; }
.fixture .teams {
  font-family: var(--display);
  font-size: clamp(1.05rem, 3.6vh, 1.65rem);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  line-height: 1.05;
}
.fixture .teams em { font-style: normal; color: var(--chalk-dim); }
.fixture .seasonnote {
  margin-top: 0.2rem;
  color: var(--brass);
  font-size: clamp(0.62rem, 1.6vh, 0.76rem);
  font-style: italic;
}
.fixture .meta {
  font-family: var(--data);
  font-size: clamp(0.58rem, 1.5vh, 0.7rem);
  color: var(--chalk-dim);
  margin-top: 0.2rem;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0 0.7rem;
}
.fixture .meta b { font-weight: 400; white-space: nowrap; }

/* ----------------------------------------------------------------- tally */
.tally { display: grid; grid-template-columns: repeat(4, 1fr); border: var(--rule); margin: 0; }
.tally div { border-right: var(--rule); padding: 0.3rem 0.2rem; text-align: center; }
.tally div:last-child { border-right: 0; }
.tally span {
  display: block;
  font: 700 0.52rem/1 var(--body);
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--chalk-dim);
}
.tally strong {
  display: block;
  font-family: var(--data);
  font-size: clamp(0.85rem, 2.2vh, 1.05rem);
  font-variant-numeric: tabular-nums;
  margin-top: 0.1rem;
  font-weight: 500;
}
.tally .late strong { color: var(--flag); }

.whistle { height: 3px; background: rgba(234, 242, 236, 0.1); overflow: hidden; }
.whistle i { display: block; height: 100%; width: 100%; background: var(--brass); transition: width 0.95s linear; }
.whistle i.late { background: var(--flag); }

/* ----------------------------------------------------------------- board
   The cell is a size container, so the pitch can be the larger of "as tall as
   the space allows" and "as wide as the space allows" while keeping its shape.
   That is what stops it ever overflowing the screen. */
.board-cell {
  min-height: 0;
  min-width: 0;
  container-type: size;
  display: grid;
  place-items: center;
}
.board {
  aspect-ratio: 68 / 95;
  block-size: min(100cqh, calc(100cqw * 95 / 68));
  container-type: size;
  position: relative;
  border: var(--rule);
  overflow: hidden;
  background-color: var(--board);
  background-image: repeating-linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.045) 0,
    rgba(255, 255, 255, 0.045) 12.5%,
    transparent 12.5%,
    transparent 25%
  );
}

.marks { position: absolute; inset: 0; }
.marks > i { position: absolute; border: 1px solid var(--chalk-line); display: block; }
.marks .circle { width: 30%; aspect-ratio: 1; border-radius: 50%; left: 35%; top: 50%; transform: translateY(-50%); }
.marks .half { left: 0; right: 0; top: 50%; border-width: 0 0 1px; }
.marks .area { left: 21%; width: 58%; height: 13%; }
.marks .area.own { bottom: 0; border-bottom: 0; }
.marks .area.opp { top: 0; border-top: 0; }

/* Player chips scale with the pitch, so they stay readable at any size. */
.man {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 23cqw;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
  text-align: center;
  /* Hidden players are buttons; strip the browser's chrome. */
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  color: inherit;
}
button.man { cursor: pointer; }
button.man:hover .disc, button.man:focus-visible .disc {
  border-color: var(--brass);
  color: var(--brass);
}
button.man:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
/* A player you have already spent points on. */
.man.probed .disc { border-color: var(--brass); border-style: dashed; }
.disc {
  inline-size: clamp(20px, 9cqmin, 46px);
  block-size: clamp(20px, 9cqmin, 46px);
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--body);
  font-weight: 700;
  font-size: clamp(7px, 2.7cqmin, 14px);
  border: 1px solid var(--chalk-line);
  background: rgba(10, 31, 24, 0.72);
  color: var(--chalk-dim);
}
.tag {
  font-size: clamp(7px, 2.9cqmin, 15px);
  font-weight: 600;
  line-height: 1.15;
  padding: 0.05rem 0.25rem;
  background: rgba(10, 31, 24, 0.82);
  color: var(--chalk-dim);
  max-width: 100%;
  overflow-wrap: break-word;
}
.man.named .disc { background: var(--brass); border-color: var(--brass); color: var(--board-deep); }
.man.spotted .disc { background: var(--chalk-dim); border-color: var(--chalk); color: var(--board-deep); }
.man.told .disc { background: var(--brass-deep); border-color: var(--brass); color: var(--board-deep); }
.man.gone .disc { background: rgba(226, 87, 76, 0.85); border-color: var(--flag); color: var(--board-deep); }
.man.named .tag, .man.spotted .tag, .man.told .tag { color: var(--chalk); }
.man.gone .tag { color: #f6cfcb; }
.man.new .disc { animation: place 0.4s ease-out; }
@keyframes place { 0% { transform: scale(0.5); } 60% { transform: scale(1.22); } 100% { transform: scale(1); } }

/* -------------------------------------------------------------- controls */
.controls { display: flex; flex-direction: column; gap: 0.4rem; }
/* An author `display` beats the `hidden` attribute, so say it explicitly. */
.controls[hidden] { display: none; }
.call { display: flex; gap: 0.4rem; }
.call input {
  flex: 1;
  min-width: 0;
  padding: 0.55rem 0.7rem;
  border: var(--rule);
  background: var(--panel);
  color: var(--chalk);
  font: 400 1rem var(--body);   /* 1rem keeps iOS from zooming on focus */
}
.call input::placeholder { color: var(--chalk-dim); }
.call input:focus-visible { outline: 2px solid var(--brass); outline-offset: 1px; }
.call .btn { width: auto; padding-inline: 0.9rem; }

.verdict { min-height: 1.3em; margin: 0; font-size: 0.8rem; font-weight: 600; }
.verdict.good { color: var(--brass); }
.verdict.bad { color: var(--flag); }
.verdict.note { color: var(--chalk-dim); }

.bench { display: flex; gap: 0.4rem; }
.bench .btn { font-size: 0.6rem; letter-spacing: 0.06em; padding: 0.5rem 0.25rem; }
.tip { margin: 0; font-size: 0.68rem; color: var(--chalk-dim); }

/* ------------------------------------------------------------ clue sheet */
.clue-sub {
  margin: -0.3rem 0 0.8rem;
  font-family: var(--data);
  font-size: 0.7rem;
  color: var(--chalk-dim);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.clue-list { list-style: none; padding: 0; margin: 0 0 0.9rem; }
.clue { border-top: var(--rule); padding: 0.5rem 0; }
.clue-head { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
.clue-label { font-weight: 700; font-size: 0.84rem; }
.clue-buy {
  flex: none;
  border: 1px solid var(--brass);
  background: none;
  color: var(--brass);
  font: 700 0.72rem/1 var(--data);
  padding: 0.32rem 0.6rem;
  cursor: pointer;
  min-width: 3.2rem;
}
.clue-buy:hover:not(:disabled) { background: var(--brass); color: var(--board-deep); }
.clue-buy:disabled { opacity: 0.4; cursor: not-allowed; }
.clue-cost.spent { font-family: var(--data); font-size: 0.7rem; color: var(--chalk-dim); }
.clue-blurb { margin: 0.2rem 0 0; font-size: 0.72rem; color: var(--chalk-dim); }
.clue-text { margin: 0.3rem 0 0; font-size: 0.84rem; color: var(--chalk); }
.clue.got .clue-label { color: var(--brass); }
.clue-none { border-top: var(--rule); padding: 0.6rem 0 0; font-size: 0.72rem; color: var(--chalk-dim); }

/* ---------------------------------------------------------------- result */
.result { display: flex; flex-direction: column; gap: 0.4rem; }
.result[hidden] { display: none; }
.headline { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; flex-wrap: wrap; }
.outcome {
  font-family: var(--display);
  font-size: clamp(1.1rem, 3.4vh, 1.7rem);
  text-transform: uppercase;
  margin: 0;
  text-wrap: balance;
}
.points {
  font-family: var(--data);
  font-size: clamp(1.5rem, 5vh, 2.4rem);
  font-variant-numeric: tabular-nums;
  color: var(--brass);
  line-height: 1;
  margin: 0;
}
.points small {
  font-family: var(--body);
  font-size: 0.6rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--chalk-dim);
  margin-left: 0.4rem;
}
.ledger { width: 100%; border-collapse: collapse; font-size: 0.72rem; }
.ledger td { padding: 0.15rem 0; border-bottom: var(--rule); color: var(--chalk-dim); text-align: left; }
.ledger td:last-child { text-align: right; color: var(--chalk); font-family: var(--data); font-variant-numeric: tabular-nums; }
.ledger tr.sum td { color: var(--chalk); font-weight: 700; border-bottom: 0; }

/* The leaderboard. One line in the result panel, the table itself in a dialog -
   the result has to keep fitting on a phone without scrolling, and a top ten
   cannot. */
.standing {
  /* Plain running text, not flex. A flex container turns each run of text into its
     own item, which put "1st" and "of 43 on this XI" on separate lines. */
  margin: 0.35rem 0 0; font-size: 0.72rem; color: var(--chalk-dim); line-height: 1.4;
}
.standing b { color: var(--chalk); font-family: var(--data); }
.standing button {
  background: none; border: 0; padding: 0; margin-left: 0.4rem; cursor: pointer;
  color: var(--pitch-line, var(--chalk)); font: inherit; text-decoration: underline;
}
.build { margin: 0.6rem 0 0; font-size: 0.62rem; color: var(--chalk-dim); opacity: 0.7; }
.board { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
.board td { padding: 0.28rem 0; border-bottom: var(--rule); color: var(--chalk-dim); }
.board td.rank { width: 2.2rem; font-family: var(--data); }
.board td.tally {
  text-align: right; color: var(--chalk);
  font-family: var(--data); font-variant-numeric: tabular-nums;
}
.board tr.you td { color: var(--chalk); font-weight: 700; }
.board tr.you td.rank::after { content: " \2190"; }
#name-input {
  width: 100%; padding: 0.5rem 0.6rem; font: inherit; color: var(--chalk);
  background: rgba(0, 0, 0, 0.25); border: var(--rule); border-radius: 0.4rem;
}

.report {
  color: var(--chalk-dim);
  font-size: 0.72rem;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
}
.report a { color: var(--brass); }
.again { display: flex; gap: 0.4rem; }

/* On a short or narrow screen the result panel has to give way, or it squeezes
   the finished XI off the pitch. The total is the number that matters; the
   itemised breakdown is a luxury for bigger screens. */
@media (max-height: 46rem), (max-width: 30rem) {
  .result .ledger { display: none; }
  .report { -webkit-line-clamp: 2; line-clamp: 2; }
}

/* ---------------------------------------------------------------- dialog */
dialog {
  border: var(--rule);
  background: var(--panel);
  color: var(--chalk);
  max-width: 30rem;
  width: calc(100% - 2rem);
  max-height: 85dvh;
  overflow: auto;               /* only place a scrollbar is ever allowed */
  padding: 1.1rem;
}
dialog::backdrop { background: rgba(6, 18, 14, 0.78); }
dialog h2 { font-family: var(--display); text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 0.6rem; font-size: 1.2rem; }
dialog ul { padding-left: 1.1rem; color: var(--chalk-dim); font-size: 0.82rem; margin: 0 0 0.9rem; }
dialog li { margin-bottom: 0.35rem; }
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
    <button class="textlink install" type="button" id="install" hidden>Install</button>
    <button class="textlink" type="button" data-dialog="rules">Rules</button>
    <button class="textlink" type="button" data-dialog="record">Record</button>
  </nav>
</header>

<main class="stage">
  <section class="view on" id="v-home">
    <p class="eyebrow">The football lineup quiz</p>
    <h1>Name the eleven</h1>
    <p class="standfirst">
      A famous starting XI, blanked out. The shape is there, the names are not.
      Fill in everyone you recognise before the whistle.
    </p>

    <div class="decks">
      <div class="deck">
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

      <div class="deck">
        <h2>Today's XI</h2>
        <p id="daily-note">One lineup a day, the same for everyone who plays it.</p>
        <button class="btn btn-quiet" type="button" id="go-daily">Play today's lineup</button>
      </div>
    </div>

    <dl class="record" id="home-record"></dl>
    <p class="footnote" id="archive-note"></p>
  </section>

  <section class="view" id="v-game">
    <div class="pitchside">
      <div class="board-cell">
        <div class="board" id="board">
          <div class="marks" aria-hidden="true">
            <i class="circle"></i><i class="half"></i>
            <i class="area own"></i><i class="area opp"></i>
          </div>
        </div>
      </div>

      <div class="dugout">
        <div class="fixture" id="fixture"></div>

        <dl class="tally">
          <div><span>Named</span><strong id="t-found">0/11</strong></div>
          <div id="t-clock-cell"><span>Clock</span><strong id="t-clock">0:00</strong></div>
          <div><span>Points</span><strong id="t-points">0</strong></div>
          <div><span>Misses</span><strong id="t-misses">0</strong></div>
        </dl>
        <div class="whistle"><i id="whistle-bar"></i></div>

        <div class="controls" id="controls">
          <form class="call" id="call-form" autocomplete="off">
            <input id="call-input" type="text" placeholder="Name a player&hellip;" aria-label="Name a player"
                   maxlength="80" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" />
            <button class="btn" type="submit">Call</button>
          </form>
          <p class="verdict" id="verdict" role="status" aria-live="polite"></p>
          <p class="tip">Stuck? Tap any hidden player for clues.</p>
          <div class="bench">
            <button class="btn btn-flag" type="button" id="concede">Concede</button>
          </div>
        </div>

        <div class="result" id="result" hidden>
          <div class="headline">
            <p class="outcome" id="outcome"></p>
            <p class="points"><span id="final-points">0</span><small>points</small></p>
          </div>
          <table class="ledger" id="ledger"></table>
          <div class="report" id="report"></div>
          <!-- One line, not a table. The board itself opens in a dialog, because the
               result panel has to keep fitting on a phone screen without scrolling. -->
          <p class="standing" id="standing" hidden></p>
          <div class="again">
            <button class="btn" type="button" id="go-again">Another lineup</button>
            <button class="btn btn-quiet" type="button" id="go-home">Menu</button>
          </div>
        </div>
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
    <li><strong>Stuck on one player? Tap him.</strong> Every shirt has its own clue sheet &mdash;
      an anagram of the surname, its length, the vowels blanked out, his forename, or another XI
      in the archive he also starts in. The more a clue gives away, the more it costs.</li>
    <li>Get all eleven before the whistle for a bonus, plus whatever time is left.</li>
  </ul>
  <!-- Which build this is. Sounds like housekeeping; it is the difference between
       "the change is not working" and "you are looking at yesterday's page", which
       has cost real time to work out more than once. -->
  <p class="build" id="build-stamp"></p>
  <button class="btn" type="button" data-close>Close</button>
</dialog>

<dialog id="dlg-clues">
  <h2 id="clue-title">Clue sheet</h2>
  <p class="clue-sub" id="clue-sub"></p>
  <ul class="clue-list" id="clue-list"></ul>
  <button class="btn" type="button" data-close>Back to the pitch</button>
</dialog>

<dialog id="dlg-install">
  <h2>Add to your home screen</h2>
  <p id="install-lead" style="color:var(--chalk-dim);font-size:0.84rem;margin:0 0 0.7rem"></p>
  <ul class="steps" id="install-steps"></ul>
  <button class="btn" type="button" data-close>Close</button>
</dialog>

<dialog id="dlg-board">
  <h2 id="board-title">Leaderboard</h2>
  <p class="clue-sub" id="board-sub"></p>
  <table class="board" id="board-table"></table>
  <button class="btn" type="button" data-close>Close</button>
</dialog>

<dialog id="dlg-name">
  <h2>What shall we call you?</h2>
  <p class="clue-sub">It goes on the leaderboard next to your score. Nothing else &mdash;
    no email, no password.</p>
  <form id="name-form">
    <input id="name-input" type="text" maxlength="24" autocomplete="nickname"
           placeholder="Your name" aria-label="Your name" />
    <div class="again" style="margin-top:0.8rem">
      <button class="btn" type="submit">Join the board</button>
      <button class="btn btn-quiet" type="button" id="name-skip">No thanks</button>
    </div>
  </form>
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

  /* Clues are bought per player, listed most expensive first. Price tracks how
     much a clue gives away: one letter is cheap, the name itself is dear.

     Every clue here is *computed* from the lineup data - the player's name, and
     which other XIs in the archive he starts in. Nothing is recalled from
     memory, so nothing can be subtly wrong, and every player in the archive has
     a complete sheet without anyone hand-writing 220 of them. */
  var CLUES = [
    { key: "reveal",    label: "Reveal the name",         cost: 150, blurb: "Just tell me." },
    // Second only to the name: every letter, and a surname is short enough to solve.
    { key: "anagram",   label: "Anagram of the surname",  cost: 130, blurb: "Right letters, wrong order." },
    { key: "career",    label: "Every club he played for", cost: 110, blurb: "In order." },
    { key: "elsewhere", label: "Elsewhere in the archive", cost: 90,  blurb: "Another XI he starts in." },
    { key: "first",     label: "First name",              cost: 75,  blurb: "Forename only." },
    { key: "novowels",  label: "Surname, vowels hidden",  cost: 60,  blurb: "Consonants, with the gaps shown." },
    { key: "nation",    label: "Who he played for",       cost: 50,  blurb: "His national side." },
    { key: "initials",  label: "Initials",                cost: 40,  blurb: "First letters." },
    { key: "length",    label: "Length of the surname",   cost: 25,  blurb: "How many letters." },
    { key: "letter",    label: "First letter of surname", cost: 20,  blurb: "One letter." }
  ];

  /* Nationality and club career come from Wikidata, looked up by
     scripts/fetch_player_facts.py and keyed by normalised name. Unlike the rest of
     the sheet these are not derivable from the archive, so they are offered only
     where the lookup actually found something. */
  var FACTS = __PLAYER_FACTS__;

  function factsFor(name) { return FACTS[normalize(name)] || null; }

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
    return {
      lineup: lineup, grade: g, gradeKey: gradeKey, mode: mode,
      free: pickFreeSlots(g.free, seed), named: [], told: [],
      bought: {},                 // slot index -> { clueKey: true }
      penalty: 0, misses: 0,
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

  /* ============================================================= leaderboard */
  /* Best score per XI, first attempt only.

     Everything here is optional at runtime. If the leaderboard is not configured,
     or the service cannot be reached, the round plays and scores exactly as it
     always did - the board simply does not appear. A quiz that stops working
     because a server is down would be a bad trade for a list of names. */

  var BOARD = __LEADERBOARD__;
  var WHO_KEY = "lineups.who.v1";

  function boardOn() { return !!(BOARD && BOARD.url); }
  function boardUrl(path) { return String(BOARD.url).replace(/\/+$/, "") + path; }

  function readWho() {
    try { return JSON.parse(localStorage.getItem(WHO_KEY)) || {}; }
    catch (e) { return {}; }
  }
  function writeWho(w) { try { localStorage.setItem(WHO_KEY, JSON.stringify(w)); } catch (e) {} }

  /* A random id, made once and kept in this browser.

     This is not a login and is not pretending to be one. It is only what lets the
     board tell "this player again" from "somebody new", which is all the
     first-attempt rule needs. Switch device and you are a new player; clear your
     browser and you are a new player. That is the honest limit of doing this
     without asking anyone to sign in, and signing in is exactly what would stop
     people clicking a link and playing. */
  function whoAmI() {
    var who = readWho();
    if (!who.id) {
      who.id = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : String(Date.now()) + "-" + Math.random().toString(36).slice(2);
      writeWho(who);
    }
    return who;
  }

  function ordinal(n) {
    var tens = n % 100;
    if (tens >= 11 && tens <= 13) return n + "th";
    return n + (["th", "st", "nd", "rd"][n % 10] || "th");
  }

  /* Every clue bought this round, flattened. The service prices them itself. */
  function cluesBought(g) {
    var out = [];
    Object.keys(g.bought || {}).forEach(function (slot) {
      Object.keys(g.bought[slot] || {}).forEach(function (key) { out.push(key); });
    });
    return out;
  }

  /* Asked for as the round starts. The token proves later that the round was
     actually begun, and how long ago - without it a perfect score could be posted
     without playing at all. */
  function claimToken(g) {
    if (!boardOn()) return;
    fetch(boardUrl("/round/start"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ lineup: g.lineup.id, difficulty: g.gradeKey })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.token) g.token = d.token; })
      .catch(function () { /* no board this round; the game is unaffected */ });
  }

  function submitScore(g) {
    var who = whoAmI();
    standingSays("Sending your score…");
    fetch(boardUrl("/round/finish"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        token: g.token,
        player: who.id,
        name: who.name,
        guessed: g.named.length,
        secondsLeft: Math.max(0, Math.floor(g.secondsLeft)),
        completed: hidden(g).length === 0,
        clues: cluesBought(g)
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) { standingSays("The leaderboard turned that round down."); return; }
        g.standing = res.data;
        paintStanding(res.data);
      })
      .catch(function () { standingSays("Couldn't reach the leaderboard just now."); });
  }

  function standingSays(text, extra) {
    var line = $("standing");
    line.innerHTML = "";
    line.appendChild(document.createTextNode(text));
    if (extra) line.appendChild(extra);
    line.hidden = false;
  }

  function boardButton(lineupId, label) {
    var b = el("button", null, label || "See the board");
    b.type = "button";
    b.addEventListener("click", function () { openBoard(lineupId); });
    return b;
  }

  function paintStanding(data) {
    var line = $("standing");
    line.innerHTML = "";
    if (data.you) {
      /* "counted" is false when this was not the first attempt. Saying so plainly
         beats looking like the score failed to send. */
      if (data.counted === false) {
        line.appendChild(document.createTextNode("Only your first go counts — you were "));
      }
      line.appendChild(el("b", null, ordinal(data.you.rank)));
      line.appendChild(document.createTextNode(" of " + data.players + " on this XI"));
    } else {
      line.appendChild(document.createTextNode(data.players + " have played this XI"));
    }
    line.appendChild(boardButton(data.lineup));
    line.hidden = false;
  }

  /* Offered once. Someone who says no is not asked again, but can still join later
     from the same line. */
  function offerBoard(g) {
    var line = $("standing");
    line.hidden = true;
    line.innerHTML = "";
    if (!boardOn() || !g.token) return;

    var who = readWho();
    if (who.name) { submitScore(g); return; }
    if (who.declined) {
      var join = el("button", null, "Join the leaderboard");
      join.type = "button";
      join.addEventListener("click", function () { askName(g); });
      standingSays("", join);
      return;
    }
    askName(g);
  }

  function askName(g) {
    var dlg = $("dlg-name");
    var input = $("name-input");
    input.value = readWho().name || "";
    dlg.returnValue = "";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    setTimeout(function () { input.focus(); }, 50);

    $("name-form").onsubmit = function (event) {
      event.preventDefault();
      var who = whoAmI();
      who.name = input.value.trim().slice(0, 24) || "Anonymous";
      who.declined = false;
      writeWho(who);
      closeDialog(dlg);
      submitScore(g);
    };
    $("name-skip").onclick = function () {
      var who = whoAmI();
      who.declined = true;
      writeWho(who);
      closeDialog(dlg);
      offerBoard(g);
    };
  }

  function closeDialog(dlg) {
    if (dlg.close) dlg.close(); else dlg.removeAttribute("open");
  }

  function openBoard(lineupId) {
    var dlg = $("dlg-board");
    var table = $("board-table");
    var lineup = null;
    for (var i = 0; i < LINEUPS.length; i++) {
      if (LINEUPS[i].id === lineupId) { lineup = LINEUPS[i]; break; }
    }
    $("board-title").textContent = "Leaderboard";
    $("board-sub").textContent = lineup
      ? lineup.team + (lineup.opponent ? " v " + lineup.opponent : "") + " — first attempts only"
      : "First attempts only";
    table.innerHTML = "";
    var loading = table.insertRow();
    loading.insertCell().textContent = "Loading…";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");

    var who = readWho();
    fetch(boardUrl("/board?lineup=" + encodeURIComponent(lineupId)
                   + (who.id ? "&player=" + encodeURIComponent(who.id) : "")))
      .then(function (r) { return r.json(); })
      .then(function (data) { paintBoardTable(table, data, who); })
      .catch(function () {
        table.innerHTML = "";
        table.insertRow().insertCell().textContent = "Couldn't reach the leaderboard.";
      });
  }

  function paintBoardTable(table, data, who) {
    table.innerHTML = "";
    if (!data.top || !data.top.length) {
      table.insertRow().insertCell().textContent = "Nobody has played this one yet. You're first.";
      return;
    }
    var lastScore = null, place = 0, shown = 0;
    data.top.forEach(function (row) {
      shown += 1;
      /* Equal scores share a place, so a three-way tie reads 1st, 1st, 1st. */
      if (row.score !== lastScore) { place = shown; lastScore = row.score; }
      var tr = table.insertRow();
      if (data.you && data.you.name === row.name && data.you.score === row.score) {
        tr.className = "you";
      }
      var rank = tr.insertCell();
      rank.className = "rank";
      rank.textContent = ordinal(place);
      tr.insertCell().textContent = row.name;
      var tally = tr.insertCell();
      tally.className = "tally";
      tally.textContent = String(row.score);
    });
    if (data.you && data.you.rank > shown) {
      var mine = table.insertRow();
      mine.className = "you";
      var r = mine.insertCell();
      r.className = "rank";
      r.textContent = ordinal(data.you.rank);
      mine.insertCell().textContent = data.you.name;
      var t = mine.insertCell();
      t.className = "tally";
      t.textContent = String(data.you.score);
    }
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
    ["home", "game"].forEach(function (v) {
      $("v-" + v).classList.toggle("on", v === name);
    });
  }

  function paintTerms() {
    var g = GRADES[grade];
    $("terms").textContent =
      (g.free ? g.free + " shown at kick-off" : "nothing shown") +
      "  ·  " + clock(g.seconds) + " clock  ·  ×" + g.mult + " points";
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

  // Every lineup is one specific match - the dataset validator enforces it - so the
  // header can always name the opponent, the ground and the date.
  function paintFixture(l) {
    var box = $("fixture");
    box.innerHTML = "";

    var teams = el("div", "teams");
    teams.appendChild(document.createTextNode(l.team));
    teams.appendChild(el("em", null, " v " + l.opponent));
    box.appendChild(teams);

    var meta = el("div", "meta");
    [l.competition, longDate(l.date), l.venue, l.formation.join("-")]
      .filter(Boolean)
      .forEach(function (part) { meta.appendChild(el("b", null, part)); });
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

      // A hidden player is a button: tapping him opens his clue sheet.
      var open = !src && !done;
      var man = el(open ? "button" : "div", "man");
      if (open) {
        man.type = "button";
        man.setAttribute("aria-label", "Clues for the " + player.pos);
        man.addEventListener("click", function () { openClues(i); });
      }
      // Row 0 is the keeper, at the foot of the board; the last row attacks the top.
      man.style.top = (cell.rowCount > 1 ? 93 - (cell.row / (cell.rowCount - 1)) * 86 : 50) + "%";
      man.style.left = (((cell.column + 1) / (cell.rowSize + 1)) * 100) + "%";
      if (src) man.classList.add(src);
      else if (done) man.classList.add("gone");
      if (justPlaced === i) man.classList.add("new");

      var mine = g.bought[i] || {};
      var spent = Object.keys(mine).length;
      if (spent && open) man.classList.add("probed");

      man.appendChild(el("span", "disc", player.pos));
      var label = (src || done) ? player.name
                : (mine.initials ? initialsFor(player.name) : "–");
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
    $("controls").hidden = false;
    $("result").hidden = true;
    show("game");
    paintFixture(lineup);
    paintBoard(game);
    paintTally(game);
    say("");
    $("call-input").value = "";
    startClock();
    claimToken(game);
    $("call-input").focus();
  }

  function startQuick() {
    begin(LINEUPS[Math.floor(Math.random() * LINEUPS.length)], grade,
          "quick:" + Math.random(), "quick");
  }

  /* Days with a chosen puzzle. Everything else falls to the hash, which spreads
     evenly across the archive but has no sense of occasion. */
  var BUILD = "__BUILD__";
  var DAILY_PICKS = __DAILY__;

  function dailyLineup(day) {
    var chosen = DAILY_PICKS[day];
    if (chosen) {
      for (var i = 0; i < LINEUPS.length; i++) {
        if (LINEUPS[i].id === chosen) return LINEUPS[i];
      }
    }
    return LINEUPS[hashSeed(day) % LINEUPS.length];
  }

  function startDaily() {
    var day = today();
    begin(dailyLineup(day), "medium", "daily:" + day, "daily");
  }

  function finish(how) {
    stopClock();
    game.over = how;
    game.result = scoreRound(game.named.length, hidden(game).length === 0,
                             game.secondsLeft, game.penalty, game.grade);
    logResult(game);
    paintBoard(game);           // the finished XI stays on the pitch
    paintTally(game);
    paintResult(game);
    $("controls").hidden = true;
    $("result").hidden = false;
    offerBoard(game);
  }

  function call(event) {
    event.preventDefault();
    if (!game || game.over) return;
    var input = $("call-input");
    var text = input.value.trim();
    if (!text) return;
    input.value = "";

    var res = matchGuess(text, candidates(game, hidden(game)));

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

  /* ==================================================================== clues */

  function boughtFor(slot) { return game.bought[slot] || (game.bought[slot] = {}); }

  /* Which other XIs in the archive a player also starts in. Built once, by name,
     so "elsewhere" is a fact about the data rather than a claim about football. */
  var APPEARANCES = (function () {
    var index = {};
    LINEUPS.forEach(function (lineup, lineupIndex) {
      lineup.players.forEach(function (player) {
        var key = normalize(player.name);
        (index[key] || (index[key] = [])).push(lineupIndex);
      });
    });
    return index;
  })();

  function otherLineups(name, currentId) {
    return (APPEARANCES[normalize(name)] || [])
      .map(function (i) { return LINEUPS[i]; })
      .filter(function (l) { return l.id !== currentId; });
  }

  function describeLineup(l) {
    return (l.opponent ? l.team + " v " + l.opponent : l.team + " (" + l.season + ")") +
           ", " + l.competition;
  }

  // Deterministic shuffle, so a surname always anagrams the same way.
  function anagramOf(word) {
    var letters = word.replace(/[^a-z]/gi, "").toUpperCase().split("");
    if (letters.length < 3) return letters.join(" ");
    var rnd = rngFrom(hashSeed(word));
    for (var attempt = 0; attempt < 8; attempt++) {
      for (var i = letters.length - 1; i > 0; i--) {
        var j = Math.floor(rnd() * (i + 1));
        var tmp = letters[i]; letters[i] = letters[j]; letters[j] = tmp;
      }
      // An "anagram" that comes out as the word itself is no clue at all.
      if (letters.join("") !== word.replace(/[^a-z]/gi, "").toUpperCase()) break;
    }
    return letters.join(" ");
  }

  function nameParts(player) {
    var raw = String(player.name).trim().split(/\s+/);
    return { first: raw.length > 1 ? raw[0] : null, surname: surnameOf(player.name) };
  }

  // Only offer clues that say something: no forename for a single-name player,
  // no "elsewhere" for someone who appears once.
  function cluesFor(slot) {
    var player = game.lineup.players[slot];
    var parts = nameParts(player);
    var elsewhere = otherLineups(player.name, game.lineup.id);
    var facts = factsFor(player.name) || {};
    return CLUES.filter(function (clue) {
      if (clue.key === "first") return !!parts.first;
      if (clue.key === "elsewhere") return elsewhere.length > 0;
      if (clue.key === "nation") return !!facts.nationality;
      if (clue.key === "career") return (facts.career || []).length > 1;
      return true;
    });
  }

  function clueText(slot, key) {
    var player = game.lineup.players[slot];
    var parts = nameParts(player);
    var surname = parts.surname.replace(/[^a-z]/gi, "");

    if (key === "reveal") return player.name;
    if (key === "initials") return initialsFor(player.name);
    if (key === "first") return parts.first;
    if (key === "letter") return surname.charAt(0).toUpperCase();
    if (key === "length") {
      return surname.length + " letters" +
        (parts.first ? ", not counting the forename." : ", and he goes by one name only.");
    }
    if (key === "novowels") return surname.toUpperCase().replace(/[AEIOU]/g, "·");
    if (key === "anagram") return anagramOf(surname);
    if (key === "elsewhere") {
      var others = otherLineups(player.name, game.lineup.id);
      return "He also starts for " + describeLineup(others[0]) +
             (others.length > 1 ? " (and " + (others.length - 1) + " more in this archive)." : ".");
    }
    if (key === "nation") return (factsFor(player.name) || {}).nationality || "";
    if (key === "career") {
      var career = (factsFor(player.name) || {}).career || [];
      // The club he is wearing today would give it away, so it is left out.
      var here = normalize(game.lineup.team);
      return career.filter(function (club) { return normalize(club) !== here; }).join(" → ");
    }
    return "";
  }

  function buyClue(slot, key) {
    if (!game || game.over) return;
    var clue = CLUES.filter(function (c) { return c.key === key; })[0];
    if (!clue || boughtFor(slot)[key]) return;

    boughtFor(slot)[key] = true;
    game.penalty += clue.cost;

    if (key === "reveal") {
      game.told.push(slot);
      say(game.lineup.players[slot].name + " — handed to you.", "note");
      closeDialogs();
      if (hidden(game).length === 0) { finish("won"); return; }
    }
    paintBoard(game);
    paintTally(game);
    if (key !== "reveal") paintClues(slot);
  }

  var clueSlot = null;

  function paintClues(slot) {
    clueSlot = slot;
    var player = game.lineup.players[slot];
    var mine = boughtFor(slot);

    $("clue-title").textContent = "Clue sheet";
    $("clue-sub").textContent = player.pos + " · " +
      (mine.reveal ? player.name : "still hidden");

    var list = $("clue-list");
    list.innerHTML = "";
    var offers = cluesFor(slot);

    offers.forEach(function (clue) {
      var row = el("li", "clue" + (mine[clue.key] ? " got" : ""));
      var head = el("div", "clue-head");
      head.appendChild(el("span", "clue-label", clue.label));

      if (mine[clue.key]) {
        head.appendChild(el("span", "clue-cost spent", "−" + clue.cost));
        row.appendChild(head);
        row.appendChild(el("p", "clue-text", clueText(slot, clue.key)));
      } else {
        var buy = el("button", "clue-buy", "−" + clue.cost);
        buy.type = "button";
        buy.disabled = !!game.over;
        buy.addEventListener("click", function () { buyClue(slot, clue.key); });
        head.appendChild(buy);
        row.appendChild(head);
        row.appendChild(el("p", "clue-blurb", clue.blurb));
      }
      list.appendChild(row);
    });
  }

  function openClues(slot) {
    if (!game || game.over) return;
    if (visible(game).indexOf(slot) !== -1 && !boughtFor(slot).reveal) return;
    paintClues(slot);
    var dlg = $("dlg-clues");
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }

  var OUTCOMES = { won: "All eleven", lost: "Time up", conceded: "Lineup revealed" };

  function paintResult(g) {
    $("outcome").textContent = OUTCOMES[g.over] || "Round over";
    $("final-points").textContent = g.result.total;

    var table = $("ledger");
    table.innerHTML = "";
    [["Named (" + g.result.named + ")", g.result.points],
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
    if (l.score && l.opponent) {
      report.appendChild(el("b", null, l.team + " " + l.score + " " + l.opponent + ". "));
    }
    if (l.blurb) report.appendChild(document.createTextNode(l.blurb + " "));
    if (l.source_url) {
      var a = el("a", null, "Source");
      a.href = l.source_url; a.target = "_blank"; a.rel = "noopener noreferrer";
      report.appendChild(a);
    }
  }

  /* ================================================================= install
     Chrome fires beforeinstallprompt and lets us install in a single tap. Every
     other case - iOS, and the in-app browsers that open when you tap a link
     inside another app - has no such API, so the button explains what to do
     instead of hiding and leaving the player hunting through browser menus. */
  var installPrompt = null;

  function installed() {
    return window.matchMedia("(display-mode: standalone)").matches ||
           window.navigator.standalone === true;
  }

  function installAdvice() {
    var ua = navigator.userAgent;
    var iOS = /iphone|ipad|ipod/i.test(ua);
    // An in-app browser is a webview: Android, but reporting neither Chrome nor Firefox.
    var inApp = /android/i.test(ua) && !/chrome\/|firefox\//i.test(ua);

    if (iOS) {
      return { lead: "On an iPhone or iPad this is done from Safari's share menu.",
               steps: ["Open this page in <b>Safari</b> (it cannot be done from Chrome on iOS).",
                       "Tap the <b>Share</b> button — the square with an arrow.",
                       "Scroll down and tap <b>Add to Home Screen</b>."] };
    }
    if (inApp) {
      return { lead: "You are in the mini browser that opens inside another app. It cannot add icons — Chrome can.",
               steps: ["Tap the <b>⋮</b> at the top of this window.",
                       "Choose <b>Open in Chrome</b>, or open the Chrome app and type the address.",
                       "In Chrome, tap <b>⋮</b> then <b>Add to Home screen</b>."] };
    }
    return { lead: "Your browser did not offer a one-tap install, so add it by hand.",
             steps: ["Open the browser menu — <b>⋮</b> on Android, or the install icon in the address bar on a computer.",
                     "Choose <b>Install</b> or <b>Add to Home screen</b>.",
                     "Confirm. The gold XI icon appears with your other apps."] };
  }

  function showInstallAdvice() {
    var advice = installAdvice();
    $("install-lead").textContent = advice.lead;
    var list = $("install-steps");
    list.innerHTML = "";
    advice.steps.forEach(function (step) {
      var li = document.createElement("li");
      li.innerHTML = step;      // trusted, authored above - never player input
      list.appendChild(li);
    });
    openDialog("install");
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    installPrompt = event;
    $("install").hidden = installed();
  });

  window.addEventListener("appinstalled", function () {
    installPrompt = null;
    $("install").hidden = true;
  });

  $("install").addEventListener("click", function () {
    if (!installPrompt) { showInstallAdvice(); return; }
    installPrompt.prompt();
    installPrompt.userChoice.then(function (choice) {
      if (choice && choice.outcome === "accepted") $("install").hidden = true;
      installPrompt = null;
    });
  });

  // Offer the button to anyone not already running it as an app; the click
  // handler works out whether a real prompt is available.
  if (!installed()) $("install").hidden = false;

  /* =================================================================== wiring */
  function openDialog(name) {
    if (name === "record") paintRecord($("dlg-record-body"));
    var dlg = $("dlg-" + name);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }

  function goHome() { stopClock(); paintHome(); show("home"); }

  $("build-stamp").textContent = "Build " + BUILD;
  $("go-quick").addEventListener("click", startQuick);
  $("go-again").addEventListener("click", startQuick);
  $("go-daily").addEventListener("click", startDaily);
  $("go-home").addEventListener("click", goHome);
  $("home-link").addEventListener("click", goHome);

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
  $("concede").addEventListener("click", function () {
    if (game && !game.over && window.confirm("Concede and see the full XI?")) finish("conceded");
  });

  Array.prototype.slice.call(document.querySelectorAll("[data-dialog]")).forEach(function (b) {
    b.addEventListener("click", function () { openDialog(b.dataset.dialog); });
  });
  Array.prototype.slice.call(document.querySelectorAll("[data-close]")).forEach(function (b) {
    b.addEventListener("click", function () { b.closest("dialog").close(); });
  });
  // Buying the name closes the sheet from inside buyClue.
  function closeDialogs() {
    Array.prototype.slice.call(document.querySelectorAll("dialog")).forEach(function (d) {
      if (d.open && d.close) d.close();
    });
  }
  $("wipe-record").addEventListener("click", function () {
    if (!window.confirm("Wipe your saved record?")) return;
    writeRecord(blankRecord());
    paintRecord($("dlg-record-body"));
    paintRecord($("home-record"));
  });

  paintHome();

  /* Deep link: ?lineup=ucl-1999-final-manutd&difficulty=hard starts that exact XI,
     so a particular puzzle can be handed to someone else. Ids come from
     data/lineups.json. */
  (function deepLink() {
    var params = new URLSearchParams(window.location.search);
    var wantedGrade = params.get("difficulty");
    if (wantedGrade && GRADES[wantedGrade]) {
      grade = wantedGrade;
      document.querySelectorAll("[data-grade]").forEach(function (chip) {
        chip.setAttribute("aria-checked", String(chip.dataset.grade === grade));
      });
      paintTerms();
    }
    var wanted = params.get("lineup");
    if (!wanted) return;
    var lineup = LINEUPS.filter(function (l) { return l.id === wanted; })[0];
    if (lineup) begin(lineup, grade, "link:" + wanted + ":" + Math.random(), "quick");
  })();
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
                {
                    "name": p["name"],
                    "pos": p.get("pos"),
                    "accepts": p.get("accepts", []),
                }
                for p in entry["players"]
            ],
        }
        for entry in dataset["lineups"]
    ]
    # </script> inside a string literal would close the block early.
    payload = json.dumps(lineups, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = SCRIPT.replace("__LINEUPS_DATA__", payload)
    script = script.replace("__PLAYER_FACTS__", player_facts_payload())
    script = script.replace("__LEADERBOARD__", leaderboard_payload())
    script = script.replace("__DAILY__", daily_payload({e["id"] for e in lineups}))
    # Stamped last, over the finished script, so the mark changes whenever anything
    # in the page does - the data, the rules, the leaderboard address, any of it.
    script = script.replace("__BUILD__", hashlib.sha256(script.encode("utf-8")).hexdigest()[:8])

    if fragment:
        # Artifact hosting supplies the doctype/head/body wrapper itself.
        return f"<title>{TITLE}</title>\n{STYLE}\n{MARKUP}\n{script}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="description" content="{BLURB}" />
<meta name="theme-color" content="#0a1f18" />
<!-- Link preview: what WhatsApp, iMessage, Slack and the rest show when the
     address is pasted into a conversation. -->
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Line-Ups" />
<meta property="og:title" content="Line-Ups — the football lineup quiz" />
<meta property="og:description" content="{BLURB}" />
<meta property="og:url" content="{SITE_URL}" />
<meta property="og:image" content="{SITE_URL}og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="Line-Ups — the football lineup quiz" />
<meta name="twitter:description" content="{BLURB}" />
<meta name="twitter:image" content="{SITE_URL}og-image.png" />
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


def daily_payload(lineup_ids: set[str]) -> str:
    """Days whose daily puzzle is chosen by hand rather than left to the hash.

    The hash spreads the daily evenly across the archive, which is right most of the
    time but has no sense of occasion - it will happily open with a 1974 World Cup
    final on a day that wanted a league game. This is the override, and it is checked
    against the archive so a mistyped id fails the build rather than a day.
    """
    if not DAILY.exists():
        return "{}"
    schedule = json.loads(DAILY.read_text(encoding="utf-8")).get("schedule", {})
    for day, lineup_id in schedule.items():
        if lineup_id not in lineup_ids:
            raise SystemExit(f"daily schedule for {day} names an unknown lineup: {lineup_id!r}")
    return json.dumps(schedule, sort_keys=True)


def leaderboard_payload() -> str:
    """Where the leaderboard lives, or null when there isn't one.

    Built in rather than fetched, so a page with no leaderboard makes no network
    calls at all. An empty url yields null and the game plays as it always has -
    which is also what happens on a fresh clone, before anything is deployed.
    """
    if not LEADERBOARD.exists():
        return "null"
    config = json.loads(LEADERBOARD.read_text(encoding="utf-8"))
    url = str(config.get("url") or "").strip()
    if not url:
        return "null"
    if not url.startswith("https://"):
        raise SystemExit(f"leaderboard url must be https, got {url!r}")
    return json.dumps({"url": url.rstrip("/")})


def player_facts_payload() -> str:
    """Nationality and club career per player, keyed by normalised name.

    Keyed on the normalised name rather than the display one so the browser can look a
    player up with the same function it uses to match a guess. Returns an empty object
    when no sweep has been run, which simply removes those two clues from the sheet.
    """
    if not PLAYER_FACTS.exists():
        return "{}"

    sys.path.insert(0, str(REPO_ROOT))
    from backend.app.matching import normalize

    raw = json.loads(PLAYER_FACTS.read_text(encoding="utf-8"))
    facts = {}
    for name, entry in raw.items():
        keep = {}
        if entry.get("nationality"):
            keep["nationality"] = entry["nationality"]
        if entry.get("career"):
            keep["career"] = entry["career"]
        if keep:
            facts[normalize(name)] = keep
    return json.dumps(facts, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build_site(out_dir: Path) -> None:
    """Assemble a static, installable site: the game plus its app manifest and icons."""
    import hashlib
    import shutil

    out_dir.mkdir(parents=True, exist_ok=True)
    page = build()
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    for asset in sorted((REPO_ROOT / "web").iterdir()):
        if asset.is_file():
            shutil.copy2(asset, out_dir / asset.name)

    # Stamp the service worker with a hash of the page. The worker serves from its
    # cache first, so without a new cache name an already-installed copy would keep
    # showing the old game after every update.
    digest = hashlib.sha256(page.encode("utf-8")).hexdigest()[:12]
    worker = out_dir / "sw.js"
    worker.write_text(
        worker.read_text(encoding="utf-8").replace('"lineups-v1"', f'"lineups-{digest}"'),
        encoding="utf-8",
    )
    print(f"Service worker cache: lineups-{digest}")
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
