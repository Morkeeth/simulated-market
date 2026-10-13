// Browser port of calib/score.py. calib/score.py is canonical; calib/vectors.json is the
// contract, and tests/test_calib.py runs this file over the same vectors with node.
// A plain script (no modules) so index.html works when opened straight from disk.
(function (root) {
  "use strict";

  var ALPHA = 0.05;
  var ARMS = ["silent_null", "simulator"]; // order matters: strict > keeps ties with silent_null
  var PREDICTS = { "helps": 1, "hurts": -1, "no detectable change": 0 };
  var OBSERVED = { "1": "helped", "-1": "hurt", "0": "no change" };

  var MIN_DISCORDANT = (function () {
    var m = 1;
    while (2 * Math.pow(0.5, m) >= ALPHA) m += 1;
    return m;
  })();

  function signTestP(a, b) {
    var m = a + b;
    if (m === 0) return 1;
    var k = Math.min(a, b);
    var pmf = Math.pow(0.5, m); // P(X = 0); fine for the row counts this page will see
    var tail = 0;
    for (var i = 0; i <= k; i++) {
      tail += pmf;
      pmf = pmf * (m - i) / (i + 1);
    }
    return Math.min(1, 2 * tail);
  }

  function isWhole(v) { return typeof v === "number" && Number.isInteger(v); }

  function side(v) {
    if (!v || typeof v !== "object") return [null, "missing"];
    if (!isWhole(v.reached) || !isWhole(v.n)) return [null, "reached and n must be whole numbers"];
    if (v.n < 1) return [null, "n must be at least 1"];
    if (v.reached < 0 || v.reached > v.n) return [null, "reached must be between 0 and n"];
    return [[v.reached, v.n], null];
  }

  function checkRow(r) {
    if (!r || typeof r !== "object") throw new Error("not an object");
    var b = side(r.base), h = side(r.head);
    if (b[1]) throw new Error("base: " + b[1]);
    if (h[1]) throw new Error("head: " + h[1]);
    return [b[0], h[0]];
  }

  function reason(verdict, n, a, b, p) {
    var m = a + b;
    if (n === 0) {
      return "Undetermined. No real outcome rows yet. A verdict needs at least " + MIN_DISCORDANT +
        " rows where the simulator and silent_null disagree, all on one side.";
    }
    if (verdict === "undetermined") {
      return "Undetermined. The simulator and silent_null disagree on " + m + " of " + n + " rows. " +
        "An exact two-sided sign test needs at least " + MIN_DISCORDANT + " such rows, all on one side, " +
        "before p can fall below " + ALPHA + " (2 x 0.5^6 = 0.03125, 2 x 0.5^5 = 0.0625).";
    }
    if (verdict === "simulator ahead") {
      return "Simulator ahead on direction. It was right on " + a + " rows where silent_null was wrong, and wrong on " +
        b + " where silent_null was right. Exact two-sided sign test p = " + p.toFixed(4) + ".";
    }
    if (verdict === "silent_null ahead") {
      return "Silent_null ahead on direction. It was right on " + b + " rows where the simulator was wrong, and wrong on " +
        a + " where the simulator was right. Exact two-sided sign test p = " + p.toFixed(4) + ".";
    }
    return "Tied. The arms disagree on " + m + " rows (" + a + " for the simulator, " + b + " for silent_null). " +
      "Exact two-sided sign test p = " + p.toFixed(4) + ", which is not below " + ALPHA + ".";
  }

  function score(delta, rows) {
    var direction = delta && delta.direction;
    if (!(direction in PREDICTS)) throw new Error("unknown delta direction: " + direction);
    var predicted = { simulator: PREDICTS[direction], silent_null: 0 };
    var mag = delta.magnitude && typeof delta.magnitude.goal_rate_change === "number" ? delta.magnitude.goal_rate_change : 0;
    var predictedChange = { simulator: mag, silent_null: 0 };

    var arms = {
      silent_null: { predicts: "no change", right: 0, wrong: 0, abs_error: null },
      simulator: { predicts: direction, right: 0, wrong: 0, abs_error: null }
    };
    var errSum = { silent_null: 0, simulator: 0 };
    var scored = [], rejected = [], a = 0, b = 0;

    (rows || []).forEach(function (r, i) {
      var sides;
      try { sides = checkRow(r); } catch (e) { rejected.push({ index: i, reason: e.message }); return; }
      var bk = sides[0][0], bn = sides[0][1], hk = sides[1][0], hn = sides[1][1];
      var cross = hk * bn - bk * hn;            // exact sign of hk/hn - bk/bn
      var obs = cross > 0 ? 1 : cross < 0 ? -1 : 0;
      var diff = hk / hn - bk / bn;
      var out = { index: i, observed: OBSERVED[String(obs)], observed_change: diff };
      ARMS.forEach(function (name) {
        var ok = predicted[name] === obs;
        out[name] = ok ? "right" : "wrong";
        arms[name][ok ? "right" : "wrong"] += 1;
        errSum[name] += Math.abs(predictedChange[name] - diff);
      });
      if (out.simulator === "right" && out.silent_null === "wrong") a += 1;
      else if (out.simulator === "wrong" && out.silent_null === "right") b += 1;
      scored.push(out);
    });

    var n = scored.length;
    if (n) ARMS.forEach(function (name) { arms[name].abs_error = errSum[name] / n; });

    var leader = "", best = -1;
    ARMS.forEach(function (name) { if (arms[name].right > best) { leader = name; best = arms[name].right; } });

    var p = signTestP(a, b);
    var verdict;
    if (a + b < MIN_DISCORDANT) verdict = "undetermined";
    else if (p < ALPHA) verdict = a > b ? "simulator ahead" : "silent_null ahead";
    else verdict = "tied";

    return {
      n: n,
      rows: scored,
      rejected: rejected,
      arms: arms,
      discordant: { simulator_only: a, silent_null_only: b, p_value: p,
        test: "exact two-sided sign test on rows where exactly one arm is right, alpha 0.05" },
      min_discordant: MIN_DISCORDANT,
      leader: leader,
      verdict: verdict,
      reason: reason(verdict, n, a, b, p),
      magnitude_badge: "UNCALIBRATED"
    };
  }

  var api = { score: score, checkRow: checkRow, signTestP: signTestP, MIN_DISCORDANT: MIN_DISCORDANT };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Calib = api;
})(this);
