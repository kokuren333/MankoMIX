"""Metadata-only wiring, planned overlays, deterministic diagrams and CLI."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.director import direction as D
from mankomix.director import wiring as W
from tests.test_upgrade2_duck import _make, _doc


def _save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def song(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    # Existing fixture construction, using only tiny synthetic signals. No
    # cleanup cache exists: wiring must never need one or render anything.
    t = np.arange(64) / 24000
    stems = {name: np.column_stack([np.sin(2 * np.pi * hz * t)] * 2) * 0.1
             for name, hz in (("a", 100), ("b", 200), ("c", 300))}
    root = _make(tmp_path / "song", stems)
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    data["buses"] = [{"id": "bus_mix", "kind": "mix", "chain": []},
                     {"id": "bus_room", "kind": "fx", "output": "bus_mix", "chain": [
                         {"id": "rev", "type": "reverb", "params": {"lowcut_hz": 350, "highcut_hz": 7000}},
                         {"id": "comp", "type": "compressor", "params": {}}]}]
    for t in data["tracks"]:
        t["output"] = "bus_mix"
    a, b, c = data["tracks"]
    a["sends"] = [{"bus": "bus_room", "level_db": -12.12345, "pre_fader": True}]
    b["automation"] = {"gain_db": [[0, 0], [10, -2], [60, 0]],
                       "move_ref": ["dir_000000000000/d1"]}
    data["variants"].append({"id": "var_alt", "master": {"chain": []}, "outputs": [],
                             "track_overrides": {a["id"]: {"sends": []}},
                             "bus_overrides": {"bus_room": {"chain": [{"type": "delay", "params": {}}]}}})
    _save(root / "project.json", data)
    (root / "directions").mkdir()
    _save(root / "directions" / "dir_000000000000.apply.json", {
        "id": "dir_000000000000", "record": {"moves": {"d1": {
            "op": "duck", "track": b["id"], "key": a["id"], "depth_db": 2.0,
            "attack_ms": 5.0, "release": {"ms": 125.0, "note": "1/16"},
            "key_band_hz": [40, 120]}}}})
    return root


def test_current_nodes_routes_sends_duck_and_bus_chain(song):
    graph = W.wiring(song)
    assert {n["id"] for n in graph["nodes"]} == {
        "trk_a", "trk_b", "trk_c", "bus_room", "bus_mix", "master"}
    assert {(e["source"], e["target"]) for e in graph["edges"] if e["type"] == "route"} == {
        ("trk_a", "bus_mix"), ("trk_b", "bus_mix"), ("trk_c", "bus_mix"),
        ("bus_room", "bus_mix"), ("bus_mix", "master")}
    send = next(e for e in graph["edges"] if e["type"] == "send")
    assert send == {"type": "send", "source": "trk_a", "target": "bus_room",
                    "level_db": -12.123, "pre_fader": True, "planned": False}
    duck = next(e for e in graph["edges"] if e["type"] == "duck")
    assert (duck["source"], duck["target"], duck["depth_db"], duck["attack_ms"],
            duck["release_ms"], duck["band"], duck["key_band_hz"]) == (
                "trk_a", "trk_b", 2.0, 5.0, 125.0, "full_band", [40, 120])
    chain = next(n["chain"] for n in graph["nodes"] if n["id"] == "bus_room")
    assert [c["type"] for c in chain] == ["reverb", "compressor"]
    assert (chain[0]["lowcut_hz"], chain[0]["highcut_hz"]) == (350, 7000)
    assert graph["note"] == W.NOTE and graph["reliability"] == W.RELIABILITY


def _planned(tmp_path):
    return _doc(tmp_path / "document", {"schema_version": 1, "moves": [
        {"id": "s1", "op": "send", "target": "trk_c", "params": {"bus": "bus_parallel", "level_db": -9}},
        {"id": "b1", "op": "bus_add", "target": "bus_parallel", "params": {
            "chain": [{"processor": "compressor", "params": {}}]}},
        {"id": "c1", "op": "chain_add", "target": "bus_parallel", "processor": "filter",
         "params": {"kind": "hpf", "freq_hz": 180}},
        {"id": "d2", "op": "duck", "target": "trk_c", "params": {
            "key": "trk_a", "depth_db": [1, 3], "attack_ms": 8, "release_note": "1/8"}},
        {"id": "g1", "op": "gain", "target": "trk_b", "params": {"delta_db": -1}}]})


def test_planned_overlay_retains_current_graph(song, tmp_path):
    doc = _planned(tmp_path)
    graph = W.wiring(song, direction=doc)
    bus = next(n for n in graph["nodes"] if n["id"] == "bus_parallel")
    assert bus["planned"] is True
    assert [c["type"] for c in bus["chain"]] == ["compressor", "filter"]
    assert all(c["planned"] for c in bus["chain"])
    assert bus["chain"][1]["freq_hz"] == 180
    planned = {e.get("move"): e for e in graph["edges"] if e["planned"]}
    assert set(planned) == {"b1", "s1", "d2"}
    assert planned["d2"]["depth_db"] == 2
    assert planned["d2"]["release_ms"] == 250
    assert planned["s1"]["pre_fader"] is False
    assert len([e for e in graph["edges"] if e["type"] == "duck"]) == 2
    b = next(n for n in graph["nodes"] if n["id"] == "trk_b")
    assert b["planned_moves"][0]["op"] == "gain"


def test_applied_moves_not_overlaid_and_stale_duck_not_shown(song, tmp_path):
    doc = _planned(tmp_path)
    did = D.parse_document(doc)["id"]
    _save(song / "directions" / f"{did}.apply.json", {"id": did, "record": {"moves": {
        m["id"]: {"op": m["op"]} for m in D.parse_document(doc)["block"]["moves"]}}})
    assert W.wiring(song, direction=doc) == W.wiring(song)
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    data["tracks"][1]["automation"]["move_ref"] = []
    _save(song / "project.json", data)
    assert not any(e["type"] == "duck" for e in W.wiring(song)["edges"])


def test_variant_overrides_and_unknown_variant(song):
    graph = W.wiring(song, variant="var_alt")
    assert not any(e["type"] == "send" for e in graph["edges"])
    assert next(n for n in graph["nodes"] if n["id"] == "bus_room")["chain"][0]["type"] == "delay"
    with pytest.raises(D.DirectionError, match="unknown variant"):
        W.wiring(song, variant="missing")


def test_retained_floor_duck_metadata(song):
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    auto = {"gain_db": [[100, 0], [220, -3], [2620, 0]], "owner": "mixplan"}
    data["tracks"][2]["automation"] = auto
    _save(song / "project.json", data)
    floor_path = song / "cache" / "proposals" / "mxp_floor.json"
    floor = json.loads(floor_path.read_text(encoding="utf-8"))
    floor["changes"]["tracks"] = {"trk_c": {"automation": auto}}
    floor["measurements"] = {"final": {"time_axis": {"kick": "trk_a", "bass": "trk_c"}}}
    floor["moves"] = [{"id": "m8.01", "kind": "automation", "track": "trk_c", "status": "kept",
                       "rules": ["R-11"], "measured": {"release": {"ms": 100, "note": "1/16"}}}]
    _save(floor_path, floor)
    duck = next(e for e in W.wiring(song)["edges"] if e.get("move") == "m8.01")
    assert (duck["source"], duck["target"], duck["depth_db"], duck["attack_ms"], duck["release_ms"]) == (
        "trk_a", "trk_c", 3, 5, 100)


def test_other_moves_and_unsupported_band_duck(song, tmp_path):
    doc = _doc(tmp_path / "other", {"moves": [
        {"id": "p1", "op": "place", "target": "trk_c", "params": {"distance": 2, "room": "bus_room"}},
        {"id": "m1", "op": "master_target", "params": {"target_lufs": -14}}]})
    graph = W.wiring(song, direction=doc)
    assert any(e.get("move") == "p1" and e["target"] == "bus_room" for e in graph["edges"])
    assert next(n for n in graph["nodes"] if n["id"] == "master")["planned_moves"][0]["op"] == "master_target"
    bad = _doc(tmp_path / "bad", {"moves": [{"id": "d1", "op": "duck", "target": "trk_b",
                                             "params": {"key": "trk_a", "band_hz": [50, 100]}}]})
    with pytest.raises(D.DirectionError, match="unknown duck parameters"):
        W.wiring(song, direction=bad)


def test_mermaid_determinism_and_entire_input_tree_unchanged(song, tmp_path, monkeypatch):
    doc = _planned(tmp_path)
    before = _tree(tmp_path)
    monkeypatch.setattr(W.MR, "render_mix", lambda *a, **kw: pytest.fail("must not render"))
    graph = W.wiring(song, direction=doc)
    diagram = W.wiring(song, direction=doc, format="mermaid")
    assert diagram == W.wiring(song, direction=doc, format="mermaid") == W.mermaid(graph)
    assert diagram.startswith("flowchart LR\n")
    for word in ("full_band", "pre_fader", "lowcut_hz", "planned", "attack_ms", "release_ms"):
        assert word in diagram
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("fmt", ["json", "mermaid"])
def test_cli(song, tmp_path, capsys, fmt):
    doc = _planned(tmp_path)
    before = _tree(tmp_path)
    assert main(["direction", "wiring", "--project", str(song), "--direction", str(doc), "--format", fmt]) == 0
    text = capsys.readouterr().out
    if fmt == "json":
        assert json.loads(text) == W.wiring(song, direction=doc)
    else:
        assert text == W.wiring(song, direction=doc, format="mermaid")
    assert _tree(tmp_path) == before


def test_cli_errors_are_structured(song, capsys):
    assert main(["direction", "wiring", "--project", str(song), "--variant", "missing"]) == 2
    assert "unknown variant" in capsys.readouterr().out
    assert main(["direction", "wiring", "--project", str(song), "--format", "bad"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
