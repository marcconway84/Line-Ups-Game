// The browser half of Quick Fire: matching a typed answer, and the clue sheet.
//
// These run against quiz/engine.js directly and against every pack in data/quizzes,
// which is the point - a clue that cannot be built, or an answer its own alias does
// not match, is a question that breaks in someone's ten minutes rather than here.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const engine = require("../../quiz/engine.js");

const PACK_DIR = new URL("../../data/quizzes/", import.meta.url);
const PACKS = readdirSync(PACK_DIR)
  .filter((name) => name.endsWith(".json"))
  .map((name) => JSON.parse(readFileSync(new URL(name, PACK_DIR), "utf8")));

const EVERY_QUESTION = PACKS.flatMap((pack) =>
  pack.questions.map((question) => ({ pack, question }))
);

test("there are packs to test", () => {
  assert.ok(PACKS.length >= 1);
  assert.ok(EVERY_QUESTION.length >= 12);
});

/* ------------------------------------------------------------------ matching -- */

test("every answer in every pack is matched by typing it out", () => {
  for (const { question } of EVERY_QUESTION) {
    assert.ok(engine.answers(question.answer, question), `${question.answer} does not match itself`);
  }
});

test("every curated alias matches the question it was written for", () => {
  for (const { question } of EVERY_QUESTION) {
    for (const alias of question.accept || []) {
      assert.ok(engine.answers(alias, question), `${alias} does not match ${question.answer}`);
    }
  }
});

test("no answer is matched by another question's answer in the same pack", () => {
  // Two questions one guess can satisfy would light up the wrong tile, and the
  // generous matching makes that easier to do by accident than it sounds.
  for (const pack of PACKS) {
    for (const question of pack.questions) {
      for (const other of pack.questions) {
        if (other === question) continue;
        assert.equal(
          engine.answers(other.answer, question),
          false,
          `in ${pack.id}, "${other.answer}" also answers "${question.prompt}"`
        );
      }
    }
  }
});

test("no decoy is accepted as the answer it was written to sit beside", () => {
  // A four-option clue offering two right answers would be worse than no clue.
  for (const { question } of EVERY_QUESTION) {
    for (const decoy of question.decoys || []) {
      assert.equal(
        engine.answers(decoy, question),
        false,
        `"${decoy}" is accepted as "${question.answer}"`
      );
    }
  }
});

test("case, accents, punctuation and a leading 'the' are all forgiven", () => {
  const question = { answer: "Leonardo da Vinci", accept: ["da Vinci"] };
  for (const guess of ["leonardo da vinci", "LEONARDO DA VINCI", "Leonardo  da  Vinci", "da vinci"]) {
    assert.ok(engine.answers(guess, question), guess);
  }
  assert.ok(engine.answers("Pique", { answer: "Piqué" }), "an accent left off");
  assert.ok(engine.answers("etoo", { answer: "Eto'o" }), "an apostrophe left out");
  assert.ok(engine.answers("the Nile", { answer: "Nile" }), "an article added");
  assert.ok(engine.answers("Nile", { answer: "The Nile" }), "an article left off");
});

test("a small typo in a long answer is forgiven, in a short one it is not", () => {
  assert.ok(engine.answers("canbera", { answer: "Canberra" }), "one letter short of eight");
  assert.ok(engine.answers("millenium falcon", { answer: "Millennium Falcon" }), "the usual misspelling");
  // Four letters with one wrong is a different word as often as it is a typo.
  assert.equal(engine.answers("role", { answer: "Rome" }), false);
  assert.equal(engine.answers("nile", { answer: "Nice" }), false);
});

test("a wrong answer is a wrong answer", () => {
  const question = { answer: "Canberra", accept: [] };
  for (const guess of ["Sydney", "Melbourne", "", "   ", "x"]) {
    assert.equal(engine.answers(guess, question), false, JSON.stringify(guess));
  }
});

/* --------------------------------------------------------------- clue sheets -- */

test("every question in every pack builds a full clue sheet", () => {
  for (const { pack, question } of EVERY_QUESTION) {
    const sheet = engine.clueSheet(question, pack);
    const keys = sheet.map((clue) => clue.key);

    assert.ok(keys.includes("letters"), `${question.answer}: no length clue`);
    assert.ok(keys.includes("first"), `${question.answer}: no first letter`);
    assert.ok(keys.includes("novowels"), `${question.answer}: no vowel clue`);
    assert.ok(keys.includes("choices"), `${question.answer}: no multiple choice`);
    assert.ok(keys.includes("reveal"), `${question.answer}: no way out`);
    assert.equal(new Set(keys).size, keys.length, `${question.answer}: a clue offered twice`);

    for (const clue of sheet) {
      if (clue.reveal) continue;
      const given = clue.choices || clue.give;
      assert.ok(given && String(given).trim(), `${question.answer}: ${clue.key} came back empty`);
    }
  }
});

test("a clue that would say nothing is not offered", () => {
  // Initials on a single word are the first letter again, at thirty points more.
  const oneWord = { answer: "Canberra" };
  const keys = engine.clueSheet(oneWord, { questions: [oneWord] }).map((c) => c.key);
  assert.equal(keys.includes("initials"), false);

  const twoWords = { answer: "Blue whale" };
  assert.ok(engine.clueSheet(twoWords, { questions: [twoWords] }).map((c) => c.key).includes("initials"));

  // No written hint means no hint to sell.
  assert.equal(keys.includes("hint"), false);
  const hinted = { answer: "Canberra", hint: "Not the biggest city." };
  assert.ok(engine.clueSheet(hinted, { questions: [hinted] }).map((c) => c.key).includes("hint"));
});

test("no clue hands over the answer it is a clue to", () => {
  for (const { question } of EVERY_QUESTION) {
    const plain = question.answer.toUpperCase().replace(/[^A-Z0-9]/g, "");
    assert.notEqual(
      engine.clueAnagram(question).replace(/ /g, ""),
      plain,
      `${question.answer}: the anagram is the answer`
    );
    assert.ok(
      engine.clueNoVowels(question).includes("–") || !/[aeiou]/i.test(question.answer),
      `${question.answer}: nothing was blanked out`
    );
  }
});

test("an anagram is the same one every time", () => {
  // It is recomputed on every render, so a fresh shuffle each time would look like
  // the game changing its mind while the player stared at it.
  const question = { answer: "Millennium Falcon" };
  assert.equal(engine.clueAnagram(question), engine.clueAnagram(question));
});

test("four options include the answer and no duplicates", () => {
  for (const { pack, question } of EVERY_QUESTION) {
    const choices = engine.clueChoices(question, pack);
    assert.equal(choices.length, 4, `${question.answer}: ${choices.length} options`);
    assert.ok(choices.includes(question.answer), `${question.answer} is not among its own options`);
    assert.equal(new Set(choices).size, 4, `${question.answer}: an option appears twice`);
  }
});

test("a pack with no decoys still gets four options, from its own answers", () => {
  const pack = {
    questions: [{ answer: "Alpha" }, { answer: "Bravo" }, { answer: "Charlie" }, { answer: "Delta" }],
  };
  const choices = engine.clueChoices(pack.questions[0], pack);
  assert.equal(choices.length, 4);
  assert.ok(choices.includes("Alpha"));
});

test("the length clue counts letters, not spaces or punctuation", () => {
  assert.match(engine.clueLetters({ answer: "Canberra" }), /^8 letters, one word\.$/);
  assert.match(engine.clueLetters({ answer: "Blue whale" }), /^9 letters across two words \(4, 5\)\.$/);
  assert.equal(engine.clueInitials({ answer: "Central Processing Unit" }), "C. P. U.");
  assert.equal(engine.clueFirst({ answer: "jpeg" }), "Begins with J.");
});
