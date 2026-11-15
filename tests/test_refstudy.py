"""Raw-reference path (原液): refstudy, refsheet, engineer aggregate, `direction ref` CLI.

Every signal is synthetic (tests/fixtures/synth.py); audio files exist only under tmp_path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from mankomix.core import audio_io
from mankomix.director import kb as K
from mankomix.director import refsheet as RSH
from mankomix.director import refstudy as R

from .fixtures import synth

SR = 48000
REPO = Path(__file__).resolve().parents[1]


def _audio_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and audio_io.is_audio_file(p)}


def _tree_hash(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _noise(seconds: float, seed: int, channels: int = 2) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((int(seconds * SR), channels)) * 0.1


def _brick(x: np.ndarray, lo: float | None, hi: float | None) -> np.ndarray:
    """Brick-wall band (FFT) of a (frames, channels) signal."""
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    m = np.ones_like(f)
    if lo is not None:
        m[f < lo] = 0.0
    if hi is not None:
        m[f >= hi] = 0.0
    return np.fft.irfft(np.fft.rfft(x, axis=0) * m[:, None], n=x.shape[0], axis=0)


# ---------------------------------------------------------------------------
# material A (route 2): a master with known processing and its stems
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def material(tmp_path_factory):
    root = tmp_path_factory.mktemp("refA")
    d = synth.reference_master_set(sr=SR)
    synth.write_wav(root / "in" / "master.wav", d["master"], SR, subtype="PCM_24")
    for role, x in d["stems"].items():
        synth.write_wav(root / "in" / "stems" / f"{role}.wav", x, SR)
    return {"root": root, "set": d, "master": root / "in" / "master.wav", "stems": root / "in" / "stems"}


@pytest.fixture(scope="module")
def studied(material):
    """One ref study of material A into a tmp kb (audio before/after recorded)."""
    kb = material["root"] / "kb"
    kb.mkdir()
    before_kb = _audio_files(kb)
    know_before = _tree_hash(REPO / "knowledge")
    res = R.study_command("material-a", master=material["master"], stems=material["stems"], kb_root=kb,
                          created="2026-11-15")
    return {"kb": kb, "res": res, "before_kb": before_kb, "know_before": know_before,
            "md": (kb / "references" / "works" / "material-a" / "refstudy.md").read_text(encoding="utf-8")}


def test_material_a_difference_recovers_the_known_tilt(material, studied):
    """Acceptance (design 4.1 route 2, material A): the sum/master difference recovers the tilt."""
    known = material["set"]["tilt_db_per_oct"]
    v = R.study_values(studied["md"])
    assert v["ltas_diff_slope_db_per_oct"] == pytest.approx(known, abs=0.4)
    assert v["lag_ms"] == 0.0
    assert "判定: 信頼できる" in studied["md"]
    assert studied["res"]["difference_reliable"] is True


def test_material_a_raises_the_limiting_sign(studied):
    sign = next(s for s in studied["res"]["signs"] if s["rule"] == "RS-LIMIT")
    assert sign["raised"] and sign["confidence"] == "medium"
    assert "抑え込みの兆候: 強い" in studied["md"]


def test_unprocessed_sum_does_not_raise_the_limiting_sign(material):
    x = synth.stem_sum(material["set"]["stems"])
    mm = R.master_measure(x, SR, R.auto_sections(x, SR))
    sign = next(s for s in R.signs(mm, R.section_summary(mm["sections"])) if s["rule"] == "RS-LIMIT")
    assert not sign["raised"]


def test_refstudy_layout_and_no_file_names(material, studied):
    md = studied["md"]
    assert not md.startswith("---")                       # no front matter (machine-generated)
    for h in ("## 1. 素材", "## 2. 確度の上限", "### 3.1", "### 3.2", "### 3.3", "### 3.4", "## 4. 区間",
              "## 5. 兆候", "## 6. ステム", "### 6.4", "## 7. 和とマスターの差分"):
        assert h in md, h
    assert R.STEM_NOTE in md
    assert ".wav" not in md and "master.wav" not in md and str(material["root"]) not in md
    sha = hashlib.sha256(material["master"].read_bytes()).hexdigest()
    assert sha in md and "48k/24" in md
    for rule in ("RS-LIMIT", "RS-MONO-LOW", "RS-HF", "RS-CONTRAST", "RS-DELIVERY"):
        assert f"`{rule}`" in md


def test_work_card_template_is_private_third_party_draft(studied):
    card = studied["kb"] / "references" / "works" / "material-a" / "work.md"
    meta, body = K.parse_front_matter(card.read_text(encoding="utf-8"))
    assert meta["id"] == "work_material-a" and meta["kind"] == "work"
    assert meta["rights"] == "third_party" and meta["visibility"] == "private" and meta["status"] == "draft"
    assert meta["credits"] == [] and meta["artist"] == ""
    assert meta["study"]["sha256"] == studied["res"]["refstudy_sha256"]
    assert {m["type"] for m in meta["materials"]} == {"master", "stems"}
    assert "## 何の作品か" in body and "## 読み" in body


def test_study_leaves_no_audio_and_does_not_touch_knowledge(studied):
    assert _audio_files(studied["kb"]) == studied["before_kb"] == set()
    assert _tree_hash(REPO / "knowledge") == studied["know_before"]


def test_refstudy_passes_kb_lint(studied):
    """The refstudy granularity passes W1's lint (private root: third-party works allowed)."""
    if not hasattr(K, "granularity_errors"):
        pytest.skip("kb lint granularity rules not present")
    kb = studied["kb"]
    assert K.granularity_errors(studied["md"]) == []
    K.write_index(kb)
    res = K.lint(kb, public=False)
    assert res["ok"], res["errors"]


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def test_refstudy_is_byte_identical_across_runs(material, studied, tmp_path):
    kb2 = tmp_path / "kb2"
    R.study_command("material-a", master=material["master"], stems=material["stems"], kb_root=kb2,
                    created="2026-11-15")
    a = (studied["kb"] / "references/works/material-a/refstudy.md").read_bytes()
    b = (kb2 / "references/works/material-a/refstudy.md").read_bytes()
    assert a == b
    again = R.study_command("material-a", master=material["master"], stems=material["stems"], kb_root=kb2)
    assert again["changed"] is False and "work_card_stale" not in again


# ---------------------------------------------------------------------------
# refsheet (T-7)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A minimal rendered project core can mix: six stems with faders, one off-center pan, one send to an
    fx bus, and a master render of the first variant. Other variants change one thing each."""
    root = tmp_path_factory.mktemp("proj")
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


def test_refsheet_columns_roles_and_read_only(project, studied, tmp_path):
    before = _tree_hash(project)
    out1, out2 = tmp_path / "a" / "refsheet.md", tmp_path / "b" / "refsheet.md"
    r1 = RSH.compare_command(project, "material-a", out1, kb_root=studied["kb"])
    r2 = RSH.compare_command(project, "material-a", out2, kb_root=studied["kb"])
    assert out1.read_bytes() == out2.read_bytes()                  # deterministic
    assert _tree_hash(project) == before                            # the project is not written
    assert r1["master_compared"] and r1 == {**r2}
    md = out1.read_text(encoding="utf-8")
    assert "目標" not in md.split("## 1.")[1].split("\n")[2] and "推奨" not in md.replace("推奨の列は作らない", "")
    head = "| 量 | 参照 | こちら | 差 | 比較条件 |"
    assert md.count(head) >= 3
    assert set(r1["roles_both"]) == {"vocals", "drums", "bass", "synth", "keyboard", "guitar"}
    assert set(r1["roles_ref_only"]) == {"backing_vocals", "brass", "fx", "percussion", "strings", "woodwinds"}
    assert "## 4. 移せない特徴" in md and "`brass` | あり | なし" in md
    assert "## 5. 高域の雑音性" in md and "`flatness`" in md and "cleanup_override" in md
    assert ".wav" not in md
    if hasattr(K, "granularity_errors"):
        assert K.granularity_errors(md) == []


def test_refsheet_refuses_an_output_inside_the_project(project, studied):
    with pytest.raises(RSH.RefSheetError):
        RSH.compare_command(project, "material-a", project / "refsheet.md", kb_root=studied["kb"])
    assert not (project / "refsheet.md").exists()


def test_refsheet_needs_a_refstudy(project, tmp_path):
    with pytest.raises(RSH.RefSheetError):
        RSH.compare_command(project, "missing", tmp_path / "x.md", kb_root=tmp_path / "kb")


def _our_stems(project, variant):
    side = RSH.project_side(project, variant)
    return side["values"]["stems"], side["info"]


def test_refsheet_stems_are_the_tracks_as_they_enter_the_bus(project):
    """This side's stems follow the pan / width, the fader and the track chain (core's render_mix)."""
    before = _tree_hash(project)
    base, info = _our_stems(project, "v1")
    assert set(base) == {"vocals", "drums", "bass", "synth", "keyboard", "guitar"}
    assert info["stems"]["send_buses"] == ["bus_fx"] and info["stems"]["panned"] == 1
    from mankomix.core import mixrender
    g = synth.song_stems(sr=SR, seconds=8.0, seed=1)["guitar"]
    raw_lr = 10.0 * np.log10(np.sum(g[:, 0] ** 2) / np.sum(g[:, 1] ** 2))
    co = mixrender.pan_coefficients(0.35, 1.0, -3.0)                  # position +0.35: the left side is lowered
    want = raw_lr + 20.0 * np.log10(co["gain_l"] / co["gain_r"])
    assert abs(base["guitar"]["lr_diff_db"] - want) < 0.15 and want < raw_lr - 3.0
    pan, _ = _our_stems(project, "v_pan")
    assert pan["guitar"]["lr_diff_db"] > base["guitar"]["lr_diff_db"] + 6.0   # moved to the left
    assert pan["keyboard"]["side_ratio_db"] > base["keyboard"]["side_ratio_db"] + 3.0   # wider
    assert pan["bass"] == base["bass"]                               # untouched tracks are unchanged
    gain, _ = _our_stems(project, "v_gain")
    chain, _ = _our_stems(project, "v_chain")
    assert gain["synth"]["rel_lu"] < base["synth"]["rel_lu"] - 4.0   # fader -6 dB
    assert chain["synth"]["rel_lu"] == gain["synth"]["rel_lu"]       # a -6 dB gain step in the chain: same
    assert gain["synth"]["side_ratio_db"] == base["synth"]["side_ratio_db"]
    assert _tree_hash(project) == before                              # read-only


def test_refsheet_stem_rows_change_with_the_variant(project, studied, tmp_path):
    before = _tree_hash(project)
    a = RSH.compare_command(project, "material-a", tmp_path / "v1.md", kb_root=studied["kb"])
    b = RSH.compare_command(project, "material-a", tmp_path / "pan.md", variant="v_pan", kb_root=studied["kb"])
    b2 = RSH.compare_command(project, "material-a", tmp_path / "pan2.md", variant="v_pan", kb_root=studied["kb"])
    assert (tmp_path / "pan.md").read_bytes() == (tmp_path / "pan2.md").read_bytes() and b == b2
    assert _tree_hash(project) == before
    assert a["master_compared"] and not b["master_compared"]          # v_pan has no render
    m1, m2 = (tmp_path / "v1.md").read_text(encoding="utf-8"), (tmp_path / "pan.md").read_text(encoding="utf-8")

    def stem_rows(md, role):
        part = md.split(f"`{role}`\n", 1)[1].split("\n### ", 1)[0]
        return [ln for ln in part.splitlines() if ln.startswith("| `lr_diff_db`") or ln.startswith("| `side_ratio_db`")]

    assert stem_rows(m1, "guitar") != stem_rows(m2, "guitar")
    assert stem_rows(m1, "keyboard") != stem_rows(m2, "keyboard")
    assert stem_rows(m1, "bass") == stem_rows(m2, "bass")
    assert "パン・幅の後" in m1 and "パン前" not in m1 and "`bus_fx`" in m1 and "mixrender.render_mix" in m1


def test_refsheet_does_not_regenerate_a_missing_cleanup_cache(project, studied, tmp_path):
    """Core would rebuild a missing cleaned cache inside the project; the sheet refuses instead."""
    before = _tree_hash(project)
    RSH.compare_command(project, "material-a", tmp_path / "u.md", variant="v_unclean", kb_root=studied["kb"])
    md = (tmp_path / "u.md").read_text(encoding="utf-8")
    assert "整音の cache が無いか古い" in md and "両方にある役割がない" in md
    assert _tree_hash(project) == before


def test_refsheet_contrast_is_the_refstudy_sign_value(project, studied, tmp_path):
    """No double rounding: the reference contrast is the RS-CONTRAST evidence of the refstudy."""
    ev = next(r for r in R.parse_tables(studied["md"])["5"] if r["規則"] == "`RS-CONTRAST`")["根拠の測定値"]
    want = ev.split("ラウドネス差 LU = ")[1].split(";")[0].strip()
    assert RSH._sign_contrast(studied["md"]) == float(want)
    RSH.compare_command(project, "material-a", tmp_path / "c.md", kb_root=studied["kb"])
    row = next(ln for ln in (tmp_path / "c.md").read_text(encoding="utf-8").splitlines() if ln.startswith("| `contrast_lu`"))
    cells = [c.strip() for c in row.split("|")[1:-1]]
    assert R.cell_num(cells[1]) == float(want) and "RS-CONTRAST" in cells[4]
    lra = next(ln for ln in (tmp_path / "c.md").read_text(encoding="utf-8").splitlines() if ln.startswith("| `lra_lu`"))
    rng = next(ln for ln in (tmp_path / "c.md").read_text(encoding="utf-8").splitlines() if ln.startswith("| `short_range_lu`"))
    assert "相対ゲート −20 LU" in lra and "相対ゲートなし" in rng


# ---------------------------------------------------------------------------
# sign rules on synthetic signals
# ---------------------------------------------------------------------------

def test_known_mono_boundary():
    """Side removed below 140 Hz (brick wall): the 100-120 Hz band is mono, 120-160 Hz is not."""
    x = _noise(6.0, 3)
    mid = x.mean(axis=1, keepdims=True)
    side = (x[:, :1] - x[:, 1:]) / 2.0
    side = _brick(side, 140.0, None)
    y = np.concatenate([mid + side, mid - side], axis=1)
    sp = R.spatial_measure(y, SR)
    assert R.mono_boundary_hz(sp["low_side"]) == 120.0
    x2 = _noise(6.0, 4)                                      # independent L/R: no mono band
    assert R.mono_boundary_hz(R.spatial_measure(x2, SR)["low_side"]) is None


def test_known_rolloff():
    y = synth.pink_noise(sr=SR, seconds=6.0, channels=2, seed=5)
    cut = _brick(y, None, 12000.0)
    m = R.hf_metrics(cut, SR)
    assert m["rolloff_hz"] == pytest.approx(12000.0, abs=600.0)
    assert R.hf_metrics(y, SR)["rolloff_hz"] is None


def test_sign_confidence_caps():
    def sg():
        return [R._sign("A", "a", True, "", [], "high", "all"), R._sign("B", "b", True, "", [], "high", "hf")]
    lossy = R.apply_caps(sg(), lossy=True, separated=False)
    assert [s["confidence"] for s in lossy] == ["high", "low"]
    sep = R.apply_caps(sg(), lossy=False, separated=True)
    assert [s["confidence"] for s in sep] == ["medium", "medium"]
    both = R.apply_caps(sg(), lossy=True, separated=True)
    assert [s["confidence"] for s in both] == ["medium", "low"]


def test_lossy_input_caps_the_hf_sign(tmp_path):
    y = _brick(synth.pink_noise(sr=SR, seconds=5.0, channels=2, seed=6), None, 12000.0) * 0.5
    p = tmp_path / "ref.ogg"
    import soundfile as sf
    try:
        sf.write(str(p), y, SR, format="OGG", subtype="VORBIS")
    except Exception as e:  # pragma: no cover - libsndfile without Vorbis
        pytest.skip(f"cannot write OGG here: {e}")
    st = R.build_study("lossy", master=p)
    assert st["lossy"] is True
    hf = next(s for s in st["signs"] if s["rule"] == "RS-HF")
    assert hf["cap"] == "low"
    assert hf["confidence"] in (None, "low")
    assert "非可逆音源: 高域" in st["markdown"]


def test_separated_origin_caps_everything_at_medium(material):
    stems = material["set"]["stems"]

    def fake_separator(x, sr):
        return {"vocals": stems["vocals"], "drums": stems["drums"], "bass": stems["bass"],
                "other": synth.stem_sum({k: v for k, v in stems.items() if k not in ("vocals", "drums", "bass")})}
    st = R.build_study("sep", master=material["master"], separate=True, _separator=fake_separator)
    assert st["origin"] == "separated"
    assert "- origin: `separated`" in st["markdown"]
    assert all(s["confidence"] in (None, "low", "medium") for s in st["signs"])
    assert any(s["cap"] == "medium" for s in st["signs"])
    assert "difference" not in st                      # pseudo stems are not compared with their own source


def test_separate_without_a_model_is_a_clear_error(material, monkeypatch, tmp_path, capsys):
    from mankomix.cli.main import main
    from mankomix.core import registry
    monkeypatch.setattr(registry, "default_model", lambda mode: None)
    with pytest.raises(R.SeparationUnavailable):
        R.separate_in_memory(np.zeros((SR, 2)), SR)
    code = main(["direction", "ref", "study", "--work", "sep", "--master", str(material["master"]), "--separate",
                 "--kb", str(tmp_path / "kb")])
    out = json.loads(capsys.readouterr().out)
    assert code != 0 and out["error"] == "environment_error" and "--separate" in out["message"]
    assert not (tmp_path / "kb").exists()


# ---------------------------------------------------------------------------
# roles, alignment, sections
# ---------------------------------------------------------------------------

def test_role_assignment_and_overrides():
    names = ["01 Lead Vocal.wav", "Kick.wav", "bass_DI.wav", "weird.wav", "no_vocals.wav", "Full Mix.wav"]
    got = {a["name"]: (a["role"], a["excluded"]) for a in R.assign_roles(names)}
    assert got["01 Lead Vocal.wav"] == ("vocals", None)
    assert got["Kick.wav"] == ("drums", None)
    assert got["bass_DI.wav"] == ("bass", None)
    assert got["weird.wav"] == ("other", None)
    assert got["no_vocals.wav"][1] == "derived_sum"
    assert got["Full Mix.wav"][1] == "fullmix"
    over = {a["name"]: (a["role"], a["role_source"]) for a in R.assign_roles(names, {"weird": "synth"})}
    assert over["weird.wav"] == ("synth", "user")
    with pytest.raises(R.RefStudyError):
        R.assign_roles(names, {"weird.wav": "kazoo"})
    with pytest.raises(R.RefStudyError):
        R.assign_roles(names, {"nothere.wav": "synth"})
    assert R.assign_roles(["mystery.wav"])[0]["role"] == "other"     # a lone file is a stem, not a full mix


def test_alignment_gain_and_residual():
    st = synth.song_stems(sr=SR, seconds=6.0, seed=2)
    total = synth.stem_sum(st)
    lag = 480
    master = np.concatenate([np.zeros((lag, 2)), total[:-lag]]) * synth.db_to_amp(4.0)   # master is late
    assert R.align_lag(master, total, SR) == -lag
    df = R.sum_master_difference(master, total, SR)
    assert df["lag_samples"] == -lag
    assert df["gain_db"] == pytest.approx(4.0, abs=0.05)
    assert df["residual"]["total_db"] < -40.0 and df["reliable"] is True
    assert df["ltas_diff_slope_db_per_oct"] == pytest.approx(0.0, abs=0.05)
    other = _noise(6.0, 9)                                         # stems that do not make this master
    bad = R.sum_master_difference(other, total, SR)
    assert bad["reliable"] is False


def test_sections_user_and_auto(material):
    x, sr = R.read_audio(material["master"])
    auto = R.auto_sections(x, sr)
    assert [s["id"] for s in auto] == ["loudest", "quietest"]
    user = R.load_sections([{"id": "a", "start_s": 0, "end_s": 4}, {"id": "b", "start_s": 4, "end_s": 8}], 8.0)
    assert [s["id"] for s in user] == ["a", "b"]
    for bad in ([], [{"id": "a", "start_s": 0, "end_s": 0.5}], [{"id": "a", "start_s": 0, "end_s": 2}] * 2,
                [{"id": f"s{i}", "start_s": i, "end_s": i + 1.5} for i in range(R.MAX_SECTIONS + 1)]):
        with pytest.raises(R.RefStudyError):
            R.load_sections(bad, 60.0)


def test_slug_and_input_checks(tmp_path):
    for bad in ("Bad Slug", "../x", "", "a" * 65):
        with pytest.raises(R.RefStudyError):
            R.check_slug(bad)
    with pytest.raises(R.RefStudyError):
        R.build_study("x")
    with pytest.raises(R.RefStudyError):
        R.build_study("x", master=tmp_path / "none.wav")


# ---------------------------------------------------------------------------
# engineer aggregate (T-8) and list
# ---------------------------------------------------------------------------

def _work(kb: Path, slug: str, person: str, lufs: float):
    d = kb / "references" / "works" / slug
    d.mkdir(parents=True)
    (d / "work.md").write_text("\n".join([
        "---", f"id: work_{slug}", "kind: work", f'title: "{slug}"', "created: 2026-11-15", "status: draft",
        "visibility: private", "rights: third_party", 'credits_source: "利用者提供"',
        f'credits: [{{ role: master, person: eng_{person}, name: "x" }}]', "materials: []", "---", "", "# w", ""]),
        encoding="utf-8")
    (d / "refstudy.md").write_text("\n".join([
        "# 測定資料（refstudy）: x", "", f"- 版: refstudy {R.REFSTUDY_VERSION} / engine x", "- origin: `measured`", "",
        "### 3.1 ラウドネスと動き", "", "| 量 | 値 |", "|---|---|", f"| `lufs_i` 積分ラウドネス | {lufs:.2f} |",
        "| `plr_db` PLR dB | 8.00 |", ""]), encoding="utf-8")


def test_credit_aggregate_and_case_rule(tmp_path):
    kb = tmp_path / "kb"
    _work(kb, "w1", "alice", -9.0)
    _work(kb, "w2", "alice", -8.0)
    _work(kb, "w3", "bob", -12.0)
    r = R.credit_command("alice", kb_root=kb, created="2026-11-15")
    assert r["works"] == ["work_w1", "work_w2"] and r["card_created"]
    assert r["stats"]["lufs_i"] == {"n": 2, "median": -8.5, "iqr": 0.5, "trend": False}
    card = (kb / "references/engineers/alice.md").read_text(encoding="utf-8")
    assert "傾向とは言えない（事例）" in card and card.count(R.CREDIT_BEGIN) == 1
    first = card
    again = R.credit_command("alice", kb_root=kb)                      # regenerated in place, byte identical
    assert again["changed"] is False
    assert (kb / "references/engineers/alice.md").read_text(encoding="utf-8") == first
    _work(kb, "w4", "alice", -7.0)
    r3 = R.credit_command("alice", kb_root=kb)
    assert r3["stats"]["lufs_i"]["n"] == 3 and r3["stats"]["lufs_i"]["trend"] is True
    card = (kb / "references/engineers/alice.md").read_text(encoding="utf-8")
    assert card.count(R.CREDIT_BEGIN) == 1 and "| 3 | -8.00 |" in card


def test_ref_list_freshness(studied, tmp_path):
    res = R.list_command(studied["kb"])
    w = next(x for x in res["works"] if x["work"] == "work_material-a")
    assert w["freshness"] == "fresh" and w["origin"] == "measured"
    kb = tmp_path / "kb"
    _work(kb, "w9", "carol", -9.0)
    w9 = R.list_command(kb)["works"][0]
    assert w9["freshness"] == "no_card_hash"
    assert R.list_command(tmp_path / "empty") == {"kind": "ref_list", "works": [], "engineers": [],
                                                  "count": {"works": 0, "engineers": 0}}


# ---------------------------------------------------------------------------
# CLI and boundaries
# ---------------------------------------------------------------------------

def test_cli_ref_study_list_and_errors(material, tmp_path, capsys):
    from mankomix.cli.main import main
    kb = tmp_path / "kb"
    code = main(["direction", "ref", "study", "--work", "cli-a", "--master", str(material["master"]), "--kb", str(kb),
                 "--sections", json.dumps([{"id": "a", "start_s": 0, "end_s": 4}, {"id": "b", "start_s": 4, "end_s": 8}])])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["kind"] == "refstudy" and out["sections"] == ["a", "b"]
    assert out["sections_source"] == "user" and out["work_card_created"] is True
    assert (kb / "references/works/cli-a/refstudy.md").is_file()
    assert _audio_files(kb) == set()
    code = main(["direction", "ref", "list", "--kb", str(kb)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["works"][0]["work"] == "work_cli-a"
    code = main(["direction", "ref", "study", "--work", "Bad Slug", "--master", str(material["master"]),
                 "--kb", str(kb)])
    out = json.loads(capsys.readouterr().out)
    assert code != 0 and out["error"] == "input_error"


def test_ref_path_never_writes_project_references(project, studied, tmp_path):
    """U-1: the raw-reference path does not register a core yardstick reference."""
    data = json.loads((project / "project.json").read_text(encoding="utf-8"))
    RSH.compare_command(project, "material-a", tmp_path / "s.md", kb_root=studied["kb"])
    after = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert after == data and "references" not in after
    assert not list((project).rglob("ref_*.json"))


def test_core_does_not_import_the_raw_reference_modules():
    for p in (REPO / "core").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "refstudy" not in text and "refsheet" not in text, p
