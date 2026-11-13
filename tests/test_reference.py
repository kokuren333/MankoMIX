"""User references: vector-only registration and target distribution (SPEC 4.6, D-039, R-01, R-17)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from mankomix.core import objectives as O
from mankomix.core import reference as R
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 48000


def _ref_signal(seed: int, tilt_db: float, seconds: float = 4.0) -> np.ndarray:
    """Loud (about -10 LUFS) pink-ish stereo track with a low-shelf tilt."""
    p = synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed)
    sos = synth._peaking_sos(SR, 120.0, tilt_db, 0.7)
    x = synth._filt(sos, np.repeat(p, 2, axis=1))
    x[:, 1] = 0.9 * x[:, 1] + 0.1 * synth.pink_noise(-20.0, sr=SR, seconds=seconds, seed=seed + 7)[:, 0]
    return x / np.max(np.abs(x)) * 10 ** (-1.0 / 20)


@pytest.fixture
def setup(tmp_path):
    proj = Project.create(tmp_path / "song.mmx", title="ref test")
    outside = tmp_path / "refs"
    outside.mkdir()
    a = synth.write_wav(outside / "ref_a.wav", _ref_signal(1, 4.0), SR)
    b = synth.write_wav(outside / "ref_b.wav", _ref_signal(2, -2.0), SR)
    return proj, a, b


def _audio_files(root):
    return sorted(p.name for p in root.rglob("*") if p.suffix.lower() in (".wav", ".flac", ".aif", ".aiff", ".mp3"))


def test_add_stores_only_the_vector(setup):
    proj, a, _ = setup
    res = R.reference_add(proj, a, label="Ref A")
    assert res["added"] is True
    entry = res["reference"]
    assert entry["vector"] == f"analysis/ref_{entry['id']}.json"
    assert _audio_files(proj.root) == []                      # no audio copied (4.6)
    vec = json.loads((proj.root / entry["vector"]).read_text(encoding="utf-8"))
    assert vec["source"] == {"file_name": "ref_a.wav", "sha256": entry["sha256"]}
    assert "audio" not in vec and len(json.dumps(vec)) < 200_000
    # level matched downwards to the common comparison level (R-01)
    assert vec["level_match"]["gain_db"] < 0 and vec["level_match"]["direction"] == "down"
    assert vec["ltas_erb"]["level_matched_to_lufs"] == -23.0
    reopened = Project.open(proj.root)
    assert reopened.data["references"] == [entry]
    assert all(i["level"] != "error" for i in reopened.validate())
    # same content is not registered twice
    again = R.reference_add(proj, a, label="dup")
    assert again["added"] is False and len(proj.data["references"]) == 1
    text = (proj.root / entry["vector"]).read_text(encoding="utf-8")
    assert str(a.parent) not in text and a.parent.as_posix() not in text   # no absolute paths


def test_list_distribution_and_remove(setup):
    proj, a, b = setup
    assert R.reference_distribution(proj) is None
    assert R.reference_list(proj)["target_source"] == "generic_prior"
    ra = R.reference_add(proj, a, label="A")["reference"]
    one = R.reference_distribution(proj)
    assert one["n"] == 1 and one["iqr_source"] == "default_width_single_reference"
    centers = np.asarray(one["centers_hz"])
    iqr = np.asarray(one["iqr_db"])
    mid = (centers > 200) & (centers < 5000)
    assert np.allclose(iqr[mid], 6.0) and iqr.max() <= 10.0 + 1e-9
    assert len(one["median_db"]) == len(one["centers_hz"])

    rb = R.reference_add(proj, b, label="B")["reference"]
    two = R.reference_distribution(proj)
    assert two["n"] == 2 and min(two["iqr_db"]) >= 3.0 - 1e-9
    s = two["scalars"]["P-07:sub+bass"]
    assert s["n"] == 2 and s["iqr"] > 0

    lst = R.reference_list(proj)
    assert lst["count"] == 2 and all(i["vector_present"] for i in lst["references"])

    # resolved objective uses the references (R-17), the generic note disappears
    res = O.resolve_objective(proj)
    assert res["reference"]["source"] == "references" and res["reference"]["n"] == 2
    assert not any(n["code"] == "generic_prior" for n in res["notes"])
    p01 = next(t for t in res["terms"] if t["key"] == "P-01")
    assert p01["target"]["source"] == "references"
    bh = O.resolve_objective({"blend": [{"id": "bass_heavy", "weight": 1}], "intensity": 0.0},
                             references=two)
    t07 = next(t for t in bh["terms"] if t["key"] == "P-07:sub+bass")["target"]
    assert t07["source"].startswith("references") and t07["range"][0] < s["median"] < t07["range"][1]

    x = _ref_signal(1, 4.0)
    ev = O.evaluate(O.measure_for_objective(x, SR, res), res)
    t = next(t for t in ev["terms"] if t["key"] == "P-01")
    assert t["status"] == "measured" and t["generic_prior"] is False

    out = R.reference_remove(proj, ra["id"])
    assert out["vector_deleted"] is True
    assert not (proj.root / ra["vector"]).exists()
    assert [r["id"] for r in Project.open(proj.root).data["references"]] == [rb["id"]]
    with pytest.raises(InputError):
        R.reference_remove(proj, "missing")
