"""X-11 listening packs, recorded conditions and independence of existing checks."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil

import numpy as np
import pytest

from mankomix import repo_data_root
from mankomix.cli import main as CLI
from mankomix.core import audio_io
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.hashing import canonical_hash
from mankomix.core.project import Project
from mankomix.director import direction as D
from mankomix.director import kb
from mankomix.director import listen as L
from mankomix.director import query as Q
from tests import test_direction_update as T
from tests import test_director as TD

SR = 24000
DID = "dir_0123456789ab"
MEMBERS = {"result", "floor", "raw_gain_only"}


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _tree(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


@pytest.fixture
def projects(tmp_path):
    # Use FileAdapter's imported assets, as in existing synthetic project tests.
    t = np.arange(3 * SR) / SR
    voice = .06 * np.sin(2 * np.pi * 440 * t) * ((t >= .5) & (t < 2.5))
    bass = .04 * np.sin(2 * np.pi * 110 * t)
    raw = np.column_stack((voice + bass, voice + bass))
    source = tmp_path / "source"
    for name, signal in (("vocals", voice), ("bass", bass)):
        audio_io.write(source / f"{name}.wav", np.column_stack((signal, signal)), SR, subtype="DOUBLE")
    p = Project.create(tmp_path / "result", title="synthetic listening")
    FileAdapter().fetch(source, p, actor="human")
    p.set("/mix/applied", {"proposal_id": "mxp_listen"}, actor="human")
    p.set("/variants", [{"id": "var_x", "master": {"chain": []}, "outputs": []}], actor="human")
    tracks = copy.deepcopy(p.data["tracks"])
    for track in tracks:
        track["gain_db"] = -14.
        for clip in track["clips"]:
            clip.update(muted=True, gain_db=-12.)
    p.set("/tracks", tracks, actor="human")
    _json(p.root / "cache/proposals/mxp_listen.json", {
        "direction": {"id": DID},
        "sections": [{"id": "sec_secret", "label": "hidden_section", "start_s": 0., "end_s": 1.5}]})
    audio_io.write(p.root / "renders/var_x/main__hires_native.wav", raw * .5, SR, subtype="DOUBLE")
    floor = tmp_path / "floor"
    shutil.copytree(p.root, floor)
    audio_io.write(floor / "renders/var_x/main__hires_native.wav", raw * .25, SR, subtype="DOUBLE")
    return p.root, floor, raw


@pytest.mark.parametrize("mode", ["integrated", "section", "lead"])
def test_pack_anonymous_matched_deterministic_and_read_only(projects, tmp_path, mode):
    root, floor, raw = projects
    before = _tree(root), _tree(floor)
    opts = dict(sections=["sec_secret"], excerpts=[(1.5, 3)], match=mode)
    a, b = tmp_path / "pack_a", tmp_path / "pack_b"
    result = L.listen_pack(root, floor, out=a, **opts)
    again = L.listen_pack(root, floor, out=b, **opts)
    assert result == again
    assert result["files"] == sorted(result["files"])
    assert result["files"] == sorted(_tree(a)) == sorted(_tree(b))
    for name in result["files"]:
        assert (a / name).read_bytes() == (b / name).read_bytes()
    key = json.loads((a / "key/key.json").read_text(encoding="utf-8"))
    assert result["key"] == key
    assert key["kind"] == "direction_listen_key" and key["schema_version"] == 1
    assert key["identity"] == DID and key["match"] == mode
    assert len(key["files"]) == 6
    groups = {}
    for name, entry in key["files"].items():
        assert not any(s in name for s in (*MEMBERS, "raw", "sec_secret", "hidden_section"))
        assert entry["member"] in MEMBERS and entry["match"] == mode
        assert entry["gain_db"] <= 0
        ex = entry["excerpt"]
        start, end = ex["start_sample"], ex["end_sample"]
        assert (ex["t0_s"], ex["t1_s"]) == (start / SR, end / SR)
        audio, rate = audio_io.read(a / name)
        assert rate == SR and len(audio) == end - start
        assert audio_io.info(a / name).subtype == "PCM_24"
        scale = {"result": .5, "floor": .25, "raw_gain_only": 1.}[entry["member"]]
        expected = raw[start:end] * scale * 10 ** (entry["gain_db"] / 20)
        assert np.max(np.abs(audio - expected)) < 2 ** -23
        groups.setdefault((start, end), []).append((entry, Q.integrated_lufs(audio, SR)))
    assert set(groups) == {(0, 36000), (36000, 72000)}
    for values in groups.values():
        assert {e["member"] for e, _ in values} == MEMBERS
        assert max(v for _, v in values) - min(v for _, v in values) < .1
        assert max(e["gain_db"] for e, _ in values) == 0
        assert next(e["gain_db"] for e, _ in values if e["member"] == "floor") == 0
        assert min(e["gain_db"] for e, _ in values) == pytest.approx(-12.041, abs=.002)
    template = json.loads((a / "answers.template.json").read_text(encoding="utf-8"))
    assert set(template) == {"date", "playback", "conditions", "judgments"}
    assert template["date"] == template["playback"] == ""
    assert template["conditions"] == {"level_match": mode, "blind": True, "members": list(L.MEMBERS)}
    assert {j["axis"] for j in template["judgments"]} == {"audible", "preference", "fits_request"}
    for judgment in template["judgments"]:
        assert judgment == {"axis": judgment["axis"], "pair": ["", ""], "answer": "", "note": ""}
    sheet = (a / "sheet.md").read_text(encoding="utf-8")
    for label in ("違いが分かるか", "どちらが好きか", "依頼に合うか", "聴いた日", "再生環境"):
        assert label in sheet
    assert all(name in sheet for name in key["files"])
    assert not any(s in sheet for s in (*MEMBERS, "sec_secret", "hidden_section", DID))
    if mode == "lead":
        assert key["lead_activity"]["track"] == "trk_vocals"
    assert before == (_tree(root), _tree(floor))


def test_seed_depends_on_direction_and_excerpt(projects, tmp_path):
    root, floor, _ = projects

    def order(out, excerpt):
        key = L.listen_pack(root, floor, out=out, excerpts=[excerpt])["key"]
        return [e["member"] for _, e in sorted(key["files"].items())]

    initial = order(tmp_path / "initial", (0, 1.5))
    # There are only six permutations; test several inputs, not one collision-prone pair.
    assert any(order(tmp_path / f"excerpt{i}", (i / 10, 1.5 + i / 10)) != initial for i in range(1, 9))
    proposal = root / "cache/proposals/mxp_listen.json"
    value = json.loads(proposal.read_text(encoding="utf-8"))
    orders = []
    for i in range(8):
        value["direction"]["id"] = f"dir_{i:012x}"
        _json(proposal, value)
        orders.append(order(tmp_path / f"direction{i}", (0, 1.5)))
    assert any(o != initial for o in orders)


def test_match_modes_use_whole_section_or_active_lead_audio(projects, tmp_path):
    root, floor, raw = projects
    t = np.arange(len(raw)) / SR
    # Add sound well outside the lead's active windows; change the two halves independently.
    extra = .3 * np.sin(2 * np.pi * 1000 * t) * ((t < .3) | (t >= 2.7))
    result = raw * np.where(t < 1.5, .5, .75)[:, None] + extra[:, None]
    audio_io.write(root / "renders/var_x/main__hires_native.wav", result, SR, subtype="DOUBLE")
    signals = {"result": result, "floor": raw * .25, "raw_gain_only": raw}
    before = _tree(root), _tree(floor)
    result_gains = {}
    for mode in ("integrated", "section", "lead"):
        out = tmp_path / mode
        pack = L.listen_pack(root, floor, out=out, excerpts=[(0, 1.5), (1.5, 3)], match=mode)
        groups = {}
        for name, entry in pack["key"]["files"].items():
            start, end = entry["excerpt"]["start_sample"], entry["excerpt"]["end_sample"]
            if mode == "integrated":
                a, b = 0, len(raw)
            elif mode == "lead":
                # 50 ms windows every 10 ms overlap the known [.5, 2.5) voice activity.
                a, b = max(start, int(.46 * SR)), min(end, int(2.54 * SR))
            else:
                a, b = start, end
            levels = {member: Q.integrated_lufs(x[a:b], SR) for member, x in signals.items()}
            expected_gain = min(levels.values()) - levels[entry["member"]]
            assert entry["gain_db"] == pytest.approx(expected_gain, abs=.002)
            assert entry["loudness_lufs"] == pytest.approx(levels[entry["member"]], abs=.002)
            audio, _ = audio_io.read(out / name)
            if mode != "integrated":
                measured = Q.integrated_lufs(audio[a - start:b - start], SR)
                groups.setdefault(start, []).append(measured)
            if entry["member"] == "result":
                result_gains.setdefault(mode, {})[start] = entry["gain_db"]
        assert all(max(v) - min(v) < .1 for v in groups.values())
        if mode == "integrated":
            levels = []
            for member in MEMBERS:
                chunks = [audio_io.read(out / name)[0] for name, entry in sorted(
                    pack["key"]["files"].items(), key=lambda item: item[1]["excerpt"]["start_sample"])
                    if entry["member"] == member]
                levels.append(Q.integrated_lufs(np.concatenate(chunks), SR))
            assert max(levels) - min(levels) < .1
    assert len(set(result_gains["integrated"].values())) == 1
    assert result_gains["section"][0] != result_gains["section"][36000]
    assert result_gains["lead"][0] == pytest.approx(-6.021, abs=.002)
    assert result_gains["lead"][36000] == pytest.approx(-9.542, abs=.002)
    assert result_gains["section"] != result_gains["lead"]
    assert before == (_tree(root), _tree(floor))


@pytest.mark.parametrize("target", ["project", "floor", "kb", "private_kb", "custom_kb", "nonempty"])
def test_g5_rejects_before_writing(projects, tmp_path, monkeypatch, target):
    root, floor, _ = projects
    paths = {"project": root / "forbidden", "floor": floor / "forbidden",
             "kb": repo_data_root() / "kb/fb2_forbidden_export",
             "private_kb": repo_data_root() / "_private/kb/fb2_forbidden_export",
             "custom_kb": tmp_path / "custom_kb/forbidden", "nonempty": tmp_path / "existing"}
    out = paths[target]
    if target == "nonempty":
        out.mkdir()
        (out / "keep.txt").write_bytes(b"keep")
    before = _tree(root), _tree(floor), _tree(out)
    writes = []
    monkeypatch.setattr(L.audio_io, "write", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(D.DirectionError):
        L.listen_pack(root, floor, out=out, excerpts=[(0, 1)], kb_roots=[tmp_path / "custom_kb"])
    assert writes == []
    assert before == (_tree(root), _tree(floor), _tree(out))
    assert out.is_dir() if target == "nonempty" else not out.exists()


def _session(day="2026-11-20"):
    return {"date": day, "playback": "test playback",
            "conditions": {"level_match": "integrated", "blind": True, "members": list(L.MEMBERS)},
            "judgments": [{"axis": axis, "pair": ["result", "floor"], "answer": "floor", "note": ""}
                          for axis in ("audible", "preference", "fits_request")]}


@pytest.fixture
def record_project(tmp_path):
    root = tmp_path / "record_project"
    _json(root / "project.json", {"variants": [{"id": "var_x", "master": {"chain": []}}]})
    _json(root / f"directions/{DID}.outcome.json", {
        "direction": DID, "variant": "var_x", "status": "checked", "summary": {"claims_met": 0}})
    return root


@pytest.mark.parametrize("case", ["unknown", "conditions_unknown", "judgment_unknown", "grade",
                                  "conditions_grade", "judgment_grade", "short_date", "invalid_date",
                                  "axis", "answer", "third_member_answer", "level_match", "blind", "member"])
def test_record_rejects_invalid_answers_without_writes(record_project, case):
    answer = _session()
    if case == "unknown":
        answer["extra"] = True
    elif case == "conditions_unknown":
        answer["conditions"]["extra"] = True
    elif case == "judgment_unknown":
        answer["judgments"][0]["extra"] = True
    elif case == "grade":
        answer["grade"] = "adoption"
    elif case == "conditions_grade":
        answer["conditions"]["grade"] = "adoption"
    elif case == "judgment_grade":
        answer["judgments"][0]["grade"] = "adoption"
    elif case in ("short_date", "invalid_date"):
        answer["date"] = "2026-1-2" if case == "short_date" else "2026-02-30"
    elif case in ("axis", "answer", "third_member_answer"):
        key = "axis" if case == "axis" else "answer"
        answer["judgments"][0][key] = "raw_gain_only" if case == "third_member_answer" else "invalid"
    elif case == "level_match":
        answer["conditions"]["level_match"] = "invalid"
    elif case == "blind":
        answer["conditions"]["blind"] = "true"
    else:
        answer["conditions"]["members"] = ["unknown"]
    before = _tree(record_project)
    with pytest.raises(D.DirectionError):
        L.listen_record(record_project, DID, answer)
    assert _tree(record_project) == before


def test_record_requires_outcome(record_project):
    (record_project / f"directions/{DID}.outcome.json").unlink()
    before = _tree(record_project)
    with pytest.raises(D.DirectionError):
        L.listen_record(record_project, DID, _session())
    assert _tree(record_project) == before


@pytest.mark.parametrize("case", ["qualified", "qualified_section", "qualified_lead", "one", "same_date", "none", "not_blind", "no_raw"])
def test_grade_from_all_recorded_conditions(record_project, case):
    first, second = _session(), _session("2026-11-21")
    if case.startswith("qualified_"):
        second["conditions"]["level_match"] = case.removeprefix("qualified_")
    if case == "same_date":
        second["date"] = first["date"]
    elif case == "none":
        second["conditions"]["level_match"] = "none"
    elif case == "not_blind":
        second["conditions"]["blind"] = False
    elif case == "no_raw":
        second["conditions"]["members"].remove("raw_gain_only")
    outcome = record_project / f"directions/{DID}.outcome.json"
    before = outcome.read_bytes()
    record = L.listen_record(record_project, DID, first)
    assert record["grade"] == "trial"
    if case != "one":
        record = L.listen_record(record_project, DID, second)
    assert record["grade"] == ("adoption" if case.startswith("qualified") else "trial")
    assert record["sessions"] == ([first] if case == "one" else [first, second])
    assert outcome.read_bytes() == before
    assert json.loads((record_project / f"directions/{DID}.listening.json").read_text(encoding="utf-8")) == record


@pytest.mark.parametrize("source", ["missing", "reports", "evaluation"])
def test_conformance_copies_saved_machine_results(record_project, source):
    # O-9: verify/gate come from existing reports, with null for unrecorded results.
    if source == "reports":
        _json(record_project / "reports/verify_var_x.json", {"variant": "var_x", "overall": "fail"})
        _json(record_project / "reports/report_var_x.json", {
            "variant": "var_x", "translation_gate": {"status": "hold"}})
    elif source == "evaluation":
        _json(record_project / "project.json", {"variants": [{"id": "var_x", "master": {"chain": []},
              "evaluation": {"chain_hash": canonical_hash([]), "gate": {"status": "hold"}}}]})
    before = _tree(record_project)
    answer = _session()
    original = copy.deepcopy(answer)
    record = L.listen_record(record_project, DID, answer)
    assert answer == original
    assert record["kind"] == "direction_listening" and record["schema_version"] == 1
    assert record["direction"] == DID
    assert record["conformance"] == {"source": f"{DID}.outcome.json", "outcome_status": "checked",
        "outcome_summary": {"claims_met": 0}, "verify": "fail" if source == "reports" else None,
        "gate": None if source == "missing" else "hold"}
    after = _tree(record_project)
    assert {k: v for k, v in after.items() if k != f"directions/{DID}.listening.json"} == before


@pytest.mark.parametrize("answer_value", ["result", "floor", "none", "unsure"])
def test_record_accepts_answer_enumeration_and_is_deterministic(record_project, tmp_path, answer_value):
    twin = tmp_path / "twin"
    shutil.copytree(record_project, twin)
    answer = _session()
    for judgment in answer["judgments"]:
        judgment["answer"] = answer_value
    for project in (record_project, twin):
        first = L.listen_record(project, DID, answer)
        second = L.listen_record(project, DID, answer)
        assert first["grade"] == second["grade"] == "trial"
        assert second["sessions"] == [answer, answer]
    name = f"directions/{DID}.listening.json"
    assert (record_project / name).read_bytes() == (twin / name).read_bytes()


@pytest.fixture
def cli(capsys):
    def run(*args):
        code = CLI.main([str(a) for a in args])
        captured = capsys.readouterr()
        assert captured.err == ""
        return code, json.loads(captured.out), captured.out
    return run


@pytest.mark.parametrize("mode", ["integrated", "section", "lead"])
def test_cli_pack_json_and_blind_stdout(projects, tmp_path, mode, cli):
    root, floor, _ = projects
    before = _tree(root), _tree(floor)
    out = tmp_path / "cli_pack"
    code, data, stdout = cli("direction", "listen", "pack", "--project", root, "--floor", floor,
        "--section", "sec_secret", "--excerpt", "1.5,3", "--out", out, "--match", mode)
    assert code == 0
    assert set(data) == {"kind", "files", "key_path"}
    assert data["kind"] == "direction_listen_pack" and data["key_path"] == "key/key.json"
    assert data["files"] == sorted(_tree(out)) and len(data["files"]) == 9
    assert not any(s in stdout for s in (*MEMBERS, "sec_secret", "hidden_section", DID))
    assert before == (_tree(root), _tree(floor))


@pytest.mark.parametrize("case", ["project", "kb", "private_kb", "custom_kb", "nonempty", "bad_excerpt"])
def test_cli_pack_input_errors(projects, tmp_path, case, cli):
    root, floor, _ = projects
    out = {"project": root / "forbidden", "kb": repo_data_root() / "kb/fb2_forbidden_export",
        "private_kb": repo_data_root() / "_private/kb/fb2_forbidden_export",
        "custom_kb": tmp_path / "custom_kb/forbidden"}.get(case, tmp_path / "rejected")
    if case == "nonempty":
        out.mkdir()
        (out / "keep.txt").write_bytes(b"keep")
    before = _tree(root), _tree(floor), _tree(out)
    code, data, _ = cli("direction", "listen", "pack", "--project", root, "--floor", floor,
        "--out", out, "--kb", tmp_path / "custom_kb", "--excerpt", "invalid" if case == "bad_excerpt" else "0,1")
    assert code == 2 and data["error"] == "input_error"
    assert isinstance(data["message"], str)
    assert before == (_tree(root), _tree(floor), _tree(out))
    assert out.exists() if case == "nonempty" else not out.exists()


@pytest.mark.parametrize("case", ["valid", "grade", "missing_outcome", "bad_json"])
def test_cli_record_exit_and_json(record_project, tmp_path, cli, case):
    answer = _session()
    if case == "grade":
        answer["grade"] = "adoption"
    if case == "missing_outcome":
        (record_project / f"directions/{DID}.outcome.json").unlink()
    path = tmp_path / "answers.json"
    _json(path, answer)
    if case == "bad_json":
        path.write_text("{", encoding="utf-8")
    before = _tree(record_project)
    code, data, _ = cli("direction", "listen", "record", "--project", record_project,
                         "--direction", DID, "--from", path)
    if case == "valid":
        assert code == 0 and data["kind"] == "direction_listening" and data["grade"] == "trial"
        assert data["sessions"] == [answer] and isinstance(data["conformance"], dict)
        assert json.loads((record_project / f"directions/{DID}.listening.json").read_text(encoding="utf-8")) == data
    else:
        assert code == 2 and data["error"] == "input_error"
        assert _tree(record_project) == before


def test_validate_check_and_kb_lint_ignore_listening_records(projects, tmp_path):
    root, floor, _ = projects
    # Existing minimal direction helper uses master-only observations, avoiding rendering.
    doc_path = T._write_doc(tmp_path, TD._block())
    doc = D.parse_document(doc_path)
    valid_before = json.dumps(D.validate(doc, root), ensure_ascii=False)
    check_before = json.dumps(D.check(root, floor, doc_path), ensure_ascii=False)
    assert json.loads(valid_before)["ok"]
    assert json.loads(check_before)["status"] == "checked"
    outcome = root / f"directions/{doc['id']}.outcome.json"
    outcome_before = outcome.read_bytes()
    library = tmp_path / "library"
    _json(library / "songs/s/placeholder.json", {})
    kb.write_index(library)
    lint_before = json.dumps(kb.lint(library), ensure_ascii=False)
    assert json.loads(lint_before)["ok"]
    L.listen_record(root, doc["id"], _session())
    record = root / f"directions/{doc['id']}.listening.json"
    assert record.exists()
    shutil.copyfile(record, library / "songs/s" / record.name)
    assert json.dumps(D.validate(doc, root), ensure_ascii=False) == valid_before
    assert json.dumps(D.check(root, floor, doc_path), ensure_ascii=False) == check_before
    assert outcome.read_bytes() == outcome_before
    assert json.dumps(kb.lint(library), ensure_ascii=False) == lint_before
