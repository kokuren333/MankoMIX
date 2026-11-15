"""Cross-track ducking (UPGRADE2 §2.6, T-26 / T-27), array parameters (§8.5, T-33) and
``direction check --translation`` (§3.7-8, T-34).

§2.6
1. a direction without ``duck``: validate, mix proposal (proposal_id, changes), apply record, calibration
   selection and outcome are byte-identical to the code before the duck op
2. synthetic kick + sustained bass: known hit count, -depth_db at every hit, release from the note value,
   recovered_ratio 1.0; a release longer than the hit interval lowers the ratio and adds a note (no refusal)
3. validate refuses out-of-range values, key == target, an unknown key, a bus target, a section,
   release_note with release_ms, release_note without a tempo
4. merge_automation equals the sum of both lists at every sample (floor + duck, section gain + duck, 2 ducks)
5. render: the target renders with the envelope applied; the key track is unchanged
6. move_ref coverage ok; review tier E2 at least, E3 on the lead
7. calibration: a depth_db range resolves inside the range; without duck the selection is unchanged
8. release in ms with a tempo: the nearest note value and the deviation are recorded

§8.5
1. the three stereo array forms validate and go into the chain as arrays
2. existing ranges resolve as before (the existing tests; plus a spot check here)
3. array parameters are never calibration knobs
4. a band-split stereo on the mix bus moves the side ratio of the chosen band only, mid unchanged

§3.7-8: check --translation adds only the translation block; the flagless outcome is byte-identical.

Small synthetic projects in tmp_path (24 kHz).
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from mankomix import repo_data_root
from mankomix.core import audio_io
from mankomix.core import mixrender as mr
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.project import Project
from mankomix.director import calibrate as C
from mankomix.director import direction as D
from mankomix.director import duck as K
from tests.fixtures import synth

SR = 24000
HOP = int(K.HOP_MS * 1e-3 * SR)
REPO = repo_data_root()
SONG_DIR = REPO / "kb" / "songs" / "manko-shugi"
HIT_T0 = 0.25
HIT_IV = 0.5            # = a quarter note at 120 BPM
N_HITS = 12
SECS = HIT_T0 + HIT_IV * N_HITS


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


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


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# synthetic project: kick (60 Hz bursts every 0.5 s), bass (sustained 110 Hz), vocals
# ---------------------------------------------------------------------------

def _hit_samples() -> list[int]:
    return [int(round((HIT_T0 + i * HIT_IV) * SR)) for i in range(N_HITS)]


def _kick() -> np.ndarray:
    x = np.zeros(int(round(SECS * SR)))
    t = np.arange(int(0.15 * SR)) / SR
    burst = 0.5 * np.sin(2 * np.pi * 60.0 * t) * np.exp(-t / 0.05)
    for h in _hit_samples():
        x[h:h + burst.size] += burst
    return np.stack([x, x], axis=1)


def _tone(f: float, dbfs: float) -> np.ndarray:
    t = np.arange(int(round(SECS * SR))) / SR
    x = 10 ** (dbfs / 20.0) * np.sin(2 * np.pi * f * t)
    return np.stack([x, x], axis=1)


def _make(root: Path, stems: dict[str, np.ndarray] | None = None, *, bpm: float | None = 120.0,
          automation: dict | None = None) -> Path:
    stems = stems or {"drums": _kick(), "bass": _tone(110.0, -18.0), "vocals": _tone(440.0, -20.0)}
    src = root.parent / f"{root.name}_stems"
    for name, x in stems.items():
        synth.write_wav(src / f"{name}.wav", x, SR)
    p = Project.create(root, title="duck test")
    FileAdapter().fetch(src, p, actor="human")
    p.set("/mix/applied", {"proposal_id": "mxp_floor"}, actor="human")
    p.set("/variants", [{"id": "var_x", "objective": None,
                         "master": {"profile": "streaming_universal", "chain": []}, "outputs": []}], actor="human")
    if automation:
        tracks = copy.deepcopy(p.data["tracks"])
        for t in tracks:
            if t["id"] in automation:
                t["automation"] = automation[t["id"]]
        p.set("/tracks", tracks, actor="human")
    pdir = root / "cache" / "proposals"
    pdir.mkdir(parents=True, exist_ok=True)
    floor = {"stage": "mix", "status": "applied", "proposal_id": "mxp_floor",
             "changes": {"mix_bus": "bus_mix", "tracks": {}, "buses": []},
             "sections": [{"id": "sec1", "start_s": 0.0, "end_s": 3.0, "label": "a"},
                          {"id": "sec2", "start_s": 3.0, "end_s": SECS, "label": "b"}],
             "objective_evaluation": {"score": 0.1}, "measurements": {}, "notes": []}
    if bpm is not None:
        floor["tempo"] = {"bpm": bpm, "source": "test"}
    (pdir / "mxp_floor.json").write_text(json.dumps(floor), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def _template(tmp_path_factory) -> Path:
    import os
    old = os.environ.get("MANKOMIX_HOME")
    base = tmp_path_factory.mktemp("duck_tpl")
    os.environ["MANKOMIX_HOME"] = str(base / "home")
    try:
        return _make(base / "song")
    finally:
        if old is None:
            os.environ.pop("MANKOMIX_HOME", None)
        else:
            os.environ["MANKOMIX_HOME"] = old


@pytest.fixture
def song(_template, tmp_path) -> Path:
    dst = tmp_path / "song"
    shutil.copytree(_template, dst)
    return dst


def _block(moves: list[dict], **over) -> dict:
    b = {"schema_version": 1, "kind": "direction", "song": "s", "request": {"utterance": "let the kick through"},
         "sources": {}, "aims": [{"id": "a1", "text": "kick over bass"}],
         "variants": [{"id": "var_x", "profile": "streaming_universal"}],
         "moves": moves,
         "claims": [{"id": "c1", "quantity": "P-03", "direction": "not_worse", "tolerance": 1.0, "primary": True}]}
    b.update(over)
    return b


def _duck(mid="m01", target="trk_bass", **params) -> dict:
    return {"id": mid, "aim": "a1", "op": "duck", "target": target, "params": {"key": "trk_drums", **params},
            "basis": "kick hits through the bass", "origin": "new"}


def _doc(dirpath: Path, block: dict) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / "direction.md"
    p.write_text(f"---\nid: {D.direction_id(block)}\nkind: direction\ntitle: t\ncreated: 2026-11-15\n"
                 f"status: draft\nvisibility: private\n---\n\n# t\n\n```json direction\n"
                 f"{json.dumps(block, ensure_ascii=False)}\n```\n", encoding="utf-8")
    return p


def _validate(song: Path | None, tmp_path: Path, moves: list[dict], tag: str = "v") -> dict:
    return D.validate(D.parse_document(_doc(tmp_path / tag, _block(moves))), song)


def _codes(res: dict) -> set[str]:
    return {e["code"] for e in res["errors"]}


def _render(root: Path) -> None:
    y, sr, _ = mr.render_mix(Project.open(root), measure=False)
    d = root / "renders" / "var_x"
    d.mkdir(parents=True, exist_ok=True)
    audio_io.write(d / "song__hires_native.wav", y, sr)


# ---------------------------------------------------------------------------
# 1. nothing changes without a duck move
# ---------------------------------------------------------------------------

# outputs of direction.py / calibrate.py before the duck op (W-3 golden tmp/upgrade2/golden/W3/fixtures.json;
# the same values as the W-2 golden where both exist). apply_record_nomove / outcome are _masked hashes,
# re-taken in W-9 from HEAD 87800e8 with the current mask (tmp/upgrade2/w9/scripts)
BASE = {"validate_synth": "f0e997b2ca13d4f9", "proposal_synth": "b9fc8176b26b7c51",
        "proposal_id": "mxp_1a4b2293ec3c", "changes": "6b712b6aca37970b", "knobs": "0c9148a98cb0be4e",
        "calibrate_max": "adc832338447d3a2", "calibrate_min": "74655b720c50933d",
        "apply_record_nomove": "9ca1527ce302b959",
        "outcome": {"plain": "7da0e89a35a5ecb1", "min": "b0fb3bc89e66a490", "refs": "dcc18e8b02cdfeda"}}


class _FakePredictor:
    """Deterministic mix-stage prediction from the selection only (no rendering)."""

    def __init__(self, root, doc, progress):
        self.renders = 0

    def deltas(self, sel, label):
        self.renders += 1
        g, w = sel.get("m01.gain_db", 0.0), sel.get("m04.width", 1.0)
        d = sel.get("m09.depth_db", 0.0)
        return {"o1": round(0.3 * g + 0.4 * d, 4), "o2": round((1.0 - w) * 0.4, 4), "o3": 0.0}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def test_without_duck_everything_is_byte_identical(tmp_path, monkeypatch):
    import tests.test_direction_update as T
    proj = T._project(tmp_path / "p", low_amp=0.2)
    doc = D.parse_document(T._write_doc(tmp_path / "d", T._block()))
    assert _sha(json.dumps(D.validate(doc, proj), ensure_ascii=False, sort_keys=True)) == BASE["validate_synth"]
    prop, record, notes = D.build_proposal(D._Project(proj), doc)
    assert _sha(json.dumps({"prop": prop, "record": record, "notes": notes}, ensure_ascii=False,
                           sort_keys=True)) == BASE["proposal_synth"]
    assert prop["proposal_id"] == BASE["proposal_id"] and _h(prop["changes"]) == BASE["changes"]
    assert _sha(json.dumps(C.knobs(doc, D._Project(proj)), ensure_ascii=False, sort_keys=True)) == BASE["knobs"]
    monkeypatch.setattr(C, "_Predictor", _FakePredictor)
    for sel in ("max", "min"):
        b = T._block()
        b["moves"][0]["select"] = {"gain_db": sel}
        d2 = D.parse_document(T._write_doc(tmp_path / f"c{sel}", b))
        cal = C.calibrate(proj, d2, progress=lambda s: None)
        assert _sha(json.dumps(cal, ensure_ascii=False, sort_keys=True)) == BASE[f"calibrate_{sel}"], sel
    nomove = T._minimal_block()
    nomove["moves"] = []
    p2 = T._write_doc(tmp_path / "d2", nomove)
    D.apply(proj, p2)
    rid = D.parse_document(p2)["id"]
    assert _masked((proj / "directions" / f"{rid}.apply.json").read_text(encoding="utf-8")) == \
        BASE["apply_record_nomove"]
    for tag, blk in (("plain", T._block()), ("min", T._minimal_block()), ("refs", T._with_refs(T._block()))):
        out, raw = T._check_out(tmp_path, blk, tag)
        assert "translation" not in out
        assert _masked(raw.decode("utf-8")) == BASE["outcome"][tag], tag


GOLDEN_VALIDATE = ["2026-11-14_p1-kikigokochi", "2026-11-14_p2-ultra-sub-bass", "2026-11-14_p3-spatial-panning",
                   "2026-11-15_p4-ref-fullmix", "2026-11-15_p5-ref-stems", "2026-11-15_p6-vocal-words"]


@pytest.mark.parametrize("folder", GOLDEN_VALIDATE)
def test_existing_directions_validate_unchanged(folder):
    import tests.test_upgrade2_edit as TE
    did, h = TE.BASE_VALIDATE[folder]
    doc = D.parse_document(SONG_DIR / folder / "direction.md")
    res = D.validate(doc)
    assert doc["id"] == did and res["ok"] and _h(res) == h


def test_duck_module_is_not_imported_without_duck(tmp_path):
    import subprocess
    import sys
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
T._check_out(tmp, T._block(), "x")
print(json.dumps(["mankomix.director.duck" in sys.modules, "mankomix.director.translation" in sys.modules]))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=str(REPO), timeout=300,
                         env={**__import__("os").environ, "MANKOMIX_HOME": str(tmp_path / "home")})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [False, False]


# ---------------------------------------------------------------------------
# 2. hits, depth, release and recovery on a synthetic kick + bass
# ---------------------------------------------------------------------------

def test_hits_depth_release_and_recovery(song):
    pr = D._Project(song)
    dp = K.plan(song, {"id": "m01", "target": "trk_bass"}, {"key": "trk_drums"}, K.floor_bpm(pr.floor_mxp))
    rec = dp["record"]
    assert rec["hits"] == N_HITS
    truth = _hit_samples()
    hits, sr = K.key_hits(song, "trk_drums", K.full_params({"key": "trk_drums"}))
    assert sr == SR
    assert all(abs(h - t) <= 2 * HOP for h, t in zip(hits, truth))
    # the release is the default note value 1/8 at 120 BPM = 250 ms (R-11)
    assert rec["release"] == {"note": "1/8", "bpm": 120.0, "ms": 250.0, "rule": "R-11"}
    assert rec["depth_db"] == 2.0 and rec["attack_ms"] == 5.0 and rec["key_band_hz"] == [40.0, 120.0]
    pts = dp["points"]
    assert len(pts) == 3 * N_HITS and rec["points"] == len(pts)
    assert all(b[0] > a[0] for a, b in zip(pts, pts[1:]))
    env = K.evaluate(pts, np.asarray(hits, dtype=float))
    assert np.allclose(env, -2.0)
    for i, h in enumerate(hits):
        assert pts[3 * i + 2][0] - h == int(round(0.25 * SR))     # back at 0 dB after the note value
    r = rec["recovery"]
    assert r["hits"] == N_HITS and r["recovered"] == N_HITS and r["recovered_ratio"] == 1.0
    assert abs(r["median_interval_ms"] - 500.0) <= 2 * K.HOP_MS and r["release_ms"] == 250.0
    assert dp["notes"] == []


def test_a_long_release_lowers_the_ratio_and_is_a_note_not_a_refusal(song, tmp_path):
    m = _duck(release_note="1/2")         # 1000 ms > the 500 ms hit interval
    assert _validate(song, tmp_path, [m])["ok"]
    prop, record, notes = D.build_proposal(D._Project(song), D.parse_document(_doc(tmp_path / "d", _block([m]))))
    r = record["moves"]["m01"]["recovery"]
    assert r["recovered"] == 1 and r["recovered_ratio"] == round(1 / N_HITS, 4)
    assert any("m01" in n and "回復" in n and f"{N_HITS - 1}/{N_HITS}" in n for n in notes)
    pts = prop["changes"]["tracks"]["trk_bass"]["automation"]["gain_db"]
    hits = [p[0] for p in pts[1::3]]
    for i in range(N_HITS - 1):       # cut at the next hit's attack, so every hit still starts from 0 dB
        assert pts[3 * i + 2][0] == hits[i + 1] - int(round(0.005 * SR)) - 1
    a = D.apply(song, _doc(tmp_path / "d", _block([m])))
    assert a["applied"] is True and any("回復" in n for n in a["notes"])


def test_no_hit_writes_nothing(tmp_path):
    song = _make(tmp_path / "quiet", {"drums": _tone(1000.0, -60.0) * 0.0, "bass": _tone(110.0, -18.0)})
    prop, record, notes = D.build_proposal(D._Project(song), D.parse_document(_doc(tmp_path / "d",
                                                                                   _block([_duck()]))))
    assert record["moves"]["m01"]["hits"] == 0 and "note" in record["moves"]["m01"]
    assert "automation" not in prop["changes"]["tracks"].get("trk_bass", {})
    assert any("0 件" in n for n in notes)


# ---------------------------------------------------------------------------
# 3. validate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("params,code", [
    ({"depth_db": 6.5}, "param_range"),
    ({"depth_db": [1.0, 6.5]}, "param_range"),
    ({"depth_db": 0.4}, "param_range"),
    ({"key_lo_hz": 100.0, "key_hi_hz": 140.0}, "param_range"),
    ({"key_hi_hz": 50.0}, "param_range"),
    ({"key_lo_hz": [40.0, 80.0]}, "bad_value"),
    ({"trigger_below_p95_db": 30.0}, "param_range"),
    ({"attack_ms": 40.0}, "param_range"),
    ({"release_ms": 20.0}, "param_range"),
    ({"min_interval_ms": 600.0}, "param_range"),
    ({"release_note": "1/8", "release_ms": 120.0}, "bad_value"),
    ({"release_note": "none"}, "bad_value"),
    ({"release_note": "3/8"}, "bad_value"),
    ({"ratio": 2.0}, "bad_value"),
    ({"key": "trk_bass"}, "bad_value"),
    ({"key": "trk_nope"}, "unknown_target"),
    ({"key": "bus_mix"}, "bad_target"),
    ({"key": None}, "missing_field"),
])
def test_validate_refuses_bad_duck_params(song, tmp_path, params, code):
    m = _duck(**params)
    if params.get("key", "x") is None:
        m["params"].pop("key")
    assert code in _codes(_validate(song, tmp_path, [m]))


def test_validate_refuses_bad_targets_and_sections(song, tmp_path):
    assert "bad_target" in _codes(_validate(song, tmp_path, [_duck(target="bus_mix")], "bus"))
    assert "bad_target" in _codes(_validate(song, tmp_path, [_duck(target="master")], "master"))
    assert "unknown_target" in _codes(_validate(song, tmp_path, [_duck(target="trk_nope")], "unk"))
    for sec in ("sec1", {"t0_s": 0.0, "t1_s": 1.0}):
        m = _duck()
        m["section"] = sec
        assert "section_scope" in _codes(_validate(song, tmp_path, [m], f"sec{type(sec).__name__}"))
    m = _duck()
    m["section"] = "all"
    assert _validate(song, tmp_path, [m], "all")["ok"]


def test_release_note_needs_a_tempo(tmp_path):
    song = _make(tmp_path / "nobpm", bpm=None)
    res = _validate(song, tmp_path, [_duck(release_note="1/8")], "n1")
    assert "needs_bpm" in _codes(res)
    # without --project the tempo is unknown: not reported (apply validates with the project)
    assert _validate(None, tmp_path, [_duck(release_note="1/8")], "n2")["ok"]
    a = D.apply(song, _doc(tmp_path / "d", _block([_duck(release_note="1/8")])))
    assert a["applied"] is False and "needs_bpm" in _codes(a["validation"])
    # neither note nor ms without a tempo: the floor's ms default
    prop, record, _ = D.build_proposal(D._Project(song), D.parse_document(_doc(tmp_path / "d3", _block([_duck()]))))
    rel = record["moves"]["m01"]["release"]
    assert rel["note"] is None and rel["ms"] == 120.0 and rel["rule"] == "R-11"


def test_validate_accepts_a_full_duck(song, tmp_path):
    m = _duck(depth_db=[1.0, 3.0], key_lo_hz=40.0, key_hi_hz=120.0, trigger_below_p95_db=6.0, attack_ms=[2.0, 8.0],
              release_note="1/16", min_interval_ms=80.0)
    m["select"] = {"depth_db": "max"}
    res = _validate(song, tmp_path, [m])
    assert res["ok"], res["errors"]
    assert res["warnings"] == []


# ---------------------------------------------------------------------------
# 4. merge_automation
# ---------------------------------------------------------------------------

def _check_sum(a, b):
    m = K.merge_automation(a, b)
    xs = np.concatenate([K._points(a)[0], K._points(b)[0]])
    lo, hi = int(xs.min()) - 50, int(xs.max()) + 50
    t = np.arange(lo, hi + 1, dtype=float)
    assert np.max(np.abs(K.evaluate(m, t) - (K.evaluate(a, t) + K.evaluate(b, t)))) <= 1e-9
    assert all(q[0] > p[0] for p, q in zip(m, m[1:]))
    return m


def test_merge_automation_is_the_exact_sum():
    rng = np.random.default_rng(3)
    for _ in range(20):
        a = [[int(x), float(v)] for x, v in zip(np.sort(rng.choice(10000, 7, replace=False)), rng.normal(0, 3, 7))]
        b = [[int(x), float(v)] for x, v in zip(np.sort(rng.choice(10000, 5, replace=False)), rng.normal(0, 3, 5))]
        _check_sum(a, b)
    assert K.merge_automation([], [[10, -1.0]]) == [[10, -1.0]]
    assert K.merge_automation(None, None) == []
    # the dict form of the renderer is read as well
    _check_sum([{"at": 0, "value": -1.0}, {"at": 100, "value": 0.0}], [[50, -2.0], [80, 0.0]])


def test_merge_with_floor_automation_section_gain_and_two_ducks(tmp_path):
    floor_auto = {"gain_db": [[0, 0.0], [24000, -1.5], [48000, 0.0]], "owner": "mixplan", "reason": "floor"}
    song = _make(tmp_path / "s", automation={"trk_bass": floor_auto})
    pr = D._Project(song)
    gain = {"id": "m02", "aim": "a1", "op": "gain", "target": "trk_bass", "section": "sec2",
            "params": {"delta_db": -1.0}, "basis": "x", "origin": "new"}
    m3 = _duck("m03", depth_db=1.0, key_lo_hz=40.0, key_hi_hz=200.0)
    doc = D.parse_document(_doc(tmp_path / "d", _block([_duck(), gain, m3])))
    assert D.validate(doc, song)["ok"]
    prop, record, _ = D.build_proposal(pr, doc)
    auto = prop["changes"]["tracks"]["trk_bass"]["automation"]
    assert auto["owner"] == "director"
    assert auto["move_ref"] == [f"{doc['id']}/m02", f"{doc['id']}/m01", f"{doc['id']}/m03"]
    d1 = K.plan(song, {"id": "m01", "target": "trk_bass"}, {"key": "trk_drums"}, 120.0)["points"]
    d3 = K.plan(song, {"id": "m03", "target": "trk_bass"}, {"key": "trk_drums", "depth_db": 1.0,
                                                              "key_hi_hz": 200.0}, 120.0)["points"]
    seg = D._automation(SR, [(3.0, SECS, -1.0)], None)
    t = np.arange(0, int(SECS * SR) + 100, dtype=float)
    want = K.evaluate(floor_auto["gain_db"], t) + K.evaluate(seg, t) + K.evaluate(d1, t) + K.evaluate(d3, t)
    assert np.max(np.abs(K.evaluate(auto["gain_db"], t) - want)) <= 1e-9
    assert record["moves"]["m01"]["floor_automation"] == {"points": 3, "owner": "mixplan"}
    # each pair alone as well
    _check_sum(floor_auto["gain_db"], d1)
    _check_sum(seg, d1)
    _check_sum(d1, d3)


def test_section_gain_on_floor_automation_without_duck_is_still_refused(tmp_path):
    song = _make(tmp_path / "s", automation={"trk_bass": {"gain_db": [[0, 0.0], [100, -1.0]], "owner": "mixplan"}})
    gain = {"id": "m02", "aim": "a1", "op": "gain", "target": "trk_bass", "section": "sec2",
            "params": {"delta_db": -1.0}, "basis": "x", "origin": "new"}
    with pytest.raises(D.DirectionError, match="already has gain automation"):
        D.build_proposal(D._Project(song), D.parse_document(_doc(tmp_path / "d", _block([gain]))))


# ---------------------------------------------------------------------------
# 5. render, 6. move_ref and tier
# ---------------------------------------------------------------------------

def test_target_renders_with_the_envelope_and_the_key_is_unchanged(song, tmp_path):
    p0 = Project.open(song)
    key0, _, _ = mr.render_track(p0, "trk_drums")
    a = D.apply(song, _doc(tmp_path / "d", _block([_duck(depth_db=3.0)])))
    assert a["applied"] is True
    p1 = Project.open(song)
    bass = next(t for t in p1.data["tracks"] if t["id"] == "trk_bass")
    pts = bass["automation"]["gain_db"]
    raw, _, _ = mr.render_track(p1, "trk_bass", apply_fader=False)
    got, _, _ = mr.render_track(p1, "trk_bass")
    g = 10 ** (float(bass.get("gain_db", 0.0)) / 20.0)
    env = 10 ** (K.evaluate(pts, np.arange(raw.shape[0], dtype=float)) / 20.0)
    assert np.allclose(got, raw * (env * g)[:, None], atol=1e-12)
    key1, _, _ = mr.render_track(p1, "trk_drums")
    assert np.array_equal(key0, key1)
    kick = next(t for t in p1.data["tracks"] if t["id"] == "trk_drums")
    assert not kick.get("automation")


def test_move_ref_coverage_and_tiers(song, tmp_path):
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    _render(floor)
    lead = _duck("m02", target="trk_vocals")
    cat = _duck("m01")
    cat.update(origin="catalog", basis="R-11")
    blk = _block([cat, lead], listen_for=[{"t_s": 1.0, "what": "vocal dips"}])
    doc = _doc(tmp_path / "d", blk)
    v = D.validate(D.parse_document(doc), song)
    assert v["ok"] and v["tiers"] == {"m01": "E2", "m02": "E3"}
    assert D.validate(D.parse_document(_doc(tmp_path / "nolisten", _block([lead]))), song)["warnings"]
    D.apply(song, doc)
    _render(song)
    out = D.check(song, floor, doc)
    mr_ = out["move_ref"]
    assert mr_["ok"] and set(mr_["by_move"]) == {"m01", "m02"} and mr_["moves_without_trace"] == []
    assert out["convergence"]["mix_state_equal"] is False


def test_a_duck_without_hits_is_traced_by_its_record(tmp_path):
    song = _make(tmp_path / "quiet", {"drums": _tone(1000.0, -60.0) * 0.0, "bass": _tone(110.0, -18.0)})
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    _render(floor)
    doc = _doc(tmp_path / "d", _block([_duck()]))
    D.apply(song, doc)
    _render(song)
    out = D.check(song, floor, doc)
    assert out["move_ref"]["ok"] and out["convergence"]["mix_state_equal"] is True


# ---------------------------------------------------------------------------
# 7. calibration, 8. ms release with a tempo
# ---------------------------------------------------------------------------

def test_calibration_depth_range(song, tmp_path, monkeypatch):
    assert C.strong_end("duck", None, "depth_db", 1.0, 4.0, {}) == 4.0
    assert C.strong_end("duck", None, "attack_ms", 2.0, 8.0, {}) is None
    assert C.strong_end("duck", None, "release_ms", 60.0, 200.0, {}) is None
    m = _duck(depth_db=[1.0, 4.0], attack_ms=[2.0, 8.0])
    m["select"] = {"depth_db": "min"}
    blk = _block([m], observations=[{"id": "o1", "primitive": "crest", "target": "master"}],
                 claims=[{"id": "c1", "quantity": "obs:o1", "direction": "up", "min_delta": 0.05, "primary": True}])
    m["expect"] = [{"quantity": "obs:o1", "direction": "up", "min_delta": 0.05}]
    doc = D.parse_document(_doc(tmp_path / "d", blk))
    ks = {k["id"]: k for k in C.knobs(doc, D._Project(song))}
    assert set(ks) == {"m01.depth_db", "m01.attack_ms"}
    assert ks["m01.depth_db"]["strong"] == 4.0 and ks["m01.attack_ms"]["strong"] is None
    a = D.apply(song, _doc(tmp_path / "d", blk), calibrate=True)
    assert a["applied"] is True
    cal = a["calibration"]
    assert 1.0 <= cal["selection"]["m01.depth_db"] <= 4.0
    assert cal["selection"]["m01.attack_ms"] == 5.0
    assert a["record"]["moves"]["m01"]["depth_db"] == round(cal["selection"]["m01.depth_db"], 4)
    # the fake predictor too: a depth range resolves inside the range
    monkeypatch.setattr(C, "_Predictor", _FakePredictor)
    import tests.test_direction_update as T
    proj = T._project(tmp_path / "p", low_amp=0.2)
    b = T._block()
    b["moves"][0]["select"] = {"gain_db": "min"}
    plain = C.calibrate(proj, D.parse_document(T._write_doc(tmp_path / "c1", b)), progress=lambda s: None)
    assert _sha(json.dumps(plain, ensure_ascii=False, sort_keys=True)) == BASE["calibrate_min"]


def test_ms_release_with_a_tempo_records_the_nearest_note(song, tmp_path):
    prop, record, _ = D.build_proposal(D._Project(song), D.parse_document(
        _doc(tmp_path / "d", _block([_duck(release_ms=240.0)]))))
    rel = record["moves"]["m01"]["release"]
    assert rel["note"] == "1/8" and rel["bpm"] == 120.0 and rel["ms"] == 240.0
    assert rel["note_ms"] == 250.0 and rel["deviation_ms"] == -10.0 and rel["rule"] == "R-11"
    assert record["moves"]["m01"]["recovery"]["release_ms"] == 240.0
    assert K.nearest_note(170.0, 120.0)[0] == "1/8t"        # 166.7 ms
    assert K.nearest_note(330.0, 91.208)[0] == "1/8"        # 328.9 ms


# ---------------------------------------------------------------------------
# §8.5 stereo array parameters (T-33)
# ---------------------------------------------------------------------------

ARRAY_FORMS = [
    {"mono_below_hz": 120, "crossovers_hz": [4000], "widths": [1.0, 1.1]},
    {"crossovers_hz": [300, 4000], "widths": [0.8, 1.0, 1.2]},
    {"crossovers_hz": [2000, 6000, 10000], "widths": [1.0, 1.0, 1.1, 1.2]},
]


def _stereo(params, target="bus_mix", mid="m01") -> dict:
    return {"id": mid, "aim": "a1", "op": "chain_add", "target": target, "processor": "stereo",
            "params": params, "basis": "band width", "origin": "new"}


@pytest.mark.parametrize("i", range(len(ARRAY_FORMS)))
def test_stereo_array_forms_validate_and_stay_arrays(song, tmp_path, i):
    params = ARRAY_FORMS[i]
    res = _validate(song, tmp_path, [_stereo(params)])
    assert res["ok"], res["errors"]
    assert D.validate(D.parse_document(_doc(tmp_path / "np", _block([_stereo(params)]))))["ok"]
    a = D.apply(song, _doc(tmp_path / "d", _block([_stereo(params)])))
    assert a["applied"] is True
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    mix = next(b for b in data["buses"] if b["id"] == "bus_mix")
    it = next(x for x in mix["chain"] if x.get("move_ref"))
    assert it["type"] == "stereo"
    assert it["params"]["crossovers_hz"] == [float(x) for x in params["crossovers_hz"]]
    assert it["params"]["widths"] == [float(x) for x in params["widths"]]


def test_ranges_still_resolve_and_arrays_are_not_knobs(song, tmp_path):
    m = {"id": "m", "select": {"gain_db": "max"}}
    out, _ = D.resolve_params(m, {"gain_db": [1.5, 3.0], "widths": [1.0, 1.1], "crossovers_hz": [300, 4000]})
    assert out == {"gain_db": 3.0, "widths": [1.0, 1.1], "crossovers_hz": [300, 4000]}
    assert D._ends({"gain_db": [1.5, 3.0], "widths": [1.0, 1.1]}) == [{"gain_db": 1.5, "widths": [1.0, 1.1]},
                                                                      {"gain_db": 3.0, "widths": [1.0, 1.1]}]
    assert D._ends({"widths": [1.0, 1.1]}) == [{"widths": [1.0, 1.1]}]
    assert D.ARRAY_PARAM_IDS == frozenset({"crossovers_hz", "widths"})
    st = _stereo({"crossovers_hz": [4000], "widths": [1.0, 1.1], "mono_below_hz": [80, 160]})
    doc = D.parse_document(_doc(tmp_path / "d", _block([st])))
    assert D.validate(doc, song)["ok"]
    assert [k["id"] for k in C.knobs(doc, D._Project(song))] == ["m01.mono_below_hz"]
    bus = {"id": "m02", "aim": "a1", "op": "bus_add", "target": "bus_wide",
           "params": {"chain": [{"processor": "stereo", "params": {"crossovers_hz": [4000], "widths": [1.0, 1.2]}}]},
           "basis": "x", "origin": "new"}
    doc2 = D.parse_document(_doc(tmp_path / "d2", _block([bus])))
    assert D.validate(doc2, song)["ok"]
    assert C.knobs(doc2, D._Project(song)) == []


def _ms(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (x[:, 0] + x[:, 1]) / 2.0, (x[:, 0] - x[:, 1]) / 2.0


def _band_rms(x: np.ndarray, lo: float, hi: float) -> float:
    from mankomix.director import query as Q
    y = Q._bandpass(x, SR, [lo, hi])
    n = y.shape[0]
    return float(np.sqrt(np.mean(y[n // 10:-n // 10] ** 2)))


def test_band_split_stereo_on_the_mix_bus(tmp_path):
    t = np.arange(int(3 * SR)) / SR
    mid = 0.1 * np.sin(2 * np.pi * 200 * t) + 0.05 * np.sin(2 * np.pi * 7000 * t)
    side = 0.05 * np.sin(2 * np.pi * 300 * t) + 0.05 * np.sin(2 * np.pi * 8000 * t)
    x = np.stack([mid + side, mid - side], axis=1)
    song = _make(tmp_path / "st", {"pad": x})
    y0, _, _ = mr.render_mix(Project.open(song), measure=False)
    a = D.apply(song, _doc(tmp_path / "d", _block([_stereo({"crossovers_hz": [4000], "widths": [1.0, 0.5]})])))
    assert a["applied"] is True
    y1, _, _ = mr.render_mix(Project.open(song), measure=False)
    m0, s0 = _ms(y0)
    m1, s1 = _ms(y1)
    assert np.max(np.abs(m1 - m0)) < 1e-6                       # the mid is not touched
    assert _band_rms(s1, 6000, 10000) / _band_rms(s0, 6000, 10000) == pytest.approx(0.5, abs=0.02)
    assert _band_rms(s1, 150, 500) / _band_rms(s0, 150, 500) == pytest.approx(1.0, abs=0.02)


# ---------------------------------------------------------------------------
# §3.7-8 check --translation (T-34)
# ---------------------------------------------------------------------------

def _check_both(tmp_path: Path, block: dict, tag: str):
    import tests.test_direction_update as T
    floor = T._project(tmp_path / f"floor_{tag}", low_amp=0.2)
    res = T._project(tmp_path / f"res_{tag}", low_amp=0.3, width=0.7)
    doc = T._write_doc(tmp_path / f"doc_{tag}", block)
    did = D.parse_document(doc)["id"]
    plain = D.check(res, floor, doc)
    raw_plain = (res / "directions" / f"{did}.outcome.json").read_bytes()
    tr = D.check(res, floor, doc, translation=True)
    raw_tr = (res / "directions" / f"{did}.outcome.json").read_bytes()
    return plain, raw_plain, tr, raw_tr


def test_check_translation_adds_only_its_block(tmp_path):
    import tests.test_direction_update as T
    for tag, blk in (("plain", T._block()), ("min", T._minimal_block()), ("refs", T._with_refs(T._block()))):
        plain, raw_plain, tr, raw_tr = _check_both(tmp_path, blk, tag)
        assert _masked(raw_plain.decode("utf-8")) == BASE["outcome"][tag]
        assert "translation" not in plain and "translation" in tr
        a, b = json.loads(raw_plain), json.loads(raw_tr)
        tb = b.pop("translation")
        assert a == b                                    # claims, summary, everything else unchanged
        assert tb["note"].startswith("参考値") and tb["view"] == {"mono_band_hz": [150.0, 6000.0]}
        for k in ("mono_fold_lu", "small_speaker_lu", "low_harmonic_db", "presence_db", "crest_db"):
            assert set(tb[k]) == {"floor", "result", "change"}


def test_cli_check_translation(tmp_path):
    import tests.test_direction_update as T
    from mankomix.cli.main import main
    floor = T._project(tmp_path / "floor", low_amp=0.2)
    res = T._project(tmp_path / "res", low_amp=0.3, width=0.7)
    doc = T._write_doc(tmp_path / "doc", T._block())
    did = D.parse_document(doc)["id"]
    out = res / "directions" / f"{did}.outcome.json"
    D.check(res, floor, doc)
    direct = out.read_bytes()
    main(["direction", "check", str(doc), "--project", str(res), "--floor", str(floor)])
    assert "translation" not in json.loads(out.read_text(encoding="utf-8"))
    assert out.read_bytes() == direct
    main(["direction", "check", str(doc), "--project", str(res), "--floor", str(floor), "--translation"])
    assert "translation" in json.loads(out.read_text(encoding="utf-8"))
