// Scoring, kept apart from the request handling so it can be tested on its own.
//
// This is a deliberate re-implementation of backend/app/game.py's score_round. The
// worker never trusts the total the browser sends - it recalculates from what the
// round actually consisted of, which is the only reason a public leaderboard is
// worth reading. The constants come from rules.generated.json rather than being
// typed out again, so the two cannot drift apart unnoticed.

// The import attribute is needed by Node, which runs the tests, and understood by the
// bundler that builds the worker - so one spelling serves both.
import RULES from "./rules.generated.json" with { type: "json" };

export { RULES };

/**
 * Round half up - the same rule the game in the browser uses.
 *
 * Worth stating because it is a real trap: at the medium multiplier a second on the
 * clock is worth 7.5 points, so an odd number of seconds left lands exactly on a
 * half. Python's round() sends those to the nearest even number and JavaScript's
 * sends them up, so the two disagree by a point on about half of all finished
 * rounds. The player sees the browser's number, so the browser's rule wins here and
 * backend/app/game.py was changed to match it rather than the other way round.
 */
export function roundHalf(value) {
  return Math.round(value);
}

export function difficultyOf(key) {
  return RULES.difficulties[String(key || "").toLowerCase()] || null;
}

/** The points a set of bought clues costs. Unknown keys are refused, not ignored. */
export function cluePenalty(clues) {
  let total = 0;
  for (const key of clues) {
    const cost = RULES.clueCosts[key];
    if (cost === undefined) throw new BadRound(`unknown clue: ${key}`);
    total += cost;
  }
  return total;
}

export class BadRound extends Error {}

/**
 * Score one finished round, rejecting anything that could not have happened.
 *
 * The checks are the point. A round claiming twelve players guessed, or more seconds
 * left than the clock ever held, did not come from the game.
 */
export function scoreRound(round) {
  const difficulty = difficultyOf(round.difficulty);
  if (!difficulty) throw new BadRound(`unknown difficulty: ${round.difficulty}`);

  const guessed = asInteger(round.guessed, "guessed");
  const secondsLeft = asInteger(round.secondsLeft, "secondsLeft");
  const completed = round.completed === true;
  const clues = Array.isArray(round.clues) ? round.clues : [];

  // Eleven slots, of which the freebies were never the player's to earn.
  const earnable = 11 - difficulty.freebies;
  if (guessed < 0 || guessed > earnable) {
    throw new BadRound(`guessed ${guessed}, but only ${earnable} were there to guess`);
  }
  if (secondsLeft < 0 || secondsLeft > difficulty.seconds) {
    throw new BadRound(`${secondsLeft}s left of a ${difficulty.seconds}s clock`);
  }
  if (completed && guessed + difficulty.freebies + countReveals(clues) < 11) {
    throw new BadRound("claimed a completed XI without eleven players accounted for");
  }
  // An unfinished round may well have time left: the game lets a player concede and
  // see the XI. That earns guess points and no bonuses, which is already the answer.
  if (clues.length > 11 * Object.keys(RULES.clueCosts).length) {
    throw new BadRound("more clues bought than exist");
  }

  const multiplier = difficulty.multiplier;
  const guessPoints = roundHalf(guessed * RULES.pointsPerPlayer * multiplier);
  const completionBonus = completed ? roundHalf(RULES.completionBonus * multiplier) : 0;
  const timeBonus = completed
    ? roundHalf(secondsLeft * RULES.pointsPerSecondRemaining * multiplier)
    : 0;
  const huntPenalty = cluePenalty(clues);
  const total = Math.max(0, guessPoints + completionBonus + timeBonus - huntPenalty);

  return { guessed, guessPoints, completionBonus, timeBonus, huntPenalty, total };
}

function countReveals(clues) {
  return clues.filter((key) => key === "reveal").length;
}

function asInteger(value, field) {
  if (!Number.isInteger(value)) throw new BadRound(`${field} must be a whole number`);
  return value;
}
