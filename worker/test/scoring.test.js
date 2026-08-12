// Scoring and token tests. No network, no Cloudflare - these run anywhere.

import assert from "node:assert/strict";
import test from "node:test";

import { BadRound, RULES, cluePenalty, roundHalf, scoreRound } from "../src/scoring.js";
import { BadToken, issue, open } from "../src/session.js";

const SECRET = "a-secret-for-testing";

function round(overrides = {}) {
  return {
    difficulty: "medium",
    guessed: 9,
    secondsLeft: 40,
    completed: true,
    clues: [],
    ...overrides,
  };
}

test("a perfect medium round scores what the game shows", () => {
  // 9 named (2 given free) x 100 x 1.5, plus 250 x 1.5, plus 40s x 5 x 1.5.
  const result = scoreRound(round());
  assert.equal(result.guessPoints, 1350);
  assert.equal(result.completionBonus, 375);
  assert.equal(result.timeBonus, 300);
  assert.equal(result.total, 2025);
});

test("an odd number of seconds rounds up, as the browser does", () => {
  // 7s x 5 x 1.5 = 52.5. Rounding to even would give 52 and disagree with the
  // number the player watched tick up on their own screen.
  assert.equal(roundHalf(52.5), 53);
  assert.equal(scoreRound(round({ secondsLeft: 7 })).timeBonus, 53);
});

test("clues are taken off the total", () => {
  const clean = scoreRound(round());
  const helped = scoreRound(round({ clues: ["reveal", "anagram"] }));
  assert.equal(clean.total - helped.total, 150 + 130);
});

test("an unknown clue is refused rather than counted as free", () => {
  assert.throws(() => cluePenalty(["a-clue-that-does-not-exist"]), BadRound);
});

test("a conceded round keeps its guesses and loses the bonuses", () => {
  const result = scoreRound(round({ completed: false, secondsLeft: 90, guessed: 4 }));
  assert.equal(result.completionBonus, 0);
  assert.equal(result.timeBonus, 0);
  assert.equal(result.total, 600);
});

test("more players than the board holds is refused", () => {
  // Medium gives two away, so nine is the most anyone can earn.
  assert.throws(() => scoreRound(round({ guessed: 10 })), BadRound);
});

test("more time than the clock ever held is refused", () => {
  assert.throws(() => scoreRound(round({ secondsLeft: 181 })), BadRound);
});

test("a completed XI must add up to eleven players", () => {
  assert.throws(() => scoreRound(round({ guessed: 5 })), BadRound);
  // Four named, two free and five handed over by reveals does add up.
  const withReveals = scoreRound(
    round({ guessed: 4, clues: ["reveal", "reveal", "reveal", "reveal", "reveal"] })
  );
  assert.equal(withReveals.guessed, 4);
});

test("an unknown difficulty is refused", () => {
  assert.throws(() => scoreRound(round({ difficulty: "impossible" })), BadRound);
});

test("fractional or missing counts are refused", () => {
  assert.throws(() => scoreRound(round({ guessed: 9.5 })), BadRound);
  assert.throws(() => scoreRound(round({ secondsLeft: null })), BadRound);
});

test("the rules match the ones the game was built with", () => {
  // A guard on the generated file, so a bad regeneration is loud.
  assert.equal(RULES.clueCosts.reveal, 150);
  assert.equal(RULES.clueCosts.anagram, 130);
  assert.equal(RULES.difficulties.medium.seconds, 180);
});

test("a token survives a round trip", async () => {
  const token = await issue(SECRET, { lineup: "utd-1999", difficulty: "medium" });
  const claims = await open(SECRET, token);
  assert.equal(claims.lineup, "utd-1999");
  assert.equal(claims.difficulty, "medium");
});

test("a token signed with another secret is refused", async () => {
  const token = await issue("someone-elses-secret", { lineup: "utd-1999", difficulty: "medium" });
  await assert.rejects(() => open(SECRET, token), BadToken);
});

test("an edited token is refused", async () => {
  const token = await issue(SECRET, { lineup: "utd-1999", difficulty: "easy" });
  const [payload, signature] = token.split(".");
  const forged = Buffer.from(JSON.stringify({ l: "utd-1999", d: "easy", t: Date.now(), n: "x" }))
    .toString("base64url");
  await assert.rejects(() => open(SECRET, `${forged}.${signature}`), BadToken);
  await assert.rejects(() => open(SECRET, `${payload}.notasignature`), BadToken);
});

test("an old token is refused", async () => {
  const token = await issue(SECRET, {
    lineup: "utd-1999",
    difficulty: "medium",
    now: Date.now() - 3 * 60 * 60 * 1000,
  });
  await assert.rejects(() => open(SECRET, token), BadToken);
});

test("a token dated in the future is refused", async () => {
  const token = await issue(SECRET, {
    lineup: "utd-1999",
    difficulty: "medium",
    now: Date.now() + 10 * 60 * 1000,
  });
  await assert.rejects(() => open(SECRET, token), BadToken);
});

test("rubbish in place of a token is refused", async () => {
  await assert.rejects(() => open(SECRET, "not-a-token"), BadToken);
  await assert.rejects(() => open(SECRET, null), BadToken);
});
