"""X-09 side observations share validation and query rules."""
import numpy as np
import pytest

from mankomix.director import direction as D, query as Q, relate as R, stemobs as S
from tests import test_director as TD, test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture
def signals():
    t = np.arange(FS.N) / FS.SR
    s = .1 * np.sin(2 * np.pi * 660 * t)
    return np.column_stack([s, -s]), np.column_stack([s, s])


@pytest.mark.parametrize("primitive", ["band_energy", "crest", "loudness"])
def test_side_values_and_mono_missing(signals, primitive, tmp_path):
    side, mono = signals
    spec = {"primitive": primitive, "view": "side"}
    if primitive == "band_energy":
        spec["band_hz"] = [500, 800]
    plain = Q.observe(mono, FS.SR, {k: v for k, v in spec.items() if k != "view"})
    row = Q.observe(side, FS.SR, spec)
    assert row["status"] == "ok" and row["value"] == pytest.approx(plain["value"], abs=.001)
    if primitive == "crest":
        assert row["value"] == pytest.approx(3.010, abs=.001)
    assert Q.observe(mono, FS.SR, spec) == {"status": "error", "reason": "view 'side': the signal is silent in the range"}
    root = FS._make(tmp_path / "song", {"a": side, "b": mono}, fx=False)
    before = FS._tree(root)
    src = R._source(root, "var_x")
    for path in ("dry", "solo"):
        track = S.observe(src, {**spec, "target": "trk_a", "path": path})
        assert track["status"] == "ok" and track["value"] == pytest.approx(row["value"], abs=.001)
        assert S.observe(src, {**spec, "target": "trk_b", "path": path})["status"] == "error"
    assert FS._tree(root) == before


@pytest.mark.parametrize("target", ["master", "trk_a"])
@pytest.mark.parametrize("extra", [
    {"primitive": p} for p in ("band_ratio", "side_ratio", "correlation", "image_position", "masking", "wet_ratio")
] + [{"view_band_hz": v} for v in (None, [150, 6000], 100)])
def test_validate_and_query_reject_same_combinations(tmp_path, signals, target, extra):
    spec = {"id": "o1", "primitive": "crest", "target": target, "view": "side", **extra}
    doc = D.parse_document(TD._doc(tmp_path, TD._block(moves=[], observations=[spec])))
    result = D.validate(doc)
    with pytest.raises(Q.QueryError) as exc:
        Q.observe(signals[0], FS.SR, spec)
    assert any(e["code"] == "bad_value" and e["message"] == str(exc.value).removeprefix("bad_value: ")
               for e in result["errors"])
    class UnreadableSource:
        def track(self, *a):
            pytest.fail("bad view must fail before audio access")
    row = S.observe(UnreadableSource(), spec)
    assert row == {"status": "error", "reason": str(exc.value)}


@pytest.mark.parametrize("target", ["master", "trk_a"])
@pytest.mark.parametrize("primitive", ["band_energy", "crest", "loudness"])
def test_validate_accepts_supported_side(tmp_path, target, primitive):
    spec = {"id": "o1", "primitive": primitive, "target": target, "view": "side"}
    if primitive == "band_energy":
        spec["band_hz"] = [500, 800]
    result = D.validate(D.parse_document(TD._doc(tmp_path, TD._block(moves=[], observations=[spec]))))
    assert result["ok"] and not result["warnings"]


def test_absent_view_preserves_output_and_precision(signals, tmp_path):
    _, mono = signals
    expected = {"status": "ok", "value": 3.0103, "unit": "dB", "range_s": [0.0, 3.0], "gain_db": 0.0}
    assert Q.observe(mono, FS.SR, {"primitive": "crest"}) == expected
    assert Q.observe(mono, FS.SR, {"primitive": "crest", "view": "stereo"}) == expected
    root = FS._make(tmp_path / "plain", {"a": mono, "b": mono}, fx=False)
    src = R._source(root, "var_x")
    spec = {"primitive": "crest", "target": "trk_a"}
    plain = S.observe(src, spec)
    assert list(plain) == ["status", "value", "unit", "range_s", "gain_db", "signal", "path"]
    assert plain == S.observe(src, {**spec, "view": "stereo"})
    assert plain["value"] == 3.0103 and plain["signal"] == "mix_stage" and plain["path"] == "dry"


def test_side_silence_is_checked_in_selected_section(signals):
    side, _ = signals
    side = side.copy()
    side[:FS.SR] = 0
    assert Q.observe(side, FS.SR, {"primitive": "crest", "view": "side"})["status"] == "ok"
    assert Q.observe(side, FS.SR, {"primitive": "crest", "view": "side", "section": {"t0_s": 0, "t1_s": 1}})["status"] == "error"
