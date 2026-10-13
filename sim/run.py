"""One population run: sample personas, fork one checkpoint per user, act, probe, aggregate.

The run file is deterministic. Wall times and timestamps go to a separate timing file.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sim import labels as L
from sim.doc import Target, parse, sha256_bytes
from sim.persona import ASSUMPTIONS_SOURCE, sample
from sim.session import Session

SCHEMA_VERSION = "0.7.0"
SIM_DIR = Path(__file__).resolve().parent


def engine_sha() -> str:
    """Hash of the engine source, so a code change can never reuse an old run id."""
    h = hashlib.sha256()
    for f in sorted(SIM_DIR.rglob("*.py")):
        h.update(str(f.relative_to(SIM_DIR)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def run_id_for(*, seed: int, doc_sha: str, policy_name: str, model_info, n: int, recipe: dict, agent_info=None) -> str:
    """The run id execute() gives these inputs on this engine. Used to find a run file again."""
    recipe_sha = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    return hashlib.sha256(json.dumps({
        "seed": seed, "doc": doc_sha, "policy": policy_name, "model": model_info,
        "n": n, "recipe": recipe_sha, "schema": SCHEMA_VERSION, "engine": engine_sha(), "agents": agent_info}, sort_keys=True).encode()).hexdigest()[:16]


def dumps(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _rate(k: int, n: int) -> float:
    return round(k / n, 4) if n else 0.0


def _pop_steps(target: Target, users: list[dict], n: int, where: str) -> list[dict]:
    out, prev = [], n
    for st in target.meta["steps"]:
        k = sum(1 for u in users if st["id"] in u["reached"])
        out.append({"id": st["id"],
                    "reached": {"value": k, "source": f"count of {where} whose reached contains {st['id']}; {st['check']}"},
                    "dropped": {"value": prev - k, "source": "reached at the previous step minus reached here"}})
        prev = k
    return out


def execute(*, target: Target, section: str, patch: dict | None, seed: int, n: int,
            policy, sandbox, grounding, workers: int = 4, agents=None) -> tuple[dict, dict]:
    """policy: object with name, label, model_info, act(persona, elements, section, session) -> (gave_up, quote, topic).

    agents: optional coding-agent population with k, info, label, backend_name and act(session, section).
    Agents run after the humans, one at a time, each in its own fork of the same checkpoint."""
    t_start = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    elements = parse(section)
    doc_sha = sha256_bytes(section.encode())
    ckpt, recipe = (sandbox.checkpoint_target(target) if hasattr(sandbox, "checkpoint_target")
                    else sandbox.checkpoint(target.wheel, target.meta["wheel_sha256"]))
    t_ckpt = time.monotonic() - t_start
    run_id = run_id_for(seed=seed, doc_sha=doc_sha, policy_name=policy.name, model_info=policy.model_info,
                        n=n, recipe=recipe, agent_info=agents.info if agents else None)
    personas = sample(seed, n, [r["url"] for r in grounding.items()])
    nonce = secrets.token_hex(3)
    user_times: dict[str, float] = {}

    def one(p):
        t0 = time.monotonic()
        fork = sandbox.fork(ckpt, f"sim-{run_id[:8]}-{nonce}-{p.id}")
        try:
            s = Session(persona=p, fork=fork, target=target)
            gave_up, text, topic = policy.act(p, elements, section, s)
            reached = s.probe()
        finally:
            fork.close()
        user_times[p.id] = round(time.monotonic() - t0, 3)
        return p, s, gave_up, text, topic, reached

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = list(ex.map(one, personas))

    agent_results = []
    if agents is not None:
        for j in range(agents.k):
            aid = f"a{j:03d}"
            t0 = time.monotonic()
            fork = sandbox.fork(ckpt, f"sim-{run_id[:8]}-{nonce}-{aid}")
            try:
                s = Session(persona=None, fork=fork, target=target)
                status = agents.act(s, section)
                reached = s.probe()
            finally:
                fork.close()
            user_times[aid] = round(time.monotonic() - t0, 3)
            agent_results.append((aid, s, status, reached))

    step_ids = [st["id"] for st in target.meta["steps"]]
    users, quotes = [], []
    for p, s, gave_up, text, topic, reached in results:
        dropped_at = next((sid for sid in step_ids if sid not in reached), None)
        users.append({"id": p.id, "population": "human", "persona": p.as_dict(), "log": s.log,
                      "reached": reached, "dropped_at": dropped_at, "gave_up": gave_up})
        if text:
            g = grounding.for_topic(topic) if topic else None
            quotes.append({"user": p.id, "step": dropped_at, "text": text,
                           "labels": [L.SIMULATED, L.LOCAL, policy.label] if L.is_local(policy.label)
                           else [L.SIMULATED, policy.label],
                           "policy": policy.name,
                           "grounding": {"url": g["url"], "label": g["label"]} if g else None})

    steps, prev = [], n
    for st in target.meta["steps"]:
        k = sum(1 for u in users if st["id"] in u["reached"])
        steps.append({
            "id": st["id"], "title": st["title"], "check": st["check"],
            "reached": {"value": k, "source": f"count of users[].reached containing {st['id']}; {st['check']}"},
            "dropped": {"value": prev - k, "source": "reached at the previous step minus reached here"},
            "rate": {"value": _rate(k, n), "source": f"reached / population n ({k}/{n})"},
        })
        prev = k

    agent_users = []
    for aid, s, status, reached in agent_results:
        agent_users.append({"id": aid, "population": "coding_agent", "exit_status": status, "log": s.log,
                            "reached": reached, "dropped_at": next((sid for sid in step_ids if sid not in reached), None),
                            "gave_up": status != "Submitted"})

    any_local_people = L.is_local(sandbox.label) or L.is_local(policy.label)
    populations = [{
        "id": "humans", "population": "human",
        "labels": [L.SIMULATED, L.LOCAL] if any_local_people else [L.SIMULATED],
        "backend": {"name": policy.backend_name, "label": policy.label},
        "n": {"value": n, "source": f"--n; personas sampled from seed {seed} by {ASSUMPTIONS_SOURCE}"},
        "steps": _pop_steps(target, users, n, "users[]"),
    }]
    if agents is not None:
        k = agents.k
        populations.append({
            "id": "coding_agents", "population": "coding_agent",
            "labels": [L.SIMULATED, L.LOCAL] if (L.is_local(sandbox.label) or L.is_local(agents.label)) else [L.SIMULATED],
            "backend": {"name": agents.backend_name, "label": agents.label},
            "harness": dict(sorted(agents.info.items())),
            "n": {"value": k, "source": "--agents; each agent gets its own fork of the same checkpoint"},
            "steps": _pop_steps(target, agent_users, k, "populations[coding_agents].users[]"),
            "users": agent_users,
        })

    backends = {
        "sandbox": {"name": sandbox.name, "label": sandbox.label},
        "model": {"name": policy.backend_name, "label": policy.label},
        "grounding": {"name": grounding.name, "label": grounding.label},
    }
    any_local = any(L.is_local(b["label"]) for b in backends.values())
    all_local = all(L.is_local(b["label"]) or b["label"] == "NONE" for b in backends.values())
    run = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "seed": seed,
        "labels": [L.SIMULATED, L.LOCAL] if any_local else [L.SIMULATED],
        "policy": {"name": policy.name, "label": policy.label, "model": policy.model_info},
        "backends": backends,
        "target": {
            "name": target.meta["name"], "doc_url": target.meta["doc_url"],
            "doc_commit": target.meta["doc_commit"], "section": target.meta["section_start"],
            "wheel": ({"file": target.wheel.name, "sha256": target.meta["wheel_sha256"]}
                      if "scenario" not in target.meta else None),
            **({"scenario": {**target.meta["scenario"], "checkpoint_image_id": recipe["checkpoint_image_id"]}}
               if "scenario" in target.meta else {}),
            "goal": target.meta["goal"],
        },
        "doc": {"sha256": doc_sha, "patch": patch},
        "population": {
            "n": {"value": n, "source": f"--n; personas sampled from seed {seed} by {ASSUMPTIONS_SOURCE}"},
            "humans": {"value": n, "source": "every sampled persona is a simulated human developer"},
            "coding_agents": ({"status": "run", "reason": "see populations[coding_agents]",
                               "n": {"value": agents.k, "source": "--agents"}} if agents is not None else
                              {"status": "not_run", "reason": "not requested: run with --agents K (make demo AGENTS=K)"}),
        },
        "populations": populations,
        "cost": {"value": 0 if all_local else None, "unit": "USD",
                 "label": L.LOCAL if all_local else L.RUNTIME, "shown_before_run": True,
                 "source": ("local stand-ins bill nothing; this is not a projection of any hosted price"
                            if all_local else "Hosted cost unknown; check provider usage and billing. No zero-cost claim.")},
        "steps": steps,
        "users": users,
        "quotes": quotes,
        "grounding": {"backend": grounding.name, "label": grounding.label,
                      "items": {"value": len(grounding.items()), "source": getattr(grounding, "items_source", "rows in grounding/fixture.jsonl")}},
    }
    grounding.record(f"{target.meta['name']} quickstart problems")
    timing = {"run_id": run_id, "started_at": started_at, "label": sandbox.label,
              "note": ("Docker on this machine. Says nothing about Nebius fork times."
                       if L.is_local(sandbox.label) else "Client-observed elapsed time including remote calls; not isolated warm-fork latency."),
              "checkpoint_s": round(t_ckpt, 3), "total_s": round(time.monotonic() - t_start, 3),
              "per_user_s": dict(sorted(user_times.items()))}
    return run, timing


def write(run: dict, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(run)
    path.write_text(text, encoding="utf-8")
    return sha256_bytes(text.encode())
