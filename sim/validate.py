"""A small JSON Schema checker, standard library only, for the subset our schemas use.

The test suite also checks every run file with the jsonschema package, so this code is
cross-checked against a full implementation.
"""
from __future__ import annotations

import json
import re

from sim import ROOT

SCHEMAS = ROOT / "schema"
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text())


def _type_ok(v, t) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _resolve(ref: str, root: dict, name: str):
    file, _, frag = ref.partition("#")
    doc = load(file) if file and file != name else root
    node = doc
    for part in [p for p in frag.split("/") if p]:
        node = node[part]
    return node, doc, (file or name)


def errors(v, schema: dict, root: dict, name: str, path: str = "$") -> list[str]:
    out: list[str] = []
    if "$ref" in schema:
        sub, doc, nm = _resolve(schema["$ref"], root, name)
        return errors(v, sub, doc, nm, path)
    if "type" in schema:
        ts = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(v, t) for t in ts):
            return [f"{path}: expected {ts}, got {type(v).__name__}"]
    if "const" in schema and v != schema["const"]:
        out.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and v not in schema["enum"]:
        out.append(f"{path}: {v!r} not in {schema['enum']}")
    if "oneOf" in schema:
        n_ok = sum(1 for s in schema["oneOf"] if not errors(v, s, root, name, path))
        if n_ok != 1:
            out.append(f"{path}: matched {n_ok} of oneOf, expected 1")
    if isinstance(v, str):
        if "pattern" in schema and not re.search(schema["pattern"], v):
            out.append(f"{path}: does not match {schema['pattern']}")
        if "minLength" in schema and len(v) < schema["minLength"]:
            out.append(f"{path}: shorter than {schema['minLength']}")
    if _type_ok(v, "number"):
        if "minimum" in schema and v < schema["minimum"]:
            out.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and v > schema["maximum"]:
            out.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(v, dict):
        for k in schema.get("required", []):
            if k not in v:
                out.append(f"{path}: missing {k}")
        props = schema.get("properties", {})
        for k, sub in v.items():
            if k in props:
                out += errors(sub, props[k], root, name, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}: unexpected key {k}")
    if isinstance(v, list):
        if "minItems" in schema and len(v) < schema["minItems"]:
            out.append(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            out.append(f"{path}: items not unique")
        if "items" in schema:
            for i, x in enumerate(v):
                out += errors(x, schema["items"], root, name, f"{path}[{i}]")
        if "contains" in schema and not any(not errors(x, schema["contains"], root, name) for x in v):
            out.append(f"{path}: contains nothing matching {schema['contains']}")
    return out


def check(doc: dict, schema_name: str = "run.schema.json") -> list[str]:
    # Frozen results keep their original contract. Never rewrite their version
    # or validate a legacy artifact against a widened current schema.
    if schema_name == "run.schema.json" and doc.get("schema_version") == "0.6.0":
        schema_name = "run-0.6.0.schema.json"
    schema = load(schema_name)
    return errors(doc, schema, schema, schema_name)


LOCAL_FAMILY = {"LOCAL", "LOCAL-SCRIPTED", "LOCAL-MODEL", "LOCAL-FIXTURE"}


def semantic(run: dict) -> list[str]:
    """Checks a schema cannot express. A planted or hand-edited transcript fails here.

    1. Every `run` log entry has an integer exit code (the schema allows null for notes).
    2. When the run is LOCAL, every population carries SIMULATED and LOCAL, and a
       population whose backend is LOCAL carries LOCAL even if the run label was stripped.
    3. Each population's per-step reached and dropped counts recount from its transcripts.
    """
    out: list[str] = []
    grounding = run.get('grounding', {})
    backend = run.get('backends', {}).get('grounding', {})
    if grounding.get('label') == 'NONE' or backend.get('label') == 'NONE':
        if (grounding.get('label') != 'NONE' or backend.get('label') != 'NONE'
                or grounding.get('backend') != 'none-requested'
                or backend.get('name') != 'none-requested'
                or grounding.get('items', {}).get('value') != 0
                or any(q.get('grounding') for q in run.get('quotes', []))):
            out.append('Disabled grounding cannot contain external evidence or a runtime backend.')
    run_local = "LOCAL" in run.get("labels", [])
    humans = run.get("users", [])
    for p in run.get("populations", []):
        pid = p.get("id", "?")
        labels = p.get("labels", [])
        if "SIMULATED" not in labels:
            out.append(f"populations[{pid}]: missing SIMULATED label")
        if (run_local or p.get("backend", {}).get("label") in LOCAL_FAMILY) and "LOCAL" not in labels:
            out.append(f"populations[{pid}]: LOCAL run or backend but the population has no LOCAL label")
        people = humans if pid == "humans" else p.get("users", [])
        if p.get("n", {}).get("value") != len(people):
            out.append(f"populations[{pid}]: n is {p.get('n', {}).get('value')} but {len(people)} transcripts")
        prev = len(people)
        for st in p.get("steps", []):
            k = sum(1 for u in people if st.get("id") in u.get("reached", []))
            if st.get("reached", {}).get("value") != k:
                out.append(f"populations[{pid}].steps[{st.get('id')}]: reached {st.get('reached', {}).get('value')}, transcripts give {k}")
            if st.get("dropped", {}).get("value") != prev - k:
                out.append(f"populations[{pid}].steps[{st.get('id')}]: dropped does not recount")
            prev = k
        for u in people:
            for e in u.get("log", []):
                if e.get("action") == "run" and not isinstance(e.get("exit_code"), int):
                    out.append(f"populations[{pid}] user {u.get('id')} log {e.get('i')}: run with no exit code")
    return out
