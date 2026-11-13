"""Cleanup stage integrated into projects (core/cleanstage.py; SPEC 6.4, 6.6.1, 6.7, 9.1; S-07, S-08).

A synthetic stem project with injected AI-audio defects (shimmer + HF ceiling
on one stem, a head click on another, one clean stem) is planned, applied,
rendered and verified.
"""

from __future__ import annotations

import copy
import json
import re
import types

import numpy as np
import pytest

from mankomix.core import cleanstage as cs
from mankomix.core import journal, mastering, mixrender, render, verify
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from tests.fixtures import synth
from tests.test_cleanup_policy import SR, music

SECONDS = 4.0


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("MANKOMIX_HOME", str(tmp_path_factory.mktemp("home")))
    yield
    mp.undo()


def _stems() -> dict[str, np.ndarray]:
    synth_stem = synth.add_hf_ceiling(
        synth.add_shimmer(music(SECONDS, seed=1), SR, depth_db=-22.0, seed=3), SR, 16000.0)
    return {
        "synth.wav": 0.5 * synth_stem,
        "drums.wav": 0.5 * synth.add_head_click(music(SECONDS, seed=2), SR, dbfs=-3.0),
        "vocals.wav": 0.5 * music(SECONDS, seed=4),  # clean: nothing detected
    }


@pytest.fixture(scope="module")
def stems():
    return _stems()


@pytest.fixture(scope="module")
def cleaned(tmp_path_factory, home, stems):
    base = tmp_path_factory.mktemp("clean")
    src = base / "src"
    for name, x in stems.items():
        synth.write_wav(src / name, x, SR)
    proj = Project.create(base / "song.mmx", title="cleanup test")
    FileAdapter().fetch(src, proj, actor="human")
    prop = cs.plan_clean(proj)
    files_after_plan = sorted(p.name for p in (proj.root / "cache").rglob("*") if p.is_file())
    res = cs.apply_clean(proj, prop, actor="human")
    return {"project": proj, "root": proj.root, "proposal": prop, "result": res,
            "files_after_plan": files_after_plan}


def _aid(proj, role):
    return next(a["id"] for a in proj.data["assets"] if a["role"] == role)


def _tid(proj, role):
    return next(t["id"] for t in proj.data["tracks"] if t["role"] == role)


def _band_energy(x, lo, hi):
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    sel = (f >= lo) & (f < hi)
    return float(np.sum(np.abs(spec[sel]) ** 2))


# --------------------------------------------------------------------------
# plan (R-31)


def test_plan_is_a_proposal_per_stem(cleaned):
    prop, proj = cleaned["proposal"], cleaned["project"]
    assert prop["stage"] == "clean" and prop["operations"] == ["approve", "reject"]
    assert prop["proposal_id"].startswith("cln_")
    assert prop["route"]["route"] == "stem_sum"  # stems only -> stem-wise cleanup, no 2mix
    items = {i["asset"]: i for i in prop["items"]}
    syn, drm, voc = _aid(proj, "synth"), _aid(proj, "drums"), _aid(proj, "vocals")
    assert set(items) == {syn, drm}
    assert items[syn]["steps"]["spectral_reduction"] == "run"
    assert items[syn]["diagnosis"]["hf_ceiling_hz"] is not None
    assert items[drm]["steps"]["click_repair"] == "run"
    for it in items.values():
        assert it["kind"] == "stem" and it["track"] and it["mode"] == "auto"
        assert it["reasons"] and it["alternatives"] and len(it["plan_hash"]) == 64
        assert "policy" not in it["plan"] and it["plan"]["policy_hash"]
    sk = {s["asset"]: s for s in prop["skipped"]}
    assert sk[voc]["code"] == "nothing_detected" and "nothing detected" in sk[voc]["reason"]
    assert prop["neural_completion"]["used"] is False  # D-041
    # planning writes nothing
    assert cleaned["files_after_plan"] == []


def test_overrides_and_disabled_tracks(cleaned):
    proj = cleaned["project"]
    syn, tid = _aid(proj, "synth"), _tid(proj, "synth")
    p = cs.plan_clean(proj, targets=[tid], overrides={"spectral_reduction": "light"})
    assert [i["asset"] for i in p["items"]] == [syn]
    assert p["items"][0]["steps"]["spectral_reduction"] == "light" and p["items"][0]["mode"] == "custom"
    p2 = cs.plan_clean(proj, targets=[syn], overrides={tid: {"spectral_reduction": "skip"}})
    assert p2["items"][0]["steps"]["spectral_reduction"] == "skip"
    data = copy.deepcopy(proj.data)
    i = next(k for k, t in enumerate(data["tracks"]) if t["id"] == tid)
    data["tracks"][i]["cleanup"]["enabled"] = False

    # read-only view of the project with the track's cleanup disabled
    view = types.SimpleNamespace(root=proj.root, data=data, asset=proj.asset, asset_path=proj.asset_path,
                                 content_hash=proj.content_hash)
    p3 = cs.plan_clean(view, targets=[tid])
    assert p3["items"] == [] and p3["skipped"][0]["code"] == "disabled"
    with pytest.raises(InputError):
        cs.plan_clean(proj, targets=["trk_nope"])


# --------------------------------------------------------------------------
# apply: project, files, journal


def test_apply_stores_plan_and_files(cleaned):
    proj, root, res = cleaned["project"], cleaned["root"], cleaned["result"]
    syn, drm, voc = _aid(proj, "synth"), _aid(proj, "drums"), _aid(proj, "vocals")
    assert res["applied"] is True and res["s07_pass"] is True
    by = {a["asset"]: a for a in res["assets"]}
    assert by[voc]["skipped"] is True and not by[syn]["skipped"]
    fresh = Project.open(root)
    t = next(t for t in fresh.data["tracks"] if t["id"] == _tid(proj, "synth"))
    c = t["cleanup"]
    assert c["enabled"] is True and c["plan"] == "auto" and c["overrides"] == {}
    e = c["applied"]["assets"][syn]
    assert e["plan_hash"] == by[syn]["plan_hash"] and e["asset_sha256"] == proj.asset(syn)["sha256"]
    assert e["skipped"] is False and e["s07_pass"] is True and e["record_path"] == f"analysis/cleanup_{syn}.json"
    tv = next(t for t in fresh.data["tracks"] if t["id"] == _tid(proj, "vocals"))
    assert tv["cleanup"]["applied"]["assets"][voc]["skipped"] is True
    assert fresh.validate() == [] or all(i["level"] != "error" for i in fresh.validate())
    assert journal.list_entries(root, limit=1)[-1]["op"] == "clean_apply"
    # files: cache (32-bit float + sidecar), delta, record, baselines - all project-relative
    for aid in (syn, drm):
        f = by[aid]["files"]
        assert re.fullmatch(r"cache/clean/[0-9a-f]{16}_[0-9a-f]{16}\.wav", f["cache"])
        assert f["delta"] == f"renders/delta/{aid}.wav" and f["record"] == f"analysis/cleanup_{aid}.json"
        for rel in f.values():
            assert (root / rel).is_file()
        assert synth.read_wav(root / f["cache"])[0].dtype == np.float64
        import soundfile as sf
        assert sf.info(str(root / f["cache"])).subtype == "FLOAT"
    assert not (root / "renders" / "delta" / f"{voc}.wav").exists()
    base = json.loads((root / cs.BASELINE_FILE).read_text(encoding="utf-8"))
    assert set(base["assets"]) == {syn, drm, voc}
    assert base["assets"][syn]["cleaned"] is True and base["assets"][voc]["cleaned"] is False
    assert base["routes"]["stem_sum"]["baseline"]["kind"] == "cleanup_noise_baseline"
    assert {a["asset"] for a in base["routes"]["stem_sum"]["cleaned_assets"]} == {syn, drm}
    # nothing absolute anywhere
    text = json.dumps(res) + "".join(p.read_text(encoding="utf-8") for p in
                                     list((root / "analysis").glob("*.json")) + [root / "project.json"])
    assert str(root) not in text and root.as_posix() not in text
    assert not re.search(r"[A-Za-z]:[\\/]|/Users/|/home/", text)


def test_records_s07_pass_and_cleanup_details(cleaned):
    proj = cleaned["project"]
    syn, drm, voc = _aid(proj, "synth"), _aid(proj, "drums"), _aid(proj, "vocals")
    rs = cs.cleanup_record(proj, syn)
    assert rs["s07"]["pass"] is True and rs["s07"]["residual_stored_dbfs"] <= rs["s07"]["limit_dbfs"]
    assert rs["steps"]["spectral_reduction"]["action"] == "run"
    rep = rs["report"]
    assert rep["removed_energy"]["shimmer"]["removed_rel_db"] is not None
    assert rep["p21"]["check"] == "P-21" and "oversuppression" in rep and "rerun" in rep["oversuppression"]
    assert rep["neural_completion_used"] is False
    rd = cs.cleanup_record(proj, drm)
    assert rd["report"]["steps"]["click_repair"]["count"] >= 1 and rd["s07"]["pass"] is True
    rv = cs.cleanup_record(proj, voc)
    assert rv["skipped"] is True and rv["reasons"]
    s07 = cs.s07_check(proj, "stem_sum")
    assert s07["status"] == "pass" and set(s07["assets"]) == {syn, drm}
    assert cs.s07_check(proj, "full_mix")["status"] == "not_applicable"


def test_delta_is_input_minus_cleaned(cleaned, stems):
    proj, root = cleaned["project"], cleaned["root"]
    syn = _aid(proj, "synth")
    rel = cs.delta(proj, syn)
    assert rel == f"renders/delta/{syn}.wav"
    d, _ = synth.read_wav(root / rel)
    raw, _ = synth.read_wav(proj.asset_path(syn))
    cl, _ = synth.read_wav(cs.cleaned_asset_path(proj, syn))
    assert np.allclose(d, raw - cl, atol=1e-6)
    assert _band_energy(d, 10000.0, 14000.0) > 10.0 * _band_energy(d, 0.0, 1000.0)
    with pytest.raises(InputError):
        cs.delta(proj, _aid(proj, "vocals"))  # skipped: nothing removed


# --------------------------------------------------------------------------
# rendering uses the cleaned audio


def test_mixrender_uses_cleaned_audio(cleaned):
    proj = cleaned["project"]
    syn, tid = _aid(proj, "synth"), _tid(proj, "synth")
    y, _, rec = mixrender.render_track(proj, tid)
    raw, _, rec_raw = mixrender.render_track(proj, tid, overrides={tid: {"cleanup": {"enabled": False}}})
    assert rec["cleanup"]["applied"] is True
    assert rec["cleanup"]["assets"] == [{"asset": syn, "sha256": proj.asset(syn)["sha256"],
                                         "plan_hash": cs.applied_entry(proj.data, syn)["plan_hash"]}]
    assert rec_raw["cleanup"]["applied"] is False
    e_cl, e_raw = _band_energy(y, 10000.0, 14000.0), _band_energy(raw, 10000.0, 14000.0)
    assert e_cl < 0.95 * e_raw  # tonal partials in the band are protected; the shimmer goes
    # the low band is untouched (S-07 seen through the renderer)
    lo = np.fft.irfft(np.where(np.fft.rfftfreq(y.shape[0], 1 / SR)[:, None] < 900.0,
                               np.fft.rfft(y - raw, axis=0), 0.0), y.shape[0], axis=0)
    assert np.max(np.abs(lo)) < 1e-4
    m, _, mrec = mixrender.render_mix(proj)
    assert {a["asset"] for a in mrec["cleanup"]["assets"]} == {syn, _aid(proj, "drums")}
    before, _, srec = mixrender.static_sum(proj)
    assert srec["cleanup"]["applied"] is False  # D-036 "Before" stays raw
    after, _, crec = mixrender.static_sum(proj, cleaned=True)
    assert crec["cleanup"]["applied"] is True
    assert _band_energy(after, 10000.0, 14000.0) < _band_energy(before, 10000.0, 14000.0)


def test_cache_regeneration_is_deterministic(cleaned):
    proj, root = cleaned["project"], cleaned["root"]
    syn = _aid(proj, "synth")
    p = cs.cleaned_asset_path(proj, syn)
    rec_path = root / cs.record_rel(syn)
    first, delta_first = p.read_bytes(), (root / cs.delta_rel(syn)).read_bytes()
    rec_first = json.loads(rec_path.read_text(encoding="utf-8"))
    p.unlink()
    (root / cs.delta_rel(syn)).unlink()
    rec_path.unlink()
    again = cs.cleaned_asset_path(proj, syn)
    assert again == p and again.read_bytes() == first
    assert (root / cs.delta_rel(syn)).read_bytes() == delta_first
    rec2 = json.loads(rec_path.read_text(encoding="utf-8"))
    assert rec2["plan_hash"] == rec_first["plan_hash"] and rec2["s07"] == rec_first["s07"]
    # a corrupted cache is detected (sidecar file hash) and regenerated
    p.write_bytes(first[:-8] + b"\0" * 8)
    assert cs.cleaned_asset_path(proj, syn).read_bytes() == first
    # renders through a missing cache are identical
    y1, _, _ = mixrender.render_mix(proj)
    p.unlink()
    y2, _, _ = mixrender.render_mix(proj)
    assert np.array_equal(y1, y2)


# --------------------------------------------------------------------------
# mastering: S-07 / S-08 in verify, manifests


def _hf_shelf_chain(chain, gain_db):
    out = copy.deepcopy(chain)
    shelf = mastering.eq_proc("mst_hf_test", "high_shelf", 9000.0, gain_db, 1.0, "test: strong HF boost")
    idx = max(i for i, p in enumerate(out) if p["type"] == "eq") + 1 if any(p["type"] == "eq" for p in out) else 0
    out.insert(idx, shelf)
    return out


def _gentle(chain, less_db=6.0):
    """The planned chain with ``less_db`` less drive into the limiter (a clean, modest master)."""
    out = copy.deepcopy(chain)
    for p in out:
        if p["type"] == "loudness_gain":
            p["params"]["gain_db"] = round(p["params"]["gain_db"] - less_db, 3)
    return out


@pytest.fixture(scope="module")
def mastered(cleaned):
    proj = cleaned["project"]
    plan = mastering.plan_master(proj, profile_id="streaming_universal", delivery_id="hires_native")
    mastering.apply_master_plan(proj, plan, actor="planner")
    v = mastering.find_variant(proj.data, "var_streaming_universal")
    gentle = copy.deepcopy(v)
    gentle["id"] = "var_gentle"
    gentle["master"]["chain"] = _gentle(v["master"]["chain"])
    bad = copy.deepcopy(gentle)
    bad["id"] = "var_hfboost"
    bad["master"]["chain"] = _hf_shelf_chain(gentle["master"]["chain"], 9.0)
    proj.data["variants"] += [gentle, bad]
    proj.save(actor="human", op="edit", reason="test: modest master and the same with a strong HF shelf")
    out = {}
    for var in ("var_gentle", "var_hfboost"):
        out[var] = {"render": render.render_variant(proj, var), "verify": verify.verify_variant(proj, var)}
    return {"clean": out["var_gentle"], "bad": out["var_hfboost"], "project": proj}


def test_s08_clean_master_passes_hf_boost_fails(mastered):
    good = mastered["clean"]["verify"]["outputs"][0]["checks"]
    assert good["S-07"]["status"] == "pass"
    s08 = good["S-08"]
    assert s08["status"] == "pass", s08
    assert s08["baseline"]["cleaned"] is True and s08["baseline"]["cleaned_assets"]
    assert s08["gain_source"].startswith("output integrated loudness")
    bad = mastered["bad"]["verify"]["outputs"][0]
    b08 = bad["checks"]["S-08"]
    assert b08["status"] == "fail"
    assert b08["deltas"]["shimmer_index_db"]["pass"] is False
    assert "reduce_hf_boost" in {s["action"] for s in b08["suggestions"]}
    assert bad["overall"] == "fail"  # S-08 is a hard check
    for c in ("S-07", "S-08"):
        assert good[c]["status"] != "not_evaluated"


def test_manifest_records_cleanup_plan_hashes(mastered):
    proj = mastered["project"]
    out = mastered["clean"]["render"]["outputs"][0]
    man = json.loads((proj.root / out["manifest"]).read_text(encoding="utf-8"))
    cl = man["cleanup"]
    assert cl["applied"] is True and cl["neural_completion_used"] is False
    hashes = {a["asset"]: a["plan_hash"] for a in cl["assets"]}
    assert hashes == {aid: e["plan_hash"] for aid, e in cs.cleaned_assets(proj.data, "stem_sum").items()}


def test_fullmix_route_uses_cleaned_fullmix(tmp_path, home):
    """2mix only: the full mix is cleaned; the full-mix route input is the cleaned 2mix and the
    stored baseline of the cleaned full mix is the S-08 reference."""
    x = 0.5 * synth.add_head_click(synth.add_shimmer(music(SECONDS, seed=7), SR, depth_db=-22.0, seed=5), SR)
    src = tmp_path / "src"
    synth.write_wav(src / "fullmix.wav", x, SR)
    proj = Project.create(tmp_path / "fm.mmx", title="fullmix cleanup")
    FileAdapter().fetch(src / "fullmix.wav", proj, actor="human")
    fid = proj.data["fullmix_asset"]
    assert fid
    prop = cs.plan_clean(proj)
    assert [i["asset"] for i in prop["items"]] == [fid] and prop["items"][0]["kind"] == "fullmix"
    cs.apply_clean(proj, prop, actor="agent")
    fresh = Project.open(proj.root)
    assert fresh.data["fullmix_cleanup"]["applied"]["assets"][fid]["s07_pass"] is True
    from mankomix.core.routes import load_master_input
    xin, _ = load_master_input(fresh, "full_mix")
    cl, _ = synth.read_wav(cs.cleaned_asset_path(fresh, fid))
    assert np.array_equal(xin, cl)
    b = cs.route_baseline(fresh, "full_mix")
    assert b["cleaned"] is True and b["source"].startswith("stored: cleaned full mix")
    assert cs.s07_check(fresh, "full_mix")["status"] == "pass"
