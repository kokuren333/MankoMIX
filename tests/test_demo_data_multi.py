"""Numbered project overrides; only synthetic projects are built here."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mankomix.core import api
from tests.fixtures import synth
from .test_demo_data import HAS_MP3, _build, _load, _tool_module, project
from .test_mastering import synth_mix


@pytest.fixture(scope="module")
def other_project(project, tmp_path_factory):
    root = tmp_path_factory.mktemp("demo_multi")
    other = root / "other.mmx"
    api.init_project(str(other), title="Other synthetic project", genre="hiphop")
    # Core import preserves the exact source bytes in a separate project-local file.
    api.import_files(str(other), [str(project.parent / "mix.wav")])
    api.analyze(str(other))
    api.master_plan(str(other), profile="streaming_universal", objective="comfort", apply=True)
    api.render(str(other), "var_streaming_universal")
    api.verify(str(other), "var_streaming_universal")
    api.patch(str(other), [{"op": "add", "path": "/variants/-", "value": {
        "id": "var_cd", "objective": {"blend": [{"id": "comfort", "weight": 1.0}], "intensity": 0.5},
        "master": {"chain": []}, "outputs": [{"profile": "cd", "delivery": "cd_redbook"}]}}],
        reason="unrendered synthetic variant")
    return other


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _project_tree_without_listen(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")
            if p.relative_to(root).as_posix() != "cache/listen"
            and not p.relative_to(root).as_posix().startswith("cache/listen/")}


def test_unrendered_slot_preserves_project_tree_and_index(project, tmp_path, monkeypatch):
    mod = _tool_module()
    unrendered = tmp_path / "unrendered.mmx"
    api.init_project(str(unrendered), title="Unrendered synthetic project", genre="hiphop")
    api.import_files(str(unrendered), [str(project.parent / "mix.wav")])
    api.master_plan(str(unrendered), profile="cd", objective="comfort", apply=True)
    assert not api.variant_list(str(unrendered))["variants"][0]["rendered"]
    before = _project_tree_without_listen(unrendered)
    original = api.audio_set

    def audio_set(path, *args, **kwargs):
        assert Path(path) != unrendered, "unrendered slots must not call audio_set"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(api, "audio_set", audio_set)
    # The legacy no-override path supplies the unchanged unavailable index fields.
    baseline = mod.Builder(unrendered, tmp_path / "baseline", mod.DEFAULT_SAMPLE_SET, None)
    baseline.build()
    expected = copy.deepcopy(baseline.files["index.json"]["variants"][7])
    expected["source"] = {k: baseline.files["index.json"]["source"][k]
                          for k in ("project_id", "content_hash")}
    builder = mod.Builder(project, tmp_path / "out", mod.DEFAULT_SAMPLE_SET, None,
                          slots={8: unrendered})
    builder.build()
    assert _project_tree_without_listen(unrendered) == before
    assert _load(builder.out, "index.json")["variants"][7] == expected
    assert expected["unavailable_reason"] == "not_rendered"
    assert not (builder.out / "variants/v08").exists()


def test_available_slot_preserves_project_tree_outside_listen(project, tmp_path):
    mod = _tool_module()
    available = tmp_path / "available.mmx"
    api.init_project(str(available), title="Available synthetic project", genre="hiphop")
    api.import_files(str(available), [str(project.parent / "mix.wav")])
    api.analyze(str(available))
    api.master_plan(str(available), profile="streaming_universal", objective="comfort", apply=True)
    api.render(str(available), "var_streaming_universal")
    api.verify(str(available), "var_streaming_universal")
    before = _project_tree_without_listen(available)
    builder = mod.Builder(project, tmp_path / "out", mod.DEFAULT_SAMPLE_SET, None,
                          slots={1: available})
    builder.build()
    assert _load(builder.out, "index.json")["variants"][0]["available"]
    assert _project_tree_without_listen(available) == before


def test_slot_assignment_and_per_variant_project_history(project, other_project, tmp_path):
    out = tmp_path / "out"
    _build(project, out, "--slot", f"1={other_project / 'project.json'}", "--slot", f"8={other_project}")
    idx = _load(out, "index.json")
    one, cd, club = idx["variants"][0], idx["variants"][7], idx["variants"][8]
    assert one["available"] and club["available"]
    assert "source" not in club and "project" not in club
    assert one["project"] == "variants/v01/project.json"
    assert one["history"] == "variants/v01/history.json"
    assert _load(out, one["project"])["title"] == "Other synthetic project"
    history = _load(out, one["history"])["entries"]
    assert history and all(e["summary"] == (e.get("reason") or e["op"]) for e in history)
    assert one["source"] == {"project_id": api.project_get(str(other_project))["value"]["id"],
                              "content_hash": history[-1]["after_hash"]}
    assert cd["source"] == one["source"]
    assert not cd["available"] and cd["unavailable_reason"] == "not_rendered"
    assert "project" not in cd and "history" not in cd
    assert not (out / "variants/v08").exists()
    assert _load(out, "project.json")["title"] == "Demo data test"
    mod = _tool_module()
    roots = [str(p) for p in (project, other_project, tmp_path)]
    assert not any(mod.find_leaks(_load(out, name), roots) for name in _tree(out) if name.endswith(".json"))


@pytest.mark.parametrize("slot", [2, 6])
def test_slot_missing_variant_fails(project, other_project, tmp_path, slot):
    r = _build(project, tmp_path / "out", "--slot", f"{slot}={other_project}", expect=1)
    assert f"--slot #{slot}" in r.stderr and "found 0" in r.stderr
    assert not (tmp_path / "out").exists()


def test_slot_ambiguous_variant_fails(project, other_project, tmp_path):
    duplicate = tmp_path / "duplicate.mmx"
    api.init_project(str(duplicate), title="Ambiguous synthetic project", genre="hiphop")
    variant = copy.deepcopy(api.project_get(str(other_project))["value"]["variants"][0])
    extra = copy.deepcopy(variant)
    extra["id"] = "duplicate"
    api.patch(str(duplicate), [{"op": "add", "path": "/variants/-", "value": variant},
                               {"op": "add", "path": "/variants/-", "value": extra}],
              reason="two matching synthetic variants")
    r = _build(project, tmp_path / "out", "--slot", f"1={duplicate}", expect=1)
    assert "--slot #1" in r.stderr and "found 2" in r.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("intensity", [None, 0.7])
def test_slot_intensity_must_match(intensity):
    mod = _tool_module()
    entry = {"n": 1, "objective": "comfort", "profile": "club", "intensity": 0.5}
    variant = {"profile": "club", "objective": {"blend": [{"id": "comfort", "weight": 1}]},
               "intensity": intensity}
    with pytest.raises(mod.BuildError, match="found 0"):
        mod.assign_slots([entry], {1: Path("synthetic.mmx")}, lambda p: [variant])


def test_before_sha_shares_distinct_project_files(project, other_project, tmp_path):
    mod = _tool_module()
    # Inspect the real encoder queue in JSON-only environments as well.
    class Encoder:
        info = {"test": True}

        def encode(self, src, dst, gain):
            pass

    encoder = mod.Mp3Encoder(mod.find_ffmpeg(None)) if HAS_MP3 else Encoder()
    builder = mod.Builder(project, tmp_path / "out", mod.DEFAULT_SAMPLE_SET, encoder,
                          slots={1: other_project})
    builder.build()
    one = builder.files["variants/v01/audio.json"]
    club = builder.files["variants/v09/audio.json"]
    assert one["files"]["before"] == club["files"]["before"] == "audio/before.mp3"
    paths = [Path(p) / api.audio_set(str(p), "var_streaming_universal")["files"]["before"]
             for p in (project, other_project)]
    assert paths[0] != paths[1]
    assert len({hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}) == 1
    assert [p for p in builder.audio_jobs if p.startswith("audio/before") and "matched" not in p] == ["audio/before.mp3"]


@pytest.mark.parametrize("name", ["before", "delta", "fullmix_reference", "before_level_matched"])
def test_shared_audio_sha_keeps_first_project_source(project, other_project, tmp_path, name):
    mod = _tool_module()
    builder = mod.Builder(project, tmp_path / "out", None, object(), slots={1: other_project})
    # Reuse core-imported synthetic files: no audio is hand-created or copied here.
    sources = [api.audio_set(str(p), "var_streaming_universal")["files"]["before"]
               for p in (project, other_project)]
    paths = [p / rel for p, rel in zip((project, other_project), sources)]
    assert paths[0] != paths[1] and mod._sha256(paths[0]) == mod._sha256(paths[1])
    dst = f"audio/{name}.mp3"
    gain = -1.0 if name == "before_level_matched" else None
    assert builder._audio(dst, sources[0], gain) == dst
    first = builder.audio_jobs[dst]
    assert builder._audio(dst, sources[1], gain, project=other_project) == dst
    assert builder.audio_jobs == {dst: first}
    assert first == (paths[0], gain)


@pytest.mark.parametrize("name", ["before", "delta", "fullmix_reference", "before_level_matched"])
@pytest.mark.parametrize("mismatch", ["sha", "gain"])
def test_shared_audio_rejects_content_or_gain_mismatch(project, other_project, tmp_path, name, mismatch):
    mod = _tool_module()
    builder = mod.Builder(project, tmp_path / "out", None, object(), slots={1: other_project})
    main = api.audio_set(str(project), "var_streaming_universal")["files"]
    other = api.audio_set(str(other_project), "var_streaming_universal")["files"]
    # The existing rendered master differs from the imported input.
    rel = other["after" if mismatch == "sha" else "before"]
    assert (mod._sha256(project / main["before"]) == mod._sha256(other_project / rel)) == (mismatch == "gain")
    dst = f"audio/{name}.mp3"
    builder._audio(dst, main["before"], -1.0)
    first = builder.audio_jobs[dst]
    with pytest.raises(mod.BuildError, match=f"two different sources for {dst}"):
        builder._audio(dst, rel, -2.0 if mismatch == "gain" else -1.0, project=other_project)
    assert builder.audio_jobs == {dst: first}


def test_variant_audio_does_not_share_distinct_project_sources(project, other_project, tmp_path):
    mod = _tool_module()
    builder = mod.Builder(project, tmp_path / "out", None, object())
    dst = "variants/v01/after.mp3"
    for p in (project, other_project):
        rel = api.audio_set(str(p), "var_streaming_universal")["files"]["before"]
        if p == project:
            builder._audio(dst, rel)
        else:
            with pytest.raises(mod.BuildError, match="two different sources"):
                builder._audio(dst, rel, project=p)


def test_before_sha_mismatch_fails_for_rendered_slot_json_only(project, tmp_path):
    # Unrendered slots are not checked (no audio, and audio_set would write into the project:
    # see test_unrendered_slot_preserves_project_tree_and_index); a rendered slot still is.
    synth.write_wav(tmp_path / "mix.wav", synth_mix(dur=4.0) * 0.5, synth.DEFAULT_SR)
    other = tmp_path / "different.mmx"
    api.init_project(str(other), title="Different before", genre="hiphop")
    api.import_files(str(other), [str(tmp_path / "mix.wav")])
    api.master_plan(str(other), profile="cd", objective="comfort", apply=True)
    vid = api.variant_list(str(other))["variants"][0]["id"]
    api.render(str(other), vid)
    api.verify(str(other), vid)
    assert api.variant_list(str(other))["variants"][0]["rendered"]
    out = tmp_path / "out"
    r = _build(project, out, "--slot", f"8={other}", expect=1)
    assert "before source sha256 differs" in r.stderr
    assert not out.exists()


@pytest.mark.parametrize("assignment", ["bad", "0=x", "1=", "99={project}", "1={project}|1={project}"])
def test_invalid_slot_assignment_fails(project, tmp_path, assignment):
    args = []
    for value in assignment.format(project=project).split("|"):
        args += ["--slot", value]
    r = _build(project, tmp_path / "out", *args, expect=1)
    assert "--slot" in r.stderr and not (tmp_path / "out").exists()


def test_no_slot_output_is_byte_identical(project, tmp_path):
    mod = _tool_module()
    a, b = tmp_path / "cli", tmp_path / "default"
    _build(project, a)
    mod.Builder(project, b, mod.DEFAULT_SAMPLE_SET, None).build()
    assert _tree(a) == _tree(b)
    for item in _load(a, "index.json")["variants"]:
        assert not {"project", "history", "source"}.intersection(item)


def _legacy_probe(mod, out):
    """Fixed core responses isolate byte compatibility from journal timestamps and UUIDs."""
    pv = {"id": "var_test", "objectives": ["comfort"], "profile": "club", "intensity": 0.5,
          "deliveries": ["club"], "rendered": True}
    builder = mod.Builder(Path("fixture.mmx").resolve(), out, None, None)
    builder.api = SimpleNamespace(
        project_get=lambda *a: {"value": {"id": "prj_test", "title": "Legacy fixture", "assets": []}},
        history=lambda *a, **kw: {"entries": [{"op": "init", "after_hash": "fixed_hash"}]},
        objective_list=lambda **kw: {"objectives": []},
        profile_list=lambda **kw: {"profiles": []},
        variant_list=lambda *a: {"variants": [pv]},
        analysis_view=lambda *a: {"schema_version": 1},
        verification_get=lambda *a: {"overall": "pass"},
        audio_set=lambda *a: {"variant": "var_test", "files": {"before": "assets/input.wav",
                             "after": "renders/master.wav"}, "match_gain_db": -1.0, "match_target": "after"},
        report=lambda *a, **kw: {"report": {"language": kw["lang"]}},
        proposal_list=lambda *a: {"proposals": []})
    builder._engine_version = lambda: "fixed_version"
    builder.build()
    tree = _tree(out)
    digest = hashlib.sha256()
    for name, content in sorted(tree.items()):
        if not name.startswith("definitions/"):
            digest.update(name.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def test_no_slot_matches_legacy_byte_snapshot(tmp_path):
    # Captured from the unmodified builder with _legacy_probe's fixed core responses.
    assert _legacy_probe(_tool_module(), tmp_path / "out") == "c01fc7aa979808ac7872a07f228ae4e83d4c0a7a4f99fae567a7f90f30580c8f"


def test_leak_roots_include_all_slot_projects(project, other_project, tmp_path, monkeypatch):
    mod = _tool_module()
    seen = []
    original = mod._local_roots

    def roots(path):
        seen.append(path)
        return original(path)

    monkeypatch.setattr(mod, "_local_roots", roots)
    mod.Builder(project, tmp_path / "out", mod.DEFAULT_SAMPLE_SET, None,
                slots={1: other_project}).build()
    assert {project, other_project} <= set(seen)


class _SyntheticAPI:
    """Use real synthetic core projects, adding a direction marker without DSP work."""
    def __init__(self, directed=None, delivery_sources=False):
        self.directed = directed
        self.delivery_sources = delivery_sources

    def __getattr__(self, name):
        return getattr(api, name)

    def proposal_list(self, path):
        result = copy.deepcopy(api.proposal_list(path))
        if self.directed and Path(path) == self.directed:
            result["proposals"].append({"id": "synthetic_direction", "variant": None, "stage": "mix",
                "steps": [{"processor": {"owner": "director", "move_ref": "dir_synthetic/m01"}}]})
        return result

    def audio_set(self, path, variant):
        result = api.audio_set(path, variant)
        is_main = Path(path) == self.directed and variant == "var_streaming_universal"
        if self.delivery_sources and not is_main and result["files"].get("after"):
            result["files"]["after"] = api.verification_get(path, variant)["outputs"][0]["file"]
        return result


def _builder(mod, project, out, *, directed=None, delivery_sources=False, **kwargs):
    builder = mod.Builder(project, out, kwargs.pop("sample_set", mod.DEFAULT_SAMPLE_SET),
                          kwargs.pop("encoder", None), **kwargs)
    builder.api = _SyntheticAPI(directed, delivery_sources)
    return builder


def test_floor_accepted_contract_and_leak_roots(project, other_project, tmp_path, monkeypatch):
    mod = _tool_module()
    seen = []
    original = mod._local_roots
    monkeypatch.setattr(mod, "_local_roots", lambda p: (seen.append(p) or original(p)))
    b = _builder(mod, project, tmp_path / "out", directed=project, floors={1: other_project})
    b.build()
    audio = b.files["variants/v01/audio.json"]
    core = api.audio_set(str(other_project), "var_streaming_universal")
    assert audio["files"]["floor"] is None
    assert audio["floor"]["project_variant"] == core["variant"]
    assert audio["floor"]["match_gain_db"] == core["match_gain_db"]
    assert audio["floor"]["match_target"] == ("floor" if core["match_target"] == "after" else "before")
    assert audio["floor"]["source_files"] == {k: v for k, v in core["files"].items() if v}
    assert audio["measurements"]["floor"] == audio["floor"]["measurements"] == core["measurements"]["after"]
    assert audio["floor"]["content_hash"]
    assert b.files["index.json"]["variants"][0]["floor"] == {
        "objective": "comfort", "profile": "streaming_universal",
        "project_id": api.project_get(str(other_project))["value"]["id"]}
    assert other_project in seen
    assert not any("floor" in name for name in b.audio_jobs)
    assert "floor" not in b.files["variants/v09/audio.json"]


@pytest.mark.parametrize("failure", ["slot_undirected", "floor_directed", "unrendered", "unverified", "sha"])
def test_floor_rejections(project, other_project, tmp_path, failure):
    mod = _tool_module()
    b = _builder(mod, project, tmp_path / "out", directed=project, floors={1: other_project})
    if failure == "slot_undirected":
        b.api.directed = None
    elif failure == "floor_directed":
        original = b.api.proposal_list
        b.api.proposal_list = lambda path: original(str(project))
    elif failure == "unrendered":
        original = b.api.variant_list
        b.api.variant_list = lambda path: {"variants": [dict(v, rendered=False) for v in original(path)["variants"]]} \
            if Path(path) == other_project else original(path)
    elif failure == "unverified":
        original = b.api.verification_get
        def verification(path, variant):
            if Path(path) == other_project:
                raise api.NotGenerated("synthetic unverified floor")
            return original(path, variant)
        b.api.verification_get = verification
    else:
        # A real, separate synthetic input, imported through core rather than copied audio.
        synth.write_wav(tmp_path / "different.wav", synth_mix(dur=4.0) * 0.25, synth.DEFAULT_SR)
        mismatch = tmp_path / "mismatch.mmx"
        api.init_project(str(mismatch), title="Different input", genre="hiphop")
        api.import_files(str(mismatch), [str(tmp_path / "different.wav")])
        different_before = api.project_get(str(mismatch))["value"]["assets"][0]["path"]
        original = b.api.audio_set
        def audio_set(path, variant):
            result = original(path, variant)
            if Path(path) == other_project:
                # Resolve this project's imported source through the same source guard.
                result["files"]["before"] = "different_source"
            return result
        b.api.audio_set = audio_set
        source = b._source
        b._source = lambda rel, p=None: mismatch / different_before if rel == "different_source" else source(rel, p)
    with pytest.raises(mod.BuildError, match="--floor"):
        b.build()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("after,floor,expected", [
    ((-1.02, "after"), (-1.02, "after"), {"before": 0.0, "floor": -1.02, "after": -1.02}),
    ((-2.0, "before"), (-1.0, "after"), {"before": -2.0, "floor": -3.0, "after": 0.0}),
    ((-1.0, "after"), (-3.0, "before"), {"before": -3.0, "floor": 0.0, "after": -4.0}),
    ((-2.123, "before"), (-3.456, "before"), {"before": -3.46, "floor": 0.0, "after": -1.33}),
])
def test_three_way_gains_arithmetic(after, floor, expected):
    pair = lambda p: {"match_gain_db": p[0], "match_target": p[1]}
    assert _tool_module().three_way_gains(pair(after), pair(floor)) == expected


def _official_fixture(mod, project, tmp_path):
    sample = _load(mod.REPO, "samples/sample_set.json")
    sample["variants"] = [v for v in sample["variants"] if v["n"] in (1, 8, 9)]
    sample["published"] = {"verified": [1, 9], "stopped": [{"n": 8, "at": "master", "rule": "S-08"}]}
    sp = tmp_path / "sample_set.json"
    sp.write_text(json.dumps(sample), encoding="utf-8")
    manifest = {"variants": [], "audio": {}}
    for n, vid in ((1, "var_streaming_universal"), (9, "var_club")):
        audio = api.audio_set(str(project), vid)
        verification = api.verification_get(str(project), vid)
        manifest["variants"].append({"id": f"v{n:02d}",
            "level_match": {"gain_db": audio["match_gain_db"], "target": audio["match_target"]},
            "listening_copy": {"of_master": verification["outputs"][0]["delivery"], "mp3_sha256": "0" * 64}})
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    return sp, mp, sample, manifest


def test_official_json_only_stopped_and_skip_notice(project, tmp_path):
    mod = _tool_module()
    sp, mp, _, _ = _official_fixture(mod, project, tmp_path)
    r = _build(project, tmp_path / "out", "--variants-from", str(sp), "--official-manifest", str(mp))
    assert "skipped (JSON-only" in r.stdout
    stopped = _load(tmp_path / "out", "index.json")["variants"][1]
    assert stopped["stopped"] == {"at": "master", "rule": "S-08"}
    assert not stopped["available"] and stopped["unavailable_reason"] == "not_rendered"
    assert not (tmp_path / "out/variants/v08").exists()


@pytest.mark.parametrize("failure", ["gain", "target", "verified_unavailable", "stopped_available"])
def test_official_strict_failures(project, tmp_path, failure):
    mod = _tool_module()
    sp, mp, sample, manifest = _official_fixture(mod, project, tmp_path)
    if failure == "gain":
        manifest["variants"][0]["level_match"]["gain_db"] -= 1
    elif failure == "target":
        target = manifest["variants"][0]["level_match"]["target"]
        manifest["variants"][0]["level_match"]["target"] = "before" if target == "after" else "after"
    elif failure == "verified_unavailable":
        sample["published"] = {"verified": [8]}
    else:
        sample["published"] = {"stopped": [{"n": 9, "at": "master", "rule": "S-08"}]}
    sp.write_text(json.dumps(sample), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    r = _build(project, tmp_path / "out", "--variants-from", str(sp), "--official-manifest", str(mp), expect=1)
    assert ("level_match mismatch" if failure in ("gain", "target") else "published.") in r.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg + libmp3lame not installed")
def test_official_mp3_regeneration_and_sha_failure(project, tmp_path):
    mod = _tool_module()
    sp, mp, _, manifest = _official_fixture(mod, project, tmp_path)
    encoder = mod.Mp3Encoder(mod.find_ffmpeg(None))
    # Reference hashes are regenerated by the builder from synthetic delivery masters.
    baseline = _builder(mod, project, tmp_path / "baseline", sample_set=sp,
                        encoder=encoder, delivery_sources=True)
    baseline.build()
    for record in manifest["variants"]:
        record["listening_copy"]["mp3_sha256"] = mod._sha256(baseline.out / f"variants/{record['id']}/after.mp3")
    for key, path in baseline.files["variants/v01/audio.json"]["files"].items():
        if path and key != "after":
            manifest["audio"]["level_matched_pair" if "level_matched" in key else key] = {
                "mp3_sha256": mod._sha256(baseline.out / path)}
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    strict = _builder(mod, project, tmp_path / "strict", sample_set=sp, encoder=encoder, official_manifest=mp)
    assert strict.build()["mp3_sha256_verification"] == "passed"
    for rel, (source, _) in strict.audio_jobs.items():
        assert mod._sha256(strict.out / rel) == mod._sha256(baseline.out / rel)
        if rel.endswith("/after.mp3"):
            assert "archive_f32" not in source.name
    manifest["variants"][0]["listening_copy"]["mp3_sha256"] = "0" * 64
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    r = _build(project, tmp_path / "bad", "--variants-from", str(sp), "--official-manifest", str(mp), "--mp3", expect=1)
    assert "MP3 sha256 mismatch" in r.stderr


@pytest.mark.parametrize("bad_floor_gain", [False, True])
def test_official_directed_floor_match_validation(project, other_project, tmp_path, bad_floor_gain):
    mod = _tool_module()
    sp, mp, _, manifest = _official_fixture(mod, project, tmp_path)
    directed = api.audio_set(str(project), "var_streaming_universal")
    floor = api.audio_set(str(other_project), "var_streaming_universal")
    manifest["main_sample"] = {"of": "v01", "level_match": {
        "gain_db": directed["match_gain_db"], "lowered_side": directed["match_target"]}}
    manifest["variants"][0] = _gate2_record(other_project, "var_streaming_universal", "v01")
    manifest["variants"][0]["level_match"]["gain_db"] += 1 if bad_floor_gain else 0
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    b = _builder(mod, project, tmp_path / "out", sample_set=sp, directed=project,
                 floors={1: other_project}, official_manifest=mp)
    if bad_floor_gain:
        with pytest.raises(mod.BuildError, match="v01 floor: level_match mismatch"):
            b.build()
    else:
        b.build()
        assert b.files["variants/v01/audio.json"]["source_files"]["after"] == directed["files"]["after"]
        actual_floor = b.files["variants/v01/audio.json"]["floor"]
        record = manifest["variants"][0]
        assert actual_floor["match_gain_db"] == record["level_match"]["gain_db"]
        assert actual_floor["after_master"] == record["listening_copy"]["of_master"]
        assert actual_floor["core_audio_set"] == {
            "gain_db": floor["match_gain_db"], "target": floor["match_target"],
            "measurements": floor["measurements"]}


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg + libmp3lame not installed")
def test_official_directed_floor_mp3_sources_and_hashes(project, other_project, tmp_path):
    mod = _tool_module()
    sp, mp, _, manifest = _official_fixture(mod, project, tmp_path)
    manifest["variants"][0] = _gate2_record(other_project, "var_streaming_universal", "v01")
    encoder = mod.Mp3Encoder(mod.find_ffmpeg(None))
    # This reference uses archive_f32 for the directed main and delivery for the floor.
    reference = _builder(mod, project, tmp_path / "reference", sample_set=sp, encoder=encoder,
                         directed=project, delivery_sources=True, floors={1: other_project})
    reference.build()
    main_audio = reference.files["variants/v01/audio.json"]
    sha = lambda rel: mod._sha256(reference.out / rel)
    manifest["main_sample"] = {"of": "v01", "level_match": {
        "gain_db": main_audio["match_gain_db"], "lowered_side": main_audio["match_target"]},
        "mp3": {"main": {"sha256": sha(main_audio["files"]["after"])},
                "level_matched": {"sha256": sha(main_audio["files"].get("after_level_matched") or
                                                   main_audio["files"]["before_level_matched"])}}}
    for record in manifest["variants"]:
        path = main_audio["files"]["floor"] if record["id"] == "v01" else f"variants/{record['id']}/after.mp3"
        record["listening_copy"]["mp3_sha256"] = sha(path)
    for key in ("before", "delta", "fullmix_reference"):
        if main_audio["files"].get(key):
            manifest["audio"][key] = {"mp3_sha256": sha(main_audio["files"][key])}
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    strict = _builder(mod, project, tmp_path / "strict", sample_set=sp, encoder=encoder,
                      directed=project, floors={1: other_project}, official_manifest=mp)
    strict.build()
    assert "archive_f32" in strict.audio_jobs["variants/v01/after.mp3"][0].name
    floor_source = strict.audio_jobs["variants/v01/floor.mp3"][0]
    assert other_project in floor_source.parents and "hires_native" in floor_source.name
    assert set(strict.audio_jobs) == set(reference.audio_jobs)
    assert not any("floor_level_matched" in rel for rel in strict.audio_jobs)
    assert all(sha(rel) == mod._sha256(strict.out / rel) for rel in strict.audio_jobs)


@pytest.mark.parametrize("assignment", ["bad", "0=x", "1=", "99={project}", "1={project}|1={project}"])
def test_invalid_floor_assignment_fails(project, tmp_path, assignment):
    args = []
    for value in assignment.format(project=project).split("|"):
        args += ["--floor", value]
    r = _build(project, tmp_path / "out", *args, expect=1)
    assert "--floor" in r.stderr and not (tmp_path / "out").exists()


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg + libmp3lame not installed")
def test_official_cd_redbook_master_selection(project, tmp_path):
    mod = _tool_module()
    cd = tmp_path / "cd.mmx"
    api.init_project(str(cd), title="Synthetic CD", genre="hiphop")
    api.import_files(str(cd), [str(project.parent / "mix.wav")])
    api.analyze(str(cd))
    api.master_plan(str(cd), profile="cd", objective="comfort", apply=True)
    api.render(str(cd), "var_cd")
    api.verify(str(cd), "var_cd")
    sample = _load(mod.REPO, "samples/sample_set.json")
    sample["variants"] = [v for v in sample["variants"] if v["n"] == 8]
    sample["published"] = {"verified": [8]}
    sp = tmp_path / "sample_set.json"
    sp.write_text(json.dumps(sample), encoding="utf-8")
    encoder = mod.Mp3Encoder(mod.find_ffmpeg(None))
    reference = _builder(mod, cd, tmp_path / "reference", sample_set=sp, encoder=encoder, delivery_sources=True)
    reference.build()
    audio = reference.files["variants/v08/audio.json"]
    record = _gate2_record(cd, "var_cd", "v08")
    record["listening_copy"]["mp3_sha256"] = mod._sha256(reference.out / audio["files"]["after"])
    manifest = {"variants": [record],
        "audio": {"before": {"mp3_sha256": mod._sha256(reference.out / audio["files"]["before"])}}}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    b = _builder(mod, cd, tmp_path / "strict", sample_set=sp, encoder=encoder, official_manifest=mp)
    b.build()
    source = b.audio_jobs["variants/v08/after.mp3"][0]
    import soundfile as sf
    assert "cd_redbook" in source.name and sf.info(source).samplerate == 44100
    assert mod._sha256(b.out / "variants/v08/after.mp3") == manifest["variants"][0]["listening_copy"]["mp3_sha256"]
    actual = b.files["variants/v08/audio.json"]
    core = api.audio_set(str(cd), "var_cd")
    assert mod._sha256(source) == record["masters"][0]["sha256"]
    assert actual["match_gain_db"] == record["level_match"]["gain_db"] != core["match_gain_db"]
    assert actual["match_target"] == record["level_match"]["target"]
    assert actual["measurements"]["after"] == {k: record["masters"][0]["measured"][k]
                                              for k in ("lufs_i", "true_peak_dbtp")}
    assert actual["after_master"] == "cd_redbook"
    assert actual["core_audio_set"] == {"gain_db": core["match_gain_db"], "target": core["match_target"],
                                        "measurements": core["measurements"]}


def _gate2_record(project, variant, vid):
    from tools.build_samples import level_match, proxies
    audio = api.audio_set(str(project), variant)
    output = api.verification_get(str(project), variant)["outputs"][0]
    measured = proxies(api.measure_audio(str(project / output["file"]))["vector"])
    before = proxies(api.measure_audio(str(project / audio["files"]["before"]))["vector"])
    return {"id": vid, "masters": [{"delivery": output["delivery"],
            "sha256": hashlib.sha256((project / output["file"]).read_bytes()).hexdigest(),
            "measured": measured}],
        "level_match": {**level_match(before["lufs_i"], measured["lufs_i"]),
                        "core_audio_set": {"gain_db": audio["match_gain_db"], "target": audio["match_target"]}},
        "listening_copy": {"of_master": output["delivery"], "mp3_sha256": "0" * 64}}


@pytest.fixture(scope="module")
def gate2_cd(project, tmp_path_factory):
    cd = tmp_path_factory.mktemp("gate2_cd") / "cd.mmx"
    api.init_project(str(cd), title="Gate 2 synthetic CD", genre="hiphop")
    api.import_files(str(cd), [str(project.parent / "mix.wav")])
    api.analyze(str(cd))
    api.master_plan(str(cd), profile="cd", objective="comfort", apply=True)
    api.render(str(cd), "var_cd")
    api.verify(str(cd), "var_cd")
    return cd


def _gate2_builder(cd, tmp_path, encoder=None):
    mod = _tool_module()
    sample = _load(mod.REPO, "samples/sample_set.json")
    sample["variants"] = [v for v in sample["variants"] if v["n"] == 8]
    sample["published"] = {"verified": [8]}
    sp, mp = tmp_path / "sample.json", tmp_path / "manifest.json"
    sp.write_text(json.dumps(sample), encoding="utf-8")
    record = _gate2_record(cd, "var_cd", "v08")
    manifest = {"variants": [record]}
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    b = _builder(mod, cd, tmp_path / "out", sample_set=sp, official_manifest=mp, encoder=encoder)
    return b, record


def test_official_listening_master_values_and_core_provenance(gate2_cd, tmp_path):
    b, record = _gate2_builder(gate2_cd, tmp_path)
    core = api.audio_set(str(gate2_cd), "var_cd")
    assert record["level_match"]["gain_db"] != core["match_gain_db"]
    b.build()
    audio = b.files["variants/v08/audio.json"]
    assert audio["match_gain_db"] == record["level_match"]["gain_db"]
    assert audio["match_target"] == record["level_match"]["target"]
    assert audio["after_master"] == "cd_redbook"
    assert audio["measurements"]["after"] == {k: record["masters"][0]["measured"][k]
                                              for k in ("lufs_i", "true_peak_dbtp")}
    assert audio["measurements"]["after"] != core["measurements"]["after"]
    assert audio["core_audio_set"] == {"gain_db": core["match_gain_db"], "target": core["match_target"],
                                        "measurements": core["measurements"]}
    assert audio["files"]["after"] is None


@pytest.mark.parametrize("failure,error", [
    ("gain", "level_match mismatch"), ("target", "level_match mismatch"),
    ("core_gain", "core_audio_set: level_match mismatch"),
    ("core_target", "core_audio_set: level_match mismatch"),
    ("after_lufs", "after LUFS/TP mismatch"), ("after_tp", "after LUFS/TP mismatch"),
    ("master_sha", "master sha256 mismatch"),
    ("before_lufs", "before measurements mismatch"), ("before_tp", "before measurements mismatch"),
    ("missing_masters", "expected one of_master"),
    ("missing_core", "core_audio_set: level_match mismatch"),
])
def test_official_listening_master_mismatches_fail(gate2_cd, tmp_path, failure, error):
    b, record = _gate2_builder(gate2_cd, tmp_path)
    lm = record["level_match"]
    if failure == "gain":
        lm["gain_db"] -= 0.01
    elif failure == "target":
        lm["target"] = "before" if lm["target"] == "after" else "after"
    elif failure == "core_gain":
        lm["core_audio_set"]["gain_db"] -= 0.01
    elif failure == "core_target":
        core = lm["core_audio_set"]
        core["target"] = "before" if core["target"] == "after" else "after"
    elif failure.startswith("after_"):
        record["masters"][0]["measured"]["lufs_i" if failure == "after_lufs" else "true_peak_dbtp"] += 0.01
    elif failure == "master_sha":
        record["masters"][0]["sha256"] = "0" * 64
    elif failure.startswith("before_"):
        original = b.api.audio_set
        def audio_set(*args):
            a = copy.deepcopy(original(*args))
            a["measurements"]["before"]["lufs_i" if failure == "before_lufs" else "true_peak_dbtp"] += 0.01
            return a
        b.api.audio_set = audio_set
    elif failure == "missing_masters":
        del record["masters"]
    else:
        del lm["core_audio_set"]
    b.official["variants"][0] = record
    with pytest.raises(b.build.__globals__["BuildError"], match=error):
        b.build()
    assert not b.out.exists()


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg + libmp3lame not installed")
def test_official_measures_exact_encoding_master(gate2_cd, tmp_path):
    mod = _tool_module()
    encoder = mod.Mp3Encoder(mod.find_ffmpeg(None))
    reference = _builder(mod, gate2_cd, tmp_path / "reference", sample_set=None,
                         encoder=encoder, delivery_sources=True)
    reference.build()
    b, record = _gate2_builder(gate2_cd, tmp_path, encoder)
    main = reference.files["variants/v01/audio.json"]["files"]
    record["listening_copy"]["mp3_sha256"] = mod._sha256(reference.out / main["after"])
    b.official["variants"][0] = record
    b.official["audio"] = {key: {"mp3_sha256": mod._sha256(reference.out / main[key])}
                           for key in ("before", "fullmix_reference") if main.get(key)}
    measured = []
    original = b.api.measure_audio
    b.api.measure_audio = lambda path: (measured.append(Path(path)) or original(path))
    b.build()
    source, gain = b.audio_jobs["variants/v08/after.mp3"]
    assert source in measured and gain is None and "cd_redbook" in source.name
    assert mod._sha256(source) == record["masters"][0]["sha256"]
    assert mod._sha256(b.out / "variants/v08/after.mp3") == record["listening_copy"]["mp3_sha256"]


def test_official_floor_provenance_and_three_way_inputs(project, other_project, tmp_path, monkeypatch):
    mod = _tool_module()
    sp, mp, _, manifest = _official_fixture(mod, project, tmp_path)
    manifest["variants"] = [_gate2_record(other_project, "var_streaming_universal", "v01"),
                            _gate2_record(project, "var_club", "v09")]
    main = api.audio_set(str(project), "var_streaming_universal")
    manifest["main_sample"] = {"of": "v01", "level_match": {
        "gain_db": main["match_gain_db"], "lowered_side": main["match_target"]}}
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    pairs = []
    original = mod.three_way_gains
    monkeypatch.setattr(mod, "three_way_gains", lambda a, f: (pairs.append((a, f)) or original(a, f)))
    b = _builder(mod, project, tmp_path / "out", sample_set=sp, directed=project,
                 floors={1: other_project}, official_manifest=mp)
    b.build()
    a = b.files["variants/v01/audio.json"]
    floor = a["floor"]
    assert floor["after_master"] == "hires_native"
    assert a["measurements"]["floor"] == floor["measurements"]
    assert floor["core_audio_set"]["measurements"] == api.audio_set(str(other_project), "var_streaming_universal")["measurements"]
    assert pairs[0][0] == main
    assert pairs[0][1]["measurements"] == floor["measurements"]
    assert pairs[0][1]["match_target"] == ("after" if floor["match_target"] == "floor" else "before")
    assert a["level_match_gains_db"] == original(*pairs[0])
    assert "core_audio_set" not in a and "after_master" not in a
    assert a["measurements"]["after"] == main["measurements"]["after"]


def test_official_non_v08_pair_difference_requires_pm(gate2_cd, tmp_path):
    b, record = _gate2_builder(gate2_cd, tmp_path)
    audio = api.audio_set(str(gate2_cd), "var_cd")
    verification = api.verification_get(str(gate2_cd), "var_cd")
    master = verification["outputs"][0]["file"]
    with pytest.raises(b.build.__globals__["BuildError"], match="PM review required"):
        b._listening_values("v07", audio, record, gate2_cd, master, "v07")
