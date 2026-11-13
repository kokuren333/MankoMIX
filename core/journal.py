"""Append-only operation journal (journal.jsonl, SPEC 9.5).

One JSON object per line:
``{seq, ts, actor, op, reason, before_hash, after_hash, patch?, ..., before}``.
``before`` is the full project data before the operation (null for "create"),
so undo and checkout can restore any recorded state. Undo and checkout are
themselves recorded as new operations; history is never rewritten.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import EnvironmentProblem, InputError
from .hashing import canonical_hash

if TYPE_CHECKING:  # pragma: no cover
    from .project import Project

JOURNAL_FILE = "journal.jsonl"
ACTORS = ("human", "agent", "planner")
_FIELD_ORDER = ("seq", "ts", "actor", "op", "reason", "before_hash", "after_hash", "patch")


def journal_path(root: str | os.PathLike[str]) -> Path:
    return Path(root) / JOURNAL_FILE


def check_actor(actor: str) -> str:
    if actor not in ACTORS:
        raise InputError(f"unknown actor '{actor}'; valid: {', '.join(ACTORS)}")
    return actor


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_all(root) -> list[dict]:
    path = journal_path(root)
    if not path.is_file():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise InputError(f"journal.jsonl line {n} is not valid JSON") from exc
    return out


def last_seq(root) -> int:
    entries = _read_all(root)
    return max((e.get("seq", 0) for e in entries), default=0)


def append(root, entry: dict) -> dict:
    """Append ``entry`` (seq and ts are assigned when missing). Returns the stored entry.

    Callers must hold the project lock (Project does) so seq stays unique.
    """
    check_actor(entry.get("actor", ""))
    stored = dict(entry)
    stored.setdefault("seq", last_seq(root) + 1)
    stored.setdefault("ts", _now())
    stored.setdefault("reason", "")
    ordered = {k: stored[k] for k in _FIELD_ORDER if k in stored}
    ordered.update({k: v for k, v in stored.items() if k not in ordered and k != "before"})
    if "before" in stored:
        ordered["before"] = stored["before"]  # bulky; keep it last
    line = json.dumps(ordered, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    try:
        with open(journal_path(root), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        raise EnvironmentProblem("cannot append to journal.jsonl", details={"error": str(exc)}) from exc
    return ordered


def list_entries(root, limit: int | None = None, *, include_before: bool = False) -> list[dict]:
    """Journal entries, oldest first. ``limit`` keeps only the most recent N."""
    entries = _read_all(root)
    if limit is not None:
        entries = entries[-limit:] if limit > 0 else []
    if not include_before:
        entries = [{k: v for k, v in e.items() if k != "before"} for e in entries]
    return entries


def get_entry(root, seq: int, *, include_before: bool = True) -> dict:
    for e in _read_all(root):
        if e.get("seq") == seq:
            return e if include_before else {k: v for k, v in e.items() if k != "before"}
    raise InputError(f"no journal entry with seq {seq}")


def _undo_target(entries: list[dict]) -> dict:
    undone = {e.get("undoes") for e in entries if e.get("op") == "undo"}
    for e in reversed(entries):
        if e.get("op") == "undo" or e.get("seq") in undone:
            continue
        if e.get("before") is None:
            break  # the project creation itself cannot be undone
        return e
    raise InputError("nothing to undo")


def undo(project: "Project", actor: str, reason: str = "") -> dict:
    """Restore the state before the last operation that has not been undone yet.

    Recorded as a new "undo" operation; calling it again walks further back.
    Returns the journal entry of the undo (without "before").
    """
    check_actor(actor)
    target: dict[str, Any] = {}

    def compute(latest, _raw_hash):
        entry = _undo_target(_read_all(project.root))
        target["seq"] = entry["seq"]
        return copy.deepcopy(entry["before"])

    entry = project._commit(compute, actor=actor, op="undo",
                            reason=reason or "undo", extra=lambda: {"undoes": target["seq"]}, force=True)
    return entry


def _state_after(entries: list[dict], seq: int, current: Any) -> Any:
    entry = next((e for e in entries if e.get("seq") == seq), None)
    if entry is None:
        raise InputError(f"no journal entry with seq {seq}")
    want = entry.get("after_hash")
    for e in entries:
        if e.get("seq", 0) > seq and e.get("before_hash") == want and e.get("before") is not None:
            return copy.deepcopy(e["before"])
    if current is not None and canonical_hash(current) == want:
        return copy.deepcopy(current)
    raise InputError(f"the state after seq {seq} is not recoverable from the journal")


def checkout(project: "Project", seq: int, actor: str, reason: str = "") -> dict:
    """Restore the project state right after journal entry ``seq`` (recorded as a new op)."""
    check_actor(actor)
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise InputError("seq must be an integer")

    def compute(latest, _raw_hash):
        return _state_after(_read_all(project.root), seq, latest)

    return project._commit(compute, actor=actor, op="checkout",
                           reason=reason or f"checkout {seq}", extra=lambda: {"target_seq": seq}, force=True)
