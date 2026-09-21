/* ---------------------------------------------------------------------------
   The engine: matching a typed answer, and building a clue sheet from one.

   Split out from app.js because these are the two things worth testing on their
   own. They are pure - no clock, no DOM, no network, no state - so the tests in
   worker/test/quiz-engine.test.js run them directly against every pack in
   data/quizzes and check that every clue exists for every answer.

   Loaded as a plain script before app.js and inlined ahead of it by
   scripts/build_quiz.py. It publishes one global and reads nothing else.
   --------------------------------------------------------------------------- */
var QuickFireEngine = (function () {
  "use strict";

  /* =========================================================== matching ===
     A generous match, because this is a quiz and not a spelling test. The
     rules mirror backend/app/matching.py: fold to plain lowercase ASCII, treat
     apostrophes as joins rather than breaks, then forgive a typo or two on
     anything long enough that a typo is plausible.
  */

  var TRANSLITERATIONS = {
    "ø": "o", "đ": "d", "ð": "d", "ß": "ss", "æ": "ae",
    "œ": "oe", "ł": "l", "þ": "th", "ı": "i"
  };

  function normalize(text) {
    if (!text) return "";
    var lowered = String(text).toLowerCase();
    var folded = "";
    for (var i = 0; i < lowered.length; i += 1) {
      var ch = lowered.charAt(i);
      folded += Object.prototype.hasOwnProperty.call(TRANSLITERATIONS, ch)
        ? TRANSLITERATIONS[ch]
        : ch;
    }
    folded = folded.replace(/['\u2019\u02bc`]/g, "");
    var stripped = folded.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    var kept = stripped.replace(/[^a-z0-9]+/g, " ");
    return kept.trim().replace(/\s+/g, " ");
  }

  /** Drop a leading article, so "the Nile" and "Nile" are the same answer. */
  function withoutArticle(key) {
    return key.replace(/^(the|a|an) /, "");
  }

  /** Every normalised string that counts as this question's answer. */
  function answerKeys(question) {
    var keys = {};
    var add = function (value) {
      var key = normalize(value);
      if (key) {
        keys[key] = true;
        var bare = withoutArticle(key);
        if (bare) keys[bare] = true;
      }
    };
    add(question.answer);
    (question.accept || []).forEach(add);
    return Object.keys(keys);
  }

  function editDistance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    if (a === b) return 0;
    var previous = [];
    for (var j = 0; j <= b.length; j += 1) previous.push(j);
    for (var i = 1; i <= a.length; i += 1) {
      var current = [i];
      var best = i;
      for (var k = 1; k <= b.length; k += 1) {
        var cost = a.charAt(i - 1) === b.charAt(k - 1) ? 0 : 1;
        var value = Math.min(previous[k] + 1, current[k - 1] + 1, previous[k - 1] + cost);
        current.push(value);
        if (value < best) best = value;
      }
      if (best > max) return max + 1;
      previous = current;
    }
    return previous[b.length];
  }

  /** How many characters of a key may be wrong. Short answers must be exact. */
  function typoAllowance(key) {
    var letters = key.replace(/ /g, "").length;
    if (letters >= 12) return 2;
    if (letters >= 6) return 1;
    return 0;
  }

  /**
   * Does this guess answer this question?
   *
   * Exact first, so a curated short alias such as "AWS" works even though it is
   * far too short to risk a fuzzy pass on.
   */
  function answers(guess, question) {
    var needle = normalize(guess);
    if (!needle) return false;
    var keys = answerKeys(question);
    var i;
    for (i = 0; i < keys.length; i += 1) {
      if (needle === keys[i]) return true;
    }
    var bare = withoutArticle(needle);
    for (i = 0; i < keys.length; i += 1) {
      if (bare === keys[i]) return true;
    }
    for (i = 0; i < keys.length; i += 1) {
      var allowance = typoAllowance(keys[i]);
      if (allowance && editDistance(bare, keys[i], allowance) <= allowance) return true;
    }
    return false;
  }

  /* ============================================================== clues ===
     Every clue is computed from the answer itself rather than written out by
     hand - the same bargain the football game strikes. Writing a new pack is
     then a list of questions and answers, and the clue sheet comes free and
     cannot go stale. Only `hint` is authored, and only `hint` is optional.
  */

  /** A small deterministic generator, so an anagram is the same every time. */
  function seededRandom(seed) {
    var state = 0;
    for (var i = 0; i < seed.length; i += 1) {
      state = (state * 31 + seed.charCodeAt(i)) >>> 0;
    }
    return function () {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
  }

  function shuffled(list, seed) {
    var out = list.slice();
    var random = seededRandom(seed);
    for (var i = out.length - 1; i > 0; i -= 1) {
      var j = Math.floor(random() * (i + 1));
      var swap = out[i];
      out[i] = out[j];
      out[j] = swap;
    }
    return out;
  }

  function wordsOf(answer) {
    return String(answer).trim().split(/\s+/).filter(Boolean);
  }

  var NUMBER_WORDS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];

  function spell(count) {
    return count < NUMBER_WORDS.length ? NUMBER_WORDS[count] : String(count);
  }

  function clueLetters(question) {
    var words = wordsOf(question.answer);
    var letters = String(question.answer).replace(/[^A-Za-z0-9]/g, "").length;
    if (words.length === 1) return letters + " letters, one word.";
    return letters + " letters across " + spell(words.length) + " words (" +
      words.map(function (w) { return w.replace(/[^A-Za-z0-9]/g, "").length; }).join(", ") + ").";
  }

  function clueFirst(question) {
    return "Begins with " + String(question.answer).trim().charAt(0).toUpperCase() + ".";
  }

  function clueInitials(question) {
    return wordsOf(question.answer)
      .map(function (word) { return word.charAt(0).toUpperCase() + "."; })
      .join(" ");
  }

  function clueNoVowels(question) {
    return String(question.answer).replace(/[aeiou]/gi, "\u2013");
  }

  function clueAnagram(question) {
    var letters = String(question.answer).toUpperCase().replace(/[^A-Z0-9]/g, "").split("");
    var mixed = shuffled(letters, "anagram:" + question.answer);
    // A shuffle that lands back on the answer would be a free reveal.
    if (mixed.join("") === letters.join("") && letters.length > 1) {
      mixed = mixed.slice(1).concat(mixed[0]);
    }
    return mixed.join(" ");
  }

  /**
   * Four options, one of them right.
   *
   * Authored decoys when the pack supplies them, otherwise the other answers in
   * the same pack. The fallback is weaker - a pack of mixed subjects makes for
   * obviously wrong options - but it means a pack written in a hurry still has
   * a full clue sheet.
   */
  function clueChoices(question, pack) {
    var decoys = (question.decoys || []).slice();
    if (decoys.length < 3) {
      var others = pack.questions
        .filter(function (other) { return other !== question; })
        .map(function (other) { return other.answer; });
      shuffled(others, "decoys:" + question.answer).forEach(function (answer) {
        if (decoys.length < 3 && decoys.indexOf(answer) === -1) decoys.push(answer);
      });
    }
    return shuffled([question.answer].concat(decoys.slice(0, 3)), "choices:" + question.answer);
  }

  /**
   * The clue sheet for one question, dearest last.
   *
   * A clue is left off when it would tell the player nothing new: initials are
   * the first letter again on a one word answer, and an anagram of four letters
   * is barely a disguise.
   */
  function clueSheet(question, pack) {
    var words = wordsOf(question.answer);
    var letters = String(question.answer).replace(/[^A-Za-z0-9]/g, "").length;
    var sheet = [
      { key: "letters", label: "How long is it?", give: clueLetters(question), plain: true },
      { key: "first", label: "The first letter", give: clueFirst(question), plain: true }
    ];
    if (words.length > 1) {
      sheet.push({ key: "initials", label: "The initials", give: clueInitials(question) });
    }
    if (question.hint) {
      sheet.push({ key: "hint", label: "A clue in words", give: question.hint, plain: true });
    }
    sheet.push({ key: "novowels", label: "Vowels removed", give: clueNoVowels(question) });
    if (letters > 4) {
      sheet.push({ key: "anagram", label: "An anagram", give: clueAnagram(question) });
    }
    sheet.push({ key: "choices", label: "Four to choose from", choices: clueChoices(question, pack) });
    sheet.push({ key: "reveal", label: "Just tell me", reveal: true });
    return sheet;
  }

  return {
    normalize: normalize,
    withoutArticle: withoutArticle,
    answerKeys: answerKeys,
    editDistance: editDistance,
    typoAllowance: typoAllowance,
    answers: answers,
    clueSheet: clueSheet,
    clueLetters: clueLetters,
    clueFirst: clueFirst,
    clueInitials: clueInitials,
    clueNoVowels: clueNoVowels,
    clueAnagram: clueAnagram,
    clueChoices: clueChoices
  };
})();

// So the same file can be pulled into a node test without a browser around it.
if (typeof module !== "undefined" && module.exports) module.exports = QuickFireEngine;
