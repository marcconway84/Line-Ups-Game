// Scoring for Quick Fire, kept apart from request handling so it can be tested alone.
//
// Same bargain as scoring.js: the worker never believes the total the browser sends,
// it recalculates the round from what the round consisted of. A leaderboard that
// takes a number on trust is a leaderboard of whoever last opened the console.
//
// The constants come from quiz-rules.generated.json, copied there from
// data/quiz_rules.json by scripts/generate_worker_rules.py, so the price the player
// was charged on screen and the price the board charges cannot part company.

import RULES from "./quiz-rules.generated.json" with { type: "json" };

export { RULES };

export class BadQuiz extends Error {}

/** How many questions this pack has, or null if the worker has never heard of it. */
export function packSize(id) {
  const size = RULES.packs[String(id || "")];
  return Number.isInteger(size) ? size : null;
}

/** The points a set of bought clues costs. An unknown key is refused, not ignored. */
export function cluePenalty(clues) {
  let total = 0;
  for (const key of clues) {
    const cost = RULES.clueCosts[key];
    if (cost === undefined) throw new BadQuiz(`unknown clue: ${key}`);
    total += cost;
  }
  return total;
}

/**
 * Score one finished round, refusing anything that could not have been played.
 *
 * The refusals are the point. Thirteen right out of twelve, a clock with more left
 * on it than it ever held, or a clue the game does not sell - none of those came
 * from someone playing the game.
 */
export function scoreQuiz(round) {
  const questions = packSize(round.pack);
  if (questions === null) throw new BadQuiz(`unknown pack: ${round.pack}`);

  const right = asInteger(round.right, "right");
  const secondsLeft = asInteger(round.secondsLeft, "secondsLeft");
  const clues = Array.isArray(round.clues) ? round.clues : [];

  if (right < 0 || right > questions) {
    throw new BadQuiz(`${right} right out of a pack of ${questions}`);
  }
  if (secondsLeft < 0 || secondsLeft > RULES.secondsOnTheClock) {
    throw new BadQuiz(`${secondsLeft}s left of a ${RULES.secondsOnTheClock}s clock`);
  }
  // Eight kinds of clue, one question each. Anything past that is not a clue sheet.
  if (clues.length > questions * Object.keys(RULES.clueCosts).length) {
    throw new BadQuiz("more clues bought than the pack has to sell");
  }
  if (round.questions !== undefined && asInteger(round.questions, "questions") !== questions) {
    throw new BadQuiz("that pack does not have that many questions");
  }

  // Every bonus wants a clean sheet. A revealed answer is never counted right, so
  // this is also what stops "reveal the lot" buying the finisher bonus.
  const perfect = right === questions;
  const base = right * RULES.pointsPerQuestion;
  const spent = cluePenalty(clues);
  const finisher = perfect ? RULES.finisherBonus : 0;
  const timeBonus = perfect ? secondsLeft * RULES.pointsPerSecondRemaining : 0;
  const cleanSweep = perfect && clues.length === 0 ? RULES.cleanSweepBonus : 0;
  const total = Math.max(0, base - spent + finisher + timeBonus + cleanSweep);

  return { right, questions, base, spent, finisher, timeBonus, cleanSweep, total };
}

function asInteger(value, field) {
  if (!Number.isInteger(value)) throw new BadQuiz(`${field} must be a whole number`);
  return value;
}
