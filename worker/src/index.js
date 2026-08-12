// The leaderboard: a small HTTP service in front of one SQLite table.
//
// Four routes:
//
//   POST /round/start   a round is beginning - hand back a signed token
//   POST /round/finish  a round has ended - recalculate it, store it, return the board
//   GET  /board         the top ten for one lineup, and where this player came
//   GET  /boards        the leader and your own score for many lineups at once
//
// The rule the game is built around - a lineup counts on your first attempt only - is
// a primary key on (lineup, player), so it holds even if something above it is wrong.

import { BadRound, difficultyOf, scoreRound } from "./scoring.js";
import { BadToken, issue, open } from "./session.js";

const BOARD_SIZE = 10;
const MAX_NAME = 24;
const ROUNDS_PER_HOUR = 120;
const TOKEN_SWEEP_MS = 3 * 60 * 60 * 1000;
// One day of dailies each. A year of them still fits comfortably in one query.
const MAX_BOARDS = 400;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }));
    try {
      if (url.pathname === "/round/start" && request.method === "POST") {
        return cors(await startRound(request, env));
      }
      if (url.pathname === "/round/finish" && request.method === "POST") {
        return cors(await finishRound(request, env));
      }
      if (url.pathname === "/board" && request.method === "GET") {
        return cors(await board(url, env));
      }
      if (url.pathname === "/boards" && request.method === "GET") {
        return cors(await boards(url, env));
      }
      if (url.pathname === "/health") return cors(json({ ok: true }));
      return cors(json({ error: "no such route" }, 404));
    } catch (err) {
      if (err instanceof BadRound || err instanceof BadToken) {
        return cors(json({ error: err.message }, 400));
      }
      console.error(err);
      return cors(json({ error: "something went wrong" }, 500));
    }
  },
};

async function startRound(request, env) {
  const body = await readJson(request);
  const lineup = requireText(body.lineup, "lineup", 64);
  const difficulty = requireText(body.difficulty, "difficulty", 16);

  if (!(await underRateLimit(request, env))) {
    return json({ error: "too many rounds from here in the last hour" }, 429);
  }
  return json({ token: await issue(env.SCORE_SECRET, { lineup, difficulty }) });
}

async function finishRound(request, env) {
  const body = await readJson(request);
  const claims = await open(env.SCORE_SECRET, body.token);
  const player = requireText(body.player, "player", 64);
  const name = tidyName(body.name);

  // The clock the player reports has to agree with how long they actually held the
  // token. Without this a round could be started and finished in the same second
  // with a full clock still showing.
  const spent = Math.round(claims.age / 1000);
  const claimedSpend = secondsOf(claims.difficulty) - toInt(body.secondsLeft);
  if (claimedSpend > spent + 5) {
    throw new BadRound("the round ended sooner than it could have been played");
  }

  const result = scoreRound({
    difficulty: claims.difficulty,
    guessed: toInt(body.guessed),
    secondsLeft: toInt(body.secondsLeft),
    completed: body.completed === true,
    clues: body.clues,
  });

  // One token, one score. Replaying a good round under new player ids would
  // otherwise fill the board from a single genuine game.
  const fresh = await env.DB.prepare(
    "INSERT OR IGNORE INTO spent_tokens (nonce, created_at) VALUES (?, ?)"
  )
    .bind(claims.nonce, Date.now())
    .run();
  if (!fresh.meta.changes) throw new BadToken("this round has already been submitted");

  const inserted = await env.DB.prepare(
    `INSERT OR IGNORE INTO scores
       (lineup, player, name, score, guessed, completed, seconds_left, difficulty, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
  )
    .bind(
      claims.lineup,
      player,
      name,
      result.total,
      result.guessed,
      body.completed === true ? 1 : 0,
      toInt(body.secondsLeft),
      claims.difficulty,
      Date.now()
    )
    .run();

  await sweep(env);

  const standings = await standingsFor(env, claims.lineup, player);
  return json({
    ...standings,
    score: result.total,
    breakdown: result,
    // Says plainly why a second run at the same XI did not move the board, rather
    // than looking like the submission failed.
    counted: Boolean(inserted.meta.changes),
    reason: inserted.meta.changes ? null : "only your first attempt at an XI counts",
  });
}

async function board(url, env) {
  const lineup = requireText(url.searchParams.get("lineup"), "lineup", 64);
  const player = url.searchParams.get("player") || null;
  return json(await standingsFor(env, lineup, player));
}

/**
 * Several boards at once, for the list of past daily puzzles.
 *
 * One request rather than one per day: the list grows by a day every day, and a
 * page that fires thirty requests to draw a list is a page that feels broken on a
 * phone. Only the leader and the asking player's own place come back, which is all
 * the list shows - the full board is a tap away and fetched then.
 */
async function boards(url, env) {
  const wanted = (url.searchParams.get("lineups") || "")
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
  if (!wanted.length) throw new BadRound("lineups is required");
  if (wanted.length > MAX_BOARDS) throw new BadRound(`at most ${MAX_BOARDS} boards at a time`);
  const player = url.searchParams.get("player") || null;

  const placeholders = wanted.map(() => "?").join(", ");
  const rows = await env.DB.prepare(
    `SELECT lineup, name, score FROM scores WHERE lineup IN (${placeholders})
       ORDER BY lineup, score DESC, created_at ASC`
  )
    .bind(...wanted)
    .all();

  const counts = new Map();
  const leaders = new Map();
  for (const row of rows.results || []) {
    counts.set(row.lineup, (counts.get(row.lineup) || 0) + 1);
    if (!leaders.has(row.lineup)) leaders.set(row.lineup, { name: row.name, score: row.score });
  }

  const mine = new Map();
  if (player) {
    const own = await env.DB.prepare(
      `SELECT lineup, score FROM scores WHERE player = ? AND lineup IN (${placeholders})`
    )
      .bind(player, ...wanted)
      .all();
    for (const row of own.results || []) mine.set(row.lineup, row.score);
  }

  const out = {};
  for (const lineup of wanted) {
    out[lineup] = {
      players: counts.get(lineup) || 0,
      leader: leaders.get(lineup) || null,
      yourScore: mine.has(lineup) ? mine.get(lineup) : null,
    };
  }
  return json({ boards: out });
}

async function standingsFor(env, lineup, player) {
  const top = await env.DB.prepare(
    `SELECT name, score, guessed, completed, difficulty
       FROM scores WHERE lineup = ?
       ORDER BY score DESC, created_at ASC LIMIT ?`
  )
    .bind(lineup, BOARD_SIZE)
    .all();

  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM scores WHERE lineup = ?")
    .bind(lineup)
    .first();

  let you = null;
  if (player) {
    const mine = await env.DB.prepare(
      "SELECT name, score, guessed, completed FROM scores WHERE lineup = ? AND player = ?"
    )
      .bind(lineup, player)
      .first();
    if (mine) {
      // Rank by how many beat you, so equal scores share a place rather than being
      // ordered by who happened to submit first.
      const ahead = await env.DB.prepare(
        "SELECT COUNT(*) AS n FROM scores WHERE lineup = ? AND score > ?"
      )
        .bind(lineup, mine.score)
        .first();
      you = { ...mine, rank: ahead.n + 1 };
    }
  }

  return { lineup, players: total.n, top: top.results || [], you };
}

async function underRateLimit(request, env) {
  const address = request.headers.get("CF-Connecting-IP") || "unknown";
  const hour = Math.floor(Date.now() / 3_600_000);
  const bucket = await hash(`${address}:${hour}`);
  await env.DB.prepare(
    `INSERT INTO rate (bucket, hits, created_at) VALUES (?, 1, ?)
     ON CONFLICT(bucket) DO UPDATE SET hits = hits + 1`
  )
    .bind(bucket, Date.now())
    .run();
  const row = await env.DB.prepare("SELECT hits FROM rate WHERE bucket = ?").bind(bucket).first();
  return row.hits <= ROUNDS_PER_HOUR;
}

/** Drop spent tokens and rate buckets once they can no longer matter. */
async function sweep(env) {
  const cutoff = Date.now() - TOKEN_SWEEP_MS;
  await env.DB.prepare("DELETE FROM spent_tokens WHERE created_at < ?").bind(cutoff).run();
  await env.DB.prepare("DELETE FROM rate WHERE created_at < ?").bind(cutoff).run();
}

async function hash(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function secondsOf(difficulty) {
  const found = difficultyOf(difficulty);
  if (!found) throw new BadRound(`unknown difficulty: ${difficulty}`);
  return found.seconds;
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new BadRound("expected a JSON body");
  }
}

function requireText(value, field, max) {
  if (typeof value !== "string" || !value.trim()) throw new BadRound(`${field} is required`);
  if (value.length > max) throw new BadRound(`${field} is too long`);
  return value.trim();
}

function toInt(value) {
  if (!Number.isInteger(value)) throw new BadRound("expected whole numbers for the round");
  return value;
}

/** A display name, trimmed and stripped of anything that could break a page. */
function tidyName(value) {
  const raw = typeof value === "string" ? value.trim() : "";
  const cleaned = raw.replace(/[\u0000-\u001f<>]/g, "").trim().slice(0, MAX_NAME);
  return cleaned || "Anonymous";
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function cors(response) {
  const headers = new Headers(response.headers);
  // The game is served from GitHub Pages and can be opened from anywhere, so the
  // board is readable by any origin. There is nothing private behind it.
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET, POST, OPTIONS");
  headers.set("access-control-allow-headers", "content-type");
  headers.set("access-control-max-age", "86400");
  return new Response(response.body, { status: response.status, headers });
}
