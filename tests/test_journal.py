"""Operation journal: history, undo, checkout (SPEC 9.5)."""
from __future__ import annotations

import pytest

from mankomix.core import journal
from mankomix.core.errors import InputError
from mankomix.core.project import Project


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture
def proj(tmp_path):
    p = Project.create(tmp_path / "song.mmx", title="Original")
    p.set("/title", "A", actor="human", reason="rename")     # seq 2
    p.set("/objective/intensity", 0.8, actor="agent")         # seq 3
    p.set("/title", "B", actor="planner")                     # seq 4
    return p


def test_history(proj):
    entries = journal.list_entries(proj.root)
    assert [e["seq"] for e in entries] == [1, 2, 3, 4]
    assert [e["op"] for e in entries] == ["create", "set", "set", "set"]
    assert entries[0]["before_hash"] is None
    for prev, cur in zip(entries, entries[1:]):
        assert cur["before_hash"] == prev["after_hash"]
    assert entries[-1]["after_hash"] == proj.content_hash()
    assert all("before" not in e for e in entries)
    assert entries[1]["actor"] == "human" and entries[1]["reason"] == "rename"
    assert entries[1]["ts"].endswith("Z")
    full = journal.list_entries(proj.root, include_before=True)
    assert full[0]["before"] is None and full[1]["before"]["title"] == "Original"
    assert [e["seq"] for e in journal.list_entries(proj.root, limit=2)] == [3, 4]


def test_undo_twice(proj):
    raw_before = journal.journal_path(proj.root).read_bytes()
    e = journal.undo(proj, actor="human")
    assert e["op"] == "undo" and e["undoes"] == 4
    assert proj.data["title"] == "A" and proj.data["objective"]["intensity"] == 0.8
    e = journal.undo(proj, actor="human")
    assert e["undoes"] == 3
    assert proj.data["objective"]["intensity"] == 0.5 and proj.data["title"] == "A"
    on_disk = Project.open(proj.root).data
    assert on_disk == proj.data
    # append-only: earlier lines untouched
    assert journal.journal_path(proj.root).read_bytes().startswith(raw_before)
    journal.undo(proj, actor="agent")
    assert proj.data["title"] == "Original"
    with pytest.raises(InputError):
        journal.undo(proj, actor="agent")  # creation cannot be undone


def test_undo_after_new_op(proj):
    journal.undo(proj, actor="human")                        # back to title A
    proj.set("/title", "C", actor="human")
    journal.undo(proj, actor="human")                        # undoes the C rename
    assert proj.data["title"] == "A"
    journal.undo(proj, actor="human")                        # undoes intensity 0.8
    assert proj.data["objective"]["intensity"] == 0.5


def test_checkout(proj):
    e = journal.checkout(proj, 2, actor="human")
    assert e["op"] == "checkout" and e["target_seq"] == 2
    assert proj.data["title"] == "A" and proj.data["objective"]["intensity"] == 0.5
    assert journal.list_entries(proj.root)[-1]["after_hash"] == proj.content_hash()
    # checkout to the latest state of the original line
    journal.checkout(proj, 4, actor="agent")
    assert proj.data["title"] == "B" and proj.data["objective"]["intensity"] == 0.8
    # a checkout is undoable like any other op
    journal.undo(proj, actor="human")
    assert proj.data["title"] == "A"
    with pytest.raises(InputError):
        journal.checkout(proj, 99, actor="human")


def test_bad_actor_rejected(proj):
    with pytest.raises(InputError):
        journal.undo(proj, actor="someone")
