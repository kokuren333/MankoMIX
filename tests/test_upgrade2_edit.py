"""The edit (declutter) stage of a direction (UPGRADE2 §1.5, T-24 / T-25).

1. a direction without an edit op: validate / apply record / outcome byte-identical to the code before
   the edit stage, and director/edit.py is never imported
2. synthetic stems: noise is cut, a decaying tone is refused by EG-3, EG-1 / EG-2 refuse loud regions,
   EG-4 withdraws the largest regions first, EG-5 withholds a move of 49 regions
3. validate: ranges, unknown keys, bus / master targets; a section is allowed
4. detection does not depend on the track's cleanup (applied or not, with or without overrides)
5. the ledger lists every region; its journal seqs exist; the apply record and outcome counts agree
6. revert (and checkout) render bit-identically to the state before the edit
7. the timeline length is unchanged; no audio file appears in the project or kb
8. review tier: E2 at least, E3 on the lead, never E1
9. an edit-only direction is not converged with the floor; with nothing cut it is
10. scan writes nothing and agrees with apply

Small synthetic projects in tmp_path (24 kHz), no real project is rendered.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mankomix import repo_data_root
from mankomix.core import api
from mankomix.core import audio_io
from mankomix.core import journal
from mankomix.core import mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.project import Project
from mankomix.director import direction as D
from mankomix.director import edit as E
from tests.fixtures import synth

SR = 24000
REPO = repo_data_root()
SONG_DIR = REPO / "kb" / "songs" / "manko-shugi"
AUDIO_EXT = {".wav", ".flac", ".mp3", ".aif", ".aiff", ".ogg", ".m4a"}


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# synthetic signals (levels in dBFS as the edit stage measures them: mean of L^2 and R^2)
# ---------------------------------------------------------------------------

def _sine(secs: float, dbfs: float, f: float = 1000.0) -> np.ndarray:
    t = np.arange(int(round(secs * SR))) / SR
    return 10 ** ((dbfs + 3.0103) / 20.0) * np.sin(2 * np.pi * f * t)


def _square(secs: float, dbfs: float = 0.0, f: float = 220.0) -> np.ndarray:
    return 10 ** (dbfs / 20.0) * np.sign(_sine(secs, 0.0, f) + 1e-12)


def _noise(secs: float, dbfs: float, seed: int) -> np.ndarray:
    return 10 ** (dbfs / 20.0) * np.random.default_rng(seed).standard_normal(int(round(secs * SR)))


def _decay(secs: float, start_dbfs: float, db_per_s: float, f: float = 1000.0) -> np.ndarray:
    t = np.arange(int(round(secs * SR))) / SR
    return _sine(secs, start_dbfs, f) * 10 ** (-db_per_s * t / 20.0)


def _sil(secs: float) -> np.ndarray:
    return np.zeros(int(round(secs * SR)))


def _st(*parts: np.ndarray) -> np.ndarray:
    x = np.concatenate(parts)
    return np.stack([x, x], axis=1)


def _guitar() -> np.ndarray:
    """content / silence / content / low noise / content / decaying tone: 12 s."""
    return _st(_sine(2, -13, 440), _sil(2), _sine(2, -13, 440), _noise(3, -58, 1), _sine(1, -13, 440),
               _decay(2, -52, 8))


def _vocal() -> np.ndarray:
    return _st(_sine(12, -16, 330))


def _make(root: Path, stems: dict[str, np.ndarray]) -> Path:
    src = root.parent / f"{root.name}_stems"
    for name, x in stems.items():
        synth.write_wav(src / f"{name}.wav", x, SR)
    p = Project.create(root, title="edit test")
    FileAdapter().fetch(src, p, actor="human")
    n = max(x.shape[0] for x in stems.values())
    p.set("/mix/applied", {"proposal_id": "mxp_floor"}, actor="human")
    p.set("/variants", [{"id": "var_x", "objective": None,
                         "master": {"profile": "streaming_universal", "chain": []}, "outputs": []}], actor="human")
    pdir = root / "cache" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    floor = {"stage": "mix", "status": "applied", "proposal_id": "mxp_floor",
             "changes": {"mix_bus": "bus_mix", "tracks": {}, "buses": []},
             "sections": [{"id": "sec1", "start_s": 0.0, "end_s": 6.0, "label": "a"},
                          {"id": "sec2", "start_s": 6.0, "end_s": n / SR, "label": "b"}],
             "objective_evaluation": {"score": 0.1}, "measurements": {}, "notes": []}
    (pdir / "mxp_floor.json").write_text(json.dumps(floor), encoding="utf-8")
    return root


@pytest.fixture
def song(tmp_path) -> Path:
    return _make(tmp_path / "song", {"guitar": _guitar(), "vocals": _vocal()})


def _gate(**p) -> dict:
    return {"threshold_db": -36.0, "hold_ms": 400.0, "lead_ms": 10.0, "min_gap_ms": 1000.0, "fade_ms": 20.0, **p}


def _plan(x: np.ndarray, op: str = "edit_gate", **p) -> dict:
    params = E.full_params(op, _gate(**p) if op == "edit_gate" else p)
    return E.plan_signal(x, SR, op, params)


def _block(moves: list[dict], **over) -> dict:
    b = {"schema_version": 1, "kind": "direction", "song": "s", "request": {"utterance": "declutter"},
         "sources": {}, "aims": [{"id": "a1", "text": "clean tails"}],
         "variants": [{"id": "var_x", "profile": "streaming_universal"}],
         "moves": moves,
         "claims": [{"id": "c1", "quantity": "P-03", "direction": "not_worse", "tolerance": 1.0, "primary": True}]}
    b.update(over)
    return b


def _move(mid="m01", op="edit_gate", target="trk_guitar", params=None, **kw) -> dict:
    m = {"id": mid, "aim": "a1", "op": op, "target": target,
         "params": _gate() if params is None and op == "edit_gate" else (params or {"side": "tail"}),
         "basis": "stem noise between phrases", "origin": "new"}
    m.update(kw)
    return m


def _doc(dirpath: Path, block: dict) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / "direction.md"
    p.write_text(f"---\nid: {D.direction_id(block)}\nkind: direction\ntitle: t\ncreated: 2026-11-15\n"
                 f"status: draft\nvisibility: private\n---\n\n# t\n\n```json direction\n"
                 f"{json.dumps(block, ensure_ascii=False)}\n```\n", encoding="utf-8")
    return p


def _files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _audio_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT)


# ---------------------------------------------------------------------------
# 1. nothing changes without an edit op
# ---------------------------------------------------------------------------

# hashes of the output of direction.py before the edit stage (W-2 golden, HEAD 87800e8)
BASE_VALIDATE = {
    "2026-11-14_p1-kikigokochi": ("dir_68e88f393670", "ae7269da2c2a3306"),
    "2026-11-14_p2-ultra-sub-bass": ("dir_2a6c9969107a", "e3d534ab96d12f97"),
    "2026-11-14_p3-spatial-panning": ("dir_b465721f74fb", "df6057e37a5a1b07"),
    "2026-11-15_p4-ref-fullmix": ("dir_9a31fadac3cc", "6e7e8b698f3a472d"),
    "2026-11-15_p5-ref-stems": ("dir_b86a8a0667a2", "1508342f97f86112"),
    "2026-11-15_p6-vocal-words": ("dir_89dc56c90b97", "1a5623aec838033e"),
}
# _masked hashes, re-taken in W-9 from HEAD 87800e8 with the current mask (tmp/upgrade2/w9/scripts)
BASE_APPLY_RECORD_NOMOVE = "9ca1527ce302b959"
BASE_OUTCOME = {"plain": "7da0e89a35a5ecb1", "min": "b0fb3bc89e66a490", "refs": "dcc18e8b02cdfeda"}


def _masked(text: str) -> str:
    """Hash of an output with the environment-dependent parts masked: the gate definition hashes
    (combined and per file; the working copy's line endings change the raw file bytes) and the newline
    convention of the platform's text-mode write. Everything else must stay byte-identical."""
    gate = D.gate_definitions_hash()
    text = text.replace("\r\n", "\n")
    for v in (gate["combined"], *gate["files"].values()):
        if v is not None:
            text = text.replace(v, "<gate>")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize("folder", sorted(BASE_VALIDATE))
def test_existing_directions_validate_byte_identical(folder):
    doc = D.parse_document(SONG_DIR / folder / "direction.md")
    did, h = BASE_VALIDATE[folder]
    assert doc["id"] == did
    res = D.validate(doc)
    assert res["ok"], res["errors"]
    assert _h(res) == h


def test_apply_record_and_outcome_without_edit_ops_are_unchanged(tmp_path):
    import tests.test_direction_update as T
    proj = T._project(tmp_path / "p", low_amp=0.2)
    nomove = T._minimal_block()
    nomove["moves"] = []
    p2 = T._write_doc(tmp_path / "d2", nomove)
    D.apply(proj, p2)
    rid = D.parse_document(p2)["id"]
    assert _masked((proj / "directions" / f"{rid}.apply.json").read_text(encoding="utf-8")) == BASE_APPLY_RECORD_NOMOVE
    assert not (proj / "directions" / f"{rid}.edits.json").exists()
    for tag, blk in (("plain", T._block()), ("min", T._minimal_block()), ("refs", T._with_refs(T._block()))):
        out, raw = T._check_out(tmp_path, blk, tag)
        assert "edits" not in out
        assert _masked(raw.decode("utf-8")) == BASE_OUTCOME[tag], tag


def test_edit_module_is_not_imported_without_edit_ops(tmp_path):
    script = f"""
import sys, json
sys.path.insert(0, {str(REPO)!r})
from pathlib import Path
import tests.test_direction_update as T
from mankomix.director import direction as D
tmp = Path({str(tmp_path)!r})
proj = T._project(tmp / "p", low_amp=0.2)
doc = D.parse_document(T._write_doc(tmp / "d", T._block()))
D.validate(doc, proj)
D.build_proposal(D._Project(proj), doc)
nomove = T._minimal_block(); nomove["moves"] = []
D.apply(proj, T._write_doc(tmp / "d2", nomove))
T._check_out(tmp, T._block(), "x")
# repo directions that carry no edit op; a direction that does choose edit_trim/edit_gate
# is allowed to import the edit module, so it is excluded by parsing its moves.
EDIT_OPS = {{"edit_trim", "edit_gate"}}
picked = []
for f in sorted(Path({str(SONG_DIR)!r}).glob("*/direction.md")):
    d = D.parse_document(f)
    if any((m or {{}}).get("op") in EDIT_OPS for m in ((d.get("block") or {{}}).get("moves") or [])):
        continue
    D.validate(d)
    picked.append(f.parent.name)
print(json.dumps(picked))
print(json.dumps("mankomix.director.edit" in sys.modules))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=str(REPO), timeout=300,
                         env={**__import__("os").environ, "MANKOMIX_HOME": str(tmp_path / "home")})
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    # at least the six pre-existing directions were validated (never pass on an empty set)
    assert set(json.loads(lines[-2])) >= set(BASE_VALIDATE), lines[-2]
    assert lines[-1] == "false"


# ---------------------------------------------------------------------------
# 2. detection and the safeguards on synthetic stems
# ---------------------------------------------------------------------------

def test_noise_is_cut_and_a_decaying_tone_is_refused_by_eg3():
    plan = _plan(_guitar())
    cut = [(r["t0_s"], r["t1_s"]) for r in plan["regions"]]
    # the silence after the first phrase and the low noise are cut
    assert any(t0 < 2.5 and t1 > 3.9 for t0, t1 in cut), cut
    assert any(t0 < 6.5 and t1 > 8.9 for t0, t1 in cut), cut
    noise = next(r for r in plan["regions"] if r["t0_s"] < 6.5 and r["t1_s"] > 8.9)
    assert noise["flatness"] is not None and noise["flatness"] > 0.5
    # the decaying tone after the last phrase is musical: refused by EG-3, never cut
    tail = [r for r in plan["refused"] if r["t0_s"] >= 10.0]
    assert len(tail) == 1 and tail[0]["guard"] == "EG-3" and tail[0]["value"] < 0.10
    assert not any(t1 > 10.0 for _, t1 in cut)
    assert plan["status"] == "ok"


@pytest.mark.parametrize("snr_db,refused", [(None, True), (20.0, True), (10.0, True), (-10.0, False)])
def test_eg3_separates_noise_from_decaying_tones(snr_db, refused):
    """White noise passes; a decaying tone (alone or above the noise) stops at the fixed 0.10."""
    tone = _decay(2, -50, 6)
    if snr_db is None:
        region = tone
    else:
        nz = _noise(2, -50, 7)
        region = tone / np.sqrt(np.mean(tone ** 2)) * np.sqrt(np.mean(nz ** 2)) * 10 ** (snr_db / 20.0) + nz
        region *= 10 ** (-50 / 20.0) / np.sqrt(np.mean(region ** 2))
    plan = _plan(_st(_sine(2, -10), _sil(0.6), region), hold_ms=50.0, lead_ms=0.0)
    rows = plan["regions"] + plan["refused"]
    assert len(rows) == 1
    if refused:
        assert plan["refused"] and plan["refused"][0]["guard"] == "EG-3"
    else:
        assert plan["regions"] and plan["regions"][0]["flatness"] >= 0.10


def test_eg1_refuses_a_region_within_36_db_of_the_activity_level():
    # a quiet track (-45 dBFS): the fade margin reaches the phrase, so the region holds content
    x = _st(_sine(1.5, -45), _sil(1.5), _sine(1.5, -45))
    plan = _plan(x, hold_ms=50.0, lead_ms=0.0, fade_ms=200.0)
    assert not plan["regions"]
    assert [r["guard"] for r in plan["refused"]] == ["EG-1"]
    assert plan["refused"][0]["value"] > -36.0 and plan["refused"][0]["limit"] == -36.0


def test_eg2_refuses_a_region_louder_than_minus_40_dbfs():
    x = _st(_square(2.0), _noise(2.0, -38.0, 3), _square(2.0))
    plan = _plan(x)
    assert not plan["regions"]
    r = plan["refused"][0]
    assert r["guard"] == "EG-2" and r["value"] > -40.0 and r["rel_active_db"] <= -36.0


def test_eg4_withdraws_the_largest_regions_first():
    x = _st(_sine(1, -10), _noise(10, -50, 4), _sine(1, -10), _noise(10, -60.3, 5), _sine(0.5, -10))
    plan = _plan(x)
    eg4 = [r for r in plan["refused"] if r["guard"] == "EG-4"]
    assert len(eg4) == 1 and eg4[0]["t0_s"] < 2.0          # the -50 dBFS region (the larger energy)
    assert len(plan["regions"]) == 1 and plan["regions"][0]["t0_s"] > 11.0
    assert plan["removed_energy_rel_db"] <= -40.0


def _bursts(k: int) -> np.ndarray:
    parts = []
    for i in range(k + 1):
        parts.append(_sine(0.1, -10))
        if i < k:
            parts.append(_sil(0.4))
    return _st(*parts)


def test_eg5_withholds_a_move_of_49_regions():
    p = dict(hold_ms=50.0, lead_ms=0.0, min_gap_ms=200.0, fade_ms=2.0)
    ok = _plan(_bursts(48), **p)
    assert ok["status"] == "ok" and len(ok["regions"]) == 48
    many = _plan(_bursts(49), **p)
    assert many["status"] == "too_many_regions" and not many["regions"]
    assert len(many["refused"]) == 49 and {r["guard"] for r in many["refused"]} == {"EG-5"}
    assert many["refused"][0]["value"] == 49 and many["refused"][0]["limit"] == 48


def test_trim_tail_and_head():
    x = _st(_sil(1.0), _sine(3, -12), _noise(2, -80, 9))
    tail = _plan(x, "edit_trim", side="tail")
    assert [(r["start"], r["end"]) for r in tail["regions"]] == [(tail["regions"][0]["start"], x.shape[0])]
    assert tail["regions"][0]["t0_s"] == pytest.approx(4.0 + 0.4, abs=0.06)
    both = _plan(x, "edit_trim", side="both")
    assert len(both["regions"]) == 2 and both["regions"][0]["start"] == 0
    assert both["regions"][0]["t1_s"] == pytest.approx(1.0 - 0.07, abs=0.03)


def test_silent_track_has_no_region():
    plan = _plan(_st(_sil(3)))
    assert plan["regions"] == [] and plan["active_db"] is None and "silent" in plan["note"]


# ---------------------------------------------------------------------------
# 3. validate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mutate,code", [
    (lambda m: m["params"].update(threshold_db=-30.0), "param_range"),
    (lambda m: m["params"].update(hold_ms=[40.0, 400.0]), "param_range"),
    (lambda m: m["params"].update(fade_ms=500), "param_range"),
    (lambda m: m["params"].update(min_gap_ms=100), "param_range"),
    (lambda m: m["params"].update(lead_ms=150), "param_range"),
    (lambda m: m["params"].update(guard_off=True), "bad_value"),
    (lambda m: m["params"].update(side="tail"), "bad_value"),          # side is edit_trim only
    (lambda m: m["params"].update(hold_ms="long"), "bad_value"),
    (lambda m: m.update(target="bus_mix"), "bad_target"),
    (lambda m: m.update(target="trk_nope"), "unknown_target"),
    (lambda m: m.update(params={}), "missing_field"),
])
def test_validate_rejects_bad_edit_moves(song, tmp_path, mutate, code):
    m = _move()
    mutate(m)
    v = D.validate(D.parse_document(_doc(tmp_path / "d", _block([m]))), song)
    assert not v["ok"] and code in {e["code"] for e in v["errors"]}, v["errors"]


def test_validate_rejects_master_target_and_trim_side(song, tmp_path):
    v = D.validate(D.parse_document(_doc(tmp_path / "a", _block([_move(target="master")]))), song)
    assert {"bad_target", "invariant"} <= {e["code"] for e in v["errors"]}
    m = _move(op="edit_trim", params={"side": "middle"})
    v = D.validate(D.parse_document(_doc(tmp_path / "b", _block([m]))), song)
    assert "bad_value" in {e["code"] for e in v["errors"]}
    m = _move(op="edit_trim", params={"side": "both", "min_gap_ms": 500})
    v = D.validate(D.parse_document(_doc(tmp_path / "c", _block([m]))), song)
    assert "bad_value" in {e["code"] for e in v["errors"]}


@pytest.mark.parametrize("section", ["sec2", {"t0_s": 5.0, "t1_s": 12.0}, "all", None])
def test_validate_accepts_sections_and_ranges(song, tmp_path, section):
    m = _move(section=section, params=_gate(threshold_db=[-48.0, -36.0]), select={"threshold_db": "max"})
    v = D.validate(D.parse_document(_doc(tmp_path / "d", _block([m]))), song)
    assert v["ok"], v["errors"]
    t = _move(op="edit_trim", params={"side": "both", "hold_ms": 200, "fade_ms": [5, 50]}, section=section)
    v = D.validate(D.parse_document(_doc(tmp_path / "t", _block([t]))), song)
    assert v["ok"], v["errors"]


def test_validate_unknown_section(song, tmp_path):
    v = D.validate(D.parse_document(_doc(tmp_path / "d", _block([_move(section="sec9")]))), song)
    assert "unknown_section" in {e["code"] for e in v["errors"]}


# ---------------------------------------------------------------------------
# 4. detection is on the raw asset
# ---------------------------------------------------------------------------

def test_detection_does_not_depend_on_the_cleanup(song):
    params = E.full_params("edit_gate", _gate())
    before = E.plan_track(song, "trk_guitar", "edit_gate", params)
    r = api.clean_plan(str(song), targets=["trk_guitar"], overrides={"spectral_reduction": "light"}, apply=True,
                       actor="agent")
    assert r.get("applied")
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    assert data["tracks"][0]["cleanup"]["applied"]["assets"]   # the cleanup is really in use now
    cleaned, _, _ = mr.render_track(Project.open(song), "trk_guitar", apply_chain=False, apply_fader=False)
    raw, _, _ = E.raw_track(song, "trk_guitar")
    assert not np.array_equal(cleaned, raw)
    after = E.plan_track(song, "trk_guitar", "edit_gate", params)
    assert after == before
    r = api.clean_plan(str(song), targets=["trk_guitar"], overrides={"spectral_reduction": "run"}, apply=True,
                       actor="agent")
    assert E.plan_track(song, "trk_guitar", "edit_gate", params) == before


def test_cleanup_override_and_edit_in_one_direction(song, tmp_path):
    scan = E.scan(song, "trk_guitar", "edit_gate", _gate())
    co = {"id": "m02", "aim": "a1", "op": "cleanup_override", "target": "trk_guitar",
          "params": {"overrides": {"spectral_reduction": "light"}}, "basis": "x", "origin": "new"}
    doc = _doc(tmp_path / "d", _block([_move(), co]))
    a = D.apply(song, doc)
    assert a["applied"] and a["cleanup"][0]["applied"]
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))
    got = [(r["start"], r["end"]) for r in led["moves"]["m01"]["regions"]]
    assert got == [(r["start"], r["end"]) for r in scan["regions"]]


# ---------------------------------------------------------------------------
# 5-7, 10. apply, ledger, revert, scan
# ---------------------------------------------------------------------------

def test_apply_ledger_record_and_journal(song, tmp_path):
    seq0 = journal.last_seq(song)
    trim = _move("m02", op="edit_trim", target="trk_vocals", params={"side": "tail"})
    doc = _doc(tmp_path / "d", _block([_move(), trim], listen_for=[{"t_s": 11.0, "what": "end"}]))
    a = D.apply(song, doc)
    did = D.parse_document(doc)["id"]
    assert a["applied"] and "mix_proposal" not in a
    led = json.loads((song / "directions" / f"{did}.edits.json").read_text(encoding="utf-8"))
    assert led["kind"] == "direction_edits" and led["journal_seq_before"] == seq0 and led["reverted"] is False
    assert led["measure"]["guards"] == {"EG-1": -36.0, "EG-2": -40.0, "EG-3": 0.10, "EG-4": -40.0, "EG-5": 48}
    m = led["moves"]["m01"]
    assert m["status"] == "applied" and len(m["regions"]) >= 2 and len(m["refused"]) == 1
    seqs = {e["seq"]: e for e in journal.list_entries(song)}
    for r in m["regions"]:
        assert r["journal_seq"] in seqs and seqs[r["journal_seq"]]["op"] == "range_mute"
        assert r["muted_clips"]
    assert m["fades_journal_seq"] in seqs and m["fades"]
    assert all(f["after"] == int(0.02 * SR) and f["before"] == 0 for f in m["fades"])
    assert led["moves"]["m02"]["status"] == "no_regions"          # the vocal plays to the end
    # the apply record and its summary
    rec = json.loads((song / "directions" / f"{did}.apply.json").read_text(encoding="utf-8"))
    rm = rec["record"]["moves"]["m01"]
    assert rm["regions"] == len(m["regions"]) and rm["refused"] == len(m["refused"])
    assert rm["ledger"] == f"directions/{did}.edits.json" and rm["track"] == "trk_guitar"
    assert a["edits"] == {"moves": 2, "regions": len(m["regions"]), "refused": len(m["refused"]),
                          "ledger": f"directions/{did}.edits.json"}
    # muted clips really are muted, the rest of the clip layout plays
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    clips = {c["id"]: c for c in data["tracks"][0]["clips"]}
    assert all(clips[c]["muted"] for r in m["regions"] for c in r["muted_clips"])


def test_apply_keeps_the_timeline_and_writes_no_audio(song, tmp_path):
    rate = mr.project_rate(Project.open(song).data)
    n0 = mr.timeline_length(Project.open(song).data, rate)
    audio0, kb0 = _audio_files(song), _audio_files(REPO / "kb")
    D.apply(song, _doc(tmp_path / "d", _block([_move()])))
    assert mr.timeline_length(Project.open(song).data, rate) == n0
    assert _audio_files(song) == audio0 and _audio_files(REPO / "kb") == kb0


def test_revert_and_checkout_render_bit_identically(song, tmp_path):
    p0 = Project.open(song)
    t0, _, _ = mr.render_track(p0, "trk_guitar")
    m0, _, _ = mr.render_mix(p0, measure=False)
    doc = _doc(tmp_path / "d", _block([_move()]))
    a = D.apply(song, doc)
    did = a["id"]
    t1, _, _ = mr.render_track(Project.open(song), "trk_guitar")
    assert not np.array_equal(t0, t1)
    r = E.revert(song, did)
    assert r["reverted_moves"] == ["m01"] and r["ledger_reverted"]
    p2 = Project.open(song)
    t2, _, _ = mr.render_track(p2, "trk_guitar")
    m2, _, _ = mr.render_mix(p2, measure=False)
    assert np.array_equal(t0, t2) and np.array_equal(m0, m2)
    led = json.loads((song / "directions" / f"{did}.edits.json").read_text(encoding="utf-8"))
    assert led["reverted"] is True and led["moves"]["m01"]["status"] == "reverted"
    assert led["moves"]["m01"]["reverted_journal_seq"] == r["journal_seq"] == journal.last_seq(song)
    # checkout to the state before the edit
    api.checkout(str(song), led["journal_seq_before"], actor="human")
    p3 = Project.open(song)
    t3, _, _ = mr.render_track(p3, "trk_guitar")
    m3, _, _ = mr.render_mix(p3, measure=False)
    assert np.array_equal(t0, t3) and np.array_equal(m0, m3)


def test_revert_one_move(song, tmp_path):
    g2 = _move("m02", target="trk_vocals")
    a = D.apply(song, _doc(tmp_path / "d", _block([_move(), g2])))
    r = E.revert(song, a["id"], "m01")
    assert r["reverted_moves"] == ["m01"]
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))
    assert led["moves"]["m01"]["status"] == "reverted" and led["moves"]["m02"]["status"] == "no_regions"
    assert led["reverted"] is True                       # no applied move is left
    with pytest.raises(E.EditError):
        E.revert(song, a["id"], "m09")


def test_scan_writes_nothing_and_matches_apply(song, tmp_path):
    before = _files(song)
    s = E.scan(song, "trk_guitar", "edit_gate", _gate())
    s2 = E.scan(song, "trk_guitar", "edit_gate", _gate(), "sec2")
    assert _files(song) == before
    assert s["kind"] == "direction_edit_scan" and s["regions"]
    assert all(r["start"] >= 6 * SR for r in s2["regions"] + s2["refused"])
    a = D.apply(song, _doc(tmp_path / "d", _block([_move()])))
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))["moves"]["m01"]
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("muted_clips", "journal_seq")} for r in rows]  # noqa: E731
    assert strip(led["regions"]) == s["regions"] and led["refused"] == s["refused"]
    assert led["removed_energy_rel_db"] == s["removed_energy_rel_db"]


def test_scan_rejects_bad_params(song):
    with pytest.raises(E.EditError):
        E.scan(song, "trk_guitar", "edit_gate", {"threshold_db": -10})
    with pytest.raises(E.EditError):
        E.scan(song, "trk_guitar", "edit_other", {})


def test_cli_scan_and_revert(song, tmp_path):
    from mankomix.cli.main import main
    before = _files(song)
    assert main(["direction", "edit", "scan", "--project", str(song), "--track", "trk_guitar", "--op", "edit_gate",
                 "--params", json.dumps(_gate())]) == 0
    assert _files(song) == before
    a = D.apply(song, _doc(tmp_path / "d", _block([_move()])))
    assert main(["direction", "edit", "revert", "--project", str(song), "--direction", a["id"]]) == 0
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))
    assert led["reverted"] is True


# ---------------------------------------------------------------------------
# 8. review tier
# ---------------------------------------------------------------------------

def test_edit_moves_are_never_e1(song, tmp_path):
    cat = _move(origin="catalog", basis="R-06")
    lead = _move("m02", target="trk_vocals", origin="catalog", basis="R-06")
    v = D.validate(D.parse_document(_doc(tmp_path / "a", _block([cat, lead]))), song)
    assert v["ok"], v["errors"]
    assert v["tiers"] == {"m01": "E2", "m02": "E3"}
    assert {"listen_for"} <= {w["code"] for w in v["warnings"]}
    v = D.validate(D.parse_document(_doc(tmp_path / "b", _block([cat, lead], listen_for=[{"t_s": 1, "what": "x"}]))),
                   song)
    assert v["tiers"]["m02"] == "E3" and not v["warnings"]
    # the same basis on a gain move still gives E1 (nothing else changed)
    g = {"id": "m03", "aim": "a1", "op": "gain", "target": "trk_guitar", "params": {"delta_db": -1.0},
         "basis": "R-06", "origin": "catalog"}
    v = D.validate(D.parse_document(_doc(tmp_path / "c", _block([g]))), song)
    assert v["tiers"]["m03"] == "E1"


# ---------------------------------------------------------------------------
# 9. convergence with the floor
# ---------------------------------------------------------------------------

def _render(root: Path) -> None:
    y, sr, _ = mr.render_mix(Project.open(root), measure=False)
    d = root / "renders" / "var_x"
    d.mkdir(parents=True, exist_ok=True)
    audio_io.write(d / "song__hires_native.wav", y, sr)


def test_edit_only_direction_is_not_converged(song, tmp_path):
    floor = _make(tmp_path / "floor", {"guitar": _guitar(), "vocals": _vocal()})
    _render(floor)
    doc = _doc(tmp_path / "d", _block([_move()]))
    D.apply(song, doc)
    _render(song)
    out = D.check(song, floor, doc)
    assert out["convergence"]["mix_state_equal"] is False
    assert out["convergence"]["diff_rms_rel_db"] > -60.0 and out["convergence"]["converged"] is False
    e = out["edits"]
    assert e["moves"] == 1 and e["regions"] >= 2 and e["refused"] == 1 and e["reverted"] is False
    assert e["ledger"].endswith(".edits.json") and out["move_ref"]["ok"]


def test_nothing_cut_stays_converged(song, tmp_path):
    floor = _make(tmp_path / "floor", {"guitar": _guitar(), "vocals": _vocal()})
    _render(floor)
    doc = _doc(tmp_path / "d", _block([_move(target="trk_vocals")]))
    D.apply(song, doc)
    _render(song)
    out = D.check(song, floor, doc)
    assert out["convergence"]["mix_state_equal"] is True and out["convergence"]["converged"] is True
    assert out["edits"]["regions"] == 0 and out["edits"]["status"] == {"m01": "no_regions"}


def test_calibration_never_takes_an_edit_parameter_as_a_knob(song, tmp_path):
    from mankomix.director import calibrate as C
    m = _move(params=_gate(threshold_db=[-48.0, -36.0]))
    doc = D.parse_document(_doc(tmp_path / "d", _block([m])))
    assert C.knobs(D._without_edit_params(doc), D._Project(song)) == []
    assert C.knobs(doc, D._Project(song)) == []          # the skip in knobs itself (PM P3 16.2)
    a = D.apply(song, _doc(tmp_path / "d", _block([m])), calibrate=True)
    assert a["calibration"]["knobs"] == [] and a["calibration"]["chosen"] == "select"
    assert copy.deepcopy(m)["params"]["threshold_db"] == [-48.0, -36.0]


# ---------------------------------------------------------------------------
# PM P3 16.5: two edit moves on one track (the cut-edge fades wait for the track's last move)
# ---------------------------------------------------------------------------

_SEC_A = {"t0_s": 7.5, "t1_s": 9.0}
_SEC_B = {"t0_s": 6.0, "t1_s": 7.5}
TWO_MOVES = {
    "A": [("m01", {}, _SEC_A), ("m02", {}, _SEC_B)],
    "B": [("m01", {}, _SEC_B), ("m02", {}, _SEC_A)],
    "C": [("m01", {"hold_ms": 1200.0}, None), ("m02", {"hold_ms": 400.0}, None)],
}


def _two_moves(case: str) -> list[dict]:
    out = []
    for mid, extra, sec in TWO_MOVES[case]:
        m = _move(mid, params=_gate(min_gap_ms=200.0, **extra))
        if sec is not None:
            m["section"] = sec
        out.append(m)
    return out


def _renders(root: Path) -> tuple[np.ndarray, np.ndarray]:
    p = Project.open(root)
    t, _, _ = mr.render_track(p, "trk_guitar")
    m, _, _ = mr.render_mix(p, measure=False)
    return t, m


def _guitar_clips(root: Path) -> list[dict]:
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    return next(t for t in data["tracks"] if t["id"] == "trk_guitar")["clips"]


@pytest.mark.parametrize("case", ["A", "B", "C"])
def test_revert_is_bit_identical_with_two_moves_on_one_track(song, tmp_path, case):
    t0, m0 = _renders(song)
    a = D.apply(song, _doc(tmp_path / "d", _block(_two_moves(case))))
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))
    for mid in ("m01", "m02"):
        assert led["moves"][mid]["status"] == "applied" and led["moves"][mid]["regions"], mid
    if case in ("A", "B"):
        first = led["moves"]["m01"]["regions"]
        second = led["moves"]["m02"]["regions"]
        edges = {r["end"] for r in first + second} & {r["start"] for r in first + second}
        assert 180000 in edges                            # the two cuts meet at 7.5 s
    t1, _ = _renders(song)
    assert not np.array_equal(t0, t1)
    r = E.revert(song, a["id"])
    assert r["reverted_moves"] == ["m01", "m02"] and r["ledger_reverted"]
    t2, m2 = _renders(song)
    assert np.array_equal(t0, t2) and np.array_equal(m0, m2)
    clips = _guitar_clips(song)
    assert not any(c.get("muted") for c in clips)
    assert all(int(c.get("fade_in", 0) or 0) == 0 and int(c.get("fade_out", 0) or 0) == 0 for c in clips)
    api.checkout(str(song), led["journal_seq_before"], actor="human")
    t3, m3 = _renders(song)
    assert np.array_equal(t0, t3) and np.array_equal(m0, m3)


def test_revert_one_move_is_refused_when_moves_share_a_track(song, tmp_path):
    t0, m0 = _renders(song)
    a = D.apply(song, _doc(tmp_path / "d", _block(_two_moves("A"))))
    lp = song / a["edits"]["ledger"]

    def state():
        return (hashlib.sha256((song / "project.json").read_bytes()).hexdigest(), journal.last_seq(song),
                lp.read_bytes())

    s0 = state()
    for mid, other in (("m01", "m02"), ("m02", "m01")):
        with pytest.raises(E.EditError) as ei:
            E.revert(song, a["id"], mid)
        assert other in str(ei.value) and "checkout" in str(ei.value)
        assert state() == s0
    E.revert(song, a["id"])
    t2, m2 = _renders(song)
    assert np.array_equal(t0, t2) and np.array_equal(m0, m2)


def test_cut_edges_keep_their_fades_with_two_moves_on_one_track(song, tmp_path):
    a = D.apply(song, _doc(tmp_path / "d", _block(_two_moves("A"))))
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    rate = mr.project_rate(data)
    live = [c for c in _guitar_clips(song) if not c.get("muted")]
    ends = [c for c in live if int(c.get("timeline_start", 0)) + int(mr.clip_length(data, c, rate)) == 154560]
    starts = [c for c in live if int(c.get("timeline_start", 0)) == 214800]
    assert len(ends) == 1 and int(ends[0].get("fade_out", 0)) == 480
    assert len(starts) == 1 and int(starts[0].get("fade_in", 0)) == 480
    led = json.loads((song / a["edits"]["ledger"]).read_text(encoding="utf-8"))
    rows = [f for e in led["moves"].values() for f in e["fades"]]
    assert rows and all(f["before"] == 0 for f in rows)


# ---------------------------------------------------------------------------
# PM P4 17: another direction's edits still in the project on the same track stop the edit stage
# (X = gate on 7.5-9.0 s, Y = gate on 6.0-7.5 s, min_gap_ms 200: 16.5 example A split in two)
# ---------------------------------------------------------------------------

def _one(dirpath: Path, sec, target: str = "trk_guitar") -> Path:
    m = _move(target=target, params=_gate(min_gap_ms=200.0))
    if sec is not None:
        m["section"] = sec
    return _doc(dirpath, _block([m]))


def _no_edit_left(root: Path, track: str = "trk_guitar") -> None:
    data = json.loads((root / "project.json").read_text(encoding="utf-8"))
    clips = next(t for t in data["tracks"] if t["id"] == track)["clips"]
    assert not any(c.get("muted") for c in clips)
    assert all(int(c.get("fade_in", 0) or 0) == 0 and int(c.get("fade_out", 0) or 0) == 0 for c in clips)


def test_apply_refuses_edits_over_another_directions_live_edits(song, tmp_path):
    x = D.apply(song, _one(tmp_path / "x", _SEC_A))
    assert x["edits"]["regions"] >= 1
    ddir = song / "directions"

    def state():
        return (hashlib.sha256((song / "project.json").read_bytes()).hexdigest(), journal.last_seq(song),
                {p.name: p.read_bytes() for p in sorted(ddir.iterdir())})

    s0 = state()
    ydoc = _one(tmp_path / "y", _SEC_B)
    yid = D.parse_document(ydoc)["id"]
    with pytest.raises(D.DirectionError) as ei:
        D.apply(song, ydoc)
    assert x["id"] in str(ei.value) and "trk_guitar" in str(ei.value)
    assert state() == s0
    assert not any(p.name.startswith(yid) for p in ddir.iterdir())


def test_apply_passes_after_the_other_direction_is_reverted(song, tmp_path):
    t0, m0 = _renders(song)
    x = D.apply(song, _one(tmp_path / "x", _SEC_A))
    E.revert(song, x["id"])
    y = D.apply(song, _one(tmp_path / "y", _SEC_B))
    assert y["applied"] and y["edits"]["regions"] >= 1
    E.revert(song, y["id"])
    t2, m2 = _renders(song)
    assert np.array_equal(t0, t2) and np.array_equal(m0, m2)
    _no_edit_left(song)


def test_apply_passes_after_checkout_of_the_other_direction(song, tmp_path):
    t0, m0 = _renders(song)
    x = D.apply(song, _one(tmp_path / "x", _SEC_A))
    xl = song / x["edits"]["ledger"]
    api.checkout(str(song), json.loads(xl.read_text(encoding="utf-8"))["journal_seq_before"], actor="human")
    assert json.loads(xl.read_text(encoding="utf-8"))["reverted"] is False
    y = D.apply(song, _one(tmp_path / "y", _SEC_B))
    assert y["applied"] and y["edits"]["regions"] >= 1
    E.revert(song, y["id"])
    t2, m2 = _renders(song)
    assert np.array_equal(t0, t2) and np.array_equal(m0, m2)


@pytest.mark.parametrize("order", ["x_first", "y_first"])
def test_apply_passes_when_the_other_direction_edits_another_track(tmp_path, order):
    keys = _st(_sine(2, -13, 220), _sil(2), _sine(2, -13, 220), _noise(3, -58, 2), _sine(3, -13, 220))
    root = _make(tmp_path / "song3", {"guitar": _guitar(), "vocals": _vocal(), "keys": keys})
    p0 = Project.open(root)
    t0 = {t: mr.render_track(p0, t)[0] for t in ("trk_guitar", "trk_keyboard")}
    m0, _, _ = mr.render_mix(p0, measure=False)
    x = D.apply(root, _one(tmp_path / "x", None, target="trk_keyboard"))
    assert x["edits"]["regions"] >= 1
    y = D.apply(root, _one(tmp_path / "y", _SEC_B))
    assert y["applied"] and y["edits"]["regions"] >= 1
    for did in ((x["id"], y["id"]) if order == "x_first" else (y["id"], x["id"])):
        E.revert(root, did)
    p2 = Project.open(root)
    for t in ("trk_guitar", "trk_keyboard"):
        assert np.array_equal(t0[t], mr.render_track(p2, t)[0]), t
        _no_edit_left(root, t)
    assert np.array_equal(m0, mr.render_mix(p2, measure=False)[0])


def test_apply_passes_when_the_other_ledger_cut_nothing(song, tmp_path):
    x = D.apply(song, _one(tmp_path / "x", {"t0_s": 0.0, "t1_s": 2.0}))
    led = json.loads((song / x["edits"]["ledger"]).read_text(encoding="utf-8"))
    assert led["reverted"] is False and led["moves"]["m01"]["status"] == "no_regions"
    y = D.apply(song, _one(tmp_path / "y", _SEC_B))
    assert y["applied"] and y["edits"]["regions"] >= 1
