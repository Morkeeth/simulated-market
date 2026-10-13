"""Tavily search adapter (the real one), ported from agent-science clearance/search.py.

Kept from the original: the key is never in this repo and never echoed; every call
appends a row to a receipts jsonl; last_verified_receipt() reads that log, not process
memory, so a cold process can still prove a runtime call happened.

Changed: the endpoint is Tavily, not Parallel. Request and response field names follow
the Tavily search API as documented at https://docs.tavily.com (query, max_results,
results[].url/title/content). The `request_id` field is read if present and is
unverified until the first live call.

A LOCAL-FIXTURE row written by sim.standins.fixture_grounding has source
"local-fixture" and live False. It never counts as a verified Tavily call.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sim import ROOT
from sim.errors import NoKey

ENDPOINT = "https://api.tavily.com/search"
KEY_ENV = "TAVILY_API_KEY"
KEY_PATH = Path.home() / ".config" / "keys" / "tavily.key"
RECEIPTS = ROOT / "runs" / "receipts" / "grounding.jsonl"
SOURCE = "tavily"

LIVE_CALLS = 0


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str
    excerpt: str


def load_key() -> str:
    env = os.environ.get(KEY_ENV)
    if env and env.strip():
        return env.strip()
    if KEY_PATH.exists():
        key = KEY_PATH.read_text().strip()
        if key:
            return key
    raise NoKey(
        f"no Tavily key: set {KEY_ENV} or place it at {KEY_PATH}. "
        "Execution stays off until configured."
    )


def log_receipt(*, source: str, query: str, candidates: list[Candidate], live: bool,
                labels: list[str], search_id: Optional[str] = None, path=None) -> dict:
    target = Path(path) if path is not None else RECEIPTS
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "live": live,
        "labels": labels,
        "query": query[:240],
        "n_candidates": len(candidates),
        "urls": [c.url for c in candidates[:8]],
        "search_id": search_id,
    }
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def last_verified_receipt(path=None) -> dict:
    """Proof that Tavily ran, read from the receipts log. Only live tavily rows count."""
    target = Path(path) if path is not None else RECEIPTS
    out = {"last_verified_utc": None, "verified_search_id": None,
           "verified_calls_logged": 0, "local_rows_logged": 0, "source": str(target)}
    if not target.exists():
        return out
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("source") == SOURCE and rec.get("live") is True:
            out["verified_calls_logged"] += 1
            out["last_verified_utc"] = rec.get("at")
            out["verified_search_id"] = rec.get("search_id")
        elif any(str(lab).startswith("LOCAL") for lab in rec.get("labels") or []):
            out["local_rows_logged"] += 1
    return out


def search(query: str, *, max_results: int = 6, receipts_path=None) -> list[Candidate]:
    global LIVE_CALLS
    key = load_key()  # refuses before any network
    body = json.dumps({"query": query, "max_results": max_results}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Tavily search failed: HTTP {e.code} {e.reason}") from None
    LIVE_CALLS += 1
    out = [Candidate(url=x["url"], title=x.get("title") or "(untitled)",
                     excerpt=(x.get("content") or "")[:400])
           for x in payload.get("results") or [] if x.get("url")]
    log_receipt(source=SOURCE, query=query, candidates=out, live=True, labels=["RUNTIME"],
                search_id=payload.get("request_id"), path=receipts_path)
    return out


class TavilyGrounding:
    """Grounding from a runtime Tavily call. Same interface as the LOCAL fixture."""
    name = "tavily"
    label = "RUNTIME"
    items_source = "results returned by the Tavily search request"

    def __init__(self, query: str, receipts_path=None):
        self.rows = [{"url": c.url, "title": c.title, "topic": None, "label": "RUNTIME"}
                     for c in search(query, receipts_path=receipts_path)]

    def items(self) -> list[dict]:
        return list(self.rows)

    def for_topic(self, topic: str) -> dict | None:
        return None

    def record(self, query: str, receipts_path=None) -> None:
        return None  # search() already wrote the receipt
