"""Optional regression scaffold for the official sample (docs/SPEC.md 15.1, 16.2).

These tests run only when the sample location is given from outside:

* ``MANKOMIX_SAMPLE_DIR`` - folder with the conform set (12 stems and the
  aligned full mix, 48 kHz). Required; without it every test here is skipped
  by ``tests/conftest.py`` (``sample`` marker).
* ``MANKOMIX_SAMPLE_EXPORT_DIR`` - optional folder with the as-downloaded
  Suno Studio export set ("<number> <part>.wav" names, number 0 = full mix).

The sample audio itself never enters the repository. Expected measurement
ranges (data only, no audio) may be added later (SPEC 15.4).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.sample

AUDIO_SUFFIXES = {".wav", ".flac", ".aif", ".aiff"}


def _audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)


def _folder_from_env(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} not set")
    return Path(value).expanduser()


def test_sample_conform_set_is_present():
    folder = _folder_from_env("MANKOMIX_SAMPLE_DIR")
    assert folder.is_dir(), "MANKOMIX_SAMPLE_DIR does not point to a folder"
    assert len(_audio_files(folder)) >= 1, "no audio files in MANKOMIX_SAMPLE_DIR"
    # TODO(M1 intake): ingest the conform set unchanged; expect 12 stems plus the
    #   aligned full mix, 48 kHz; the derived "other" / "no_vocals" files must
    #   not be used as inputs (D-037); content hashes unchanged after intake.
    # TODO(M2 measure): compare the measurement vector (P-03 loudness, P-14 true
    #   peak, P-16 noise/shimmer, ...) with stored expected ranges.
    # TODO(later milestones): render the 11 sample variants of SPEC 15.2 and check
    #   the safety invariants S-01..S-11 and bit-identical re-rendering (16.3).


def test_sample_export_set_is_present():
    folder = _folder_from_env("MANKOMIX_SAMPLE_EXPORT_DIR")
    assert folder.is_dir(), "MANKOMIX_SAMPLE_EXPORT_DIR does not point to a folder"
    assert len(_audio_files(folder)) >= 1, "no audio files in MANKOMIX_SAMPLE_EXPORT_DIR"
    # TODO(M1 intake): detect the Suno export pattern, assign roles from part
    #   names, register the number-0 file as fullmix, and report the stem-sum vs
    #   full-mix residual (SPEC 6.1.3, 6.1.4) without converting anything.


# The conform set's file names (D-037: "other" / "no_vocals" are derived sums and are not
# inputs; "0_fullmix" is the unaligned download, the conformed full mix is used instead).
CONFORM_STEMS = ("backing_vocals", "bass", "brass", "drums", "fx", "guitar", "keyboard", "percussion",
                 "strings", "synth", "vocals", "woodwinds")
CONFORM_FULLMIX = "fullmix_conformed.wav"


def test_sample_cleanup_fullmix_s07(tmp_path, monkeypatch):
    """M5: import the conform set (link mode), clean the full mix, S-07 passes (SPEC 4.3, 6.4)."""
    import json
    import time

    from mankomix.core import cleanstage
    from mankomix.core.adapters.file import FileAdapter
    from mankomix.core.project import Project

    folder = _folder_from_env("MANKOMIX_SAMPLE_DIR")
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))  # linked locations stay out of the user config
    files = [folder / f"{n}.wav" for n in CONFORM_STEMS] + [folder / CONFORM_FULLMIX]
    files = [f for f in files if f.is_file()]
    if not (folder / CONFORM_FULLMIX).is_file():
        pytest.skip(f"{CONFORM_FULLMIX} not in MANKOMIX_SAMPLE_DIR")
    proj = Project.create(tmp_path / "sample.mmx", title="official sample")
    FileAdapter().fetch(files, proj, mode="link", actor="human")
    fid = proj.data.get("fullmix_asset")
    assert fid and proj.asset(fid)["original_name"] == CONFORM_FULLMIX
    assert all(a.get("linked") for a in proj.data["assets"])

    t0 = time.perf_counter()
    prop = cleanstage.plan_clean(proj, targets=[fid])
    t_plan = time.perf_counter() - t0
    entries = prop["items"] + prop["skipped"]
    assert [e["asset"] for e in entries] == [fid]
    t1 = time.perf_counter()
    res = cleanstage.apply_clean(proj, prop, actor="human")
    t_apply = time.perf_counter() - t1
    a = res["assets"][0]
    rec = cleanstage.cleanup_record(proj, fid)
    assert rec["s07"]["pass"] is True, rec["s07"]
    assert cleanstage.s07_check(proj, "full_mix")["status"] in ("pass", "not_applicable")
    base = cleanstage.route_baseline(proj, "full_mix")
    assert base["baseline"]["kind"] == "cleanup_noise_baseline"
    if not a["skipped"]:
        assert (proj.root / cleanstage.delta(proj, fid)).is_file()
    summary = {"diagnosis": entries[0]["diagnosis"], "steps": a["steps"], "skipped": a["skipped"],
               "s07": a["s07"], "p21_pass": a["p21_pass"], "oversuppression_rerun": a["oversuppression_rerun"],
               "removed_energy": {k: v.get("removed_rel_db") for k, v in
                                  ((rec.get("report") or {}).get("removed_energy") or {}).items()},
               "seconds": {"plan": round(t_plan, 1), "apply": round(t_apply, 1)}}
    print("\nSAMPLE_CLEANUP " + json.dumps(summary, ensure_ascii=False))
