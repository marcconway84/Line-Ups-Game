/* ---------------------------------------------------------------------------
   Quick Fire - a twelve question quiz on a ten minute clock, where clues cost
   points.

   The whole game runs in the browser. There is no server to ask, which is the
   point: a team can play it from a static page with nothing deployed. The
   leaderboard is the one exception, and it is optional - with no address built
   in, the game plays exactly the same and makes no network calls at all.

   Answers are in the page source. That is unavoidable in an offline game and
   is not worth pretending otherwise: this is an ice breaker, and the person
   who reads the source to win has already lost. The leaderboard does refuse to
   believe a score it was simply handed, so the board itself stays honest about
   what a round could have been worth.

   Sections below, in order: the data, matching, clues, the round, rendering,
   the leaderboard, and boot.
   --------------------------------------------------------------------------- */
(function () {
  "use strict";

  // Filled in by scripts/build_quiz.py.
  var PACKS = __PACKS__;
  var RULES = __RULES__;
  var LEADERBOARD = __LEADERBOARD__;

  var STORE_PLAYER = "quickfire.player";
  var STORE_NAME = "quickfire.name";
  var STORE_ROUND = "quickfire.round";

  /* =========================================================== engine ===
     Matching and the clue sheet live in quiz/engine.js, which the build inlines
     just above this. Pulled into locals here so the rest of the file reads as it
     did when they were defined in it.
  */

  var normalize = QuickFireEngine.normalize;
  var answers = QuickFireEngine.answers;
  // The engine builds the sheet; the price list is the game's, so it is put on here.
  var clueSheet = function (question, pack) {
    return QuickFireEngine.clueSheet(question, pack).map(function (clue) {
      clue.cost = RULES.clueCosts[clue.key];
      return clue;
    });
  };

  /* ============================================================ the round ===
     State is one object, saved to localStorage on every change. The clock is a
     deadline rather than a countdown, so closing the tab does not pause it and
     a refresh mid-round picks up where it left off - which matters when the
     whole idea is that people play whenever they get a spare ten minutes.
  */

  var state = null;
  var ticker = null;

  function newRound(pack, token) {
    return {
      pack: pack.id,
      token: token || null,
      endsAt: Date.now() + RULES.secondsOnTheClock * 1000,
      current: 0,
      questions: pack.questions.map(function () {
        return { status: "open", clues: [], typed: "" };
      })
    };
  }

  function packOf(id) {
    for (var i = 0; i < PACKS.length; i += 1) {
      if (PACKS[i].id === id) return PACKS[i];
    }
    return null;
  }

  function secondsLeft() {
    return Math.max(0, Math.ceil((state.endsAt - Date.now()) / 1000));
  }

  function cluesBought() {
    var all = [];
    state.questions.forEach(function (entry) {
      entry.clues.forEach(function (key) { all.push(key); });
    });
    return all;
  }

  /**
   * What the round is worth.
   *
   * The bonuses all want a clean sheet - every question right, which rules out
   * reveals because a revealed question is never marked right. That is what
   * lets reveal be free without turning "reveal the lot" into a way of
   * collecting the finisher bonus.
   */
  function tally(finalSeconds) {
    var right = 0;
    state.questions.forEach(function (entry) {
      if (entry.status === "right") right += 1;
    });
    var clues = cluesBought();
    var spent = clues.reduce(function (sum, key) { return sum + (RULES.clueCosts[key] || 0); }, 0);
    var perfect = right === state.questions.length;
    var left = typeof finalSeconds === "number" ? finalSeconds : secondsLeft();
    return {
      right: right,
      of: state.questions.length,
      base: right * RULES.pointsPerQuestion,
      spent: spent,
      clues: clues,
      secondsLeft: left,
      finisher: perfect ? RULES.finisherBonus : 0,
      timeBonus: perfect ? left * RULES.pointsPerSecondRemaining : 0,
      cleanSweep: perfect && clues.length === 0 ? RULES.cleanSweepBonus : 0,
      get running() { return Math.max(0, this.base - this.spent); },
      get total() {
        return Math.max(0, this.base - this.spent + this.finisher + this.timeBonus + this.cleanSweep);
      }
    };
  }

  function save() {
    try {
      window.localStorage.setItem(STORE_ROUND, JSON.stringify(state));
    } catch (err) { /* private browsing; the round simply will not survive a refresh */ }
  }

  function clearSaved() {
    try { window.localStorage.removeItem(STORE_ROUND); } catch (err) { /* nothing to clear */ }
  }

  function remembered(key, fallback) {
    try { return window.localStorage.getItem(key) || fallback; } catch (err) { return fallback; }
  }

  function remember(key, value) {
    try { window.localStorage.setItem(key, value); } catch (err) { /* not essential */ }
  }

  function playerId() {
    var id = remembered(STORE_PLAYER, "");
    if (!id) {
      id = "p-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      remember(STORE_PLAYER, id);
    }
    return id;
  }

  /* ========================================================== rendering === */

  var $ = function (id) { return document.getElementById(id); };

  function show(screen) {
    ["screen-home", "screen-round", "screen-result"].forEach(function (id) {
      $(id).hidden = id !== screen;
    });
    $("scoreboard").hidden = screen !== "screen-round";
    $("quit-link").hidden = screen !== "screen-round";
    window.scrollTo(0, 0);
  }

  function renderPacks(boards) {
    var list = $("pack-list");
    list.innerHTML = "";
    PACKS.forEach(function (pack) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "pack";

      var subject = document.createElement("span");
      subject.className = "subject";
      subject.textContent = pack.subject;

      var title = document.createElement("h2");
      title.textContent = pack.title;

      var blurb = document.createElement("p");
      blurb.textContent = pack.blurb;

      var meta = document.createElement("p");
      meta.className = "packmeta";
      var count = document.createElement("span");
      count.textContent = pack.questions.length + " questions";
      meta.appendChild(count);

      var board = boards && boards[pack.id];
      if (board && board.leader) {
        var leader = document.createElement("span");
        leader.textContent = "Leader: " + board.leader.name + " (" + board.leader.score + ")";
        meta.appendChild(leader);
      }
      if (board && board.yourScore !== null && board.yourScore !== undefined) {
        var mine = document.createElement("span");
        mine.className = "played";
        mine.textContent = "You scored " + board.yourScore;
        meta.appendChild(mine);
      }

      button.appendChild(subject);
      button.appendChild(title);
      button.appendChild(blurb);
      button.appendChild(meta);
      button.addEventListener("click", function () { begin(pack); });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function renderClock() {
    var left = secondsLeft();
    var minutes = Math.floor(left / 60);
    var seconds = left % 60;
    $("clock").textContent = minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
    $("gauge-clock").classList.toggle("urgent", left <= 60);
  }

  function renderGauges() {
    var scores = tally();
    $("score").textContent = scores.running;
    $("tally").textContent = scores.right + "/" + scores.of;
  }

  function renderProgress() {
    var progress = $("progress");
    progress.innerHTML = "";
    progress.style.gridTemplateColumns = "repeat(" + state.questions.length + ", 1fr)";
    state.questions.forEach(function (entry, index) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = String(index + 1);
      if (entry.status === "right") button.className = "is-right";
      else if (entry.status === "shown") button.className = "is-shown";
      else if (entry.clues.length) button.className = "is-hinted";
      if (index === state.current) button.className += " is-current";
      button.setAttribute("aria-label", "Question " + (index + 1) + ", " + entry.status);
      button.addEventListener("click", function () { goTo(index); });
      item.appendChild(button);
      progress.appendChild(item);
    });
  }

  function renderClues(pack, question, entry) {
    var list = $("clue-list");
    list.innerHTML = "";
    var resolved = entry.status !== "open";

    clueSheet(question, pack).forEach(function (clue) {
      var bought = entry.clues.indexOf(clue.key) !== -1;
      // A revealed answer is already on screen; leaving the button there would
      // only invite a second click that does nothing.
      if (clue.reveal && resolved) return;

      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "clue" + (bought ? " bought" : "");
      button.disabled = bought || resolved;

      var body = document.createElement("span");
      body.className = "cluename";

      var label = document.createElement("span");
      label.textContent = clue.label;
      body.appendChild(label);

      if (bought) {
        if (clue.choices) {
          var options = document.createElement("ul");
          options.className = "choicelist";
          clue.choices.forEach(function (option) {
            var li = document.createElement("li");
            li.textContent = option;
            options.appendChild(li);
          });
          body.appendChild(options);
        } else {
          var given = document.createElement("span");
          given.className = "given" + (clue.plain ? " plain" : "");
          given.textContent = clue.give;
          body.appendChild(given);
        }
      }

      var cost = document.createElement("span");
      cost.className = "cost";
      if (bought) cost.textContent = clue.cost ? "−" + clue.cost : "paid";
      else if (clue.reveal) cost.textContent = "free, scores 0";
      else cost.textContent = "−" + clue.cost;

      button.appendChild(body);
      button.appendChild(cost);
      button.addEventListener("click", function () { buy(clue); });
      item.appendChild(button);
      list.appendChild(item);
    });
  }

  function renderQuestion() {
    var pack = packOf(state.pack);
    var index = state.current;
    var question = pack.questions[index];
    var entry = state.questions[index];

    $("q-index").textContent = "Question " + (index + 1) + " of " + pack.questions.length;
    var spent = entry.clues.reduce(function (sum, key) { return sum + RULES.clueCosts[key]; }, 0);
    $("q-worth").textContent = spent
      ? RULES.pointsPerQuestion + " points, " + spent + " spent"
      : RULES.pointsPerQuestion + " points";
    $("q-prompt").textContent = question.prompt;

    var resolved = entry.status !== "open";
    $("answer-form").hidden = resolved;
    $("answer-input").value = entry.typed || "";
    $("verdict").textContent = " ";
    $("verdict").className = "verdict";

    var panel = $("resolved");
    panel.hidden = !resolved;
    panel.className = "resolved" + (entry.status === "shown" ? " shown" : "");
    if (resolved) {
      $("resolved-answer").textContent = (entry.status === "right" ? "Right: " : "The answer: ")
        + question.answer;
      $("resolved-note").textContent = question.note || "";
    }

    renderClues(pack, question, entry);
    $("prev-q").disabled = index === 0;
    $("next-q").disabled = index === pack.questions.length - 1;
    renderProgress();
    renderGauges();

    if (!resolved) $("answer-input").focus();
  }

  /* ============================================================= playing === */

  function goTo(index) {
    stash();
    state.current = Math.max(0, Math.min(state.questions.length - 1, index));
    save();
    renderQuestion();
  }

  /** Keep whatever is half-typed, so wandering off and back does not lose it. */
  function stash() {
    var entry = state.questions[state.current];
    if (entry && entry.status === "open") entry.typed = $("answer-input").value;
  }

  /** Move to the next unresolved question, or stay put if this was the last. */
  function advance() {
    for (var step = 1; step <= state.questions.length; step += 1) {
      var index = (state.current + step) % state.questions.length;
      if (state.questions[index].status === "open") {
        goTo(index);
        return true;
      }
    }
    return false;
  }

  function submitGuess(event) {
    event.preventDefault();
    var pack = packOf(state.pack);
    var question = pack.questions[state.current];
    var entry = state.questions[state.current];
    if (entry.status !== "open") return;

    var guess = $("answer-input").value;
    if (!normalize(guess)) return;

    if (answers(guess, question)) {
      entry.status = "right";
      entry.typed = "";
      save();
      renderQuestion();
      $("verdict").textContent = "Right — " + RULES.pointsPerQuestion + " points.";
      $("verdict").className = "verdict good";
      if (!everythingResolved()) {
        window.setTimeout(function () { if (state) advance(); }, 750);
      } else {
        finish();
      }
      return;
    }

    entry.typed = guess;
    save();
    $("verdict").textContent = "Not that. Try again, or buy a clue.";
    $("verdict").className = "verdict bad";
    $("answer-input").select();
  }

  function buy(clue) {
    var entry = state.questions[state.current];
    if (entry.status !== "open") return;

    if (clue.reveal) {
      entry.status = "shown";
      entry.typed = "";
      save();
      renderQuestion();
      $("verdict").textContent = "Shown — this one scores nothing.";
      $("verdict").className = "verdict soft";
      if (everythingResolved()) finish();
      return;
    }

    if (entry.clues.indexOf(clue.key) === -1) entry.clues.push(clue.key);
    stash();
    save();
    renderQuestion();
    $("verdict").textContent = "−" + clue.cost + " points.";
    $("verdict").className = "verdict soft";
  }

  function everythingResolved() {
    return state.questions.every(function (entry) { return entry.status !== "open"; });
  }

  function begin(pack) {
    var name = $("player-name").value.trim();
    if (!name) {
      $("name-note").textContent = "Put a name in first \u2014 it is how your team will find you on the board.";
      $("name-note").style.color = "var(--amber)";
      $("player-name").focus();
      $("player-name").scrollIntoView({ block: "center" });
      return;
    }
    remember(STORE_NAME, name);

    state = newRound(pack, null);
    save();
    show("screen-round");
    renderClock();
    renderQuestion();
    startTicking();

    // The token is what lets the leaderboard believe the round took ten minutes
    // to play. Asked for in the background: a board that is slow or missing must
    // never stop anyone playing.
    startRound(pack.id).then(function (token) {
      if (state && state.pack === pack.id) {
        state.token = token;
        save();
      }
    });
  }

  function startTicking() {
    stopTicking();
    ticker = window.setInterval(function () {
      renderClock();
      if (secondsLeft() <= 0) finish();
    }, 1000);
  }

  function stopTicking() {
    if (ticker) window.clearInterval(ticker);
    ticker = null;
  }

  function finish() {
    if (!state) return;
    stopTicking();
    stash();
    var scores = tally(secondsLeft());
    var pack = packOf(state.pack);
    var token = state.token;
    var finished = state;
    clearSaved();
    state = null;

    renderResult(pack, finished, scores);
    show("screen-result");
    submitRound(pack, token, scores);
  }

  /* ============================================================= results === */

  function row(table, label, value, className) {
    var tr = table.insertRow();
    tr.insertCell().textContent = label;
    var cell = tr.insertCell();
    cell.textContent = value;
    if (className) { cell.className = className; tr.className = className === "total" ? "total" : ""; }
    return tr;
  }

  function renderResult(pack, finished, scores) {
    var perfect = scores.right === scores.of;
    $("result-kicker").textContent = pack.title;
    $("result-total").textContent = scores.total.toLocaleString();
    $("result-sub").textContent = scores.right + " of " + scores.of + " right"
      + (scores.clues.length ? ", " + scores.clues.length + " clue" + (scores.clues.length === 1 ? "" : "s") + " bought" : ", no clues bought")
      + (scores.secondsLeft > 0 ? ", " + formatClock(scores.secondsLeft) + " left on the clock" : ", clock ran out");

    var table = $("breakdown");
    table.innerHTML = "";
    row(table, scores.right + " × " + RULES.pointsPerQuestion + " a question", scores.base);
    if (scores.spent) row(table, "Clues bought", "−" + scores.spent, "minus");
    if (scores.finisher) row(table, "All twelve right", "+" + scores.finisher, "bonus");
    if (scores.timeBonus) {
      row(table, formatClock(scores.secondsLeft) + " left × " + RULES.pointsPerSecondRemaining,
        "+" + scores.timeBonus, "bonus");
    }
    if (scores.cleanSweep) row(table, "Clean sweep, not a single clue", "+" + scores.cleanSweep, "bonus");
    if (!perfect && scores.right) {
      var note = table.insertRow();
      var cell = note.insertCell();
      cell.colSpan = 2;
      cell.className = "boardnote";
      cell.textContent = "The bonuses need all " + scores.of + " right — next time.";
    }
    row(table, "Total", scores.total, "total");

    var answerList = $("answer-list");
    answerList.innerHTML = "";
    pack.questions.forEach(function (question, index) {
      var entry = finished.questions[index];
      var item = document.createElement("li");

      var prompt = document.createElement("p");
      prompt.className = "aq";
      prompt.textContent = question.prompt;

      var answer = document.createElement("p");
      answer.className = "aa " + (entry.status === "right" ? "got" : "missed");
      answer.textContent = question.answer;

      item.appendChild(prompt);
      item.appendChild(answer);
      if (question.note) {
        var note = document.createElement("p");
        note.className = "an";
        note.textContent = question.note;
        item.appendChild(note);
      }
      answerList.appendChild(item);
    });

    $("share-btn").onclick = function () { copyResult(pack, finished, scores, $("share-btn")); };
  }

  function formatClock(seconds) {
    var minutes = Math.floor(seconds / 60);
    var rest = seconds % 60;
    return minutes + ":" + (rest < 10 ? "0" : "") + rest;
  }

  /** A Wordle-shaped line for the team chat: clean, hinted, or not at all. */
  function shareText(pack, finished, scores) {
    var squares = finished.questions.map(function (entry) {
      if (entry.status !== "right") return "⬛";
      return entry.clues.length ? "🟨" : "🟩";
    }).join("");
    var lines = [
      "Quick Fire — " + pack.title,
      scores.total.toLocaleString() + " points · " + scores.right + "/" + scores.of
        + " · " + formatClock(scores.secondsLeft) + " left",
      squares
    ];
    if (window.location && window.location.href) lines.push(window.location.href.split("?")[0]);
    return lines.join("\n");
  }

  function copyResult(pack, finished, scores, button) {
    var text = shareText(pack, finished, scores);
    var done = function (ok) {
      button.textContent = ok ? "Copied" : "Press and hold to copy";
      window.setTimeout(function () { button.textContent = "Copy my result"; }, 2000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
    } else {
      done(false);
    }
  }

  /* ========================================================= leaderboard ===
     Optional throughout. Every call is wrapped so that a board that is down,
     blocked or simply not deployed costs the player nothing but the board.
  */

  function boardUrl(path) {
    return LEADERBOARD ? LEADERBOARD.url + path : null;
  }

  function startRound(packId) {
    var url = boardUrl("/quiz/start");
    if (!url) return Promise.resolve(null);
    return fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ pack: packId })
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (body) {
      return body ? body.token : null;
    }).catch(function () { return null; });
  }

  function submitRound(pack, token, scores) {
    var url = boardUrl("/quiz/finish");
    var board = $("board");
    if (!url || !token) { board.hidden = true; return; }

    board.hidden = false;
    $("board-title").textContent = "Leaderboard — " + pack.title;
    $("board-note").textContent = "Posting your score…";
    $("board-table").innerHTML = "";

    fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        token: token,
        player: playerId(),
        name: remembered(STORE_NAME, "") || $("player-name").value.trim(),
        right: scores.right,
        questions: scores.of,
        clues: scores.clues,
        secondsLeft: scores.secondsLeft
      })
    }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok) throw new Error(result.body && result.body.error);
      renderBoard(result.body);
    }).catch(function () {
      $("board-note").textContent = "The leaderboard could not be reached. Your score still stands — "
        + "use “Copy my result” to post it to the team.";
    });
  }

  function renderBoard(body) {
    var table = $("board-table");
    table.innerHTML = "";
    var head = table.createTHead().insertRow();
    ["", "Player", "Score"].forEach(function (label) {
      var th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    });
    var tbody = table.createTBody();
    (body.top || []).forEach(function (entry, index) {
      var tr = tbody.insertRow();
      tr.insertCell().textContent = String(index + 1);
      tr.insertCell().textContent = entry.name;
      tr.insertCell().textContent = entry.score.toLocaleString();
      if (body.you && entry.name === body.you.name && entry.score === body.you.score) {
        tr.className = "you";
      }
    });

    var parts = [];
    if (body.you) parts.push("You are " + ordinal(body.you.rank) + " of " + body.players + ".");
    if (body.counted === false) parts.push("Only your first attempt at a pack counts, so this run did not move the board.");
    if (body.score !== undefined && body.score !== null) {
      parts.push("The board scored this round at " + body.score.toLocaleString() + ".");
    }
    $("board-note").textContent = parts.join(" ");
  }

  function ordinal(n) {
    var rest = n % 100;
    if (rest >= 11 && rest <= 13) return n + "th";
    var suffixes = { 1: "st", 2: "nd", 3: "rd" };
    return n + (suffixes[n % 10] || "th");
  }

  function loadBoards() {
    var url = boardUrl("/quiz/boards");
    if (!url) { renderPacks(null); return; }
    var query = "?packs=" + PACKS.map(function (p) { return encodeURIComponent(p.id); }).join(",")
      + "&player=" + encodeURIComponent(playerId());
    fetch(url + query)
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (body) { renderPacks(body ? body.boards : null); })
      .catch(function () { renderPacks(null); });
  }

  /* ================================================================ boot === */

  function goHome() {
    stopTicking();
    state = null;
    clearSaved();
    show("screen-home");
    loadBoards();
  }

  function wire() {
    $("answer-form").addEventListener("submit", submitGuess);
    $("prev-q").addEventListener("click", function () { goTo(state.current - 1); });
    $("next-q").addEventListener("click", function () { goTo(state.current + 1); });
    $("home-link").addEventListener("click", function () {
      if (!state || window.confirm("Leave this round? It will not be scored.")) goHome();
    });
    $("quit-link").addEventListener("click", function () {
      if (window.confirm("End the round here and see the answers?")) finish();
    });
    $("rules-link").addEventListener("click", function () { $("rules-sheet").hidden = false; });
    $("rules-close").addEventListener("click", function () { $("rules-sheet").hidden = true; });
    $("rules-sheet").addEventListener("click", function (event) {
      if (event.target === $("rules-sheet")) $("rules-sheet").hidden = true;
    });
    $("again-btn").addEventListener("click", goHome);
    $("player-name").addEventListener("change", function () {
      remember(STORE_NAME, $("player-name").value.trim());
    });
    // The clock is wall-clock based, so a tab that was asleep comes back to the
    // right time rather than to wherever the interval last left it.
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && state) {
        renderClock();
        if (secondsLeft() <= 0) finish();
      }
    });
  }

  /** Pick up an interrupted round, or clean up one whose clock ran out while away. */
  function resume() {
    var saved;
    try { saved = JSON.parse(window.localStorage.getItem(STORE_ROUND)); } catch (err) { saved = null; }
    if (!saved || !packOf(saved.pack) || !Array.isArray(saved.questions)) return false;
    state = saved;
    if (secondsLeft() <= 0) { finish(); return true; }
    show("screen-round");
    renderClock();
    renderQuestion();
    startTicking();
    return true;
  }

  function boot() {
    wire();
    $("player-name").value = remembered(STORE_NAME, "");
    if (!resume()) goHome();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
