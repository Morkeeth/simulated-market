"""Same-seed counterfactual. Skeleton from MAGNET adopt: record the change, re-probe, print a receipt.

Order is fixed:
1. Base run on the unpatched doc.
2. Control run: same seeds, same checkpoint, no patch. It must match the base run byte
   for byte. If it does not, the same-seed claim is false and no delta is written.
3. Head run on the patched doc, same seeds.
4. Delta: direction first (exact sign test on per-user pairs), magnitude under an
   "uncalibrated" badge.
"""
from __future__ import annotations

import difflib
from math import comb
from pathlib import Path

from sim import labels as L
from sim.doc import sha256_bytes

# 0.2.0: paired.steps_back and paired.steps_forward added. Nothing removed or renamed.
DELTA_SCHEMA_VERSION = "0.2.0"


def sign_test_p(improved: int, worsened: int) -> float:
    m = improved + worsened
    if m == 0:
        return 1.0
    k = min(improved, worsened)
    tail = sum(comb(m, i) for i in range(0, k + 1)) / 2 ** m
    return round(min(1.0, 2 * tail), 6)


def control_diff(a: str, b: str, limit: int = 20) -> list[str]:
    return list(difflib.unified_diff(a.splitlines(), b.splitlines(), "base", "control", lineterm="", n=0))[:limit]


def step_moves(base: dict, head: dict, *, base_file: str, head_file: str) -> tuple[dict, dict]:
    """Per user, compare the furthest step reached on base and on head.

    users[].reached is a prefix of steps (sim/session.py probe stops at the first miss),
    so the furthest step is reached[-1] and its position is len(reached).
    steps_back: users who got past a step on base and stopped at it on head. These are
    visible even when the goal outcome did not change, which the sign test cannot show.
    """
    ids = [s["id"] for s in base["steps"]]
    b_reach = {u["id"]: u["reached"] for u in base["users"]}
    h_reach = {u["id"]: u["reached"] for u in head["users"]}
    back, fwd = [], []
    for uid in sorted(b_reach):
        kb, kh = len(b_reach[uid]), len(h_reach[uid])
        if kb == kh:
            continue
        row = {"user": uid,
               "base_furthest": b_reach[uid][-1] if kb else None,
               "head_furthest": h_reach[uid][-1] if kh else None,
               # The first step that one side reached and the other did not.
               "step": ids[min(kb, kh)],
               "steps_moved": kh - kb}
        (back if kh < kb else fwd).append(row)
    src = f"same user id: furthest step in users[].reached, {base_file} against {head_file}"
    return (
        {"value": len(back), "source": src + "; earlier on head", "users": [r["user"] for r in back], "moves": back},
        {"value": len(fwd), "source": src + "; later on head", "users": [r["user"] for r in fwd], "moves": fwd},
    )


def delta(base: dict, head: dict, *, base_file: str, head_file: str, base_sha: str, control_sha: str) -> dict:
    if base["seed"] != head["seed"]:
        raise ValueError("base and head used different seeds")
    n = base["population"]["n"]["value"]
    goal = base["steps"][-1]["id"]
    b_goal = {u["id"]: goal in u["reached"] for u in base["users"]}
    h_goal = {u["id"]: goal in u["reached"] for u in head["users"]}
    if set(b_goal) != set(h_goal):
        raise ValueError("base and head populations differ")
    improved = sum(1 for k in b_goal if h_goal[k] and not b_goal[k])
    worsened = sum(1 for k in b_goal if b_goal[k] and not h_goal[k])
    p = sign_test_p(improved, worsened)
    steps_back, steps_forward = step_moves(base, head, base_file=base_file, head_file=head_file)
    if p < 0.05 and improved > worsened:
        direction = "helps"
    elif p < 0.05 and worsened > improved:
        direction = "hurts"
    else:
        direction = "no detectable change"
    bg, hg = sum(b_goal.values()), sum(h_goal.values())
    labels = sorted(set(base["labels"]) | set(head["labels"]), key=lambda x: (x != L.SIMULATED, x))
    return {
        "schema_version": DELTA_SCHEMA_VERSION,
        "labels": labels,
        "seed": base["seed"],
        "n": {"value": n, "source": "population n of both runs"},
        "base": {"run_id": base["run_id"], "file": base_file, "doc_sha256": base["doc"]["sha256"],
                 "goal_reached": {"value": bg, "source": f"users reaching {goal} in {base_file}"}},
        "head": {"run_id": head["run_id"], "file": head_file, "doc_sha256": head["doc"]["sha256"],
                 "goal_reached": {"value": hg, "source": f"users reaching {goal} in {head_file}"}},
        "control": {"identical": True, "base_sha256": base_sha, "control_sha256": control_sha},
        "paired": {
            "improved": {"value": improved, "source": "same user id: goal reached on head only"},
            "worsened": {"value": worsened, "source": "same user id: goal reached on base only"},
            "p_value": {"value": p, "source": "exact binomial, p=0.5, over improved + worsened"},
            "test": "exact two-sided sign test on discordant pairs, alpha 0.05",
            "steps_back": steps_back,
            "steps_forward": steps_forward,
        },
        "direction": direction,
        "steps": [{"id": bs["id"],
                   "base_reached": {"value": bs["reached"]["value"], "source": base_file},
                   "head_reached": {"value": hs["reached"]["value"], "source": head_file},
                   "change": hs["reached"]["value"] - bs["reached"]["value"]}
                  for bs, hs in zip(base["steps"], head["steps"])],
        "magnitude": {"goal_rate_change": round((hg - bg) / n, 4) if n else 0.0, "badge": "uncalibrated",
                      "source": "(head goal - base goal) / n. Not scored against any real outcome yet."},
    }


def same_bytes(a: Path, b: Path) -> bool:
    return a.read_bytes() == b.read_bytes()


def file_sha(p: Path) -> str:
    return sha256_bytes(p.read_bytes())
