"""Local command line. Uses the LOCAL stand-ins. The submission path lives in sim/submission.py."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sim import ROOT
from sim import labels as L
from sim.counterfactual import control_diff, delta, file_sha
from sim.doc import load_target, sha256_bytes, sha256_file
from sim.run import dumps, execute, run_id_for, write
from sim.tree import distinct_paths, render
from sim.validate import check, semantic

RUNS = ROOT / "runs"
DEFAULT_PATCH = ROOT / "target" / "python-dotenv" / "patches" / "explicit-steps.md"


def make_policy(name: str, seed: int):
    if name == "scripted":
        from sim.standins.scripted_policy import ScriptedPolicy
        return ScriptedPolicy(), None, 4
    if name == "local-model":
        from sim.model_policy import ModelPolicy
        from sim.standins.local_model import RUNTIME, LocalModel
        lm = LocalModel()
        lm.start()
        return ModelPolicy(name=L.LOCAL_MODEL, client=lm.client(), runtime=RUNTIME, seed=seed), lm, 1
    raise SystemExit(f"unknown policy {name!r}. Use scripted or local-model.")


def make_agents(k: int, seed: int, server):
    """Coding-agent population on the LOCAL model server. Starts the server if the policy did not."""
    if k <= 0:
        return None, server
    from sim.standins.coding_agent import AgentUnavailable, CodingAgents
    from sim.standins.local_model import MODEL, RUNTIME, LocalModel, LocalModelUnavailable
    try:
        if server is None:
            server = LocalModel()
            server.start()
        return CodingAgents(k=k, base_url=server.base_url, model=MODEL, runtime=RUNTIME, seed=seed), server
    except (AgentUnavailable, LocalModelUnavailable) as e:
        if server is not None:
            server.stop()
        raise SystemExit(f"Coding agents cannot run: {e} They need make agent and make model.")


def _stand_ins():
    from sim.standins.docker_sandbox import DockerSandbox, docker_ok
    from sim.standins.fixture_grounding import FixtureGrounding
    if not docker_ok():
        raise SystemExit("Docker is not running. Start Docker Desktop, then run make setup.")
    return DockerSandbox(), FixtureGrounding()


def cmd_setup(a) -> int:
    from sim.standins.docker_sandbox import BASE_IMAGE, DockerSandbox, _docker, docker_ok
    if not docker_ok():
        print("Docker is not running. Start Docker Desktop and run this again.")
        return 1
    if _docker("image", "inspect", BASE_IMAGE, check=False).returncode != 0:
        print(f"Pulling {BASE_IMAGE}. This needs network, once.")
        _docker("pull", "-q", BASE_IMAGE, timeout=900)
    t = load_target()
    tag, _ = DockerSandbox().checkpoint(t.wheel, t.meta["wheel_sha256"])
    print(f"Checkpoint ready: {tag}. The demo runs offline from here.")
    return 0


def _bar(k: int, n: int, width: int = 20) -> str:
    fill = round(width * k / n) if n else 0
    return "#" * fill + "." * (width - fill)


def _policy_line(policy) -> str:
    if policy.name == L.LOCAL_SCRIPTED:
        return "Simulated users: scripted readers (LOCAL-SCRIPTED). No model ran."
    return f"Simulated users: {policy.backend_name} on this machine (LOCAL-MODEL). This is not Nemotron."


def cmd_demo(a) -> int:
    target = load_target()
    patch_path = Path(a.patch).resolve()
    base_section = target.base_section()
    head_section = patch_path.read_text(encoding="utf-8")
    sandbox, grounding = _stand_ins()
    policy, server, workers = make_policy(a.policy, a.seed)
    agents, server = make_agents(a.agents, a.seed, server)
    try:
        print(f"Target: {target.meta['name']} README, section \"Getting Started\", pinned copy fetched {target.meta['doc_fetched']}.")
        print(f"Goal: {target.meta['goal']}")
        print(_policy_line(policy))
        print("Sandbox: one Docker checkpoint on this machine, one fork per user, no network (LOCAL).")
        print("Grounding: hand-copied public issue links (LOCAL-FIXTURE). No search API ran.")
        print(f"Cost of this run: 0 USD (LOCAL). Local stand-ins bill nothing. Users: {a.n}. Seed: {a.seed}.")
        if agents is not None:
            print(f"Coding agents: {agents.k}, {agents.backend_name} on this machine (LOCAL-MODEL), "
                  f"at most {agents.step_limit} model calls each, in forks of the same checkpoint. SIMULATED, LOCAL.")
        print("Every result below is SIMULATED.\n")

        common = dict(target=target, n=a.n, policy=policy, sandbox=sandbox, grounding=grounding, workers=workers,
                      agents=agents)
        print("1/3 Base run on the published section ...", flush=True)
        base, t1 = execute(section=base_section, patch=None, seed=a.seed, **common)
        base_file = RUNS / f"{base['run_id']}.json"
        base_sha = write(base, base_file)
        (RUNS / f"{base['run_id']}.timing.json").write_text(dumps(t1))

        print("2/3 Control run: same seeds, same checkpoint, no patch ...", flush=True)
        cseed = a.seed if a.control_seed is None else a.control_seed
        control, t2 = execute(section=base_section, patch=None, seed=cseed, **common)
        control_file = RUNS / f"{base['run_id']}.control.json"
        control_sha = write(control, control_file)
        if base_sha != control_sha:
            print("\nCONTROL FAILED. The no-patch rerun did not match the base run byte for byte.")
            print("The same-seed claim is false for this run, so no delta is reported.")
            for line in control_diff(base_file.read_text(), control_file.read_text()):
                print("  " + line)
            return 2
        print("    Control matched the base run byte for byte.")

        print("3/3 Patched run: same seeds, same checkpoint ...", flush=True)
        patch = {"file": str(patch_path.relative_to(ROOT)) if patch_path.is_relative_to(ROOT) else patch_path.name,
                 "sha256": sha256_file(patch_path)}
        head, t3 = execute(section=head_section, patch=patch, seed=a.seed, **common)
        head_file = RUNS / f"{head['run_id']}.json"
        write(head, head_file)
        (RUNS / f"{head['run_id']}.timing.json").write_text(dumps(t3))
    finally:
        if server is not None:
            server.stop()

    for doc in (base, head):
        errs = check(doc) + semantic(doc)
        if errs:
            print("Run file failed the schema:", *errs[:10], sep="\n  ")
            return 3
    rel = lambda p: str(p.relative_to(ROOT))
    d = delta(base, head, base_file=rel(base_file), head_file=rel(head_file), base_sha=base_sha, control_sha=control_sha)
    errs = check(d, "delta.schema.json")
    if errs:
        print("Delta failed the schema:", *errs[:10], sep="\n  ")
        return 3
    delta_file = RUNS / f"delta-{base['run_id']}-{head['run_id']}.json"
    delta_file.write_text(dumps(d))
    report(base, head, d, delta_file)
    if agents is not None:
        report_populations(base, head, rel(base_file), rel(head_file))
    return 0


def report(base: dict, head: dict, d: dict, delta_file: Path) -> None:
    n = d["n"]["value"]
    goal_b, goal_h = d["base"]["goal_reached"]["value"], d["head"]["goal_reached"]["value"]
    imp, wor = d["paired"]["improved"]["value"], d["paired"]["worsened"]["value"]
    p = d["paired"]["p_value"]["value"]
    verdict = {"helps": "The doc patch HELPS onboarding.", "hurts": "The doc patch HURTS onboarding.",
               "no detectable change": "NO DETECTABLE CHANGE from the doc patch."}[d["direction"]]
    print(f"\nDirection: {verdict}  [SIMULATED, LOCAL]")
    print(f"  Same {n} users, same seeds. {imp} reached the goal only with the patch, {wor} only without it.")
    ptxt = "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
    print(f"  Exact sign test on those pairs: {ptxt}. Direction is called only when p < 0.05.")
    pts = d["magnitude"]["goal_rate_change"] * 100
    print(f"Size: {goal_b}/{n} to {goal_h}/{n} reached the goal ({pts:+.1f} points).  [uncalibrated]")
    print("  The size is not scored against real users yet. Trust the direction before the size.")
    pb, ph = distinct_paths(base), distinct_paths(head)
    print(f"  Distinct paths through the docs: {pb} of {n} users on the published section, {ph} of {n} with the patch.")
    if min(pb, ph) < n / 2:
        print("  Most users took the same few paths. The result depends on how the persona weights split users")
        print("  between those paths, and those weights are assumptions, not measurements.")
    titles = {s["id"]: s["title"] for s in base["steps"]}
    back = d["paired"]["steps_back"]
    if back["value"]:
        print(f"Step back: {back['value']} of {n} users got stuck at an earlier step with the patch.  [SIMULATED, LOCAL]")
        print("  The direction counts only the goal, so these users do not show in the pairs above.")
        for m in back["moves"]:
            print(f"  {m['user']} got past \"{titles[m['base_furthest']]}\" on the published section"
                  f" and stopped at \"{titles[m['step']]}\" with the patch.")
    else:
        print("Step back: no user got stuck at an earlier step with the patch.  [SIMULATED, LOCAL]")
    print()
    print(f"  {'Step':34} {'published':>10}   {'patched':>10}")
    for bs, hs in zip(base["steps"], head["steps"]):
        kb, kh = bs["reached"]["value"], hs["reached"]["value"]
        print(f"  {bs['title'][:34]:34} {kb:>4}/{n:<4} {_bar(kb, n, 10)} {kh:>4}/{n:<4} {_bar(kh, n, 10)}")
    for title, run, f in (("on the published section", base, d["base"]["file"]), ("with the patch", head, d["head"]["file"])):
        print()
        for line in render(run, f, title):
            print(line)
    for title, run in (("on the published section", base), ("with the patch, among users who missed the goal", head)):
        goal = run["steps"][-1]["id"]
        qs = [q for q in run["quotes"] if q["step"] is not None or goal not in
              next(u["reached"] for u in run["users"] if u["id"] == q["user"])]
        if not qs:
            continue
        print(f"\nWhat simulated users said {title}  [SIMULATED, LOCAL]:")
        seen = set()
        for q in qs:
            if q["text"] in seen:
                continue
            seen.add(q["text"])
            k = sum(1 for x in qs if x["text"] == q["text"])
            g = f"\n      Related real issue (LOCAL-FIXTURE): {q['grounding']['url']}" if q["grounding"] else ""
            print(f"  {k:>3}x \"{q['text']}\"{g}")
            if len(seen) >= 4:
                break
    print(f"\nFiles: {delta_file} and the two run files it names.")


def _paths(users: list[dict]) -> int:
    return len({json.dumps([(e["action"], e["detail"]) for e in u["log"]]) for u in users})


def _cell(st: dict, n: int) -> str:
    k = st["reached"]["value"]
    return f"{k:>3}/{n:<3} {_bar(k, n, 8)}"


def report_populations(base: dict, head: dict, base_file: str, head_file: str) -> list[str]:
    """Humans and coding agents side by side, per step, on both doc versions. Returns the printed lines."""
    lines = []
    say = lines.append
    pops = {r: {p["id"]: p for p in run["populations"]} for r, run in (("base", base), ("head", head))}
    h_b, h_h = pops["base"]["humans"], pops["head"]["humans"]
    a_b, a_h = pops["base"]["coding_agents"], pops["head"]["coding_agents"]
    nh, na = h_b["n"]["value"], a_b["n"]["value"]
    say("")
    say("Humans and coding agents, same checkpoint, same forks  [SIMULATED, LOCAL]")
    say("  Each cell: how many of the population reached the step. Bar width: that count over the population.")
    say(f"  {'Step':32} {'humans published':>16}  {'humans patched':>16}  {'agents published':>16}  {'agents patched':>16}")
    for i, bs in enumerate(base["steps"]):
        say(f"  {bs['title'][:32]:32} {_cell(h_b['steps'][i], nh):>16}  {_cell(h_h['steps'][i], nh):>16}  "
            f"{_cell(a_b['steps'][i], na):>16}  {_cell(a_h['steps'][i], na):>16}")
    hname = "scripted readers, no model" if h_b["backend"]["label"] == L.LOCAL_SCRIPTED else h_b["backend"]["name"]
    say(f"  humans: {hname} ({h_b['backend']['label']}), n {nh}. "
        f"Labels: {', '.join(h_b['labels'])}.")
    say(f"  coding agents: {a_b['backend']['name']} ({a_b['backend']['label']}), n {na}. "
        f"Labels: {', '.join(a_b['labels'])}.")
    say(f"  Distinct paths: humans {_paths(base['users'])} published, {_paths(head['users'])} patched. "
        f"Coding agents {_paths(a_b['users'])} published, {_paths(a_h['users'])} patched.")
    say(f"  Source: populations[] in {base_file} (published) and {head_file} (patched).")
    for label, pop, f in (("published", a_b, base_file), ("patched", a_h, head_file)):
        for u in pop["users"]:
            runs = [e for e in u["log"] if e["action"] == "run"]
            failed = [e for e in runs if e["exit_code"] != 0]
            stop = u["dropped_at"] or "none, reached the goal"
            say(f"  Agent {u['id']} on the {label} section: {u['exit_status']} after {len(runs)} command(s), "
                f"{len(failed)} failed. First missed step: {stop}.")
            for e in failed[:2]:
                say(f"    log {e['i']}: exit {e['exit_code']}: {e['detail'].splitlines()[0][:70]}")
            say(f"    Source: {f}, populations[coding_agents].users[{u['id']}].log")
    print("\n".join(lines))
    return lines


def cmd_tree(a) -> int:
    """Print the fork tree of run files that already exist. Runs nothing."""
    if a.run:
        files = [Path(f) for f in a.run]
    else:
        if a.policy != "scripted":
            raise SystemExit("Only the scripted policy can be found by seed. Pass the run file with --run.")
        from sim.standins.docker_sandbox import DockerSandbox, DockerUnavailable, docker_ok
        from sim.standins.scripted_policy import ScriptedPolicy
        if not docker_ok():
            raise SystemExit("Docker is not running, so the run id cannot be worked out. Pass --run runs/<id>.json.")
        target = load_target()
        try:
            recipe = DockerSandbox().recipe(target.wheel, target.meta["wheel_sha256"])
        except DockerUnavailable as e:
            raise SystemExit(str(e))
        files = []
        for section in (target.base_section(), Path(a.patch).resolve().read_text(encoding="utf-8")):
            rid = run_id_for(seed=a.seed, doc_sha=sha256_bytes(section.encode()), policy_name=ScriptedPolicy.name,
                             model_info=None, n=a.n, recipe=recipe)
            files.append(RUNS / f"{rid}.json")
    titles = ["on the published section", "with the patch"] if not a.run else [None] * len(files)
    rc = 0
    for f, title in zip(files, titles):
        if not f.exists():
            print(f"No run file at {f.relative_to(ROOT) if f.is_relative_to(ROOT) else f} for seed {a.seed}, n {a.n} on this code.")
            print(f"Run make demo SEED={a.seed} N={a.n} first, or pass --run runs/<id>.json.")
            rc = 1
            continue
        run = json.loads(f.read_text())
        if "users" not in run or "policy" not in run:
            print(f"{f}: not a run file. Pass runs/<id>.json, not a delta or timing file.")
            rc = 1
            continue
        src = str(f.resolve().relative_to(ROOT)) if f.resolve().is_relative_to(ROOT) else str(f)
        for line in render(run, src, title or f"in {src}"):
            print(line)
        print()
    return rc


def cmd_validate(a) -> int:
    rc = 0
    for f in a.files:
        doc = json.loads(Path(f).read_text())
        if "per_user_s" in doc:
            print(f"{f}: timing file, not validated")
            continue
        schema = "delta.schema.json" if "paired" in doc else "run.schema.json"
        errs = check(doc, schema)
        if schema == "run.schema.json":
            errs += semantic(doc)
        print(f"{f}: {'ok' if not errs else 'INVALID'}")
        for e in errs[:20]:
            print("  " + e)
        rc |= bool(errs)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    from sim.compare import add_parser, cmd_compare
    add_parser(sub)
    from sim.workspace import add_parser as workspace_parser, cmd_workspace
    workspace_parser(sub)
    d = sub.add_parser("demo")
    d.add_argument("--policy", default="scripted", choices=["scripted", "local-model"])
    d.add_argument("--n", type=int, default=24)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--patch", default=str(DEFAULT_PATCH))
    d.add_argument("--agents", type=int, default=0, help="coding agents to run beside the humans (needs make agent, make model)")
    d.add_argument("--control-seed", type=int, default=None, help="test only: break the control on purpose")
    t = sub.add_parser("tree", help="print where simulated users split, from existing run files")
    t.add_argument("--seed", type=int, default=7)
    t.add_argument("--n", type=int, default=24)
    t.add_argument("--policy", default="scripted", choices=["scripted", "local-model"])
    t.add_argument("--patch", default=str(DEFAULT_PATCH))
    t.add_argument("--run", nargs="+", default=None, help="run files to read instead of finding them by seed")
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    return {"setup": cmd_setup, "demo": cmd_demo, "tree": cmd_tree, "validate": cmd_validate, "compare": cmd_compare, "workspace": cmd_workspace}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
