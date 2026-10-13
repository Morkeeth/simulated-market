"""Coding-agent stand-in: mini-swe-agent driven by the LOCAL mlx model, acting in the same forks.

Two halves in one file:

- Parent (standard library only, imported by sim.cli): CodingAgents. For each agent it
  starts a child process with the .venv-agent interpreter, then replays the child's steps
  into a Session so the agent log has the same shape as a simulated human's log.
- Child (`.venv-agent/bin/python -m sim.standins.coding_agent ...`): runs the real
  mini-swe-agent DefaultAgent with a ForkEnvironment whose execute() calls Fork.exec.
  The agent acts in the same checkpoint and the same `--network none` fork as a human.

The model is mlx_lm.server on this machine (temperature 0, no prompt cache, no batching),
reached through mini-swe-agent's litellm text-based model. Everything is labelled LOCAL.
The child writes only commands, exit codes and outputs. Timestamps, cost and litellm
response metadata never leave the child, so the run file stays byte-identical on rerun.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from sim import ROOT
from sim.labels import LOCAL_MODEL

from sim.agent_protocol import (HARNESS, HARNESS_VERSION, STEP_LIMIT, MAX_TOKENS,
    OUTPUT_CAP, SUBMIT, SYSTEM, INSTANCE, OBSERVATION, AgentUnavailable,
    task_text, runs_marked_code)
VENV = ROOT / ".venv-agent"
PYTHON = VENV / "bin" / "python"

# ---------------------------------------------------------------- parent side

class CodingAgents:
    """K coding agents, run serially against one local model server."""

    label = LOCAL_MODEL

    def __init__(self, *, k: int, base_url: str, model: str, runtime: str, seed: int,
                 step_limit: int = STEP_LIMIT):
        if not PYTHON.exists():
            raise AgentUnavailable(f"{PYTHON} not found. Run make agent first.")
        self.k = k
        self.base_url = base_url
        self.model = model
        self.runtime = runtime
        self.seed = seed
        self.step_limit = step_limit
        self.backend_name = f"{HARNESS} {HARNESS_VERSION} with {runtime} {model}"
        self.info = {"k": k, "harness": HARNESS, "harness_version": HARNESS_VERSION, "model": model,
                     "runtime": runtime, "temperature": 0.0, "seed": seed, "step_limit": step_limit,
                     "max_tokens": MAX_TOKENS, "output_cap": OUTPUT_CAP}

    def act(self, s, section: str) -> str:
        """Run one agent in the session's fork. Replays its steps into the session log. Returns exit status."""
        with tempfile.TemporaryDirectory(prefix="simagent-") as tmp:
            out_file = Path(tmp) / "steps.json"
            task_file = Path(tmp) / "task.txt"
            task_file.write_text(task_text(s.target.meta, section), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
            env.update(MSWEA_SILENT_STARTUP="1", MSWEA_GLOBAL_CONFIG_DIR=str(Path(tmp) / "mswea"),
                       MSWEA_COST_TRACKING="ignore_errors", LITELLM_LOCAL_MODEL_COST_MAP="True",
                       PYTHONHASHSEED="0")
            cmd = [str(PYTHON), "-m", "sim.standins.coding_agent", "--fork", s.fork.name,
                   "--base-url", self.base_url, "--model", self.model, "--seed", str(self.seed),
                   "--step-limit", str(self.step_limit), "--marker", s.target.meta["app_marker"],
                   "--task-file", str(task_file), "--out", str(out_file)]
            p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=3600)
            if p.returncode != 0 or not out_file.exists():
                raise AgentUnavailable(f"coding agent child failed: {(p.stderr or p.stdout).strip()[-600:]}")
            result = json.loads(out_file.read_text(encoding="utf-8"))
        return replay(s, result)


def replay(s, result: dict) -> str:
    """Map the child's steps into the Session log shape. Pure function of the child output."""
    for st in result["steps"]:
        if st["kind"] == "run":
            s.record("run", st["command"], st["returncode"], st["output"], marker_run=st["marker_run"])
        elif st["kind"] == "format_error":
            s.record("skip", f"agent reply had no single command: {st['text'][:120]!r}", None, None)
    status = result["exit_status"]
    if status == "Submitted":
        s.record("done", "agent submitted", None, None)
    else:
        s.record("give_up", f"agent stopped: {status}", None, None)
    return status


# ---------------------------------------------------------------- child side

def _child(a) -> int:
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.exceptions import FormatError, Submitted
    from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel

    from sim.standins.docker_sandbox import Fork

    fork = Fork(name=a.fork)
    steps: list[dict] = []

    def read_file(path: str) -> str | None:
        code, out = fork.exec(["cat", path])
        return out if code == 0 else None

    class ForkEnvironment:
        """mini-swe-agent Environment. execute() is Fork.exec: same checkpoint, same no-network fork."""

        def __init__(self):
            self.config = None

        def execute(self, action: dict, cwd: str = "") -> dict:
            command = action.get("command", "")
            code, out = fork.exec(["bash", "-c", command])
            lines = out.lstrip().splitlines(keepends=True)
            if lines and lines[0].strip() == SUBMIT and code == 0:
                raise Submitted({"role": "exit", "content": "".join(lines[1:]),
                                 "extra": {"exit_status": "Submitted", "submission": "".join(lines[1:])}})
            steps.append({"kind": "run", "command": command.strip(), "returncode": code, "output": out,
                          "marker_run": runs_marked_code(command, read_file, a.marker)})
            return {"output": out, "returncode": code, "exception_info": ""}

        def get_template_vars(self, **kwargs) -> dict:
            return {}

        def serialize(self) -> dict:
            return {}

    class LoggedAgent(DefaultAgent):
        def step(self):
            try:
                return super().step()
            except FormatError as e:
                steps.append({"kind": "format_error", "text": e.messages[0]["extra"].get("model_response", "")})
                raise

    model = LitellmTextbasedModel(
        model_name=f"openai/{a.model}", cost_tracking="ignore_errors", observation_template=OBSERVATION,
        model_kwargs={"api_base": a.base_url, "api_key": "local", "temperature": 0.0, "seed": a.seed,
                      "max_tokens": MAX_TOKENS, "drop_params": True})
    agent = LoggedAgent(model, ForkEnvironment(), system_template=SYSTEM, instance_template=INSTANCE,
                        step_limit=a.step_limit, cost_limit=0.0, max_consecutive_format_errors=3)
    task = Path(a.task_file).read_text(encoding="utf-8")
    exit_info = agent.run(task)
    status = exit_info.get("exit_status") or "unknown"
    Path(a.out).write_text(json.dumps({"exit_status": status, "steps": steps}, sort_keys=True), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sim.standins.coding_agent")
    for flag in ("--fork", "--base-url", "--model", "--marker", "--task-file", "--out"):
        ap.add_argument(flag, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--step-limit", type=int, default=STEP_LIMIT)
    return _child(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
