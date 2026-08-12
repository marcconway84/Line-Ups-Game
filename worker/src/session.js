// Signed round tokens.
//
// Without these, posting a perfect score is one command away: the finish endpoint
// would happily accept any well-formed round. A token is handed out when a round
// starts and must come back with the result, which means a faked score has to at
// least ask for a round first and then wait out the clock - it stops the trivial
// attack rather than every attack, and it costs one small table and no accounts.

const encoder = new TextEncoder();

export class BadToken extends Error {}

function b64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(text) {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

async function key(secret) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
}

async function sign(secret, payload) {
  const signature = await crypto.subtle.sign("HMAC", await key(secret), encoder.encode(payload));
  return b64url(new Uint8Array(signature));
}

/** A token binding one round to one lineup, difficulty and moment in time. */
export async function issue(secret, { lineup, difficulty, now = Date.now() }) {
  const nonce = b64url(crypto.getRandomValues(new Uint8Array(12)));
  const payload = b64url(
    encoder.encode(JSON.stringify({ l: lineup, d: difficulty, t: now, n: nonce }))
  );
  return `${payload}.${await sign(secret, payload)}`;
}

/**
 * Check a token and return what it was issued for.
 *
 * Comparison is constant-time-ish by construction: the signature is recomputed and
 * compared whole, and nothing about the payload is trusted until it matches.
 */
export async function open(secret, token, { now = Date.now(), maxAgeMs = 2 * 60 * 60 * 1000 } = {}) {
  if (typeof token !== "string" || !token.includes(".")) throw new BadToken("missing token");
  const [payload, signature] = token.split(".", 2);
  const expected = await sign(secret, payload);
  if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) {
    throw new BadToken("token does not check out");
  }
  let claims;
  try {
    claims = JSON.parse(new TextDecoder().decode(unb64url(payload)));
  } catch {
    throw new BadToken("token is not readable");
  }
  const age = now - claims.t;
  // A token from the future is a clock problem or a forgery attempt; either way it
  // cannot be scored honestly.
  if (age < -60_000) throw new BadToken("token is dated in the future");
  if (age > maxAgeMs) throw new BadToken("token has expired");
  return { lineup: claims.l, difficulty: claims.d, issuedAt: claims.t, nonce: claims.n, age };
}

function timingSafeEqual(a, b) {
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
