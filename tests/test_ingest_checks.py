"""Import checks and conform policy (SPEC 6.1.4, 6.1.5; D-054)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import soundfile as sf

from mankomix.core.adapters import FileAdapter
from mankomix.core.ingest import conform_policy, project_sample_rate, resolve_timebase, run_checks
from mankomix.core.project import Project
from tests.fixtures.folders import make_mismatched_folder, make_suno_export, stem_signal


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snapshot(folder: Path) -> dict[str, tuple[str, int]]:
    return {p.name: (_sha(p), p.stat().st_mtime_ns) for p in sorted(folder.iterdir()) if p.is_file()}


def _find(checks, check, asset=None, level=None):
    return [c for c in checks if c["check"] == check and (asset is None or c["asset"] == asset)
            and (level is None or c["level"] == level)]


@pytest.fixture(scope="module")
def mismatched(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mm")
    src = make_mismatched_folder(tmp / "in")
    before = _snapshot(src)
    proj = Project.create(tmp / "song.mmx", title="mismatch")
    rec = FileAdapter().fetch(src, proj)
    return SimpleNamespace(src=src, before=before, proj=Project.open(proj.root), rec=rec)


def test_no_conversion_happens(mismatched):
    m = mismatched
    assert _snapshot(m.src) == m.before
    assets = {a["original_name"]: a for a in m.proj.data["assets"]}
    for name, (sha, _) in m.before.items():
        a = assets[name]
        assert a["sha256"] == sha
        assert _sha(m.proj.root / a["path"]) == sha  # copy is byte-identical
        info = sf.info(str(m.proj.root / a["path"]))
        assert info.samplerate == a["sample_rate"]
    assert assets["Bass.wav"]["sample_rate"] == 44100   # kept, not resampled
    assert assets["Keys.wav"]["subtype"] == "PCM_24"     # kept, not converted
    assert assets["Synth.wav"]["length_samples"] == 2 * 48000  # kept, not padded


def test_rate_mismatch_reported_and_policy_recorded(mismatched):
    data = mismatched.proj.data
    assert data["timebase"]["sample_rate"] == 48000  # 7 of 8 files are 48 kHz
    assert data["timebase"]["length_samples"] == 3 * 48000
    pol = data["timebase"]["conform_policy"]
    assert pol["sample_rate"] == "majority" and pol["alignment"] == "head"
    assert {"asset": "ast_bass", "from_rate": 44100, "to_rate": 48000,
            "action": "resample_at_render"} in pol["applied"]
    padded = {e["asset"] for e in pol["applied"] if e["action"] == "pad_silence_at_render"}
    assert padded == {"ast_guitar", "ast_synth"}
    checks = data["ingest"]["checks"]
    w = _find(checks, "format_sample_rate", "ast_bass", "warning")
    assert w and w[0]["values"]["project_sample_rate"] == 48000
    assert data["ingest"]["conform"]["rates"] == {"48000": 7, "44100": 1}
    assert _find(checks, "format_bit_depth", "ast_keyboard", "warning")


def test_length_reject_vs_warning(mismatched):
    checks = mismatched.proj.data["ingest"]["checks"]
    g = _find(checks, "length_mismatch", "ast_guitar")
    s = _find(checks, "length_mismatch", "ast_synth")
    assert len(g) == 1 and g[0]["level"] == "warning"
    assert len(s) == 1 and s[0]["level"] == "reject"
    assert g[0]["values"]["boundary_s"] == 0.5
    # the 44.1 kHz stem has the same duration: no length finding
    assert not _find(checks, "length_mismatch", "ast_bass")


def test_silence_reject_and_health_warnings(mismatched):
    checks = mismatched.proj.data["ingest"]["checks"]
    assert _find(checks, "silence", "ast_fx", "reject")
    assert any(a["id"] == "ast_fx" for a in mismatched.proj.data["assets"])  # import still records it
    assert not _find(checks, "silence", "ast_vocals")
    clip = _find(checks, "health_clipping", "ast_keyboard", "warning")
    assert clip and clip[0]["values"]["runs"] > 0
    assert not _find(checks, "health_clipping", "ast_vocals")
    assert _find(checks, "health_head_click", "ast_percussion", "warning")
    assert not _find(checks, "health_head_click", "ast_vocals")
    assert _find(checks, "headroom", "ast_keyboard", "warning")
    assert _find(checks, "headroom", "ast_vocals", "info")
    assert all(c["level"] in ("info", "warning", "reject") for c in checks)
    assert {r["asset"] for r in mismatched.rec["rejects"]} == {"ast_fx", "ast_synth"}


def test_run_checks_does_not_modify_files(mismatched):
    root = mismatched.proj.root
    before = _snapshot(root / "assets")
    checks = run_checks(mismatched.proj)
    assert _snapshot(root / "assets") == before
    assert checks == mismatched.proj.data["ingest"]["checks"]  # deterministic


def test_stem_sum_consistency_recorded(tmp_path):
    src = make_suno_export(tmp_path / "export", n_stems=4, seconds=2.0)
    proj = Project.create(tmp_path / "song.mmx", title="sum")
    rec = FileAdapter().fetch(src, proj)
    ss = _find(rec["checks"], "stem_sum_consistency")
    assert len(ss) == 1
    v = ss[0]["values"]
    assert ss[0]["level"] == "info" and ss[0]["asset"] == "ast_fullmix"
    # Suno-like full mix (x0.9 + slight EQ): clearly not a null, still highly correlated
    assert -40.0 < v["residual_db"] < -6.0
    assert 0.9 < v["correlation"] <= 1.0
    assert v["best_fit_gain_db"] == pytest.approx(-0.9, abs=0.5)
    assert len(v["stems_summed"]) == 4
    assert not _find(rec["checks"], "stem_sum_consistency", level="reject")


def test_stem_sum_with_rate_mismatch_uses_temporary_resample(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    a = stem_signal(0, 48000, 1.0)
    b48 = stem_signal(1, 48000, 1.0)
    sf.write(str(src / "Vocals.wav"), a, 48000, subtype="FLOAT")
    sf.write(str(src / "Drums.wav"), stem_signal(1, 44100, 1.0), 44100, subtype="FLOAT")
    sf.write(str(src / "Full Mix.wav"), a + b48, 48000, subtype="FLOAT")
    before = _snapshot(src)
    proj = Project.create(tmp_path / "song.mmx", title="rates")
    rec = FileAdapter().fetch(src, proj)
    assert _snapshot(src) == before
    v = _find(rec["checks"], "stem_sum_consistency")[0]["values"]
    assert v["sample_rate"] == 48000 and v["correlation"] > 0.95
    assert sf.info(str(proj.root / "assets" / "Drums.wav")).samplerate == 44100


def test_conform_policy_majority_and_tie():
    assets = [{"id": "a", "sample_rate": 44100, "length_samples": 44100},
              {"id": "b", "sample_rate": 48000, "length_samples": 48000},
              {"id": "c", "sample_rate": 44100, "length_samples": 44100},
              {"id": "d", "sample_rate": 48000, "length_samples": 48000}]
    assert project_sample_rate(assets) == 48000  # tie -> higher
    assert project_sample_rate(assets[:3]) == 44100  # majority
    pol = conform_policy(assets)
    assert {e["asset"] for e in pol["applied"] if e["action"] == "resample_at_render"} == {"a", "c"}
    tb = resolve_timebase(assets)
    assert tb["sample_rate"] == 48000 and tb["length_samples"] == 48000


def test_length_boundary_scales_with_length(tmp_path):
    """Boundary is max(0.5 s, 0.5 % of the longest length): 1.0 s for a 200 s song."""
    sr = 48000
    data = {"assets": [
        {"id": "ast_long", "sample_rate": sr, "length_samples": 200 * sr, "channels": 2, "sha256": "1" * 64,
         "path": "assets/missing_a.wav", "role": "vocals", "role_source": "filename_keyword"},
        {"id": "ast_warn", "sample_rate": sr, "length_samples": int(199.2 * sr), "channels": 2,
         "sha256": "2" * 64, "path": "assets/missing_b.wav", "role": "drums", "role_source": "filename_keyword"},
        {"id": "ast_rej", "sample_rate": sr, "length_samples": int(198.8 * sr), "channels": 2,
         "sha256": "3" * 64, "path": "assets/missing_c.wav", "role": "bass", "role_source": "filename_keyword"},
    ]}
    fake = SimpleNamespace(root=tmp_path, data=data)
    checks = run_checks(fake)
    assert _find(checks, "length_mismatch", "ast_warn")[0]["level"] == "warning"
    assert _find(checks, "length_mismatch", "ast_rej")[0]["level"] == "reject"
    assert _find(checks, "length_mismatch", "ast_rej")[0]["values"]["boundary_s"] == 1.0
