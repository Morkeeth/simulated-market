"""Shared mini-swe-agent prompts and transcript semantics, no backend imports."""
import re

HARNESS = "mini-swe-agent"
HARNESS_VERSION = "2.4.6"
STEP_LIMIT = 12
MAX_TOKENS = 400
OUTPUT_CAP = 4000
SUBMIT = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

# A command word `python` or `python3`, not the `python` inside `python-dotenv`.
PY_CMD = re.compile(r"(?:^|[\s;&|(])python3?(?=\s|$)")
PY_FILE = re.compile(r"(?:^|[\s;&|(])python3?\s+(?:-u\s+)?([\w.\-/]+\.py)\b")

SYSTEM = """You are a coding agent working in a Linux terminal.

Each response must contain exactly ONE bash code block with ONE command (or commands joined with && or ||).
Write a short THOUGHT before the command. Use this format:

THOUGHT: why you run this command.

```mswea_bash_command
your_command_here
```

Every command runs in a new subshell in the same working directory. Files persist between commands.
When you are done, or you cannot continue, run this command alone:

```mswea_bash_command
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```"""

INSTANCE = """A user asked you to follow the quickstart of a Python library and reach this goal:

{{task}}

Work in the current directory."""

OBSERVATION = (
    "<returncode>{{output.returncode}}</returncode>\n"
    "{% if output.output | length < " + str(OUTPUT_CAP) + " -%}<output>\n{{ output.output -}}\n</output>"
    "{%- else -%}<output_tail>\n{{ output.output[-" + str(OUTPUT_CAP) + ":] }}\n</output_tail>{%- endif -%}"
)


class AgentUnavailable(RuntimeError):
    pass


def task_text(target_meta: dict, section: str) -> str:
    return f"{target_meta['goal']}\n\nThe quickstart section from the {target_meta['name']} README:\n\n{section}"


def runs_marked_code(command: str, read_file, marker: str) -> bool:
    """True when a command ran Python code that contains the target's app marker.

    The command must invoke python as a command word. The marker counts if it is in the
    command text (python -c, a heredoc piped to python) or in a .py file the command runs,
    read from the fork right after the command. A heredoc that only writes app.py does not count.
    """
    if not PY_CMD.search(command):
        return False
    if marker in command:
        return True
    return any(marker in (read_file(f) or "") for f in PY_FILE.findall(command))


