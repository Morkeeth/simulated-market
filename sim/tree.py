"""Fork tree: where simulated users split, derived from one run file.

The tree is a prefix trie over each user's log of (action, detail) entries. A node is
one action. Its count is the number of users whose logs share every action up to and
including it. Depth is the position in the log. Each node also names the doc element
that caused the action (the log's `el` field), so reading down the tree reads down the doc.

The tree reads a run file and nothing else. It draws no random numbers, so it cannot
change a run file or the control check.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sim import labels as L


def path_key(user: dict) -> tuple:
    """The path a user took: the ordered (action, detail) pairs of the log."""
    return tuple((e["action"], e["detail"]) for e in user["log"])


def distinct_paths(run: dict) -> int:
    return len({path_key(u) for u in run["users"]})


@dataclass
class Node:
    action: str | None
    detail: str | None
    depth: int
    els: set = field(default_factory=set)
    users: list = field(default_factory=list)
    children: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.users)


def build(run: dict) -> Node:
    root = Node(None, None, 0)
    for u in run["users"]:
        node = root
        node.users.append(u["id"])
        for e in u["log"]:
            key = (e["action"], e["detail"])
            child = node.children.get(key)
            if child is None:
                child = node.children[key] = Node(e["action"], e["detail"], node.depth + 1)
            child.els.add(e.get("el"))
            child.users.append(u["id"])
            node = child
    return root


def walk(node: Node):
    yield node
    for c in node.children.values():
        yield from walk(c)


def leaves(root: Node) -> list[Node]:
    return [n for n in walk(root) if not n.children and n is not root]


def _short(detail: str, width: int = 44) -> str:
    lines = detail.splitlines() or [""]
    s = lines[0].strip()
    if len(lines) > 1:
        s += f" (+{len(lines) - 1} lines)"
    return s if len(s) <= width else s[: width - 3] + "..."


def _step(node: Node) -> str:
    els = sorted(e for e in node.els if e is not None)
    el = ",".join(str(e) for e in els) if els else "end"
    return f"step {node.depth:<2} el {el:<3}"


def _order(node: Node) -> list[Node]:
    # Most users first, then a stable order by the action text, so the print is deterministic.
    return sorted(node.children.values(), key=lambda c: (-c.count, c.action or "", c.detail or ""))


def render(run: dict, source: str, title: str) -> list[str]:
    """Lines of the printed tree. `source` is the run file path every node cites."""
    root = build(run)
    rows: list[tuple[str, Node]] = []

    def kids(node: Node, prefix: str) -> None:
        cs = _order(node)
        if len(cs) == 1:
            rows.append((prefix, cs[0]))
            kids(cs[0], prefix)
            return
        for j, c in enumerate(cs):
            last = j == len(cs) - 1
            rows.append((prefix + ("└─ " if last else "├─ "), c))
            kids(c, prefix + ("   " if last else "│  "))

    kids(root, "")
    n = root.count
    labels = f"{L.SIMULATED} {L.LOCAL}" if L.LOCAL in run["labels"] else L.SIMULATED
    body = [(f"{pre}{c.count:>3}  {c.action}: {_short(c.detail)}", c) for pre, c in rows]
    w = max((len(t) for t, _ in body), default=0)
    out = [f"Where simulated users split, {title}  [{', '.join(labels.split())}]",
           f"  Source: {source} (seed {run['seed']}, n {n}, policy {run['policy']['label']}).",
           "  One line per action. A branch is where users stopped doing the same thing.",
           "  The number is how many users took the same path up to that line.",
           ""]
    out += [f"  {t:<{w}}   {_step(c)}  {labels}  {source}" for t, c in body]
    k, p = len(leaves(root)), distinct_paths(run)
    out.append("")
    out.append(f"  Leaves: {k}. Distinct paths in the same file: {p}.")
    if k != p:
        out.append("  These differ because one path is a prefix of another. Count the paths, not the leaves.")
    return out
