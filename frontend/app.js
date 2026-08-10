/* Line-Ups - browser client.
 *
 * The server owns the puzzle: it decides which slots are visible, resolves guesses and
 * keeps the clock. This file renders whatever state the API returns and never tries to
 * work out an answer locally - hidden players simply arrive with `name: null`.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "lineups.stats.v1";
  var state = null; // latest game state from the API
  var meta = null; // /api/metadata
  var difficulty = "medium";
  var ticker = null;
  var localSeconds = 0;

  /* ------------------------------------------------------------------ helpers */

  function $(id) { return document.getElementById(id); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  async function api(path, options) {
    var response = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" }
    }, options));
    var payload = null;
    try { payload = await response.json(); } catch (err) { payload = null; }
    if (!response.ok) {
      var detail = (payload && payload.detail) || ("Request failed (" + response.status + ")");
      throw new Error(typeof detail === "string" ? detail : "Request failed");
    }
    return payload;
  }

  function showView(name) {
    ["home", "game", "result"].forEach(function (view) {
      $("view-" + view).classList.toggle("is-active", view === name);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function formatClock(seconds) {
    var safe = Math.max(0, Math.floor(seconds));
    var mins = Math.floor(safe / 60);
    var secs = safe % 60;
    return mins + ":" + (secs < 10 ? "0" : "") + secs;
  }

  /* -------------------------------------------------------------------- stats */

  function loadStats() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (err) { /* private browsing, corrupted value - fall through */ }
    return { played: 0, completed: 0, bestScore: 0, totalFound: 0, streak: 0, bestStreak: 0, lastDaily: null };
  }

  function saveStats(stats) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stats)); } catch (err) { /* ignore */ }
  }

  function recordResult(finished) {
    var stats = loadStats();
    stats.played += 1;
    stats.totalFound += finished.guessed;
    stats.bestScore = Math.max(stats.bestScore, finished.score);
    if (finished.status === "won") {
      stats.completed += 1;
      stats.streak += 1;
      stats.bestStreak = Math.max(stats.bestStreak, stats.streak);
    } else {
      stats.streak = 0;
    }
    if (finished.mode === "daily") stats.lastDaily = new Date().toISOString().slice(0, 10);
    saveStats(stats);
    return stats;
  }

  function statTiles(stats) {
    var rate = stats.played ? Math.round((stats.completed / stats.played) * 100) : 0;
    var avg = stats.played ? (stats.totalFound / stats.played).toFixed(1) : "0.0";
    return [
      ["Played", stats.played],
      ["Full XIs", stats.completed],
      ["Win rate", rate + "%"],
      ["Avg named", avg],
      ["Best score", stats.bestScore],
      ["Streak", stats.streak + " / " + stats.bestStreak]
    ];
  }

  function renderStats(container) {
    container.innerHTML = "";
    statTiles(loadStats()).forEach(function (pair) {
      var wrap = el("div");
      wrap.appendChild(el("dt", null, pair[0]));
      wrap.appendChild(el("dd", null, String(pair[1])));
      container.appendChild(wrap);
    });
  }

  /* --------------------------------------------------------------------- home */

  function renderDifficultyDetail() {
    if (!meta) return;
    var info = meta.difficulties[difficulty];
    if (!info) return;
    var freebies = info.revealed_at_kickoff;
    var given = freebies === 0 ? "nothing given away" : freebies + " shown at kick-off";
    $("difficulty-detail").textContent =
      given + " · " + formatClock(info.seconds) + " on the clock · ×" + info.multiplier + " points";
  }

  function renderHome() {
    renderStats($("home-stats"));
    var stats = loadStats();
    var today = new Date().toISOString().slice(0, 10);
    $("daily-status").textContent =
      stats.lastDaily === today ? "You have already played today's XI - go again for practice." : "";
    if (meta) {
      var range = meta.date_range[0] && meta.date_range[1]
        ? " spanning " + meta.date_range[0].slice(0, 4) + "–" + meta.date_range[1].slice(0, 4)
        : "";
      $("archive-note").textContent =
        meta.lineups_count + " lineups in the archive" + range + ".";
    }
    renderDifficultyDetail();
  }

  /* --------------------------------------------------------------------- game */

  function renderFixture(fixture) {
    var box = $("fixture");
    box.innerHTML = "";

    var teams = el("div", "fixture-teams");
    teams.appendChild(document.createTextNode(fixture.team || "Unknown XI"));
    if (fixture.opponent) {
      var vs = el("span", "opponent", " vs " + fixture.opponent);
      teams.appendChild(vs);
    }
    box.appendChild(teams);

    var bits = [fixture.competition, fixture.season].filter(Boolean);
    if (fixture.venue) bits.push(fixture.venue);
    box.appendChild(el("div", "fixture-meta", bits.join(" · ")));
    box.appendChild(el("span", "fixture-formation", fixture.formation_label));
  }

  function renderPitch(slots, justFound) {
    var pitch = $("pitch");
    // Keep the markings, replace the players.
    Array.prototype.slice.call(pitch.querySelectorAll(".slot")).forEach(function (node) {
      node.remove();
    });

    slots.forEach(function (slot) {
      var node = el("div", "slot");
      // Row 0 (the keeper) sits at the bottom; the last row attacks the top of the screen.
      var rows = slot.row_count;
      var top = rows > 1 ? 92 - (slot.row / (rows - 1)) * 84 : 50;
      var left = ((slot.column + 1) / (slot.row_size + 1)) * 100;
      node.style.top = top + "%";
      node.style.left = left + "%";

      if (slot.revealed) node.classList.add("is-revealed");
      if (slot.source === "free") node.classList.add("is-free");
      if (slot.source === "hint") node.classList.add("is-hint");
      if (slot.source === "missed") node.classList.add("is-missed");
      if (justFound === slot.slot) node.classList.add("just-found");

      node.appendChild(el("span", "slot-marker", slot.position || ""));
      var label = slot.name || slot.initials || "?";
      node.appendChild(el("span", "slot-name", label));
      pitch.appendChild(node);
    });
  }

  function renderHud() {
    $("hud-found").textContent = state.found + " / " + state.total;
    $("hud-score").textContent = state.score;
    $("hud-misses").textContent = state.wrong_guesses;
    $("hud-time").textContent = formatClock(localSeconds);

    var fraction = state.seconds_total ? localSeconds / state.seconds_total : 0;
    var urgent = localSeconds <= 30;
    $("clock-fill").style.width = Math.max(0, Math.min(100, fraction * 100)) + "%";
    $("clock-fill").classList.toggle("is-urgent", urgent);
    $("hud-time").parentElement.classList.toggle("is-urgent", urgent);

    $("hint-initials").disabled = state.hints_used.initials;
    $("hint-initials").textContent = state.hints_used.initials
      ? "Initials shown"
      : "Initials (−" + state.hint_costs.initials + ")";
    $("hint-reveal").textContent = "Give me one (−" + state.hint_costs.reveal + ")";
  }

  function setFeedback(message, tone) {
    var node = $("feedback");
    node.textContent = message || "";
    node.className = "feedback" + (tone ? " is-" + tone : "");
  }

  function stopTicker() {
    if (ticker) { window.clearInterval(ticker); ticker = null; }
  }

  function startTicker() {
    stopTicker();
    ticker = window.setInterval(function () {
      if (!state || state.status !== "in_progress") { stopTicker(); return; }
      localSeconds -= 1;
      if (localSeconds <= 0) {
        localSeconds = 0;
        stopTicker();
        // The server is the authority on time - ask it to close the game out.
        api("/api/games/" + state.game_id).then(function (payload) {
          applyState(payload.state);
        }).catch(function () { /* offline; the next action will resync */ });
      }
      renderHud();
    }, 1000);
  }

  function applyState(next, justFound) {
    state = next;
    localSeconds = next.seconds_remaining;
    renderFixture(next.fixture);
    renderPitch(next.slots, justFound);
    renderHud();

    var live = next.status === "in_progress";
    $("guess-input").disabled = !live;
    $("hint-reveal").disabled = !live;
    if (!live) $("hint-initials").disabled = true;

    if (live) {
      startTicker();
    } else {
      stopTicker();
      showResult(next);
    }
  }

  async function startGame(body) {
    setFeedback("");
    try {
      var payload = await api("/api/games", { method: "POST", body: JSON.stringify(body) });
      showView("game");
      applyState(payload.state);
      $("guess-input").value = "";
      $("guess-input").focus();
    } catch (err) {
      setFeedback(err.message, "wrong");
      window.alert("Could not start a game: " + err.message);
    }
  }

  async function submitGuess(event) {
    event.preventDefault();
    var input = $("guess-input");
    var text = input.value.trim();
    if (!text || !state || state.status !== "in_progress") return;

    input.value = "";
    try {
      var payload = await api("/api/games/" + state.game_id + "/guesses", {
        method: "POST",
        body: JSON.stringify({ text: text })
      });
      var result = payload.result;
      var tones = { correct: "correct", wrong: "wrong" };
      var messages = {
        correct: "✓ " + result.message,
        wrong: "✗ " + text + " — not in this lineup.",
        already_found: "Already on the pitch.",
        ambiguous: result.message,
        too_short: "Type at least three letters.",
        empty: ""
      };
      setFeedback(messages[result.status] || result.message, tones[result.status] || "note");
      applyState(payload.state, result.status === "correct" ? result.slot : undefined);
    } catch (err) {
      setFeedback(err.message, "wrong");
    } finally {
      input.focus();
    }
  }

  async function buyHint(type) {
    if (!state || state.status !== "in_progress") return;
    try {
      var payload = await api("/api/games/" + state.game_id + "/hints", {
        method: "POST",
        body: JSON.stringify({ type: type })
      });
      setFeedback(type === "initials" ? "Initials revealed." : "One player handed over.", "note");
      applyState(payload.state);
    } catch (err) {
      setFeedback(err.message, "wrong");
    } finally {
      $("guess-input").focus();
    }
  }

  async function giveUp() {
    if (!state || state.status !== "in_progress") return;
    if (!window.confirm("Give up and see the full XI?")) return;
    try {
      var payload = await api("/api/games/" + state.game_id + "/surrender", { method: "POST" });
      applyState(payload.state);
    } catch (err) {
      setFeedback(err.message, "wrong");
    }
  }

  /* ------------------------------------------------------------------- result */

  var VERDICTS = {
    won: "Full house — all eleven.",
    lost: "Time up.",
    gave_up: "Lineup revealed."
  };

  var TICKS = {
    guessed: ["got", "named"],
    free: ["free", "given"],
    hint: ["hinted", "hint"],
    missed: ["missed", "missed"]
  };

  function showResult(finished) {
    var stats = recordResult({
      status: finished.status,
      score: finished.score,
      guessed: finished.guessed,
      mode: finished.mode
    });

    $("result-verdict").textContent = VERDICTS[finished.status] || "Round over.";
    $("result-score").textContent = finished.score;

    var table = $("result-breakdown");
    table.innerHTML = "";
    var breakdown = finished.score_breakdown || {};
    [
      ["Players named (" + (breakdown.guessed || 0) + ")", breakdown.guess_points],
      ["Completion bonus", breakdown.completion_bonus],
      ["Time bonus", breakdown.time_bonus],
      ["Hints", breakdown.hint_penalty ? -breakdown.hint_penalty : 0]
    ].forEach(function (row) {
      if (!row[1]) return;
      var tr = table.insertRow();
      tr.insertCell().textContent = row[0];
      tr.insertCell().textContent = (row[1] > 0 ? "+" : "") + row[1];
    });
    var totalRow = table.insertRow();
    totalRow.className = "is-total";
    totalRow.insertCell().textContent = "Total";
    totalRow.insertCell().textContent = String(finished.score);

    var fixture = finished.fixture;
    var fixtureBox = $("result-fixture");
    fixtureBox.innerHTML = "";
    var headline = fixture.team + (fixture.opponent ? " " + (fixture.score || "vs") + " " + fixture.opponent : "");
    fixtureBox.appendChild(el("div", null, headline));
    fixtureBox.appendChild(el("div", "result-competition",
      [fixture.competition, fixture.date].filter(Boolean).join(" · ")));

    var blurb = $("result-blurb");
    blurb.innerHTML = "";
    if (fixture.blurb) blurb.appendChild(document.createTextNode(fixture.blurb + " "));
    if (fixture.source_url) {
      var link = el("a", null, "Source");
      link.href = fixture.source_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      blurb.appendChild(link);
    }

    var list = $("result-lineup");
    list.innerHTML = "";
    finished.slots.forEach(function (slot) {
      var item = el("li");
      item.appendChild(el("span", "pos", slot.position || ""));
      item.appendChild(el("span", "who", slot.name || "?"));
      var tick = TICKS[slot.source] || TICKS.missed;
      item.appendChild(el("span", "tick " + tick[0], tick[1]));
      list.appendChild(item);
    });

    renderStats($("home-stats"));
    renderStats($("modal-stats-body"));
    void stats;
    showView("result");
  }

  /* -------------------------------------------------------------------- wiring */

  function openModal(name) {
    if (name === "stats") renderStats($("modal-stats-body"));
    $("modal-" + name).hidden = false;
  }

  function closeModals() {
    ["howto", "stats"].forEach(function (name) { $("modal-" + name).hidden = true; });
  }

  function bind() {
    $("play-quick").addEventListener("click", function () {
      startGame({ mode: "quick", difficulty: difficulty });
    });
    $("play-daily").addEventListener("click", function () {
      startGame({ mode: "daily" });
    });
    $("play-again").addEventListener("click", function () {
      startGame({ mode: "quick", difficulty: difficulty });
    });
    $("back-home").addEventListener("click", function () { renderHome(); showView("home"); });
    $("brand").addEventListener("click", function () { renderHome(); showView("home"); });

    Array.prototype.slice.call(document.querySelectorAll("[data-difficulty]")).forEach(function (chip) {
      chip.addEventListener("click", function () {
        difficulty = chip.dataset.difficulty;
        document.querySelectorAll("[data-difficulty]").forEach(function (other) {
          other.classList.toggle("is-selected", other === chip);
        });
        renderDifficultyDetail();
      });
    });

    $("guess-form").addEventListener("submit", submitGuess);
    $("hint-initials").addEventListener("click", function () { buyHint("initials"); });
    $("hint-reveal").addEventListener("click", function () { buyHint("reveal"); });
    $("give-up").addEventListener("click", giveUp);

    Array.prototype.slice.call(document.querySelectorAll("[data-open]")).forEach(function (button) {
      button.addEventListener("click", function () { openModal(button.dataset.open); });
    });
    Array.prototype.slice.call(document.querySelectorAll("[data-close]")).forEach(function (button) {
      button.addEventListener("click", closeModals);
    });
    Array.prototype.slice.call(document.querySelectorAll(".modal")).forEach(function (modal) {
      modal.addEventListener("click", function (event) {
        if (event.target === modal) closeModals();
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeModals();
    });

    $("reset-stats").addEventListener("click", function () {
      if (!window.confirm("Clear your saved stats?")) return;
      saveStats({ played: 0, completed: 0, bestScore: 0, totalFound: 0, streak: 0, bestStreak: 0, lastDaily: null });
      renderStats($("modal-stats-body"));
      renderStats($("home-stats"));
    });
  }

  async function init() {
    bind();
    try {
      meta = await api("/api/metadata");
    } catch (err) {
      $("archive-note").textContent = "Could not reach the server - is the API running?";
    }
    renderHome();

    // Deep link: /?lineup=ucl-1999-final-manutd&difficulty=hard sets up that exact XI,
    // so a particular puzzle can be shared with someone else.
    var params = new URLSearchParams(window.location.search);
    var requested = params.get("lineup");
    if (params.get("difficulty") && meta && meta.difficulties[params.get("difficulty")]) {
      difficulty = params.get("difficulty");
      document.querySelectorAll("[data-difficulty]").forEach(function (chip) {
        chip.classList.toggle("is-selected", chip.dataset.difficulty === difficulty);
      });
      renderDifficultyDetail();
    }
    if (requested) {
      await startGame({ mode: "quick", difficulty: difficulty, lineup: requested });
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
