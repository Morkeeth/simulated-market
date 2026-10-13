"""Score a simulated delta against real outcome rows, next to a silent-null arm.

Harvested from agents-for-humans/magnet/eval.py: every arm is scored against
explicit ground truth, never against itself, and one arm always predicts the
baseline. Here the ground truth is a real outcome row and the baseline is
"no change".

Arms
  simulator    predicts the delta's direction: helps, hurts or no detectable change.
  silent_null  always predicts no change.

Outcome row (one line of JSON; see calib/README.md):
  {"base": {"reached": k, "n": n}, "head": {"reached": k, "n": n},
   "base_doc_sha256": ..., "head_doc_sha256": ..., "source": "...", "runner": "..."}
A row needs both sides. One side alone has no direction, so it is rejected,
never read as "no change".

Verdict
  Rows where exactly one arm is right are the discordant rows. An exact
  two-sided sign test runs on them, the same test the delta uses for users.
  Fewer than MIN_DISCORDANT such rows: undetermined, whatever the counts say.
  The leader on raw counts is picked with strict greater-than and silent_null
  goes first, so a tie stays with silent_null. (eval.py iterates naive first,
  so its ties stay with naive; this scorer orders the arms on purpose.)

Magnitude error is reported only under the UNCALIBRATED badge.

calib/vectors.json is the contract. web/score.js must give the same results.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from fractions import Fraction
from math import comb
from pathlib import Path

ALPHA = 0.05
ARMS = ("silent_null", "simulator")      # order matters: strict > keeps ties with silent_null
PREDICTS = {"helps": 1, "hurts": -1, "no detectable change": 0}
OBSERVED = {1: "helped", -1: "hurt", 0: "no change"}


def _min_discordant(alpha: float = ALPHA) -> int:
    m = 1
    while 2 * 0.5 ** m >= alpha:
        m += 1
    return m


MIN_DISCORDANT = _min_discordant()


def sign_test_p(a: int, b: int) -> float:
    """Exact two-sided sign test on a successes for one side and b for the other."""
    m = a + b
    if m == 0:
        return 1.0
    tail = sum(comb(m, i) for i in range(min(a, b) + 1))
    return float(min(Fraction(1), Fraction(2 * tail, 2 ** m)))


def _side(value):
    if not isinstance(value, dict):
        return None, "missing"
    k, n = value.get("reached"), value.get("n")
    for v in (k, n):
        if not isinstance(v, int) or isinstance(v, bool):
            return None, "reached and n must be whole numbers"
    if n < 1:
        return None, "n must be at least 1"
    if k < 0 or k > n:
        return None, "reached must be between 0 and n"
    return (k, n), None


def check_row(r):
    """Return ((base_k, base_n), (head_k, head_n)) or raise ValueError with the reason."""
    if not isinstance(r, dict):
        raise ValueError("not an object")
    base, err_b = _side(r.get("base"))
    head, err_h = _side(r.get("head"))
    if err_b:
        raise ValueError(f"base: {err_b}")
    if err_h:
        raise ValueError(f"head: {err_h}")
    return base, head


def _reason(verdict, n, a, b, p):
    m = a + b
    if n == 0:
        return (f"Undetermined. No real outcome rows yet. A verdict needs at least {MIN_DISCORDANT} rows "
                f"where the simulator and silent_null disagree, all on one side.")
    if verdict == "undetermined":
        return (f"Undetermined. The simulator and silent_null disagree on {m} of {n} rows. An exact two-sided "
                f"sign test needs at least {MIN_DISCORDANT} such rows, all on one side, before p can fall below "
                f"{ALPHA} (2 x 0.5^6 = 0.03125, 2 x 0.5^5 = 0.0625).")
    if verdict == "simulator ahead":
        return (f"Simulator ahead on direction. It was right on {a} rows where silent_null was wrong, and wrong on "
                f"{b} where silent_null was right. Exact two-sided sign test p = {p:.4f}.")
    if verdict == "silent_null ahead":
        return (f"Silent_null ahead on direction. It was right on {b} rows where the simulator was wrong, and wrong "
                f"on {a} where the simulator was right. Exact two-sided sign test p = {p:.4f}.")
    return (f"Tied. The arms disagree on {m} rows ({a} for the simulator, {b} for silent_null). "
            f"Exact two-sided sign test p = {p:.4f}, which is not below {ALPHA}.")


def score(delta: dict, rows: list) -> dict:
    direction = delta.get("direction")
    if direction not in PREDICTS:
        raise ValueError(f"unknown delta direction: {direction!r}")
    predicted = {"simulator": PREDICTS[direction], "silent_null": 0}
    predicted_change = {"simulator": float(delta.get("magnitude", {}).get("goal_rate_change", 0.0)),
                        "silent_null": 0.0}

    scored, rejected = [], []
    arms = {name: {"predicts": OBSERVED[predicted[name]] if name == "silent_null" else direction,
                   "right": 0, "wrong": 0, "abs_error": None} for name in ARMS}
    err_sum = {name: 0.0 for name in ARMS}
    a = b = 0
    for i, r in enumerate(rows):
        try:
            (bk, bn), (hk, hn) = check_row(r)
        except ValueError as e:
            rejected.append({"index": i, "reason": str(e)})
            continue
        diff = Fraction(hk, hn) - Fraction(bk, bn)
        obs = (diff > 0) - (diff < 0)
        out = {"index": i, "observed": OBSERVED[obs], "observed_change": float(diff)}
        for name in ARMS:
            ok = predicted[name] == obs
            out[name] = "right" if ok else "wrong"
            arms[name]["right" if ok else "wrong"] += 1
            err_sum[name] += abs(predicted_change[name] - float(diff))
        if out["simulator"] == "right" and out["silent_null"] == "wrong":
            a += 1
        elif out["simulator"] == "wrong" and out["silent_null"] == "right":
            b += 1
        scored.append(out)

    n = len(scored)
    if n:
        for name in ARMS:
            arms[name]["abs_error"] = err_sum[name] / n

    leader, best = "", -1
    for name in ARMS:
        if arms[name]["right"] > best:
            leader, best = name, arms[name]["right"]

    p = sign_test_p(a, b)
    if a + b < MIN_DISCORDANT:
        verdict = "undetermined"
    elif p < ALPHA:
        verdict = "simulator ahead" if a > b else "silent_null ahead"
    else:
        verdict = "tied"

    return {
        "n": n,
        "rows": scored,
        "rejected": rejected,
        "arms": arms,
        "discordant": {"simulator_only": a, "silent_null_only": b, "p_value": p,
                       "test": "exact two-sided sign test on rows where exactly one arm is right, alpha 0.05"},
        "min_discordant": MIN_DISCORDANT,
        "leader": leader,
        "verdict": verdict,
        "reason": _reason(verdict, n, a, b, p),
        "magnitude_badge": "UNCALIBRATED",
    }


# ---- command line -----------------------------------------------------------

def _parse_side(text: str) -> dict:
    try:
        k, n = text.split("/")
        return {"reached": int(k), "n": int(n)}
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected reached/n, for example 1/1, got {text!r}")


def _read_rows(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m calib.score",
        description="Score a simulated delta against real outcome rows, next to silent_null.")
    ap.add_argument("--delta", required=True, type=Path, help="runs/delta-<base>-<head>.json from make demo")
    ap.add_argument("--outcomes", type=Path, default=Path("calib/outcomes.jsonl"),
                    help="your real outcome rows (default calib/outcomes.jsonl, kept out of git)")
    ap.add_argument("--log", type=Path, default=Path("calib/scores.jsonl"),
                    help="where to append one row per score (default calib/scores.jsonl, kept out of git)")
    ap.add_argument("--no-log", action="store_true", help="print the score without appending a row")
    ap.add_argument("--add-base", type=_parse_side, metavar="K/N",
                    help="add a row first: how many of N reached the goal on the published doc")
    ap.add_argument("--add-head", type=_parse_side, metavar="K/N",
                    help="add a row first: how many of N reached the goal on the patched doc")
    ap.add_argument("--source", help="with --add-*: where this outcome came from, in your words")
    ap.add_argument("--runner", default=None, help="with --add-*: your name or handle, optional")
    args = ap.parse_args(argv)

    delta = json.loads(args.delta.read_text())
    base_sha, head_sha = delta["base"]["doc_sha256"], delta["head"]["doc_sha256"]

    if args.add_base or args.add_head:
        if not (args.add_base and args.add_head and args.source):
            ap.error("a row needs --add-base, --add-head and --source together. One side alone has no direction.")
        new = {"base": args.add_base, "head": args.add_head, "base_doc_sha256": base_sha,
               "head_doc_sha256": head_sha, "source": args.source}
        if args.runner:
            new["runner"] = args.runner
        check_row(new)
        args.outcomes.parent.mkdir(parents=True, exist_ok=True)
        with args.outcomes.open("a") as f:
            f.write(json.dumps(new, sort_keys=True) + "\n")

    all_rows = _read_rows(args.outcomes)
    rows = [r for r in all_rows if r.get("base_doc_sha256") == base_sha and r.get("head_doc_sha256") == head_sha]
    result = score(delta, rows)
    labels = delta.get("labels", [])

    pred = delta["direction"]
    print(f"Prediction: {'the doc patch ' + pred if pred != 'no detectable change' else 'no detectable change'}"
          f"  [{', '.join(labels)}]")
    print(f"  from {args.delta}, seed {delta.get('seed')}, "
          f"{delta.get('n', {}).get('value', 'unverified')} simulated users.")
    print(f"Real outcome rows for this doc change: {result['n']} (from {args.outcomes})."
          f" Rows for other doc changes: {len(all_rows) - len(rows)}. Rejected: {len(result['rejected'])}.")
    for rj in result["rejected"]:
        print(f"  rejected row {rj['index'] + 1}: {rj['reason']}")
    if result["rows"]:
        print()
        print(f"  {'row':>3}  {'observed':<10}  {'simulator':<9}  silent_null")
        for r in result["rows"]:
            print(f"  {r['index'] + 1:>3}  {r['observed']:<10}  {r['simulator']:<9}  {r['silent_null']}")
    print()
    print(f"  {'arm':<11}  {'right':>5}  {'wrong':>5}")
    for name in ("simulator", "silent_null"):
        print(f"  {name:<11}  {result['arms'][name]['right']:>5}  {result['arms'][name]['wrong']:>5}")
    print()
    print(f"Verdict: {result['reason']}")
    if result["n"]:
        print(f"Size error [UNCALIBRATED]: simulator {result['arms']['simulator']['abs_error']:.3f}, "
              f"silent_null {result['arms']['silent_null']['abs_error']:.3f} "
              f"(mean absolute error in the goal rate change).")

    if not args.no_log:
        entry = {
            "date": _dt.date.today().isoformat(),
            "delta_file": str(args.delta),
            "base_run_file": delta["base"].get("file"),
            "head_run_file": delta["head"].get("file"),
            "seed": delta.get("seed"),
            "labels": labels,
            "prediction": pred,
            "outcomes_file": str(args.outcomes),
            "n": result["n"],
            "rejected": len(result["rejected"]),
            "simulator": {k: result["arms"]["simulator"][k] for k in ("right", "wrong")},
            "silent_null": {k: result["arms"]["silent_null"][k] for k in ("right", "wrong")},
            "discordant": {k: result["discordant"][k] for k in ("simulator_only", "silent_null_only", "p_value")},
            "leader": result["leader"],
            "verdict": result["verdict"],
        }
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        print(f"Appended one row to {args.log}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
