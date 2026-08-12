// End-to-end tests against a real worker with a real database.
//
// The unit tests cover the arithmetic; these cover the things only a database can
// tell you - that the first-attempt rule actually holds, that a token cannot be
// spent twice, that the board comes back in the right order. They start the worker
// with `wrangler dev --local`, which runs the same runtime Cloudflare does, offline.
//
//     npm run test:service
//
// Skipped automatically when the worker cannot be started, so `npm test` stays
// runnable anywhere.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { after, before, describe, test } from "node:test";

const PORT = 8788;
const BASE = `http://127.0.0.1:${PORT}`;
const ROOT = new URL("..", import.meta.url).pathname;

let worker = null;

async function waitForHealth(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${BASE}/health`);
      if (response.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function post(path, body) {
  const response = await fetch(BASE + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: await response.json() };
}

async function startRound(lineup, difficulty = "medium") {
  const { body } = await post("/round/start", { lineup, difficulty });
  return body.token;
}

/** A finished round. Worth 3075: 9 x 100 x 1.5, plus 250 x 1.5, plus 180 x 5 x 1.5. */
const PERFECT = 3075;

/**
 * Play a round through the service.
 *
 * The clock always comes back full. That is not laziness - the worker refuses a round
 * that claims to have taken longer than the token has existed, so a test that ran in
 * milliseconds cannot claim to have spent three minutes. Weaker scores are made by
 * guessing fewer players and conceding, not by burning time.
 */
async function finish(lineup, player, name, overrides = {}) {
  const token = await startRound(lineup, overrides.difficulty || "medium");
  return post("/round/finish", {
    token,
    player,
    name,
    guessed: 9,
    secondsLeft: 180,
    completed: true,
    clues: [],
    ...overrides,
  });
}

/** A conceded round: some players named, nothing else earned. */
function conceded(guessed) {
  return { guessed, completed: false, secondsLeft: 180 };
}

describe("the leaderboard service", { concurrency: false }, () => {
  before(async () => {
    rmSync(`${ROOT}.wrangler/state/v3/d1`, { recursive: true, force: true });
    const setup = spawn(
      `${ROOT}node_modules/.bin/wrangler`,
      ["d1", "execute", "lineups-scores", "--local", "--file=schema.sql"],
      { cwd: ROOT, stdio: "ignore" }
    );
    await new Promise((resolve) => setup.on("exit", resolve));

    worker = spawn(
      `${ROOT}node_modules/.bin/wrangler`,
      // The signing secret is passed in rather than read from .dev.vars, so the tests
      // need no local setup and run the same way on a fresh checkout and in CI.
      [
        "dev",
        "--local",
        "--port",
        String(PORT),
        "--ip",
        "127.0.0.1",
        "--var",
        "SCORE_SECRET:a-secret-for-testing",
      ],
      { cwd: ROOT, stdio: "ignore", env: { ...process.env, CI: "1" } }
    );
    if (!(await waitForHealth())) {
      worker.kill("SIGTERM");
      worker = null;
      throw new Error("wrangler dev did not come up - is it installed?");
    }
  });

  after(() => {
    if (worker) worker.kill("SIGTERM");
  });

  test("a finished round comes back with a score and a place", async () => {
    const { status, body } = await finish("utd-1999", "player-a", "Marc");
    assert.equal(status, 200);
    assert.equal(body.counted, true);
    assert.equal(body.score, PERFECT);
    assert.equal(body.you.rank, 1);
    assert.equal(body.players, 1);
  });

  test("only the first attempt at an XI counts", async () => {
    await finish("first-only", "player-b", "Marc", conceded(4));
    const second = await finish("first-only", "player-b", "Marc");

    assert.equal(second.body.counted, false);
    assert.match(second.body.reason, /first attempt/);
    // The board still shows the weaker first attempt, which is the point of the rule.
    assert.equal(second.body.you.score, 600);
    assert.equal(second.body.players, 1);
  });

  test("the board is ordered by score, best first", async () => {
    await finish("ordering", "p1", "Low", conceded(3));
    await finish("ordering", "p2", "High");
    await finish("ordering", "p3", "Middle", conceded(6));

    const response = await fetch(`${BASE}/board?lineup=ordering&player=p3`);
    const body = await response.json();
    assert.deepEqual(
      body.top.map((row) => row.name),
      ["High", "Middle", "Low"]
    );
    assert.equal(body.you.rank, 2);
    assert.equal(body.players, 3);
  });

  test("equal scores share a place rather than being split by who was quicker", async () => {
    await finish("ties", "t1", "First");
    await finish("ties", "t2", "Second");
    const response = await fetch(`${BASE}/board?lineup=ties&player=t2`);
    const body = await response.json();
    assert.equal(body.you.rank, 1);
  });

  test("a token cannot be spent twice", async () => {
    const token = await startRound("replay");
    const payload = {
      token,
      player: "r1",
      name: "Replay",
      guessed: 9,
      secondsLeft: 180,
      completed: true,
      clues: [],
    };
    const first = await post("/round/finish", payload);
    assert.equal(first.status, 200);

    // Same round, new identity - the shape a faked board would take.
    const again = await post("/round/finish", { ...payload, player: "r2" });
    assert.equal(again.status, 400);
    assert.match(again.body.error, /already been submitted/);
  });

  test("a made-up score is recalculated, not believed", async () => {
    const token = await startRound("honest");
    const { status, body } = await post("/round/finish", {
      token,
      player: "cheat",
      name: "Cheat",
      guessed: 9,
      secondsLeft: 180,
      completed: true,
      clues: [],
      score: 9_999_999, // ignored - the worker works it out itself
      total: 9_999_999,
    });
    assert.equal(status, 200);
    assert.equal(body.score, PERFECT);
  });

  test("a forged token is refused", async () => {
    const { status, body } = await post("/round/finish", {
      token: "bWFkZS11cA.bm90LWEtc2lnbmF0dXJl",
      player: "forger",
      name: "Forger",
      guessed: 9,
      secondsLeft: 180,
      completed: true,
      clues: [],
    });
    assert.equal(status, 400);
    assert.match(body.error, /does not check out/);
  });

  test("a round cannot finish faster than it could have been played", async () => {
    const token = await startRound("too-quick");
    // Claims to have used 175 of the 180 seconds, a moment after starting.
    const { status, body } = await post("/round/finish", {
      token,
      player: "quick",
      name: "Quick",
      guessed: 9,
      secondsLeft: 5,
      completed: true,
      clues: [],
    });
    assert.equal(status, 400);
    assert.match(body.error, /sooner than it could have been played/);
  });

  test("an impossible round is refused", async () => {
    const token = await startRound("impossible");
    const { status, body } = await post("/round/finish", {
      token,
      player: "x",
      name: "X",
      guessed: 11, // medium hands two over, so nine is the ceiling
      secondsLeft: 180,
      completed: true,
      clues: [],
    });
    assert.equal(status, 400);
    assert.match(body.error, /only 9 were there to guess/);
  });

  test("an empty board is an empty board, not an error", async () => {
    const response = await fetch(`${BASE}/board?lineup=nobody-has-played-this`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.deepEqual(body.top, []);
    assert.equal(body.players, 0);
    assert.equal(body.you, null);
  });

  test("a name with angle brackets cannot smuggle markup onto the board", async () => {
    await finish("markup", "m1", "<script>alert(1)</script>Marc");
    const response = await fetch(`${BASE}/board?lineup=markup`);
    const body = await response.json();
    assert.equal(body.top[0].name.includes("<"), false);
    assert.equal(body.top[0].name.includes(">"), false);
  });

  test("a blank name becomes Anonymous rather than an empty row", async () => {
    await finish("blank-name", "b1", "   ");
    const response = await fetch(`${BASE}/board?lineup=blank-name`);
    const body = await response.json();
    assert.equal(body.top[0].name, "Anonymous");
  });

  test("the board is readable from the page, wherever it is served from", async () => {
    const response = await fetch(`${BASE}/board?lineup=utd-1999`);
    assert.equal(response.headers.get("access-control-allow-origin"), "*");
  });
});
