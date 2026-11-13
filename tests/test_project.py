"""Project folder, canonical project.json, validation and patching (SPEC 9)."""
from __future__ import annotations

import json

import pytest

from mankomix.core import config, journal
from mankomix.core.errors import InputError, ValidationError
from mankomix.core.hashing import canonical_hash, canonical_json, sha256_file
from mankomix.core.project import PROJECT_FILE, SUBDIRS, Project, validate_project_data

SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    # Keep local settings out of the user's home during tests.
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _errors(issues):
    return [i for i in issues if i["level"] == "error"]


def _new(tmp_path, name="song.mmx", **kw):
    kw.setdefault("title", "テスト曲")
    return Project.create(tmp_path / name, **kw)


def _populate(p: Project) -> None:
    (p.root / "assets" / "12 Vocals.wav").write_bytes(b"not really audio")
    p.data["assets"].append({
        "id": "ast_vocals", "path": "assets/12 Vocals.wav", "original_name": "12 Vocals.wav",
        "sha256": SHA_A, "format": "wav_f32", "container": "wav", "subtype": "FLOAT", "channels": 2,
        "sample_rate": 48000, "length_samples": 480000, "duration_s": 10.0, "role": "vocals",
        "role_source": "filename_pattern", "origin": "native_stem", "linked": False,
    })
    p.data["buses"].insert(0, {"id": "bus_reverb", "kind": "fx", "chain": [], "output": "bus_mix"})
    p.data["tracks"].append({
        "id": "trk_vocals", "kind": "audio", "role": "vocals", "is_lead": True,
        "importance": {"value": 1.0, "source": "genre_prior", "by_section": {}},
        "clips": [{"id": "clp_1", "asset": "ast_vocals", "source_start": 0, "length": 480000,
                   "timeline_start": 0, "gain_db": 0.0, "fade_in": 0, "fade_out": 0, "muted": False}],
        "cleanup": {"enabled": True, "plan": "auto", "overrides": {}},
        "chain": [{"id": "prc_1", "type": "filter", "params": {"mode": "hpf", "cutoff_hz": 90}, "reason": "R-07"}],
        "gain_db": -1.5, "pan": {"position": 0.0, "width": 1.0},
        "sends": [{"bus": "bus_reverb", "level_db": -18.0}], "output": "bus_mix",
    })
    p.data["mix"]["declared_depth_order"] = ["trk_vocals"]
    p.data["objective"]["lead_stem"] = "trk_vocals"
    p.data["variants"].append({
        "id": "var_streaming", "objective": None, "master": {"route": "stem_mix", "chain": []},
        "outputs": [{"profile": "spotify", "delivery": "hires_native"}, {"profile": "mv", "delivery": "distributor_44k16"}],
    })
    p.save(actor="agent", op="import", reason="test assets")


# --- create / open / save ------------------------------------------------------------------

def test_create_layout_and_defaults(tmp_path):
    p = _new(tmp_path, genre="hiphop")
    for sub in SUBDIRS:
        assert (p.root / sub).is_dir()
    assert (p.root / PROJECT_FILE).is_file()
    assert (p.root / "journal.jsonl").is_file()
    d = p.data
    assert d["schema_version"] == 1 and d["id"].startswith("prj_") and d["genre"] == "hiphop"
    assert d["timebase"]["sample_rate"] is None
    assert d["timebase"]["conform_policy"] == {"sample_rate": "majority", "alignment": "head",
                                               "short_assets": "pad_silence_at_render"}
    assert d["buses"] == [{"id": "bus_mix", "kind": "mix", "chain": []}]
    assert d["objective"]["blend"] == [{"id": "comfort", "weight": 1.0}]
    assert d["engine"]["min_version"]
    assert p.validate() == []


def test_create_refuses_existing(tmp_path):
    _new(tmp_path)
    with pytest.raises(InputError):
        _new(tmp_path)


def test_create_rejects_unknown_genre(tmp_path):
    with pytest.raises(ValidationError):
        _new(tmp_path, genre="polka_core")


def test_open_roundtrip(tmp_path):
    p = _new(tmp_path)
    _populate(p)
    a = Project.open(p.root)
    b = Project.open(p.root / PROJECT_FILE)
    assert a.data == p.data == b.data
    assert a.content_hash() == p.content_hash() == canonical_hash(p.data)
    with pytest.raises(InputError):
        Project.open(tmp_path / "missing.mmx")


def test_deterministic_bytes(tmp_path):
    p1 = _new(tmp_path, "a.mmx", project_id="prj_fixed")
    p2 = _new(tmp_path, "b.mmx", project_id="prj_fixed")
    raw1 = (p1.root / PROJECT_FILE).read_bytes()
    assert raw1 == (p2.root / PROJECT_FILE).read_bytes()
    text = raw1.decode("utf-8")
    assert text.endswith("}\n") and "\r\n" not in text
    assert "テスト曲" in text  # ensure_ascii=False
    assert text.startswith('{\n  "schema_version": 1,\n  "id": "prj_fixed"')
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    # a no-op save neither rewrites nor journals
    n = len(journal.list_entries(p1.root))
    p1.save()
    assert (p1.root / PROJECT_FILE).read_bytes() == raw1
    assert len(journal.list_entries(p1.root)) == n


def test_canonical_json():
    assert canonical_json({"b": 1, "a": "曲"}) == '{"a":"曲","b":1}'
    assert canonical_hash({"b": 1, "a": 2}) == canonical_hash({"a": 2, "b": 1})


def test_save_rejects_invalid_and_keeps_file(tmp_path):
    p = _new(tmp_path)
    before = (p.root / PROJECT_FILE).read_bytes()
    p.data["objective"]["intensity"] = 1.5
    with pytest.raises(ValidationError) as exc:
        p.save()
    assert any(i["path"] == "/objective/intensity" for i in exc.value.details["issues"])
    assert (p.root / PROJECT_FILE).read_bytes() == before


# --- validation --------------------------------------------------------------------------------

@pytest.fixture
def populated(tmp_path):
    p = _new(tmp_path)
    _populate(p)
    assert p.validate() == []
    return p


def _paths(p):
    return {i["path"] for i in _errors(p.validate())}


@pytest.mark.parametrize("bad_path", [
    "C" + ":" + "/stems/vocals.wav",
    "C" + ":" + "\\" + "stems",
    "/" + "abs/vocals.wav",
    "assets/../../outside.wav",
    "assets" + "\\" + "vocals.wav",
])
def test_rejects_non_relative_asset_paths(populated, bad_path):
    populated.data["assets"][0]["path"] = bad_path
    assert "/assets/0/path" in _paths(populated)


def test_rejects_absolute_path_anywhere(populated):
    populated.data["provenance"]["notes"] = "C" + ":" + "\\" + "Users" + "\\" + "someone" + "\\" + "song"
    assert "/provenance/notes" in _paths(populated)
    populated.data["provenance"]["notes"] = "/" + "home/someone/song"
    assert "/provenance/notes" in _paths(populated)


def test_rejects_bad_references(populated):
    t = populated.data["tracks"][0]
    t["clips"][0]["asset"] = "ast_missing"
    t["output"] = "bus_missing"
    t["sends"][0]["bus"] = "bus_nope"
    populated.data["fullmix_asset"] = "ast_fullmix"
    populated.data["mix"]["declared_depth_order"] = ["trk_ghost"]
    paths = _paths(populated)
    assert {"/tracks/0/clips/0/asset", "/tracks/0/output", "/tracks/0/sends/0/bus",
            "/fullmix_asset", "/mix/declared_depth_order/0"} <= paths


def test_rejects_duplicate_ids(populated):
    populated.data["tracks"][0]["id"] = "ast_vocals"  # same as the asset
    populated.data["tracks"][0]["chain"][0]["id"] = "clp_1"  # same as the clip
    paths = _paths(populated)
    assert "/tracks/0/id" in paths and "/tracks/0/chain/0/id" in paths


def test_rejects_objective_and_catalog_errors(populated):
    d = populated.data
    d["objective"]["blend"] = [{"id": "comfort", "weight": 0.6}, {"id": "no_such", "weight": 0.4},
                               {"id": "translation", "weight": 0.1}]
    d["objective"]["intensity"] = -0.1
    d["genre"] = "unknown_genre"
    d["variants"][0]["outputs"][0]["profile"] = "radio"
    d["assets"][0]["sha256"] = "XYZ"
    paths = _paths(populated)
    assert {"/objective/blend/1/id", "/objective/blend/2/id", "/objective/intensity", "/genre",
            "/variants/0/outputs/0/profile", "/assets/0/sha256"} <= paths
    d["objective"]["blend"] = [{"id": "comfort", "weight": 0}]
    assert "/objective/blend/0/weight" in _paths(populated)


def test_rejects_routing_problems(populated):
    populated.data["buses"][0]["output"] = "bus_reverb"  # self
    assert "/buses/0/output" in _paths(populated)
    populated.data["buses"].append({"id": "bus_mix2", "kind": "mix", "chain": []})
    assert "/buses" in _paths(populated)


def test_rejects_non_audio_track_kind(populated):
    populated.data["tracks"][0]["kind"] = "midi"
    assert "/tracks/0/kind" in _paths(populated)


def test_validate_function_without_root(populated):
    assert validate_project_data(populated.data) == []


# --- patching --------------------------------------------------------------------------------------

def test_apply_patch_and_set(populated):
    p = populated
    p.apply_patch([
        {"op": "test", "path": "/tracks/0/gain_db", "value": -1.5},
        {"op": "replace", "path": "/tracks/0/gain_db", "value": -3.0},
        {"op": "add", "path": "/tracks/0/chain/-", "value":
            {"id": "prc_2", "type": "eq", "params": {"freq_hz": 300, "gain_db": -2, "bw_oct": 1}, "reason": "R-05"}},
        {"op": "remove", "path": "/tracks/0/sends/0"},
    ], actor="agent", reason="tidy")
    q = Project.open(p.root)
    t = q.data["tracks"][0]
    assert t["gain_db"] == -3.0 and t["chain"][-1]["id"] == "prc_2" and t["sends"] == []
    p.set("/objective/intensity", 0.7, actor="human", reason="more")
    p.set("/references/-", {"id": "ref_1", "label": "reference A", "vector": "analysis/ref_1.json"}, actor="human")
    q = Project.open(p.root)
    assert q.data["objective"]["intensity"] == 0.7 and q.data["references"][0]["id"] == "ref_1"
    last = journal.list_entries(p.root)[-1]
    assert last["op"] == "set" and last["actor"] == "human" and last["patch"][0]["path"] == "/references/-"


def test_apply_patch_failures_leave_project_untouched(populated):
    p = populated
    raw = (p.root / PROJECT_FILE).read_bytes()
    data = json.loads(raw)
    bad_patches = [
        [{"op": "test", "path": "/title", "value": "other"}],
        [{"op": "replace", "path": "/no/such", "value": 1}],
        [{"op": "move", "from": "/title", "path": "/genre"}],
        [{"op": "replace", "path": "/tracks/0/output", "value": "bus_ghost"}],  # semantic error
        [{"op": "add", "path": "/assets/0/path", "value": "C" + ":" + "/x.wav"}],
    ]
    for ops in bad_patches:
        with pytest.raises(ValidationError):
            p.apply_patch(ops, actor="agent")
        assert p.data == data
    assert (p.root / PROJECT_FILE).read_bytes() == raw
    with pytest.raises(InputError):
        p.set("/title", "x", actor="robot")


def test_concurrent_modification_is_reapplied(populated):
    gui = Project.open(populated.root)
    cli = Project.open(populated.root)
    gui.set("/title", "GUI title", actor="human")
    # cli is stale: its patch is re-applied on the latest project.json
    cli.apply_patch([{"op": "replace", "path": "/mix/pan_law_center_db", "value": -4.5}], actor="agent")
    latest = Project.open(populated.root).data
    assert latest["title"] == "GUI title" and latest["mix"]["pan_law_center_db"] == -4.5
    assert cli.data == latest
    # local edits + save on a stale copy merge with the other writer's change
    gui.data["tracks"][0]["gain_db"] = -6.0
    cli.set("/tracks/0/pan/position", 0.1, actor="agent")
    gui.save(actor="human")
    latest = Project.open(populated.root).data
    assert latest["tracks"][0]["gain_db"] == -6.0 and latest["tracks"][0]["pan"]["position"] == 0.1


def test_concurrent_conflict_fails(populated):
    a = Project.open(populated.root)
    b = Project.open(populated.root)
    a.set("/title", "A", actor="human")
    raw = (populated.root / PROJECT_FILE).read_bytes()
    with pytest.raises(ValidationError):
        b.apply_patch([{"op": "test", "path": "/title", "value": "テスト曲"},
                       {"op": "replace", "path": "/title", "value": "B"}], actor="agent")
    b.data["title"] = "B"
    with pytest.raises(ValidationError):
        b.save(actor="agent")
    assert (populated.root / PROJECT_FILE).read_bytes() == raw


# --- assets and paths ---------------------------------------------------------------------------------

def test_asset_path_copied_and_linked(populated, tmp_path):
    p = populated
    assert p.asset_path("ast_vocals") == p.root / "assets" / "12 Vocals.wav"
    with pytest.raises(InputError):
        p.asset("ast_none")

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    src = outside / "11 Backing Vocals.wav"
    src.write_bytes(b"linked bytes")
    sha = sha256_file(src)
    p.apply_patch([{"op": "add", "path": "/assets/-", "value": {
        "id": "ast_bv", "path": "linked/11 Backing Vocals.wav", "original_name": "11 Backing Vocals.wav",
        "sha256": sha, "role": "backing_vocals", "role_source": "filename_pattern",
        "origin": "native_stem", "linked": True}}], actor="agent", reason="link")
    with pytest.raises(InputError):
        p.asset_path("ast_bv")  # no local location registered yet
    config.set_linked_location(sha, src)
    assert p.asset_path("ast_bv") == src.resolve()
    assert config.get_linked_location(sha) == src.resolve()
    assert (tmp_path / "home" / "settings.json").is_file()
    # the location lives in local settings only, never in the project
    assert str(outside.name) not in (p.root / PROJECT_FILE).read_text(encoding="utf-8")
    # linked assets must use the logical "linked/<name>" path
    p.data["assets"][1]["path"] = "assets/x.wav"
    assert "/assets/1/path" in _paths(p)


def test_rel(populated, tmp_path):
    p = populated
    assert p.rel(p.root / "renders" / "mix.wav") == "renders/mix.wav"
    assert p.rel("reports/report.json") == "reports/report.json"
    assert p.rel(tmp_path / "elsewhere" / "x.wav") == "external/x.wav"
