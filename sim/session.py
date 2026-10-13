"""One simulated user in one fork: act, log every command, then probe the fork for the funnel."""
from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass, field

from sim.doc import Element, Target
from sim.persona import Persona

EXCERPT = 240
RUN_FILE = re.compile(r"^\s*(?:python3?|py)\s+(\S+\.py)\s*$")


@dataclass
class Session:
    persona: Persona
    fork: object
    target: Target
    log: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    python_runs: list[tuple[int, str]] = field(default_factory=list)  # (exit, stdout) of code with the app marker
    failures: int = 0
    last_failure: dict | None = None
    el: int | None = None  # index of the doc element the policy is acting on; None after the last one

    def _entry(self, action: str, detail: str, code, out: str | None) -> dict:
        e = {
            "i": len(self.log),
            "el": self.el,
            "action": action,
            "detail": detail,
            "exit_code": code,
            "stdout_sha256": hashlib.sha256(out.encode()).hexdigest() if out is not None else None,
            "stdout_excerpt": (out or "").strip()[-EXCERPT:],
        }
        self.log.append(e)
        if code not in (None, 0):
            self.failures += 1
            self.last_failure = e
        return e

    def _marker_run(self, source: str, code: int, out: str) -> None:
        if self.target.meta["app_marker"] in source:
            self.python_runs.append((code, out))

    def run(self, command: str) -> dict:
        code, out = self.fork.exec(["bash", "-c", command])
        m = RUN_FILE.match(command.strip()) if "\n" not in command.strip() else None
        if m and m.group(1) in self.files:
            self._marker_run(self.files[m.group(1)], code, out)
        return self._entry("run", command.strip(), code, out)

    def write(self, path: str, content: str) -> dict:
        if not re.fullmatch(r"[\w.\-/]+", path) or path.startswith("/") or ".." in path:
            return self._entry("skip", f"refused to write unsafe path {path!r}", None, None)
        code, out = self.fork.exec(["sh", "-c", f"cat > {shlex.quote(path)}"], stdin=content.encode())
        if code == 0:
            self.files[path] = content
        return self._entry("write", path, code, out)

    def paste_python(self, source: str) -> dict:
        # python -c, not python - : like a pasted REPL session, __main__ has no __file__.
        code, out = self.fork.exec(["python", "-c", source])
        self._marker_run(source, code, out)
        return self._entry("paste_python", "pasted the Python block into python", code, out)

    def note(self, action: str, detail: str) -> dict:
        return self._entry(action, detail, None, None)

    def record(self, action: str, detail: str, code, out: str | None, *, marker_run: bool = False) -> dict:
        """Log a step that already ran in this fork (a coding agent's command). Same entry shape."""
        if marker_run and code is not None:
            self.python_runs.append((code, out or ""))
        return self._entry(action, detail.strip(), code, out)

    _scenario_reached: list[str] | None = None

    # Funnel, decided after the session from the fork and the log.
    def probe(self) -> list[str]:
        meta = self.target.meta
        if self._scenario_reached is not None:
            return list(self._scenario_reached)
        reached = []
        for step in meta["steps"]:
            sid = step["id"]
            if "probe" in step:
                code, out = self.fork.exec(["bash", "-c", step["probe"]])
                self._entry("probe", f"{sid}: {step['probe']}", code, out)
                ok = code == 0
            elif sid == "installed":
                ok = self.fork.exec(["python", "-c", meta["installed_probe"]])[0] == 0
            elif sid == "env_file":
                ok = self.fork.exec(["python", "-c", meta["env_probe"]])[0] == 0
            elif sid == "app_ran":
                ok = any(c == 0 for c, _ in self.python_runs)
            elif sid == "saw_value":
                ok = any(c == 0 and meta["goal_value"] in o for c, o in self.python_runs)
            else:
                raise ValueError(f"unknown step {sid}")
            if not ok:
                break
            reached.append(sid)
        if "scenario" in meta:
            self._scenario_reached = list(reached)
        return reached


def code_blocks(elements: list[Element]) -> list[Element]:
    return [e for e in elements if e.kind == "code"]
