"""Submission guard. Fails if the submission path can reach a stand-in, or a LOCAL row lost its label.

Three checks:
1. Static: walk every import statement (including ones inside functions) reachable from
   sim.submission inside the sim package. No sim.standins module may appear.
2. Runtime: import sim.submission in a fresh interpreter and list sys.modules.
3. Run files: any run whose policy or a backend is LOCAL must carry the LOCAL label, and
   so must every quote and every population in it. With --submission, a LOCAL run fails outright.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

from sim import ROOT
from sim import labels as L

FORBIDDEN = "sim.standins"


def _module_file(root: Path, mod: str) -> Path | None:
    base = root.joinpath(*mod.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.exists():
            return p
    return None


def _imports(path: Path, mod: str) -> set[str]:
    tree = ast.parse(path.read_text(), str(path))
    pkg = mod if path.name == "__init__.py" else mod.rpartition(".")[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = pkg.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                name = f"{base}.{node.module}" if node.module else base
            else:
                name = node.module or ""
            out.add(name)
            out |= {f"{name}.{a.name}" for a in node.names}
    return out


def static_closure(root: Path = ROOT, entry: str = "sim.submission") -> tuple[set[str], list[str]]:
    seen: set[str] = set()
    bad: list[str] = []
    todo = [entry]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        if mod == FORBIDDEN or mod.startswith(FORBIDDEN + "."):
            bad.append(mod)
            continue
        f = _module_file(root, mod)
        if f is None:
            continue
        parts = mod.split(".")
        for i in range(1, len(parts)):
            todo.append(".".join(parts[:i]))
        for m in _imports(f, mod):
            if m == "sim" or m.startswith("sim."):
                todo.append(m)
    return seen, sorted(set(bad))


def runtime_check(root: Path = ROOT, entry: str = "sim.submission") -> list[str]:
    code = (f"import sys; import {entry}; "
            f"print('\\n'.join(sorted(m for m in sys.modules if m == '{FORBIDDEN}' or m.startswith('{FORBIDDEN}.'))))")
    p = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    if p.returncode != 0:
        return [f"import of {entry} failed: {p.stderr.strip()[-300:]}"]
    return [x for x in p.stdout.split() if x]


def label_problems(run: dict, *, submission: bool = False) -> list[str]:
    out = []
    locals_ = [k for k, b in run.get("backends", {}).items() if L.is_local(b.get("label", ""))]
    if L.is_local(run.get("policy", {}).get("label", "")):
        locals_.append("policy")
    if locals_:
        if submission:
            out.append(f"{run.get('run_id')}: submission run used LOCAL {', '.join(locals_)}")
        if L.LOCAL not in run.get("labels", []):
            out.append(f"{run.get('run_id')}: LOCAL {', '.join(locals_)} but the run has no LOCAL label")
        for i, q in enumerate(run.get("quotes", [])):
            if L.LOCAL not in q.get("labels", []):
                out.append(f"{run.get('run_id')}: quote {i} from a LOCAL run has no LOCAL label")
    for pop in run.get("populations", []):
        if L.SIMULATED not in pop.get("labels", []):
            out.append(f"{run.get('run_id')}: population {pop.get('id')} has no SIMULATED label")
        if (locals_ or L.is_local(pop.get("backend", {}).get("label", ""))) and L.LOCAL not in pop.get("labels", []):
            out.append(f"{run.get('run_id')}: population {pop.get('id')} is LOCAL but has no LOCAL label")
        if submission and L.is_local(pop.get("backend", {}).get("label", "")):
            out.append(f"{run.get('run_id')}: submission run used a LOCAL {pop.get('id')} population")
    if L.SIMULATED not in run.get("labels", []):
        out.append(f"{run.get('run_id')}: missing SIMULATED label")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sim.guard")
    ap.add_argument("runs", nargs="*", help="run files to scan (default: runs/*.json)")
    ap.add_argument("--submission", action="store_true", help="fail on any LOCAL run")
    a = ap.parse_args(argv)
    problems: list[str] = []
    seen, bad = static_closure()
    problems += [f"static: sim.submission can reach {m}" for m in bad]
    problems += [f"runtime: importing sim.submission loaded {m}" for m in runtime_check()]
    files = [Path(f) for f in a.runs] or sorted((ROOT / "runs").glob("*.json"))
    n_runs = 0
    for f in files:
        doc = json.loads(f.read_text())
        if "users" not in doc:
            continue  # delta or timing file
        n_runs += 1
        problems += label_problems(doc, submission=a.submission)
    if problems:
        print("SUBMISSION GUARD: RED")
        for p in problems:
            print("  " + p)
        return 1
    real = [m for m in seen if _module_file(ROOT, m) is not None]
    print(f"SUBMISSION GUARD: green. {len(real)} sim modules reachable from sim.submission, none in {FORBIDDEN}. "
          f"{n_runs} run file(s) scanned for labels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
