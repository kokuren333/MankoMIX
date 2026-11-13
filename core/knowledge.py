"""``knowledge_lookup`` over the data files in knowledge/ (SPEC 7.3, 10.3).

Covers everything that is data: the rule index R-01..R-33
(knowledge/rules.json), perceptual vocabulary terms and bands, genre priors,
thresholds, objective metric tables and the other knowledge tables.

Read-only; never touches a project. Wrapped 1:1 by ``core.api.knowledge_lookup``
(CLI ``mankomix knowledge``, MCP ``knowledge_lookup``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from mankomix import repo_data_root

from .errors import InputError

_META_KEYS = {"schema_version", "status", "note", "evidence", "source"}
# Top-level list keys -> entry kind (anything else uses the key itself).
_KIND = {"terms": "term", "bands": "band", "genres": "genre", "pattern_sets": "pattern_set",
         "role_vocabulary": "role", "rules": "rule"}
KINDS = ("rule", "term", "band", "genre", "section", "table", "pattern_set", "role")


def _label_text(item: dict) -> list[str]:
    out: list[str] = []
    for key in ("label", "text"):
        lab = item.get(key)
        if isinstance(lab, dict):
            out += [str(v) for v in lab.values() if isinstance(v, str)]
        elif isinstance(lab, str):
            out.append(lab)
    for lang in ("en", "ja"):
        v = item.get(lang)
        if isinstance(v, list):
            out += [str(x) for x in v if isinstance(x, str)]
        elif isinstance(v, str):
            out.append(v)
    return out


def _label(item: dict) -> str | None:
    for key in ("label", "text"):
        lab = item.get(key)
        if isinstance(lab, dict):
            v = lab.get("en") or lab.get("ja")
            if v:
                return v
        if isinstance(lab, str):
            return lab
    for lang in ("en", "ja"):
        v = item.get(lang)
        if isinstance(v, list) and v:
            return " / ".join(str(x) for x in v)
        if isinstance(v, str):
            return v
    return None


def _entries() -> list[dict]:
    kdir = repo_data_root() / "knowledge"
    out: list[dict] = []
    for f in sorted(kdir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        src = f.stem
        if not isinstance(data, dict):
            continue
        loose: dict[str, Any] = {}
        for key, val in data.items():
            if key in _META_KEYS:
                continue
            if isinstance(val, list) and val and all(isinstance(x, dict) and "id" in x for x in val):
                kind = _KIND.get(key, key)
                for item in val:
                    out.append({"source": src, "kind": kind, "id": str(item["id"]),
                                "label": _label(item), "_labels": _label_text(item), "data": item})
            elif isinstance(val, list) and val and all(isinstance(x, str) for x in val) and key in _KIND:
                kind = _KIND[key]
                for s in val:
                    out.append({"source": src, "kind": kind, "id": s, "label": None, "_labels": [], "data": s})
            elif isinstance(val, dict):
                out.append({"source": src, "kind": "section", "id": f"{src}.{key}",
                            "label": val.get("note") if isinstance(val.get("note"), str) else None,
                            "_labels": [key], "data": val})
            else:
                loose[key] = val
        if loose:
            out.append({"source": src, "kind": "table", "id": src,
                        "label": data.get("note") if isinstance(data.get("note"), str) else None,
                        "_labels": [], "data": {k: data[k] for k in data if k not in ("schema_version",)}})
    return out


def _norm_rule_id(token: str) -> str:
    """'r-1' / 'R-01' -> 'r-01' so rule ids match with or without the leading zero."""
    m = re.fullmatch(r"r-(\d{1,2})", token)
    return f"r-{int(m.group(1)):02d}" if m else token


def _score(e: dict, tokens: list[str]) -> int:
    ident = e["id"].casefold()
    labels = " ".join(e["_labels"]).casefold()
    text = json.dumps(e["data"], ensure_ascii=False).casefold()
    score = 0
    for t in tokens:
        t = _norm_rule_id(t)
        if t == ident or ident.endswith("." + t):
            score += 100
        elif t in ident:
            score += 50
        elif t in labels:
            score += 30
        elif t in text:
            score += 10
        else:
            return 0          # every token must match somewhere
    return score


def knowledge_lookup(query: str | None = None, *, id: str | None = None, kind: str | None = None,
                     source: str | None = None, limit: int = 20, detail: bool = False) -> dict:
    """Find knowledge entries by free text (ids, labels, notes), exact id, kind or source file.

    Rules are entries of kind "rule" (source "rules"): ``id="R-14"`` returns
    the rule with its text, type and related P/S ids.
    """
    if limit is not None and int(limit) < 1:
        raise InputError("limit must be >= 1")
    entries = _entries()
    if source:
        valid = sorted({e["source"] for e in entries})
        if source not in valid:
            raise InputError(f"unknown knowledge source '{source}'", details={"valid": valid})
        entries = [e for e in entries if e["source"] == source]
    if kind:
        entries = [e for e in entries if e["kind"] == kind]
    if id:
        want = _norm_rule_id(id.casefold())
        entries = [e for e in entries if e["id"] == id or _norm_rule_id(e["id"].casefold()) == want]
    tokens = [t for t in (query or "").casefold().split() if t]
    if tokens:
        scored = [(s, e) for e in entries if (s := _score(e, tokens)) > 0]
        scored.sort(key=lambda t: (-t[0], t[1]["source"], t[1]["id"]))
        entries = [e for _, e in scored]
    total = len(entries)
    entries = entries[: int(limit)] if limit else entries
    # An exact id hit is what the caller wants to read: include its data even in summary mode.
    with_data = detail or (bool(id) and total == 1)
    items = []
    for e in entries:
        item = {"source": e["source"], "kind": e["kind"], "id": e["id"], "label": e["label"]}
        if with_data:
            item["data"] = e["data"]
        items.append(item)
    out: dict[str, Any] = {"count": total, "returned": len(items), "entries": items}
    if not total:
        every = _entries()
        out["sources"] = sorted({e["source"] for e in every})
        out["kinds"] = sorted({e["kind"] for e in every})
    return out


__all__ = ["KINDS", "knowledge_lookup"]
