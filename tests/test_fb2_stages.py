"""X-05 stage measurements and read-only CLI contracts on synthetic signals."""
import copy
import json

import pytest

from mankomix.cli.main import main
from mankomix.core import audio_io, config, mixrender as MR
from mankomix.director import direction as D, relate as R, stages as T, stemobs as S
from tests import test_director as TD, test_fbreview_stemobs as FS


@pytest.fixture(autouse=True)
def local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture
def song(tmp_path):
    x = FS._noise(300, 1000, 71)
    return FS._make(tmp_path / "song", {"a": x, "b": x}, fx=False,
                    tracks={"trk_a": {"gain_db": 0.0, "chain": [
                        {"id": "prc_trim", "type": "gain", "params": {"gain_db": -6.0}}]},
                            "trk_b": {"gain_db": 0.0, "muted": True}}, variants=FS.VARIANTS)


def test_known_stage_values_master_matching_and_determinism(song):
    before = FS._tree(song)
    out = T.stages(song, band=[300, 1000])
    assert out["tracks"]["trk_a"]["chain_delta_db"] == pytest.approx(-6, abs=.002)
    assert out["tracks"]["trk_a"]["dry_db"] == out["sum_of_dry_db"] == out["mix_db"]
    assert out["cancellation_db"] == pytest.approx(0, abs=.002)
    assert out["master_db"] is None and out["master_minus_mix_matched_db"] is None
    assert out["master_reason"] == "その変種の描画済みマスターが無い"
    assert out["note"] == T.NOTE and out["reliability"] == T.RELIABILITY
    assert "large_boosts" not in out and "large_boosts_note" not in out
    assert json.dumps(out, ensure_ascii=False) == json.dumps(T.stages(song, band=[300, 1000]), ensure_ascii=False)
    assert FS._tree(song) == before
    mix, sr = R._source(song, "var_x").mix()
    audio_io.write(song / "renders/var_x/master__archive_f32.wav", mix * 10 ** (6 / 20), sr, subtype="FLOAT")
    before = FS._tree(song)
    for section in (None, "sec1", {"t0_s": .5, "t1_s": 2.5}):
        row = T.stages(song, band=[300, 1000], section=section)
        assert row["master_db"] - row["mix_db"] == pytest.approx(6, abs=.002)
        assert row["master_minus_mix_matched_db"] == pytest.approx(0, abs=.002)
    assert FS._tree(song) == before


def test_opposite_polarity_cancellation(tmp_path):
    x = FS._noise(300, 1000, 72)
    root = FS._make(tmp_path / "cancel", {"a": x, "b": -x}, fx=False,
                    tracks={"trk_a": {"gain_db": 0}, "trk_b": {"gain_db": 0}})
    before = FS._tree(root)
    row = T.stages(root, band=[300, 1000])
    assert row["cancellation_db"] < -60
    assert row["sum_of_dry_db"] < min(t["dry_db"] for t in row["tracks"].values()) - 60
    assert FS._tree(root) == before


def test_mix_observation_no_matching_and_no_validate_warning(song, tmp_path):
    spec = {"id": "o1", "primitive": "band_energy", "target": "mix", "band_hz": [300, 1000], "level_match": True}
    doc = D.parse_document(TD._doc(tmp_path, TD._block(observations=[spec], moves=[])))
    result = D.validate(doc, song)
    assert result["ok"] and not result["warnings"]
    before = FS._tree(song)
    row = R.observe_specs(song, [spec])["observations"][0]["result"]
    assert row["status"] == "ok" and row["gain_db"] == 0 and row["signal"] == "mix_stage"
    assert "path" not in row
    assert row["value"] == T.stages(song, band=[300, 1000])["mix_db"]
    assert FS._tree(song) == before


@pytest.mark.parametrize("extra", [{"primitive": "masking"}, {"primitive": "wet_ratio"}, {"path": "dry"}, {"path": None}])
def test_mix_forbidden_combinations(song, tmp_path, extra):
    spec = {"id": "o1", "primitive": "crest", "target": "mix", **extra}
    doc = D.parse_document(TD._doc(tmp_path, TD._block(observations=[spec], moves=[])))
    assert any(e["code"] == "bad_value" for e in D.validate(doc, song)["errors"])
    row = S.observe(R._source(song, "var_x"), spec)
    assert row["status"] == "error" and "bad_value" in row["reason"]


def test_large_boost_context_reads_rule_and_leaves_validate_unchanged(song, tmp_path, monkeypatch):
    limit = config.load_knowledge("mix_rules")["eq"]["max_move_db"]
    template = TD._block()["moves"][0]
    moves = []
    for i, (kind, gain) in enumerate((("eq", limit), ("eq", limit + 1), ("eq", -limit - 2),
                                     ("dynamic_eq", limit + 2), ("dynamic_eq", -limit - 2),
                                     ("gain", limit + 3))):
        m = copy.deepcopy(template)
        m.update(id=f"m{i}", target="trk_a", processor=kind, select={})
        m["params"] = {"gain_db": gain} if kind == "gain" else {
            "freq_hz": 600, "bw_oct": 1, "gain_db" if kind == "eq" else "range_db": gain}
        moves.append(m)
    # Existing range selection is used for the context, without calibration.
    moves[1]["params"]["gain_db"] = [limit - 1, limit + 1]
    moves[1]["select"] = {"gain_db": "max"}
    path = TD._doc(tmp_path, TD._block(moves=moves))
    doc = D.parse_document(path)
    before_validation = json.dumps(D.validate(doc, song), ensure_ascii=False)
    before = FS._tree(song)
    plain = T.stages(song, band=[300, 1000])
    out = T.stages(song, band=[300, 1000], direction=path)
    assert out.pop("large_boosts_note") == "読む材料。拒否も警告もしない"
    rows = out.pop("large_boosts")
    assert rows == [{"move": "m1", "target": "trk_a", "freq_hz": 600.0, "gain_db": limit + 1, "rule": "R-06"},
                    {"move": "m3", "target": "trk_a", "freq_hz": 600.0, "gain_db": limit + 2, "rule": "R-06"}]
    assert out == plain
    assert json.dumps(D.validate(doc, song), ensure_ascii=False) == before_validation
    actual = config.load_knowledge
    def changed(name):
        data = copy.deepcopy(actual(name))
        if name == "mix_rules":
            data["eq"]["max_move_db"] = limit + 1
        return data
    monkeypatch.setattr(config, "load_knowledge", changed)
    assert [r["move"] for r in T.stages(song, band=[300, 1000], direction=path)["large_boosts"]] == ["m3"]
    assert FS._tree(song) == before


def test_large_boosts_existing_eq_and_bus_chain_exclude_notch_and_reduction(song, tmp_path):
    limit = config.load_knowledge("mix_rules")["eq"]["max_move_db"]
    file = song / "project.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    track = next(t for t in data["tracks"] if t["id"] == "trk_a")
    track["chain"].append({"id": "prc_eq", "type": "eq", "params": {"freq_hz": 700, "gain_db": 0}})
    file.write_text(json.dumps(data), encoding="utf-8")
    moves = [
        {"id": "param", "op": "chain_param", "target": "trk_a", "replaces": "prc_eq", "params": {"gain_db": limit + 1}},
        {"id": "bus", "op": "bus_add", "target": "bus_new", "params": {"chain": [
            {"type": "eq", "params": {"freq_hz": 800, "gain_db": limit + 2}},
            {"type": "eq", "params": {"shape": "notch", "gain_db": limit + 2}},
            {"type": "deesser", "params": {"range_db": limit + 2}}]}}]
    path = TD._doc(tmp_path, TD._block(moves=moves))
    before = FS._tree(song)
    rows = T.stages(song, band=[300, 1000], direction=path)["large_boosts"]
    assert rows == [{"move": "param", "target": "trk_a", "freq_hz": 700.0, "gain_db": limit + 1, "rule": "R-06"},
                    {"move": "bus", "target": "bus_new", "freq_hz": 800.0, "gain_db": limit + 2, "rule": "R-06"}]
    assert FS._tree(song) == before


@pytest.mark.parametrize("damage", ["missing", "stale"])
def test_invalid_cache_does_not_render_or_write(song, monkeypatch, damage):
    from mankomix.core import cleanstage
    import hashlib
    data = json.loads((song / "project.json").read_text(encoding="utf-8"))
    track = data["tracks"][0]
    aid = track["clips"][0]["asset"]
    sha = next(a["sha256"] for a in data["assets"] if a["id"] == aid)
    phash = "b" * 64
    path = song / cleanstage.cache_rel(sha, phash)
    cleanstage.write_f32_wav(path, FS._noise(300, 1000, 73), FS.SR)
    cleanstage._sidecar(path).write_text(json.dumps({"asset_sha256": sha, "plan_hash": phash,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")
    track["cleanup"] = {"applied": {"assets": {aid: {"asset_sha256": sha, "plan_hash": phash}}}}
    (song / "project.json").write_text(json.dumps(data), encoding="utf-8")
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"stale")
    before = FS._tree(song)
    monkeypatch.setattr(MR, "render_mix", lambda *a, **k: pytest.fail("must reject before rendering"))
    monkeypatch.setattr(MR, "render_track", lambda *a, **k: pytest.fail("must reject before rendering"))
    with pytest.raises(T.StagesInputError, match="clean apply"):
        T.stages(song, band=[300, 1000])
    assert FS._tree(song) == before


@pytest.mark.parametrize("section", ["sec1", '{"t0_s": 0.5, "t1_s": 2.0}'])
def test_cli_json_and_direction(song, tmp_path, capsys, section):
    path = TD._doc(tmp_path, TD._block(moves=[]))
    args = ["direction", "stems", "stages", "--project", str(song), "--variant", "var_x", "--band", "300,1000",
            "--section", section, "--direction", str(path)]
    before = FS._tree(song)
    outputs = []
    for _ in range(2):
        assert main(args) == 0
        captured = capsys.readouterr()
        assert not captured.err
        outputs.append(captured.out)
    assert outputs[0] == outputs[1]
    out = json.loads(outputs[0])
    assert out["kind"] == "direction_stem_stages" and out["large_boosts"] == []
    assert out["range_s"] == ([0, 1.5] if section == "sec1" else [.5, 2])
    assert FS._tree(song) == before


@pytest.mark.parametrize("args,code", [(["--band", "bad"], 2), (["--band", "1,2,3"], 1),
    (["--band", "1000,300"], 1), (["--band", "nan,1000"], 1),
    (["--band", "300,1000", "--section", "unknown"], 1),
    (["--band", "300,1000", "--variant", "unknown"], 1),
    (["--band", "300,1000", "--direction", "missing.md"], 1)])
def test_cli_input_errors(song, capsys, args, code):
    before = FS._tree(song)
    assert main(["direction", "stems", "stages", "--project", str(song), *args]) == code
    captured = capsys.readouterr()
    assert not captured.err and json.loads(captured.out)["error"] == "input_error"
    assert FS._tree(song) == before
