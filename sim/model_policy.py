"""Model-driven policy. The model picks each next action; the fork executes it.

The client decides the backend: the LOCAL mlx server or Token Factory. The label of the
client travels into every quote, so a LOCAL-MODEL quote can never read as Nemotron's.
"""
from __future__ import annotations

import re

from sim.persona import STRANGER_RULES, Persona, describe
from sim.session import Session

FORMAT = """For the code block shown, answer with exactly one line, one of:
RUN            (run the block in your terminal as it is)
SAVE <name>    (save the block to a file with that exact name)
PASTE          (paste the block into the python prompt)
SKIP           (do nothing with it)
Use only what the docs say. Do not invent file names the docs do not give."""
LINE = re.compile(r"^\s*[`*]*\s*(RUN|SAVE|PASTE|SKIP)\b\s*[`'\"]?([\w.\-/]*)", re.I | re.M)


def _parse(text: str) -> tuple[str, str] | None:
    m = LINE.search(text)
    if not m:
        return None
    return m.group(1).upper(), m.group(2)


def _history(s: Session) -> str:
    rows = [f"- {e['action']} {e['detail'][:80]!r} -> exit {e['exit_code']}; output: {e['stdout_excerpt'][-160:]!r}"
            for e in s.log if e["action"] in ("run", "write", "paste_python")]
    return "\n".join(rows[-6:]) or "(nothing yet)"


def act(p: Persona, section: str, s: Session, client, *, seed: int, temperature: float = 0.0,
        blocks=None, els=None) -> tuple[bool, str | None]:
    """The model decides what to do with each code block in order. It cannot invent code:
    every command it runs and every file it writes is a block from the docs. Returns (gave_up, quote)."""
    system = f"{STRANGER_RULES}\n\n{describe(p)}"
    blocks = blocks or []
    els = els or [None] * len(blocks)
    for k, b in enumerate(blocks, 1):
        s.el = els[k - 1]
        user = (f"The docs section you are following:\n\n{section}\n\n"
                f"Your goal: {s.target.meta['goal']}\n\nWhat you did so far:\n{_history(s)}\n\n"
                f"You are now at code block {k} of {len(blocks)}:\n```{b.lang}\n{b.text}```\n\n{FORMAT}")
        reply = client.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                            temperature=temperature, seed=seed, max_tokens=24)
        a = _parse(reply.text)
        if a is None:
            s.note("skip", f"model reply did not parse: {reply.text.strip()[:80]!r}")
        elif a[0] == "RUN":
            s.run(b.text)
        elif a[0] == "SAVE" and a[1]:
            s.write(a[1], b.text)
        elif a[0] == "PASTE":
            s.paste_python(b.text)
        else:
            s.note("skip", "model chose to skip this block")
        if s.failures >= p.max_failures:
            s.note("give_up", f"stopped after {s.failures} failed command(s)")
            break
    else:
        s.el = None
        s.note("done", "reached the end of the section")
    gave_up = s.log[-1]["action"] == "give_up" if s.log else False
    reply = client.chat([{"role": "system", "content": system}, {"role": "user", "content":
                         f"Your goal was: {s.target.meta['goal']}\nWhat you did:\n{_history(s)}\n\n"
                         "In one plain sentence that starts with I, tell the person who owns these docs what happened to you."}],
                        temperature=temperature, seed=seed, max_tokens=80)
    q = reply.text.strip().splitlines()[0][:240] if reply.text.strip() else None
    return gave_up, q


class ModelPolicy:
    """name: LOCAL-MODEL or TOKEN-FACTORY. label: the client's label."""

    def __init__(self, *, name: str, client, runtime: str, seed: int, temperature: float = 0.0):
        self.name = name
        self.client = client
        self.label = client.label
        self.backend_name = f"{runtime} {client.model}"
        self.seed = seed
        self.temperature = temperature
        self.model_info = {"name": client.model, "runtime": runtime, "temperature": temperature, "seed": seed}

    def act(self, p: Persona, elements, section: str, s: Session):
        code = [(i, e) for i, e in enumerate(elements) if e.kind == "code"]
        gave_up, q = act(p, section, s, self.client, seed=self.seed, temperature=self.temperature,
                         blocks=[e for _, e in code], els=[i for i, _ in code])
        return gave_up, q, None
