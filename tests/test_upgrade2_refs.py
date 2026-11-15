"""Second update, proposal 3 (design §3.7): transient profile, guide deviation, translation views.

Everything here is optional material for the director: without ``--add`` / ``view`` the refstudy,
the refsheet and the observation values are byte-identical to the state before the change
(golden SHA-256 taken from HEAD before the change, synthetic fixtures). Audio only under tmp_path.

The coupling part (W-4b) adds validate's view rule (§3.7-7, validate side), views measured through
``direction check``, the ``--calibrate`` selection with and without the additions (§3.7-9) and the
attack-density group floor of the PM decision (§15.1, tests a-g; §15.3 GUIDE_NOTE exactly once).
``direction check --translation`` (§3.7-8) is fixed in tests/test_upgrade2_duck.py (W-3), not repeated here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from mankomix.core import audio_io
from mankomix.director import direction as D
from mankomix.director import kb as K
from mankomix.director import query as Q
from mankomix.director import refsheet as RSH
from mankomix.director import refstudy as R
from mankomix.director import translation as TR

from .fixtures import synth

SR = 48000
REPO = Path(__file__).resolve().parents[1]

# §3.7-1: flagless outputs before the change (tmp/upgrade2/golden/W4/, generated from HEAD 87800e8).
# The stems are written as PCM_24: libsndfile puts a time-stamped PEAK chunk into float WAVs, so their
# file hashes (and the refstudy lines quoting them) change from run to run.
GOLDEN = {
    "refstudy_material_a": "435a1f91aec4ea21317c4dd5fc24e509d6ebdcb3a41dd10ce36a99073034d031",
    "refstudy_master_only_sections_ab": "77fc1e75fb70430ba3ef56466dc9ed7c7a19b646c578507a4357188db9e2516c",
    "refsheet_material_a_v1": "ee35b197c97d3d3f5c4321efe768b755dcd381b2f4fb1161bc90775be7df8870",
    "refsheet_material_a_v_pan": "927b8fdfb4737eca4390ed81f663d782a4a0735a3854258a07c1d56149f60817",
}
# observe() without `view` before the change (same seeded signal as below)
GOLDEN_QUERY = [-16.5475, -16.549, 15.0229, 16.0094, -5.0474, 0.5456, -85.2903, 7.0253]
QUERY_SPECS = [{"primitive": "loudness"}, {"primitive": "loudness", "stat": "short_max"}, {"primitive": "crest"},
               {"primitive": "crest", "band_hz": [100, 1000]}, {"primitive": "side_ratio"},
               {"primitive": "correlation", "band_hz": [200, 2000]}, {"primitive": "band_energy", "band_hz": [60, 250]},
               {"primitive": "band_ratio", "band_hz": [2000, 6000], "ref_band_hz": [200, 1000]}]


def _audio_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and audio_io.is_audio_file(p)}


def _tree_hash(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _build_project(root: Path) -> Path:
    """The project of tests/test_refstudy.py (six stems, a send, a master render of v1, variants)."""
    st = synth.song_stems(sr=SR, seconds=8.0, seed=1)
    keep = ["vocals", "drums", "bass", "synth", "keyboard", "guitar"]
    tracks, assets = [], []
    for r in keep:
        synth.write_wav(root / "assets" / f"{r}.wav", st[r], SR)
        assets.append({"id": f"ast_{r}", "path": f"assets/{r}.wav", "sha256": "0" * 64, "channels": 2,
                       "sample_rate": SR, "length_samples": int(st[r].shape[0])})
        tracks.append({"id": f"trk_{r}", "kind": "audio", "role": r, "gain_db": -1.0 if r == "vocals" else 0.0,
                       "pan": {"position": 0.35 if r == "guitar" else 0.0, "width": 1.0},
                       "clips": [{"id": f"clp_{r}", "asset": f"ast_{r}"}]})
    tracks[0]["sends"] = [{"bus": "bus_fx", "level_db": -12.0}]
    buses = [{"id": "bus_fx", "kind": "fx", "output": "bus_mix",
              "chain": [{"id": "prc_fx", "type": "gain", "params": {"gain_db": -3.0}}]},
             {"id": "bus_mix", "kind": "mix", "chain": []}]
    variants = [{"id": "v1"},
                {"id": "v_pan", "track_overrides": {"trk_guitar": {"pan": {"position": -0.8}},
                                                    "trk_keyboard": {"pan": {"width": 1.8}}}},
                {"id": "v_gain", "track_overrides": {"trk_synth": {"gain_db": -6.0}}},
                {"id": "v_chain", "track_overrides": {"trk_synth": {"chain": [
                    {"id": "prc_s", "type": "gain", "params": {"gain_db": -6.0}}]}}},
                {"id": "v_unclean", "track_overrides": {"trk_drums": {"cleanup": {"applied": {"assets": {
                    "ast_drums": {"plan_hash": "f" * 16, "asset_sha256": "0" * 64}}}}}}}]
    mix = synth.stem_sum({r: st[r] for r in keep})
    synth.write_wav(root / "renders" / "v1" / "song__hires_native.wav",
                    synth.peak_limit(synth.normalize_peak(mix, 0.0) * 3.0, SR, -1.0), SR, subtype="PCM_24")
    (root / "project.json").write_text(json.dumps({"variants": variants, "tracks": tracks, "assets": assets,
                                                   "buses": buses, "mix": {"pan_law_center_db": -3.0},
                                                   "timebase": {"sample_rate": SR}}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def mat(tmp_path_factory):
    root = tmp_path_factory.mktemp("u2refs")
    d = synth.reference_master_set(sr=SR)
    synth.write_wav(root / "in" / "master.wav", d["master"], SR, subtype="PCM_24")
    for role, x in d["stems"].items():
        synth.write_wav(root / "in" / "stems" / f"{role}.wav", x, SR, subtype="PCM_24")
    kb = root / "kb"
    plain = R.study_command("material-a", master=root / "in/master.wav", stems=root / "in/stems", kb_root=kb,
                            created="2026-11-15")
    proj = _build_project(root / "proj")
    return {"root": root, "kb": kb, "master": root / "in/master.wav", "stems": root / "in/stems",
            "plain": plain, "proj": proj}


@pytest.fixture(scope="module")
def tkb(mat):
    """A second kb whose refstudy of the same material carries the transient section."""
    kb = mat["root"] / "kb_tr"
    before = _audio_files(mat["root"] / "in")
    res = R.study_command("material-a", master=mat["master"], stems=mat["stems"], kb_root=kb, created="2026-11-15",
                          add=["transient"])
    md = (kb / "references/works/material-a/refstudy.md").read_text(encoding="utf-8")
    return {"kb": kb, "res": res, "md": md, "in_before": before}


# ---------------------------------------------------------------------------
# 1. flagless outputs are byte-identical to the golden
# ---------------------------------------------------------------------------

def test_flagless_refstudy_and_refsheet_match_the_golden(mat, tmp_path):
    assert mat["plain"]["refstudy_sha256"] == GOLDEN["refstudy_material_a"]
    assert "add" not in mat["plain"] and "transient_signs" not in mat["plain"]
    st = R.build_study("master-only", master=mat["master"],
                       sections=[{"id": "a", "start_s": 0, "end_s": 4}, {"id": "b", "start_s": 4, "end_s": 8}])
    assert st["sha256"] == GOLDEN["refstudy_master_only_sections_ab"]
    assert "- 追加:" not in st["markdown"] and R.TRANSIENT_HEADING not in st["markdown"]
    for v in ("v1", "v_pan"):
        res = RSH.compare_command(mat["proj"], "material-a", tmp_path / f"{v}.md", variant=v, kb_root=mat["kb"])
        assert res["refsheet_sha256"] == GOLDEN[f"refsheet_material_a_{v}"], v
        assert "add" not in res


def test_empty_add_is_the_same_as_no_add(mat):
    a = R.build_study("master-only", master=mat["master"], add=[])
    b = R.build_study("master-only", master=mat["master"])
    assert a["markdown"] == b["markdown"]


def test_observe_without_view_is_unchanged():
    rng = np.random.default_rng(42)
    x = rng.standard_normal((SR * 3, 2)) * 0.1
    x[:, 1] = 0.6 * x[:, 1] + 0.4 * x[:, 0]
    got = [Q.observe(x, SR, s, gain_db=-1.5)["value"] for s in QUERY_SPECS]
    assert got == GOLDEN_QUERY
    assert [Q.observe(x, SR, {**s, "view": "stereo"}, gain_db=-1.5) for s in QUERY_SPECS] == \
        [Q.observe(x, SR, s, gain_db=-1.5) for s in QUERY_SPECS]


# ---------------------------------------------------------------------------
# 2. transient profile on synthetic signals
# ---------------------------------------------------------------------------

def _bursts(n: int, times, f: float, dec: float, amp: float) -> np.ndarray:
    y = np.zeros(n)
    for s in times:
        i = int(round(s * SR))
        m = min(n - i, int(0.3 * SR))
        tt = np.arange(m) / SR
        y[i:i + m] += amp * np.sin(2 * np.pi * f * tt) * np.exp(-tt / dec) * np.minimum(1.0, tt / 0.002)
    return y


def test_click_train_density_is_the_known_rate():
    T = 8.0
    n = int(T * SR)
    x = np.zeros(n)
    x[(np.arange(0.125, T, 0.25) * SR).astype(int)] = 0.8           # 4 clicks per second
    x = x + np.random.default_rng(1).standard_normal(n) * 0.001
    tr = R.transient_measure(np.stack([x, x], 1), SR, [])
    for g, _ in R.ATTACK_GROUPS:
        assert tr["rows"][0]["density"][g] == pytest.approx(4.0, rel=0.05), g


def _low_hits() -> np.ndarray:
    """§15.1 a: 60 Hz, decay 0.08 s, linear 2 ms attack, every 0.25 s, 48 kHz, 8 s."""
    n = int(8.0 * SR)
    return _bursts(n, np.arange(0.1, 8.0, 0.25), 60.0, 0.08, 0.5)


def _dens(y: np.ndarray) -> dict:
    return R.transient_measure(np.stack([y, y], 1), SR, [])["rows"][0]["density"]


def test_low_bursts_are_counted_in_the_low_group():
    """§15.1 a: hits placed in the low band only. The low group counts them at the known rate; the
    high group (-66 dB) is below the group floor and not counted; the mid group (-35 dB, the real click
    of the 2 ms attack) is counted (its value is not fixed)."""
    d = _dens(_low_hits())
    assert d["low"] == pytest.approx(4.0, rel=0.05)
    assert d["high"] is None
    assert d["mid"] is not None


def test_low_passed_hits_leave_only_the_low_group():
    """§15.1 b: the same hits low-passed (20-200 Hz): mid (-55.5 dB) and high are not counted. The low
    value is not fixed (the swell of the sustained low tone moves it away from 4)."""
    d = _dens(Q._bandpass(_low_hits(), SR, [20, 200]))
    assert d["mid"] is None and d["high"] is None
    assert d["low"] is not None


def test_group_floor_is_level_invariant():
    """§15.1 c: the floor is relative to the loudest group, so the level of the signal does not matter."""
    y = _low_hits()
    assert _dens(0.05 * y) == _dens(y)


def test_steady_noise_is_counted_in_the_groups_it_fills():
    """§15.1 d: steady noise is counted in the groups it fills (handled by the fixed note, not by the
    definition). The low group still counts the hits."""
    y = _low_hits()
    d = _dens(y + 0.02 * np.random.default_rng(7).standard_normal(y.size))
    assert d["low"] == pytest.approx(4.0, rel=0.05)
    assert d["mid"] is not None and d["high"] is not None


def test_silence_excludes_no_group():
    """§15.1: on silence max(p) = 0 and nothing is excluded (densities stay 0.00)."""
    d = _dens(np.zeros(int(2.0 * SR)))
    assert all(v == 0.0 for v in d.values())


def test_an_excluded_low_group_does_not_raise_the_low_signs():
    """§15.1 f: the low group not counted -> RS-TR-DENSITY is not raised and says so (not the tempo
    wording); RS-TR-SECTION has no density ratio and judges by the bass crest alone."""
    def row(i, crest):
        return {"id": i, "start_s": 0.0, "end_s": 4.0, "band_crest_db": {b: crest for b in R.BAND_IDS},
                "density": {"low": None, "mid": 3.0, "high": 2.0}}
    tr = {"rows": [row("whole", 10.0), row("a", 12.0), row("b", 8.0)], "bpm": 120.0, "bpm_confidence": 0.9,
          "low_per_beat": None}
    signs = {s["rule"]: s for s in R.transient_signs(tr, {"max": "a", "min": "b"})}
    den = signs["RS-TR-DENSITY"]
    assert not den["raised"] and "測定対象外" in den["finding"] and "BPM" not in den["finding"]
    assert den["finding"] == R.ATTACK_EXCLUDED_NOTE
    sec = signs["RS-TR-SECTION"]
    assert sec["raised"]                                             # bass crest 12 vs 8 dB
    assert dict(sec["evidence"])[f"low 群のアタック密度の比（≥ {R.TRANSIENT_RULE['density_ratio_min']:g}）"] is None
    tr["rows"][1]["band_crest_db"]["bass"] = 9.0                      # crest difference under 3 dB
    sec2 = next(s for s in R.transient_signs(tr, {"max": "a", "min": "b"}) if s["rule"] == "RS-TR-SECTION")
    assert not sec2["raised"]
    # the rendered section names the reason in place of the tempo wording
    md = "\n".join(R._render_transient({"transient": {**tr, "signs": list(signs.values())}}))
    assert f"{R.ATTACK_EXCLUDED_NOTE}のため出さない" in md


def test_density_note_and_dashes_in_the_documents(mat, tmp_path):
    """§15.1 g: the fixed note is in the refstudy §8.2 and in the refsheet's transient section; a group
    not counted is a dash in both tables, its value None, and kb lint passes the dashed table."""
    assert "目標" not in R.ATTACK_DENSITY_NOTE and "推奨" not in R.ATTACK_DENSITY_NOTE
    assert f"{R.ATTACK_GROUP_FLOOR_DB:g} dB" in R.ATTACK_DENSITY_NOTE
    y = _low_hits()
    synth.write_wav(tmp_path / "in" / "low.wav", np.stack([y, y], 1) * 0.9, SR, subtype="PCM_24")
    kb = tmp_path / "kb"
    R.study_command("low-only", master=tmp_path / "in" / "low.wav", kb_root=kb, created="2026-11-15",
                    add=["transient"])
    md = (kb / "references/works/low-only/refstudy.md").read_text(encoding="utf-8")
    sec82 = md[md.index("### 8.2"):md.index("### 8.3")]
    assert R.ATTACK_DENSITY_NOTE in sec82
    row = next(ln for ln in sec82.splitlines() if ln.startswith("| `whole`"))
    assert [c.strip() for c in row.split("|")[1:-1]][-1] == "—"      # high
    v = R.study_values(md)
    assert v["tr_density:whole:high"] is None and v["tr_density:whole:low"] == pytest.approx(4.0, rel=0.05)
    assert K.granularity_errors(md) == []
    K.write_index(kb)
    res = K.lint(kb, public=False)
    assert res["ok"], res["errors"]
    RSH.compare_command(mat["proj"], "low-only", tmp_path / "s.md", kb_root=kb, add=["transient"])
    part = _added_part((tmp_path / "s.md").read_text(encoding="utf-8"))
    assert part.count(R.ATTACK_DENSITY_NOTE) == 1
    _no_target_words(part)
    cells = [c.strip() for c in next(ln for ln in part.splitlines()
                                     if ln.startswith("| `tr_density:whole:high`")).split("|")[1:-1]]
    assert cells[1] == "—" and cells[3] == "—" and R.cell_num(cells[2]) is not None


def test_strong_limiting_lowers_the_band_crest_and_changes_the_band_sign():
    T = 8.0
    n = int(T * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    y = _bursts(n, np.arange(0.1, T, 0.25), 1200.0, 0.01, 0.6) + 0.3 * np.sin(2 * np.pi * 110 * t) \
        + 0.02 * rng.standard_normal(n)
    x = np.stack([y, y], 1)
    lim = np.clip(synth.normalize_peak(x, 0.0) * 8.0, -0.9, 0.9)
    a = R.transient_measure(x, SR, [])
    b = R.transient_measure(lim, SR, [])
    ca, cb = a["rows"][0]["band_crest_db"], b["rows"][0]["band_crest_db"]
    assert cb["lowmid"] < ca["lowmid"] - 6.0 and cb["mid"] < ca["mid"]
    sa, sb = R.transient_signs(a, {})[0], R.transient_signs(b, {})[0]
    assert sa["rule"] == sb["rule"] == "RS-TR-BAND"
    assert sa["finding"] != sb["finding"]
    assert "lowmid" in sb["finding"].split("ならされた帯域")[1] and "lowmid" in sa["finding"].split("ならされた帯域")[0]


def test_doubling_the_hit_density_in_a_section_raises_the_section_sign():
    T = 8.0
    n = int(T * SR)
    rng = np.random.default_rng(3)
    low = _bursts(n, list(np.arange(0.1, 4.0, 0.5)) + list(np.arange(4.1, T, 0.25)), 60.0, 0.08, 0.5)
    y = np.stack([low + 0.01 * rng.standard_normal(n)] * 2, 1)
    secs = [{"id": "a", "start_s": 0.0, "end_s": 4.0}, {"id": "b", "start_s": 4.0, "end_s": 8.0}]
    mm = R.master_measure(y, SR, secs)
    summ = R.section_summary(mm["sections"])
    tr = R.transient_measure(y, SR, secs, mm["vector"])
    dens = {r["id"]: r["density"]["low"] for r in tr["rows"]}
    assert dens["b"] == pytest.approx(4.0, rel=0.05) and dens["b"] / dens["a"] >= R.TRANSIENT_RULE["density_ratio_min"]
    sec = next(s for s in R.transient_signs(tr, summ) if s["rule"] == "RS-TR-SECTION")
    assert sec["raised"] and "`b`" in sec["finding"] and "`a`" in sec["finding"]
    # same material without the doubling: the density ratio stays under the threshold
    even = _bursts(n, np.arange(0.1, T, 0.5), 60.0, 0.08, 0.5)
    y2 = np.stack([even + 0.01 * rng.standard_normal(n)] * 2, 1)
    tr2 = R.transient_measure(y2, SR, secs, {})
    d2 = {r["id"]: r["density"]["low"] for r in tr2["rows"]}
    assert max(d2["a"], d2["b"]) / min(d2["a"], d2["b"]) < R.TRANSIENT_RULE["density_ratio_min"]


def test_density_sign_needs_a_confident_tempo():
    rows = [{"id": "whole", "start_s": 0.0, "end_s": 8.0, "band_crest_db": {b: 10.0 for b in R.BAND_IDS},
             "density": {"low": 4.0, "mid": 2.0, "high": 1.0}}]
    lo = R.transient_signs({"rows": rows, "bpm": 120.0, "bpm_confidence": 0.3, "low_per_beat": None}, {})[2]
    assert lo["rule"] == "RS-TR-DENSITY" and not lo["raised"] and lo["confidence"] is None
    hi = R.transient_signs({"rows": rows, "bpm": 120.0, "bpm_confidence": 0.8, "low_per_beat": 2.0}, {})[2]
    assert hi["raised"] and "1 拍あたり 2.00 個" in hi["finding"]


def test_transient_section_layout_and_parsing(mat, tkb):
    md = tkb["md"]
    assert "- 追加: transient" in md.split("## 1. 素材")[0]
    assert R.TRANSIENT_HEADING in md and R.TRANSIENT_NOTE in md
    assert md.index(R.TRANSIENT_HEADING) > md.index("## 7. 和とマスターの差分") and md.index(R.TRANSIENT_HEADING) < \
        md.index("## 付記")
    for rule in ("RS-TR-BAND", "RS-TR-SECTION", "RS-TR-DENSITY"):
        assert f"`{rule}`" in md
    assert tkb["res"]["add"] == ["transient"] and {s["rule"] for s in tkb["res"]["transient_signs"]} == \
        {"RS-TR-BAND", "RS-TR-SECTION", "RS-TR-DENSITY"}
    # the existing part of the document is unchanged apart from the header line and the new section
    plain = (mat["kb"] / "references/works/material-a/refstudy.md").read_text(encoding="utf-8")
    stripped = md.replace("- 追加: transient\n", "")
    a, b = stripped.index(R.TRANSIENT_HEADING), stripped.index("## 付記")
    assert stripped[:a] + stripped[b:] == plain
    v = R.study_values(md)
    assert v["transient"] and v["add"] == ["transient"]
    for b_ in R.BAND_IDS:   # whole-song band crest = the §3.2 band crest (same P-04 definition)
        assert v[f"tr_crest:whole:{b_}"] == pytest.approx(v[f"band_crest:{b_}"], abs=0.051)
    assert all(v.get(f"tr_density:{s}:{g}") is not None for s in ("whole", "loudest", "quietest")
               for g, _ in R.ATTACK_GROUPS)
    assert not R.study_values(plain)["transient"]
    # the work card of the plain study notices the different refstudy (not rewritten)
    assert K.granularity_errors(md) == []


def test_unknown_addition_is_an_input_error(mat):
    with pytest.raises(R.RefStudyError):
        R.build_study("x", master=mat["master"], add=["guide"])
    with pytest.raises(RSH.RefSheetError):
        RSH.check_add(["bogus"])


def test_stems_only_study_with_transient_says_master_only(mat):
    st = R.build_study("stems-only", stems=mat["stems"], add=["transient"])
    assert "マスターがないため空欄（輪郭はマスターだけを測る）" in st["markdown"]
    assert "transient" not in st


# ---------------------------------------------------------------------------
# 3. determinism
# ---------------------------------------------------------------------------

def test_flagged_outputs_are_deterministic(mat, tkb, tmp_path):
    again = R.build_study("material-a", master=mat["master"], stems=mat["stems"], add=["transient"])
    assert again["markdown"] == tkb["md"] and again["sha256"] == tkb["res"]["refstudy_sha256"]
    r1 = RSH.compare_command(mat["proj"], "material-a", tmp_path / "a.md", kb_root=tkb["kb"],
                             add=["guide", "transient"])
    r2 = RSH.compare_command(mat["proj"], "material-a", tmp_path / "b.md", kb_root=tkb["kb"],
                             add=["transient", "guide", "transient"])
    assert (tmp_path / "a.md").read_bytes() == (tmp_path / "b.md").read_bytes()
    assert r1["add"] == r2["add"] == ["transient", "guide"]


# ---------------------------------------------------------------------------
# 4. confidence caps
# ---------------------------------------------------------------------------

def test_lossy_caps_air_findings_and_separated_caps_everything():
    rows = [{"id": "whole", "start_s": 0.0, "end_s": 8.0,
             "band_crest_db": {"sub": 9.0, "bass": 6.0, "lowmid": 9.0, "mid": 10.0, "highmid": 11.0, "air": 18.0},
             "density": {"low": 4.0, "mid": 2.0, "high": 1.0}},
            {"id": "a", "start_s": 0.0, "end_s": 4.0, "band_crest_db": {b: 10.0 for b in R.BAND_IDS},
             "density": {"low": 2.0, "mid": 2.0, "high": 1.0}},
            {"id": "b", "start_s": 4.0, "end_s": 8.0, "band_crest_db": {b: 14.0 for b in R.BAND_IDS},
             "density": {"low": 4.0, "mid": 2.0, "high": 1.0}}]
    tr = {"rows": rows, "bpm": 120.0, "bpm_confidence": 0.9, "low_per_beat": 2.0}
    summ = {"max": "b", "min": "a"}
    lossy = R.apply_caps(R.transient_signs(tr, summ), lossy=True, separated=False)
    band = lossy[0]
    assert band["rule"] == "RS-TR-BAND" and band["raised"] and band["cap"] == "low" and band["confidence"] == "low"
    assert all(s["cap"] is None for s in lossy[1:])           # low-band findings are not HF
    sep = R.apply_caps(R.transient_signs(tr, summ), lossy=False, separated=True)
    assert all(s["cap"] == "medium" for s in sep)
    assert all(s["confidence"] in (None, "low", "medium") for s in sep)
    # without air in the finding the lossy cap does not apply
    rows2 = json.loads(json.dumps(rows))
    rows2[0]["band_crest_db"].update(air=10.5, bass=4.0)        # spread 7 dB, air neither kept, flat nor extreme
    s2 = R.apply_caps(R.transient_signs({**tr, "rows": rows2}, summ), lossy=True, separated=False)[0]
    assert s2["cap"] is None and s2["confidence"] == "high"


def test_separated_study_attaches_the_cap_to_the_transient_signs(mat):
    stems = synth.reference_master_set(sr=SR)["stems"]

    def fake_separator(x, sr):
        return {"vocals": stems["vocals"], "drums": stems["drums"], "bass": stems["bass"]}
    st = R.build_study("sep", master=mat["master"], separate=True, _separator=fake_separator, add=["transient"])
    assert all(s["cap"] == "medium" for s in st["transient"]["signs"])
    sec = st["markdown"].split(R.TRANSIENT_HEADING)[1]
    assert "medium（分離由来）" in sec


# ---------------------------------------------------------------------------
# 5. kb lint passes the largest shape (23 sections)
# ---------------------------------------------------------------------------

def test_kb_lint_passes_transient_refstudy_with_23_sections(tmp_path):
    T = 24.0
    n = int(T * SR)
    rng = np.random.default_rng(5)
    times = np.arange(0.1, T, 0.25)
    y = _bursts(n, times, 60.0, 0.08, 0.4) + _bursts(n, times + 0.125, 3000.0, 0.005, 0.2) \
        + 0.02 * rng.standard_normal(n)
    synth.write_wav(tmp_path / "in" / "long.wav", np.stack([y, 0.9 * y], 1), SR, subtype="PCM_24")
    secs = [{"id": f"s{i + 1:02d}", "start_s": float(i), "end_s": float(i + 1)} for i in range(R.MAX_SECTIONS)]
    kb = tmp_path / "kb"
    R.study_command("long", master=tmp_path / "in" / "long.wav", sections=secs, kb_root=kb, created="2026-11-15",
                    add=["transient"])
    md = (kb / "references/works/long/refstudy.md").read_text(encoding="utf-8")
    tables = R.parse_tables(md)
    assert len(tables["8.1"]) == len(tables["8.2"]) == R.MAX_SECTIONS + 1
    assert K.granularity_errors(md) == []
    K.write_index(kb)
    res = K.lint(kb, public=False)
    assert res["ok"], res["errors"]


# ---------------------------------------------------------------------------
# 6. refsheet additions: no target / recommendation, guide with and without a yardstick
# ---------------------------------------------------------------------------

def _added_part(md: str) -> str:
    a = md.index("## 6.")
    return md[a:md.index("## 付記")]


def _no_target_words(part: str) -> None:
    text = part.replace(RSH.GUIDE_NOTE, "")
    assert "目標" not in text and "推奨" not in text
    for ln in part.splitlines():
        if ln.startswith("| 量 "):
            assert ln == "| 量 | 参照 | こちら | 差 | 比較条件 |"


def test_refsheet_additions_without_a_yardstick(mat, tkb, tmp_path):
    before = _tree_hash(mat["proj"])
    res = RSH.compare_command(mat["proj"], "material-a", tmp_path / "s.md", kb_root=tkb["kb"],
                              add=["transient", "guide"])
    md = (tmp_path / "s.md").read_text(encoding="utf-8")
    assert _tree_hash(mat["proj"]) == before
    assert res["add"] == ["transient", "guide"] and "- 追加: transient, guide" in md
    assert "## 6. トランジェント輪郭の対照" in md and "## 7. 汎用ガイドからの形の偏差" in md
    part = _added_part(md)
    _no_target_words(part)
    assert RSH.GUIDE_NOTE in part and "p01_generic_prior" in part and "物差しは未登録" in part
    assert part.count(RSH.GUIDE_NOTE) == 1                          # §15.3: the excluded note, exactly once
    assert part.count(R.ATTACK_DENSITY_NOTE) == 1                   # §15.1: the density note in the transient part
    assert "参照側は未測定" not in part
    rows = {ln.split("|")[1].strip().split(" ")[0]: [c.strip() for c in ln.split("|")[1:-1]]
            for ln in part.splitlines() if ln.startswith("| `")}
    for b in R.BAND_IDS:
        assert R.cell_num(rows[f"`tr_crest:whole:{b}`"][1]) == R.study_values(tkb["md"])[f"tr_crest:whole:{b}"]
        assert R.cell_num(rows[f"`tr_crest:whole:{b}`"][2]) is not None
        assert R.cell_num(rows[f"`guide_dev:{b}`"][1]) is not None and R.cell_num(rows[f"`guide_dev:{b}`"][2]) is not None
    # shape only: the median of the three mid bands is zero on both sides (up to display rounding)
    for col in (1, 2):
        mids = sorted(R.cell_num(rows[f"`guide_dev:{b}`"][col]) for b in RSH.GUIDE_SHAPE_BANDS)
        assert abs(mids[1]) <= 0.051
    assert K.granularity_errors(md) == []
    # the part before the added sections is the flagless sheet (apart from the header line)
    plain = RSH.build_sheet(mat["proj"], "material-a", kb_root=tkb["kb"])["markdown"]
    head = md.replace("- 追加: transient, guide\n", "")
    assert head[:head.index("## 6.")] + head[head.index("## 付記"):] == plain


def test_refsheet_transient_when_the_reference_was_not_profiled(mat, tmp_path):
    RSH.compare_command(mat["proj"], "material-a", tmp_path / "t.md", kb_root=mat["kb"], add=["transient"])
    part = _added_part((tmp_path / "t.md").read_text(encoding="utf-8"))
    assert "参照側は未測定（`ref study --add transient`）" in part
    _no_target_words(part)
    row = next(ln for ln in part.splitlines() if ln.startswith("| `tr_crest:whole:mid`"))
    cells = [c.strip() for c in row.split("|")[1:-1]]
    assert cells[1] == "—" and R.cell_num(cells[2]) is not None


def test_refsheet_guide_with_a_registered_yardstick(mat, tkb, tmp_path):
    from mankomix.core.reference import measure_reference
    proj = tmp_path / "proj"
    shutil.copytree(mat["proj"], proj)
    # register one yardstick reference the way `reference add` stores it (vector file + project entry);
    # the minimal fixture project is not schema-complete, so Project.save is not used here
    y = synth.pink_noise(sr=SR, seconds=6.0, channels=2, seed=9) * 0.2
    vec = measure_reference(y, SR)
    vec.update({"id": "yard00000000", "label": "yard", "source": {"file_name": "yard.wav", "sha256": "1" * 64}})
    (proj / "analysis").mkdir(exist_ok=True)
    (proj / "analysis" / "ref_yard00000000.json").write_text(json.dumps(vec), encoding="utf-8")
    data = json.loads((proj / "project.json").read_text(encoding="utf-8"))
    data["references"] = [{"id": "yard00000000", "label": "yard", "vector": "analysis/ref_yard00000000.json",
                           "sha256": "1" * 64}]
    (proj / "project.json").write_text(json.dumps(data), encoding="utf-8")
    before = _tree_hash(proj)
    RSH.compare_command(proj, "material-a", tmp_path / "g.md", kb_root=tkb["kb"], add=["guide"])
    assert _tree_hash(proj) == before
    md = (tmp_path / "g.md").read_text(encoding="utf-8")
    part = _added_part(md)
    assert "## 6. 汎用ガイドからの形の偏差" in md and "物差しは未登録" not in part
    assert part.count(RSH.GUIDE_NOTE) == 1
    _no_target_words(part)
    ys = [[c.strip() for c in ln.split("|")[1:-1]] for ln in part.splitlines() if ln.startswith("| `yardstick_dev:")]
    assert len(ys) == len(R.BAND_IDS)
    assert all(r[1] == "—" and r[3] == "—" and R.cell_num(r[2]) is not None for r in ys)
    assert "n = 1" in part


def test_guide_band_means_follow_the_generic_prior():
    g = RSH.guide_band_means(SR)
    assert all(g[b] is not None for b in R.BAND_IDS)
    assert RSH.guide_band_means(SR) == g                                  # deterministic
    assert all(abs(v) < 1e-9 for v in RSH.shape_deviation(g, g).values())  # the guide itself has no deviation
    shifted = {b: v + 5.0 for b, v in g.items()}                         # level offsets vanish (shape only)
    assert all(abs(v) < 1e-9 for v in RSH.shape_deviation(shifted, g).values())


# ---------------------------------------------------------------------------
# 7. observation views (validate side deferred)
# ---------------------------------------------------------------------------

def _tone(f: float, seconds: float = 3.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def test_view_mono_equals_stereo_for_identical_channels():
    rng = np.random.default_rng(7)
    m = rng.standard_normal(SR * 3) * 0.1
    x = np.stack([m, m], 1)
    for spec in ({"primitive": "loudness"}, {"primitive": "crest"}, {"primitive": "band_energy", "band_hz": [200, 800]}):
        assert Q.observe(x, SR, {**spec, "view": "mono"}) == Q.observe(x, SR, spec)


def test_view_mono_drops_with_out_of_phase_content():
    rng = np.random.default_rng(8)
    m = rng.standard_normal(SR * 3) * 0.1
    s = rng.standard_normal(SR * 3) * 0.1
    x = np.stack([m + s, m - s], 1)
    st = Q.observe(x, SR, {"primitive": "loudness"})["value"]
    mo = Q.observe(x, SR, {"primitive": "loudness", "view": "mono"})["value"]
    assert mo < st - 2.0
    anti = np.stack([s, -s], 1) + 1e-6 * np.stack([m, m], 1)
    assert Q.observe(anti, SR, {"primitive": "loudness", "view": "mono"})["value"] < \
        Q.observe(anti, SR, {"primitive": "loudness"})["value"] - 40.0


def test_view_mono_band_drops_out_of_band_tones():
    for f in (50.0, 12000.0):
        x = np.stack([_tone(f)] * 2, 1)
        st = Q.observe(x, SR, {"primitive": "loudness"})["value"]
        mb = Q.observe(x, SR, {"primitive": "loudness", "view": "mono_band"})["value"]
        assert mb < st - 15.0, f
    x = np.stack([_tone(1000.0)] * 2, 1)
    st = Q.observe(x, SR, {"primitive": "loudness"})["value"]
    mb = Q.observe(x, SR, {"primitive": "loudness", "view": "mono_band"})["value"]
    assert abs(mb - st) < 0.5
    # view_band_hz narrows the band
    x = np.stack([_tone(250.0)] * 2, 1)
    wide = Q.observe(x, SR, {"primitive": "loudness", "view": "mono_band"})["value"]
    narrow = Q.observe(x, SR, {"primitive": "loudness", "view": "mono_band", "view_band_hz": [400, 6000]})["value"]
    assert narrow < wide - 3.0


BAD_VIEW_SPECS = [
    {"primitive": "side_ratio", "view": "mono"},
    {"primitive": "correlation", "view": "mono"},
    {"primitive": "side_ratio", "view": "mono_band"},
    {"primitive": "correlation", "view": "mono_band", "band_hz": [100, 1000]},
    {"primitive": "loudness", "view": "headphones"},
    {"primitive": "loudness", "view": 1},
    {"primitive": "loudness", "view": "mono", "view_band_hz": [150, 6000]},
    {"primitive": "loudness", "view_band_hz": [150, 6000]},
    {"primitive": "loudness", "view": "mono_band", "view_band_hz": [50, 6000]},
    {"primitive": "loudness", "view": "mono_band", "view_band_hz": [150, 12000]},
    {"primitive": "loudness", "view": "mono_band", "view_band_hz": [150]},
    {"primitive": "loudness", "view": "mono_band", "view_band_hz": ["150", 6000]},
]


@pytest.mark.parametrize("spec", BAD_VIEW_SPECS)
def test_bad_views_are_refused_by_observe(spec):
    x = np.stack([_tone(440.0)] * 2, 1)
    with pytest.raises(Q.QueryError, match="bad_value"):
        Q.observe(x, SR, spec)


def test_view_band_range_edges_are_accepted():
    x = np.stack([_tone(1000.0)] * 2, 1)
    for vb in ([80, 3000], [400, 10000]):
        assert Q.observe(x, SR, {"primitive": "crest", "view": "mono_band", "view_band_hz": vb})["status"] == "ok"


# ---------------------------------------------------------------------------
# 7 (validate side, W-4b). validate applies the same view rule as observe; check measures views
# ---------------------------------------------------------------------------

def _view_doc(tmp_path: Path, extra: list[dict], tag: str = "v") -> dict:
    import tests.test_direction_update as T
    b = T._block()
    b["observations"] = b["observations"] + extra
    return D.parse_document(T._write_doc(tmp_path / tag, b))


@pytest.mark.parametrize("i", range(len(BAD_VIEW_SPECS)))
def test_validate_refuses_bad_views(tmp_path, i):
    spec = BAD_VIEW_SPECS[i]
    res = D.validate(_view_doc(tmp_path, [{"id": "ov", "target": "master", **spec}]))
    assert not res["ok"]
    errs = [e for e in res["errors"] if e["where"].startswith("observations.ov")]
    assert len(errs) == 1 and errs[0]["code"] == "bad_value", res["errors"]
    assert errs[0]["where"].rsplit(".", 1)[1] in ("view", "view_band_hz")
    with pytest.raises(Q.QueryError, match="bad_value") as ei:   # the same rule and message as observe's refusal
        Q.view_spec(spec)
    assert str(ei.value) == "bad_value: " + errs[0]["message"]


def test_validate_accepts_views_without_new_messages(tmp_path):
    import tests.test_direction_update as T
    proj = T._project(tmp_path / "p", low_amp=0.2)
    good = [{"id": "v1", "primitive": "loudness", "target": "master", "view": "mono"},
            {"id": "v2", "primitive": "crest", "target": "master", "view": "mono_band"},
            {"id": "v3", "primitive": "band_energy", "target": "master", "band_hz": [150, 400],
             "view": "mono_band", "view_band_hz": [80, 10000]},
            {"id": "v4", "primitive": "side_ratio", "target": "master", "view": "stereo"},
            {"id": "v5", "primitive": "correlation", "target": "master", "view": None}]
    base = D.validate(_view_doc(tmp_path, [], "base"), proj)
    for o in good:
        res = D.validate(_view_doc(tmp_path, [o], o["id"]), proj)
        assert res["ok"], res["errors"]
        assert res["errors"] == base["errors"] and res["warnings"] == base["warnings"], o["id"]
        assert res["notes"] == base["notes"] and res["tiers"] == base["tiers"], o["id"]
    # view: stereo is the same as no view
    stereo = {"id": "s1", "primitive": "side_ratio", "target": "master"}
    a = D.validate(_view_doc(tmp_path, [stereo], "s_plain"), proj)
    b = D.validate(_view_doc(tmp_path, [{**stereo, "view": "stereo"}], "s_view"), proj)
    a.pop("id"), b.pop("id")
    assert a == b


def test_check_measures_view_observations_through_observe(tmp_path):
    """direction check passes a view observation to query.observe unchanged (result level-matched)."""
    import tests.test_direction_update as T
    views = [{"id": "vm", "primitive": "loudness", "target": "master", "view": "mono"},
             {"id": "vb", "primitive": "crest", "target": "master", "view": "mono_band", "view_band_hz": [400, 6000]},
             {"id": "ve", "primitive": "band_energy", "target": "master", "band_hz": [40, 150], "view": "mono_band",
              "level_match": False},
             {"id": "vs", "primitive": "loudness", "target": "master", "view": "stereo"},
             {"id": "vn", "primitive": "loudness", "target": "master"}]
    b = T._block()
    b["observations"] = b["observations"] + views
    out, _ = T._check_out(tmp_path, b, "views")
    res, floor = tmp_path / "res_views", tmp_path / "floor_views"
    x, sr = audio_io.read(D._render_file(res, "var_x"))
    y, _ = audio_io.read(D._render_file(floor, "var_x"))
    match = Q.integrated_lufs(y, sr) - Q.integrated_lufs(x, sr)
    secs = D._Project(res).sections()
    for o in views:
        g = match if o.get("level_match", True) else 0.0
        got = out["observations"][o["id"]]
        assert got["result"] == Q.observe(x, sr, o, sections=secs, gain_db=g), o["id"]
        assert got["floor"] == Q.observe(y, sr, o, sections=secs, gain_db=0.0), o["id"]
        assert got["result"]["status"] == "ok"
    obs = out["observations"]
    assert obs["vs"] == obs["vn"]                                      # stereo == no view
    # the floor has L = R: mono is the stereo value; the result's 1 kHz is narrower (width 0.7), mono is lower
    assert obs["vm"]["floor"]["value"] == pytest.approx(obs["vn"]["floor"]["value"], abs=1e-3)
    assert obs["vm"]["result"]["value"] < obs["vn"]["result"]["value"]
    no_view = {k: v for k, v in views[2].items() if k != "view"}       # 50 Hz is outside the 150-6000 Hz view
    assert obs["ve"]["floor"]["value"] < Q.observe(y, sr, no_view, sections=secs)["value"] - 15.0
    plain = T._block()
    out0, _ = T._check_out(tmp_path, plain, "noviews")
    for k in ("o1", "o2", "o3"):                                       # the other observations are unchanged
        assert out0["observations"][k] == obs[k]


def test_check_reports_a_bad_view_as_an_observation_error(tmp_path):
    """A view that slipped past validate (check does not validate) is an error entry, not a crash."""
    import tests.test_direction_update as T
    b = T._block()
    b["observations"] = b["observations"] + [{"id": "bad", "primitive": "side_ratio", "target": "master",
                                              "view": "mono"}]
    out, _ = T._check_out(tmp_path, b, "badview")
    assert out["observations"]["bad"]["result"]["status"] == "error"
    assert "bad_value" in out["observations"]["bad"]["result"]["reason"]


# ---------------------------------------------------------------------------
# 9 (dynamic part, W-4b). the --calibrate selection does not change with the additions
# ---------------------------------------------------------------------------

def _cal_block(extra_obs: list[dict]) -> dict:
    import tests.test_upgrade2_duck as TD
    m = {"id": "m01", "aim": "a1", "stage": "mix", "target": "trk_drums", "op": "chain_add", "processor": "eq",
         "params": {"shape": "low_shelf", "freq_hz": 90, "gain_db": [0.5, 3.0], "bw_oct": 1.0},
         "select": {"gain_db": "min"}, "basis": "x", "origin": "new",
         "expect": [{"quantity": "obs:o1", "direction": "up", "min_delta": 1.5}]}
    obs = [{"id": "o1", "primitive": "band_energy", "target": "master", "band_hz": [40, 90]}] + extra_obs
    return TD._block([m], observations=obs, claims=[
        {"id": "c1", "quantity": "obs:o1", "vs": "floor", "direction": "up", "min_delta": 1.5, "primary": True}])


def _canon(cal: dict, drop: set = frozenset()) -> str:
    c = json.loads(json.dumps(cal))
    for e in c["evaluations"]:
        for k in drop:
            e["deltas"].pop(k, None)
    return json.dumps(c, ensure_ascii=False, sort_keys=True)


def test_calibration_selection_ignores_views_translation_and_additions(mat, tkb, tmp_path, monkeypatch):
    """§3.7-9: the selection (real prediction renders) is the same with or without observations that
    carry a view, and is not changed by a translation outcome or flagged refstudy / refsheet existing."""
    import tests.test_upgrade2_duck as TD
    from mankomix.director import calibrate as C
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    song = TD._make(tmp_path / "song")
    plain_path = TD._doc(tmp_path / "d0", _cal_block([]))
    plain_doc = D.parse_document(plain_path)
    a = C.calibrate(song, plain_doc, progress=lambda s: None)
    assert a["renders"] > 1 and len(a["evaluations"]) > 1            # the selection is actually explored
    views = [{"id": "vm", "primitive": "loudness", "target": "master", "view": "mono"},
             {"id": "vb", "primitive": "crest", "target": "master", "view": "mono_band", "view_band_hz": [100, 5000]}]
    view_doc = D.parse_document(TD._doc(tmp_path / "d1", _cal_block(views)))
    assert D.validate(view_doc, song)["ok"]
    b = C.calibrate(song, view_doc, progress=lambda s: None)
    assert all(isinstance(e["deltas"]["vm"], float) and isinstance(e["deltas"]["vb"], float)
               for e in b["evaluations"])                            # the views are measured by the predictor
    assert b["selection"] == a["selection"] and b["chosen"] == a["chosen"] and b["items"] == a["items"]
    assert _canon(b, {"vm", "vb"}) == _canon(a)
    # a translation outcome and flagged reference documents inside the project change nothing
    x, sr, _ = TD.mr.render_mix(TD.Project.open(song), variant_id="var_x", measure=False)
    audio_io.write(song / "renders" / "var_x" / "song__hires_native.wav", x, sr)
    floor = tmp_path / "floor"
    shutil.copytree(song, floor)
    out = D.check(song, floor, plain_path, translation=True)
    assert "translation" in out and (song / "directions" / f"{plain_doc['id']}.outcome.json").is_file()
    RSH.compare_command(mat["proj"], "material-a", song / "directions" / "refsheet.md", kb_root=tkb["kb"],
                        add=["transient", "guide"])
    shutil.copy(tkb["kb"] / "references/works/material-a/refstudy.md", song / "directions" / "refstudy.md")
    again = C.calibrate(song, plain_doc, progress=lambda s: None)
    assert _canon(again) == _canon(a)


# ---------------------------------------------------------------------------
# 8 (unit part). the translation block
# ---------------------------------------------------------------------------

def test_translation_block_shape_and_changes():
    rng = np.random.default_rng(11)
    t = np.arange(SR * 4) / SR
    floor = np.stack([0.2 * np.sin(2 * np.pi * 60 * t) + 0.05 * rng.standard_normal(t.size)] * 2, 1)
    side = 0.05 * rng.standard_normal(t.size)
    result = floor + np.stack([side, -side], 1)                      # wider: loses level in mono
    b = TR.block(result, floor, SR, 0.0)
    assert b["note"] == TR.NOTE and b["view"] == {"mono_band_hz": [150.0, 6000.0]}
    assert set(b) == {"note", "view", *TR.KEYS}
    for k in TR.KEYS:
        assert set(b[k]) == {"floor", "result", "change"}
        assert b[k]["change"] == pytest.approx(b[k]["result"] - b[k]["floor"], abs=2e-4)
    assert b["mono_fold_lu"]["change"] < -0.1
    assert b["low_harmonic_db"]["floor"] < -20.0                     # a 60 Hz tone: little left above 150 Hz
    same = TR.block(floor, floor, SR, 0.0)
    assert all(same[k]["change"] == 0.0 for k in TR.KEYS)
    assert json.dumps(b, sort_keys=True) == json.dumps(TR.block(result, floor, SR, 0.0), sort_keys=True)


def test_translation_block_applies_the_match_gain_to_the_result_only():
    rng = np.random.default_rng(12)
    x = np.stack([rng.standard_normal(SR * 3) * 0.1] * 2, 1)
    b = TR.block(x * 0.5, x, SR, 20.0 * np.log10(2.0))
    for k in TR.KEYS:
        assert b[k]["change"] == pytest.approx(0.0, abs=2e-3), k


# ---------------------------------------------------------------------------
# 9 (structural part). calibration never reads the additions
# ---------------------------------------------------------------------------

def test_calibration_does_not_read_the_additions():
    text = (REPO / "director" / "calibrate.py").read_text(encoding="utf-8")
    for name in ("translation", "refsheet", "refstudy", "guide_dev", "tr_crest", "tr_density"):
        assert name not in text, name


def test_core_does_not_import_the_new_module():
    for p in (REPO / "core").rglob("*.py"):
        assert "director" not in re.findall(r"^\s*(?:from|import)\s+\S*director", p.read_text(encoding="utf-8"),
                                            re.MULTILINE), p


# ---------------------------------------------------------------------------
# 10. no audio in the kb; CLI flags
# ---------------------------------------------------------------------------

def test_ref_study_add_transient_writes_no_audio(tkb):
    assert _audio_files(tkb["kb"]) == set()
    assert sorted(p.name for p in (tkb["kb"] / "references/works/material-a").iterdir()) == ["refstudy.md", "work.md"]


def test_cli_add_flags(mat, tkb, tmp_path, capsys):
    from mankomix.cli.main import main
    kb = tmp_path / "kb"
    code = main(["direction", "ref", "study", "--work", "cli-t", "--master", str(mat["master"]), "--kb", str(kb),
                 "--add", "transient"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["add"] == ["transient"] and len(out["transient_signs"]) == 3
    assert _audio_files(kb) == set()
    code = main(["--project", str(mat["proj"]), "direction", "ref", "compare", "--work", "material-a",
                 "--out", str(tmp_path / "c.md"), "--kb", str(tkb["kb"]), "--add", "guide", "--add", "transient"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["add"] == ["transient", "guide"]
    code = main(["--project", str(mat["proj"]), "direction", "ref", "compare", "--work", "material-a",
                 "--out", str(tmp_path / "p.md"), "--kb", str(mat["kb"])])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and "add" not in out and out["refsheet_sha256"] == GOLDEN["refsheet_material_a_v1"]
    code = main(["direction", "ref", "study", "--work", "cli-t", "--master", str(mat["master"]), "--kb", str(kb),
                 "--add", "guide"])
    out = json.loads(capsys.readouterr().out)
    assert code != 0 and out["error"] == "input_error"
