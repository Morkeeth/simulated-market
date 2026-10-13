"""LOCAL-SCRIPTED policy: a deterministic reader that follows the docs literally. No model runs.

How it reads a code block:
- A directory diagram is skipped. A persona who reads diagrams remembers its file names.
- The block gets a file name from, in order: a first-line comment such as `# foo.py`
  (novices who skim prose miss it), a file name in the prose right above it (prose
  readers only), a matching name from a diagram seen earlier (diagram readers only).
- With a file name, the block is written to that file. Nothing runs it unless the docs
  say to run it.
- Without one, a shell block runs in bash, a Python block is pasted into `python`, and
  anything else is skipped. That is the degraded path a literal newcomer takes.
- Prose follows the persona's reading style. linear reads prose when reads_prose is true
  (the original rule). skim reads only the first prose paragraph after each heading.
  code_only reads no prose. A novice who does not read prose linearly misses the
  first-line file comment.
- A persona with retries tries once more after a failed `run`. An expert whose `pip`
  command failed reruns it as `python -m pip`. Anyone whose `python <file>.py` failed
  because the file was never saved, after pasting a Python block, saves that block
  under the name and reruns the command. A retry that succeeds does not count toward
  giving up. Personas without retries keep the original rule.
- After as many failed commands as the persona's patience allows, the persona gives up.

Quotes are fixed sentences picked by what happened in the fork. They are labelled
SIMULATED and LOCAL-SCRIPTED. They are not model output.
"""
from __future__ import annotations

import re

from sim.labels import LOCAL_SCRIPTED
from sim.persona import Persona
from sim.session import Session

NAME = LOCAL_SCRIPTED
SHELL = {"shell", "bash", "sh", "console", "zsh"}
FIRST_LINE_FILE = re.compile(r"^#\s*(\.?[\w\-]+(?:\.[\w\-]+)*)\s*$")
TICKED = re.compile(r"`(\.?[\w\-/]+\.?[\w\-]*)`")
ENV_LINE = re.compile(r"^\s*(#.*|[A-Za-z_][A-Za-z0-9_]*=.*)?$")
PIP = re.compile(r"^\s*pip3?\s+(.+)$")
RUN_PY = re.compile(r"^\s*python3?\s+(\S+\.py)\s*$")


def _is_tree(text: str) -> bool:
    return "├" in text or "└" in text


def _tree_files(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"[├└]──\s*(\S+)", text)]


def _env_like(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and all(ENV_LINE.match(ln) for ln in lines) and any("=" in ln for ln in lines)


def _looks_like_file(name: str) -> bool:
    return "." in name and not name.endswith(".") and "(" not in name


def _match(names: list[str], lang: str, text: str) -> str | None:
    for n in names:
        if lang == "python" and n.endswith(".py"):
            return n
        if _env_like(text) and n.startswith(".") and not n.endswith(".py"):
            return n
    return None


class _Prose:
    """Which prose paragraphs a persona reads, by reading style."""

    def __init__(self, p: Persona):
        self.p = p
        self.after_heading = False

    def names(self, text: str) -> list[str] | None:
        """File names the persona takes from this prose element, or None if it read none of it."""
        style = self.p.reading_style
        if style == "code_only":
            return None
        if style == "linear":
            return [n for n in TICKED.findall(text) if _looks_like_file(n)] if self.p.reads_prose else None
        read: list[str] | None = None
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if para.startswith("#"):
                self.after_heading = True
                continue
            if self.after_heading:
                self.after_heading = False
                read = (read or []) + [n for n in TICKED.findall(para) if _looks_like_file(n)]
        return read


def _retry(p: Persona, s: Session, entry: dict, pasted: str | None) -> bool:
    """One more try after a failed run. Returns True if the retry succeeded."""
    cmd = entry["detail"]
    m = PIP.match(cmd) if "\n" not in cmd else None
    if m and p.skill == "expert":
        return s.run(f"python -m pip {m.group(1)}")["exit_code"] == 0
    m = RUN_PY.match(cmd) if "\n" not in cmd else None
    if m and m.group(1) not in s.files and pasted is not None:
        if s.write(m.group(1), pasted)["exit_code"] != 0:
            return False
        return s.run(cmd)["exit_code"] == 0
    return False


def act(p: Persona, elements, s: Session) -> bool:
    """Walk the doc. Returns True if the persona gave up."""
    recent_prose: list[str] = []
    tree: list[str] = []
    prose = _Prose(p)
    pasted: str | None = None
    recovered = 0
    linear_reader = p.reads_prose and p.reading_style == "linear"
    for idx, el in enumerate(elements):
        s.el = idx
        if el.kind == "prose":
            names = prose.names(el.text)
            if names is not None:
                recent_prose = names
            continue
        text, lang = el.text, el.lang
        if _is_tree(text):
            s.note("skip", "directory diagram")
            if p.reads_diagrams:
                tree = _tree_files(text)
            recent_prose = []
            continue
        fname = None
        m = FIRST_LINE_FILE.match(text.splitlines()[0]) if text.strip() else None
        if m and _looks_like_file(m.group(1)) and (p.skill != "novice" or linear_reader):
            fname = m.group(1)
        if fname is None:
            fname = _match(recent_prose, lang, text)
        if fname is None and p.reads_diagrams:
            fname = _match(tree, lang, text)
        recent_prose = []
        before = len(s.log)
        if fname:
            s.write(fname, text)
        elif lang in SHELL:
            s.run(text)
        elif lang == "python":
            s.paste_python(text)
            pasted = text
        else:
            s.note("skip", f"code block with no language ({len(text.splitlines())} lines)")
        e = s.log[before] if len(s.log) > before else None
        if p.retries and e is not None and e["action"] == "run" and e["exit_code"] not in (None, 0):
            recovered += _retry(p, s, e, pasted)
        if s.failures - recovered >= p.max_failures:
            s.note("give_up", f"stopped after {s.failures} failed command(s)")
            return True
    s.el = None
    s.note("done", "reached the end of the section")
    return False


def quote(s: Session, reached: list[str], dropped_at: str | None, gave_up: bool) -> tuple[str, str | None]:
    """Pick the sentence that matches what happened. Returns (text, grounding topic)."""
    if "scenario" in s.target.meta:
        return (("The goal check passed." if dropped_at is None else
                 f"The first unmet check was {dropped_at}."), None)
    value = s.target.meta["goal_value"]
    if dropped_at is None:
        return f"It printed {value}, so I knew the .env file loaded.", None
    if gave_up and s.last_failure is not None:
        last = (s.last_failure["stdout_excerpt"].splitlines() or [""])[-1][:120]
        return (f"I stopped when `{s.last_failure['detail'][:60]}` failed with: {last}",
                "env_location" if dropped_at == "env_file" else None)
    if dropped_at == "installed":
        return "The install command did not leave the package importable.", None
    if dropped_at == "env_file":
        ran_env_in_shell = any(e["action"] == "run" and "DOMAIN=" in e["detail"] for e in s.log)
        if ran_env_in_shell:
            return ("I ran the settings block in my terminal. I did not see that it belonged in a file, "
                    "so no .env file existed afterwards."), "env_location"
        return "I never worked out which file the settings should go in.", "env_location"
    if dropped_at == "app_ran":
        wrote_py = [f for f in s.files if f.endswith(".py")]
        if wrote_py:
            return (f"I saved {wrote_py[0]} but the section never says how to run it, so I stopped there."), "silent_load"
        return "I never ran any code that loads the .env file.", "silent_load"
    return ("The Python code ran and printed nothing, so I could not tell whether my settings loaded."), "silent_load"


class ScriptedPolicy:
    name = LOCAL_SCRIPTED
    label = LOCAL_SCRIPTED
    backend_name = "none (scripted reader, no model)"
    model_info = None

    def act(self, p: Persona, elements, section: str, s: Session):
        gave_up = act(p, elements, s)
        reached = s.probe()
        step_ids = [st["id"] for st in s.target.meta["steps"]]
        dropped_at = next((sid for sid in step_ids if sid not in reached), None)
        text, topic = quote(s, reached, dropped_at, gave_up)
        return gave_up, text, topic
