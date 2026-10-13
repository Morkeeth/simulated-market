"""The doc under test: a quickstart section, split into prose and code blocks."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sim import ROOT

TARGETS = ROOT / "target"


@dataclass(frozen=True)
class Element:
    kind: str          # "prose" or "code"
    text: str
    lang: str = ""


@dataclass(frozen=True)
class Target:
    dir: Path
    meta: dict

    @property
    def wheel(self) -> Path:
        return self.dir / self.meta["wheel"]

    def base_section(self) -> str:
        text = (self.dir / self.meta["snapshot"]).read_text(encoding="utf-8")
        start = text.index(self.meta["section_start"])
        end = text.index(self.meta["section_end"], start)
        return text[start:end]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def load_target(name: str = "python-dotenv") -> Target:
    d = TARGETS / name
    meta = json.loads((d / "target.json").read_text())
    t = Target(dir=d, meta=meta)
    got = sha256_file(t.wheel)
    if got != meta["wheel_sha256"]:
        raise ValueError(f"vendored wheel sha256 mismatch: {got}")
    return t


FENCE = re.compile(r"^```(\S*)\s*$")


def parse(section: str) -> list[Element]:
    out: list[Element] = []
    prose: list[str] = []
    code: list[str] | None = None
    lang = ""
    for line in section.splitlines():
        m = FENCE.match(line)
        if code is None and m:
            if "".join(prose).strip():
                out.append(Element("prose", "\n".join(prose).strip()))
            prose = []
            code, lang = [], m.group(1)
        elif code is not None and line.strip() == "```":
            out.append(Element("code", "\n".join(code) + "\n", lang))
            code = None
        elif code is not None:
            code.append(line)
        else:
            prose.append(line)
    if "".join(prose).strip():
        out.append(Element("prose", "\n".join(prose).strip()))
    return out
