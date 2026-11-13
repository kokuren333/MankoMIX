"""JSON pointer (RFC 6901), a JSON Patch subset (RFC 6902) and a three-way merge.

Supported patch operations: add, remove, replace, test. The three-way merge is
used to re-apply a writer's changes on top of the latest project on disk when
another face (GUI, CLI, MCP) changed it in the meantime (SPEC 9.5).
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .errors import ValidationError
from .schema import to_pointer


class _Missing:
    """Sentinel for an absent object member (kept identical through deepcopy)."""

    def __repr__(self) -> str:  # pragma: no cover
        return "MISSING"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


MISSING: Any = _Missing()

_INDEX_RE = re.compile(r"^(0|[1-9][0-9]*)$")
SUPPORTED_OPS = ("add", "remove", "replace", "test")


# --- equality -----------------------------------------------------------------

def json_equal(a: Any, b: Any) -> bool:
    """Structural JSON equality (booleans are not numbers; 1 == 1.0)."""
    if a is MISSING or b is MISSING:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


# --- pointers -------------------------------------------------------------------

def parse_pointer(pointer: str) -> list[str]:
    if not isinstance(pointer, str):
        raise ValidationError("JSON pointer must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValidationError(f"invalid JSON pointer '{pointer}' (must start with '/')")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def _index(token: str, length: int, *, allow_end: bool, pointer: str) -> int:
    if allow_end and token == "-":
        return length
    if not _INDEX_RE.match(token):
        raise ValidationError(f"invalid array index '{token}' in '{pointer}'")
    idx = int(token)
    limit = length if allow_end else length - 1
    if idx > limit:
        raise ValidationError(f"array index {idx} out of range in '{pointer}'")
    return idx


def resolve(doc: Any, pointer: str) -> Any:
    """Value at ``pointer``; raises ValidationError if it does not exist."""
    cur = doc
    for token in parse_pointer(pointer):
        if isinstance(cur, dict):
            if token not in cur:
                raise ValidationError(f"path '{pointer}' does not exist")
            cur = cur[token]
        elif isinstance(cur, list):
            cur = cur[_index(token, len(cur), allow_end=False, pointer=pointer)]
        else:
            raise ValidationError(f"path '{pointer}' does not exist")
    return cur


def exists(doc: Any, pointer: str) -> bool:
    try:
        resolve(doc, pointer)
        return True
    except ValidationError:
        return False


# --- patch ------------------------------------------------------------------------

def apply_patch(doc: Any, ops: list[dict]) -> Any:
    """Apply ``ops`` to a deep copy of ``doc`` and return it. ``doc`` is not modified."""
    if not isinstance(ops, list):
        raise ValidationError("patch must be a list of operations")
    out = copy.deepcopy(doc)
    for i, op in enumerate(ops):
        try:
            out = _apply_one(out, op)
        except ValidationError as exc:
            raise ValidationError(f"patch operation {i} failed: {exc.message}",
                                  details={"op_index": i, "op": op}) from exc
    return out


def _apply_one(doc: Any, op: Any) -> Any:
    if not isinstance(op, dict):
        raise ValidationError("operation must be an object")
    name = op.get("op")
    if name not in SUPPORTED_OPS:
        raise ValidationError(f"unsupported op '{name}' (supported: {', '.join(SUPPORTED_OPS)})")
    if "path" not in op:
        raise ValidationError("operation has no 'path'")
    pointer = op["path"]
    tokens = parse_pointer(pointer)
    if name in ("add", "replace", "test") and "value" not in op:
        raise ValidationError(f"'{name}' needs a 'value'")
    value = copy.deepcopy(op.get("value"))

    if name == "test":
        if not json_equal(resolve(doc, pointer), op["value"]):
            raise ValidationError(f"test failed at '{pointer}'")
        return doc

    if not tokens:
        if name == "remove":
            raise ValidationError("cannot remove the document root")
        return value  # add/replace of the whole document

    parent = resolve(doc, to_pointer(tokens[:-1]))
    key = tokens[-1]
    if isinstance(parent, dict):
        if name in ("remove", "replace") and key not in parent:
            raise ValidationError(f"path '{pointer}' does not exist")
        if name == "remove":
            del parent[key]
        else:
            parent[key] = value
    elif isinstance(parent, list):
        if name == "add":
            parent.insert(_index(key, len(parent), allow_end=True, pointer=pointer), value)
        else:
            idx = _index(key, len(parent), allow_end=False, pointer=pointer)
            if name == "remove":
                del parent[idx]
            else:
                parent[idx] = value
    else:
        raise ValidationError(f"parent of '{pointer}' is not a container")
    return doc


def diff(a: Any, b: Any, base: list | None = None) -> list[dict]:
    """A patch turning ``a`` into ``b`` (objects recursively; arrays replaced whole)."""
    base = base or []
    if json_equal(a, b):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        ops: list[dict] = []
        for k in a:
            if k not in b:
                ops.append({"op": "remove", "path": to_pointer(base + [k])})
        for k in b:
            if k not in a:
                ops.append({"op": "add", "path": to_pointer(base + [k]), "value": copy.deepcopy(b[k])})
            else:
                ops.extend(diff(a[k], b[k], base + [k]))
        return ops
    return [{"op": "replace", "path": to_pointer(base), "value": copy.deepcopy(b)}]


# --- three-way merge ---------------------------------------------------------------

def merge3(base: Any, mine: Any, theirs: Any, path: list | None = None) -> Any:
    """Re-apply the changes ``base -> mine`` on top of ``theirs``.

    Raises ValidationError when both sides changed the same value differently.
    Arrays of objects with unique "id" fields are merged element by element.
    """
    path = path or []
    if json_equal(mine, base):
        return copy.deepcopy(theirs)
    if json_equal(theirs, base) or json_equal(mine, theirs):
        return copy.deepcopy(mine)
    b = {} if base is MISSING else base
    if isinstance(mine, dict) and isinstance(theirs, dict) and isinstance(b, dict):
        result: dict = {}
        keys = list(theirs) + [k for k in mine if k not in theirs]
        for k in keys:
            r = merge3(b.get(k, MISSING), mine.get(k, MISSING), theirs.get(k, MISSING), path + [k])
            if r is not MISSING:
                result[k] = r
        return result
    b = [] if base is MISSING else base
    if isinstance(mine, list) and isinstance(theirs, list) and isinstance(b, list) \
            and _id_keyed(mine) and _id_keyed(theirs) and _id_keyed(b):
        return _merge_id_lists(b, mine, theirs, path)
    raise ValidationError(f"concurrent modification conflict at '{to_pointer(path)}'",
                          details={"path": to_pointer(path)})


def _id_keyed(items: list) -> bool:
    ids = [e.get("id") if isinstance(e, dict) else None for e in items]
    return all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids)


def _merge_id_lists(base: list, mine: list, theirs: list, path: list) -> list:
    b_ids = [e["id"] for e in base]
    m_ids = [e["id"] for e in mine]
    t_ids = [e["id"] for e in theirs]
    if t_ids == b_ids:
        order = m_ids
    elif m_ids == b_ids:
        order = t_ids
    else:
        # Both sides changed membership or order: keep theirs, append my additions,
        # and refuse if I reordered existing elements.
        common = [i for i in m_ids if i in b_ids]
        if common != [i for i in b_ids if i in common]:
            raise ValidationError(f"concurrent reordering conflict at '{to_pointer(path)}'",
                                  details={"path": to_pointer(path)})
        order = t_ids + [i for i in m_ids if i not in b_ids and i not in t_ids]
    bm = {e["id"]: e for e in base}
    mm = {e["id"]: e for e in mine}
    tm = {e["id"]: e for e in theirs}
    out = []
    seen = set()
    for i in order + [i for i in t_ids if i not in order] + [i for i in m_ids if i not in order]:
        if i in seen:
            continue
        seen.add(i)
        idx_path = path + [len(out)]
        r = merge3(bm.get(i, MISSING), mm.get(i, MISSING), tm.get(i, MISSING), idx_path)
        if r is not MISSING:
            out.append(r)
    return out
