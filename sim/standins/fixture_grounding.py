"""Grounding stand-in: a hand-copied fixture of real public issue URLs, labelled LOCAL-FIXTURE.

It does not imitate the Tavily response shape. It reads grounding/fixture.jsonl and
writes one receipts row per run with source "local-fixture", live False and the LOCAL
labels, so the receipts log can never be read as a runtime Tavily call.
"""
from __future__ import annotations

import json

from sim import ROOT
from sim.adapters.tavily import Candidate, log_receipt
from sim.labels import LOCAL, LOCAL_FIXTURE

FIXTURE = ROOT / "grounding" / "fixture.jsonl"
SOURCE = "local-fixture"


class FixtureGrounding:
    name = "local-fixture"
    label = LOCAL_FIXTURE

    def __init__(self, path=FIXTURE):
        self.rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        for r in self.rows:
            if r.get("label") != LOCAL_FIXTURE:
                raise ValueError(f"fixture row without {LOCAL_FIXTURE} label: {r.get('url')}")

    def items(self) -> list[dict]:
        return list(self.rows)

    def for_topic(self, topic: str) -> dict | None:
        for r in self.rows:
            if r["topic"] == topic:
                return r
        return None

    def record(self, query: str, receipts_path=None) -> dict:
        cands = [Candidate(url=r["url"], title=r["title"], excerpt="") for r in self.rows]
        return log_receipt(source=SOURCE, query=query, candidates=cands, live=False,
                           labels=[LOCAL, LOCAL_FIXTURE], search_id=None, path=receipts_path)
