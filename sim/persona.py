"""Seeded persona sampling. Same seed and index give the same persona on any doc version.

The trait weights and reading probabilities below are assumptions of the LOCAL build.
They are not calibrated against any real population. The run file says so.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

SKILLS = (("novice", 0.35), ("intermediate", 0.45), ("expert", 0.20))
PATIENCE = (("low", 0.30), ("medium", 0.45), ("high", 0.25))
OSES = (("macos", 0.50), ("linux", 0.30), ("windows", 0.20))
P_READS_PROSE = {"novice": 0.30, "intermediate": 0.60, "expert": 0.90}
P_READS_DIAGRAMS = {"novice": 0.40, "intermediate": 0.60, "expert": 0.80}
PATIENCE_FAILURES = {"low": 1, "medium": 2, "high": 3}
# How a persona reads prose. linear: the original rule, prose read when reads_prose is true.
# skim: only the first prose paragraph after each heading. code_only: no prose at all.
READING_STYLES = {
    "novice": (("linear", 0.50), ("skim", 0.30), ("code_only", 0.20)),
    "intermediate": (("linear", 0.40), ("skim", 0.35), ("code_only", 0.25)),
    "expert": (("linear", 0.30), ("skim", 0.30), ("code_only", 0.40)),
}
# Whether a persona tries once more after a failed command. Tied to patience.
P_RETRIES = {"low": 0.20, "medium": 0.50, "high": 0.80}
ASSUMPTIONS_SOURCE = "sim/persona.py trait weights, uncalibrated assumptions of the LOCAL build"

# Adapted from the /stranger skill: follow literally, fix nothing, take the degraded path.
STRANGER_RULES = """You are a developer trying a library for the first time, using only its README.
Rules you must keep:
1. Follow the docs literally. Run exactly what they say, in order. Use no insider knowledge.
2. Fix nothing. If a step fails, do not patch the docs or the code. Record what happened.
3. If you think "obviously you also need to...", do not do it. The docs did not say it.
4. When a step is unclear, take the degraded path: do the most literal thing a newcomer would do.
5. Say what you saw in one plain sentence, as help to the person who owns the docs."""


@dataclass(frozen=True)
class Persona:
    id: str
    skill: str
    patience: str
    os: str
    reads_prose: bool
    reads_diagrams: bool
    grounding_url: str | None
    reading_style: str = "linear"
    retries: bool = False

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("id")
        return d

    @property
    def max_failures(self) -> int:
        return PATIENCE_FAILURES[self.patience]


def _pick(rng: random.Random, table) -> str:
    x = rng.random()
    acc = 0.0
    for name, w in table:
        acc += w
        if x < acc:
            return name
    return table[-1][0]


def sample(seed: int, n: int, grounding_urls: list[str]) -> list[Persona]:
    out = []
    for i in range(n):
        rng = random.Random(f"{seed}/human/{i}")
        skill = _pick(rng, SKILLS)
        patience = _pick(rng, PATIENCE)
        os_ = _pick(rng, OSES)
        reads_prose = rng.random() < P_READS_PROSE[skill]
        reads_diagrams = rng.random() < P_READS_DIAGRAMS[skill]
        g = grounding_urls[rng.randrange(len(grounding_urls))] if grounding_urls else None
        # Drawn after every older trait, so the same seed keeps the same older traits.
        reading_style = _pick(rng, READING_STYLES[skill])
        retries = rng.random() < P_RETRIES[patience]
        out.append(Persona(f"h{i:03d}", skill, patience, os_, reads_prose, reads_diagrams, g,
                           reading_style, retries))
    return out


def describe(p: Persona) -> str:
    return (f"Skill: {p.skill}. Patience: {p.patience}. "
            f"You {'read' if p.reads_prose else 'skim past'} the prose between code blocks. "
            f"You {'read' if p.reads_diagrams else 'skip'} directory diagrams.")
