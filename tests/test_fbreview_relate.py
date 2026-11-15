"""The look-ahead functions of FBREVIEW FR-3 (function level; the CLI wiring is tested elsewhere).

- observe_specs -> direction_stem_observations; stem_relate -> direction_stem_relate (the shape of
  the requirements), top_maskers in descending order with at most `top` entries
- no project file is added or changed; a missing / stale cleanup cache raises StemCacheError before
  anything is rendered
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mankomix.core import mixrender as mr
from mankomix.core.analysis.stems import band_density, masking_matrix
from mankomix.core.project import Project
from mankomix.director import relate as R
from mankomix.director import stemobs as S
from tests import test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture(scope="module")
def _four(tmp_path_factory) -> Path:
    import os
    old = os.environ.get("MANKOMIX_HOME")
    base = tmp_path_factory.mktemp("relate_tpl")
    os.environ["MANKOMIX_HOME"] = str(base / "home")
    try:
        return FS._make(base / "song", {"a": FS._noise(300, 1000, 21), "b": FS._noise(300, 1000, 22, -24.0),
                                        "c": FS._noise(200, 2000, 23, -22.0), "d": FS._noise(4000, 8000, 24, -26.0)},
                        tracks={"trk_a": {"role": "vocals", "is_lead": True,
                                          "sends": [{"bus": "bus_fx", "level_db": -12.0}]},
                                "trk_b": {"role": "keyboard"}, "trk_c": {"role": "guitar"}, "trk_d": {"role": "synth"}},
                        variants=FS.VARIANTS)
    finally:
        if old is None:
            os.environ.pop("MANKOMIX_HOME", None)
        else:
            os.environ["MANKOMIX_HOME"] = old


@pytest.fixture
def song(_four, tmp_path) -> Path:
    dst = tmp_path / "song"
    shutil.copytree(_four, dst)
    return dst


def test_relate_shape(song):
    before = FS._tree(song)
    out = R.stem_relate(song)
    assert FS._tree(song) == before
    assert list(out) == ["kind", "signal", "section", "tracks", "masking", "band_owners", "note"]
    assert out["kind"] == "direction_stem_relate" and out["signal"] == "mix_stage_dry" and out["section"] is None
    assert out["tracks"] == ["trk_a", "trk_b", "trk_c", "trk_d"]
    m = out["masking"]
    assert list(m) == ["overall_db", "lead", "per_target"] and m["lead"] == "trk_a"
    assert isinstance(m["overall_db"], float) and m["overall_db"] == round(m["overall_db"], 3)
    assert list(m["per_target"]) == out["tracks"]
    for t, row in m["per_target"].items():
        assert list(row) == ["buried_db", "by_band", "top_maskers"]
        assert list(row["by_band"]) == ["sub", "bass", "lowmid", "mid", "highmid", "air"]
        for v in [row["buried_db"], *row["by_band"].values(), *(x["buried_db"] for x in row["top_maskers"])]:
            assert v is None or (isinstance(v, float) and v == round(v, 3))
        assert all(set(x) == {"track", "buried_db"} and x["track"] != t for x in row["top_maskers"])
    assert list(out["band_owners"]) == ["sub", "bass", "lowmid", "mid", "highmid", "air"]
    assert all(isinstance(v, list) for v in out["band_owners"].values())
    assert "trk_d" in out["band_owners"]["highmid"] or "trk_d" in out["band_owners"]["air"]
    assert out["note"] == R.RELATE_NOTE
    assert R.RELATE_NOTE == ("P-02 のモデル値（粗い興奮パターン）。0 に近いほど良いわけではない。band_owners は P-22 の"
                             "担当の規則を満たしたトラックだけで、その帯域で鳴っているトラックの一覧ではない。読みは指揮者の〔推定〕")
    # deterministic: the same bytes twice
    assert json.dumps(R.stem_relate(song), ensure_ascii=False) == json.dumps(out, ensure_ascii=False)


def test_relate_values_come_from_the_core_functions(song):
    """masking_matrix and band_density on the same dry signals (no second definition)."""
    out = R.stem_relate(song)
    stems: dict = {}
    _, sr, _ = mr.render_mix(Project.open(song), variant_id=None, stems_out=stems, measure=False)
    src = S.StemSource(song, None)
    meta, genre = src.masking_context(sorted(stems))
    mm = masking_matrix(stems, sr, meta, genre=genre)
    assert out["masking"]["overall_db"] == round(mm["overall"]["value"], 3)
    for t in stems:
        assert out["masking"]["per_target"][t]["buried_db"] == round(mm["per_target"][t]["buried_db"], 3)
        vals = [(fc, b) for fc, b in zip(mm["bands_hz"], mm["per_target"][t]["buried_db_by_band"])
                if b is not None and 500 <= fc < 2000]
        want = round(sum(b for _, b in vals) / len(vals), 3) if vals else None
        assert out["masking"]["per_target"][t]["by_band"]["mid"] == want
    bd = band_density(stems, sr, meta, genre=genre)
    for name, band in bd["sections"][0]["bands"].items():
        assert out["band_owners"][name] == [o["track"] for o in band["owners"]]


@pytest.mark.parametrize("top", [1, 2, 3, 8])
def test_top_maskers_descending_and_count(song, top):
    out = R.stem_relate(song, top=top)
    for t, row in out["masking"]["per_target"].items():
        tm = row["top_maskers"]
        assert len(tm) == min(top, 3)                       # 3 other tracks
        v = [x["buried_db"] for x in tm]
        assert v == sorted(v, reverse=True)
    # trk_b (quiet, same band as trk_a) is buried most by trk_a
    assert out["masking"]["per_target"]["trk_b"]["top_maskers"][0]["track"] in ("trk_a", "trk_c")


@pytest.mark.parametrize("top", [0, 9, "3", True, 2.0])
def test_top_out_of_range(song, top):
    with pytest.raises(S.StemObsError, match="top must be"):
        R.stem_relate(song, top=top)


def test_relate_section(song):
    by_id = R.stem_relate(song, section="sec2")
    by_time = R.stem_relate(song, section={"t0_s": 1.5, "t1_s": 3.0})
    assert by_id["section"] == "sec2" and by_time["section"] == {"t0_s": 1.5, "t1_s": 3.0}
    assert by_id["masking"] == by_time["masking"]
    with pytest.raises(S.StemObsError, match="unknown section"):
        R.stem_relate(song, section="nope")


def test_observe_specs_shape_and_read_only(song):
    before = FS._tree(song)
    specs = [{"id": "o1", "primitive": "masking", "target": "trk_b"},
             {"primitive": "wet_ratio", "target": "trk_a"},
             {"primitive": "crest", "target": "trk_c", "section": "sec1"},
             {"primitive": "image_position", "target": "trk_a", "path": "solo"},
             {"primitive": "crest", "target": "master"},
             {"primitive": "crest", "target": "trk_zz"}]
    out = R.observe_specs(song, specs)
    assert FS._tree(song) == before
    assert list(out) == ["kind", "observations"] and out["kind"] == "direction_stem_observations"
    obs = out["observations"]
    assert [o["spec"] for o in obs] == specs and all(list(o) == ["spec", "result"] for o in obs)
    st = [o["result"]["status"] for o in obs]
    assert st == ["ok", "ok", "ok", "ok", "error", "error"]
    assert obs[1]["result"]["value"] == pytest.approx(-12.0, abs=0.5)
    assert obs[2]["result"]["range_s"] == [0.0, 1.5]
    assert "direction query" in obs[4]["result"]["reason"]
    # one spec (not a list) and a variant
    one = R.observe_specs(song, {"primitive": "wet_ratio", "target": "trk_a"}, variant="v_send6")
    assert len(one["observations"]) == 1
    assert one["observations"][0]["result"]["value"] == pytest.approx(-6.0, abs=0.5)
    with pytest.raises(S.StemObsError):
        R.observe_specs(song, [])
    with pytest.raises(S.StemObsError):
        R.observe_specs(song, ["crest"])


def test_no_cache_raises_and_writes_nothing(song, monkeypatch):
    before = FS._tree(song)
    calls = []
    monkeypatch.setattr(mr, "render_mix", lambda *a, **k: calls.append(1))
    with pytest.raises(R.StemCacheError, match="整音の cache が無いか古い"):
        R.stem_relate(song, variant="v_unclean")
    with pytest.raises(R.StemCacheError):
        R.observe_specs(song, [{"primitive": "crest", "target": "trk_b"}], variant="v_unclean")
    assert issubclass(R.StemCacheError, S.StemObsError)
    assert calls == [] and FS._tree(song) == before
