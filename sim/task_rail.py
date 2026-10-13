"""Independent deterministic completion enforcement, shaped like an output rail.

This is our own function, not execution of NVIDIA NeMo Guardrails. It does not
call a provider and does not treat a model's success claim as a completed act.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from sim.task_contract import TaskContract, validate

@dataclass(frozen=True)
class RailDecision:
    allowed: bool
    missing: tuple[str, ...]


def _page_identity(url):
    # A fragment scroll is not a second page. Queries and paths retain identity.
    u = urlsplit(url or '')
    if not u.scheme or not u.netloc:
        return None
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip('/'), u.query, ''))


def observed_moves(trail):
    pages = []
    for step in trail:
        if step.get('status') in ('not_allowed', 'failed', 'error_page'):
            continue
        page = _page_identity(step.get('url'))
        if page is not None:
            pages.append(page)
    moves = []
    if len(set(pages)) >= 2:
        moves.append('went_somewhere')
    if any(pages[i] == pages[k] and any(p != pages[i] for p in pages[i + 1:k])
           for i in range(len(pages)) for k in range(i + 2, len(pages))):
        moves.append('came_back')
    # The current browser is read-only. No URL or agent statement can prove a write.
    return moves


def enforce(contract: TaskContract, trail) -> RailDecision:
    contract = validate(contract.payload())
    if contract.intent == 'unknown':
        return RailDecision(False, ('task_contract',))
    made = observed_moves(trail)
    missing = tuple(move for move in contract.required_moves if move not in made)
    return RailDecision(not missing, missing)
