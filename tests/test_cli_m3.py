"""CLI end-to-end for M3 (SPEC 4.6, 4.7, 6.8, 7.2, 10.2; R-31, D-039).

A synthesized 2mix goes through: objective set (comfort:0.6+bass_heavy:0.4)
-> plan propose -> plan reject / apply (R-31) -> render -> verify -> report
(per-metric breakdown, six decision elements, constraints and gate) -> gate,
get, knowledge. A synthesized reference is registered as a vector only.
Audio is written into tmp folders only.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from mankomix.cli.main import main
from mankomix.core.errors import EXIT_INPUT_ERROR, EXIT_OK

SR = 48000
AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg", ".m4a")


def _mix(seconds: float = 4.0, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-((t % 0.5) * 12.0))
    pad = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 440 * t + 0.3)
    hats = 0.05 * rng.standard_normal(t.size) * np.exp(-((t % 0.25) * 40.0))
    mono = 0.5 * kick + pad + hats
    x = np.stack([mono, 0.95 * mono + 0.02 * rng.standard_normal(t.size)], axis=1)
    x[: int(0.8 * SR)] *= 0.3
    return 0.3 * x / np.max(np.abs(x))


def _reference(seconds: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(11)
    x = rng.standard_normal((int(SR * seconds), 2))
    x = np.cumsum(x, axis=0) * 0.02 + x * 0.3          # bright noise with a low-end tilt
    x -= x.mean(axis=0, keepdims=True)
    return 0.8 * x / np.max(np.abs(x))


def _audio_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXT)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    forbidden = [str(tmp_path), tmp_path.as_posix(), str(Path.home()), Path.home().as_posix()]

    def run(*argv, expect=EXIT_OK):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(a) for a in argv])
        out = buf.getvalue()
        assert code == expect, out
        low = out.lower()
        for f in forbidden:
            assert f.lower() not in low, f"absolute path leaked: {f}"
        return json.loads(out)

    return run


def test_m3_objective_plan_render_report(cli, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    sf.write(str(src / "song_2mix.wav"), _mix(), SR, subtype="FLOAT")
    proj = tmp_path / "song.mmx"
    p = ["-p", str(proj)]

    r = cli("init", str(proj), "--title", "m3 cli", "--project-id", "m3cli")
    assert r["id"] == "prj_m3cli"
    cli(*p, "import", str(src / "song_2mix.wav"))

    # objective (4.7): blend, validated; constraints can never be relaxed
    r = cli(*p, "objective", "set", "comfort:0.6+bass_heavy:0.4")
    assert r["set"] == "project"
    assert [(b["id"], b["weight"]) for b in r["objective"]["blend"]] == [("comfort", 0.6), ("bass_heavy", 0.4)]
    assert cli(*p, "get", "/objective/blend/1/id")["value"] == "bass_heavy"
    bad = tmp_path / "bad_objective.json"
    bad.write_text(json.dumps({"id": "mine", "schema_version": 1, "label": {"ja": "x", "en": "x"}, "kind": "score",
                               "terms": [{"metric": "P-99", "weight": 1.0, "sense": "minimize"}],
                               "params": {"relax_S-01": {"default": 1}}}), encoding="utf-8")
    r = cli("objective", "validate", str(bad), expect=EXIT_INPUT_ERROR)
    msgs = " ".join(i["message"] for i in r["details"]["issues"])
    assert "P-99" in msgs and "cannot be relaxed" in msgs
    assert cli("objective", "validate", '{"blend": [{"id": "clarity", "weight": 1}]}')["valid"] is True

    # propose -> reject (journaled) -> a rejected proposal is not applied -> propose again -> apply
    r = cli(*p, "plan", "propose", "--profile", "spotify", "--delivery", "hires_native", "--max-iter", "1")
    pid = r["proposal_id"]
    assert r["proposal_path"] == f"cache/proposals/{pid}.json" and r["applied"] is False
    assert {t["objective"] for t in r["summary"]["breakdown"]} == {"comfort", "bass_heavy"}
    assert r["proposal"]["operations"] == ["approve_and_apply", "reject_and_request_alternative"]
    r = cli(*p, "plan", "reject", pid, "--reason", "keep more low end")
    assert r["rejected"] is True and r["rejection"]["actor"] == "human" and r["rejection"]["journal_seq"]
    stored = json.loads((proj / f"cache/proposals/{pid}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "rejected" and stored["rejection"]["reason"] == "keep more low end"
    cli(*p, "plan", "apply", pid, expect=EXIT_INPUT_ERROR)
    r = cli(*p, "plan", "propose", "--profile", "spotify", "--delivery", "hires_native", "--max-iter", "1")
    pid = r["proposal_id"]
    r = cli(*p, "plan", "apply", pid)
    assert r["applied"] is True and r["evaluation_stored"] is True and r["decisions_stored"] is True
    variant = r["variant"]
    ev = cli(*p, "get", "/variants/0/evaluation")["value"]
    assert ev["proposal_id"] == pid and ev["terms"] and set(ev["constraints"]) >= {"S-01", "S-03", "S-04"}
    assert ev["score"] == pytest.approx(sum(t["contribution"] for t in ev["terms"] if t["status"] == "measured"))
    ops = [(e["op"], e["actor"]) for e in cli(*p, "history", "--limit", "50")["entries"]]
    assert ("objective_set", "human") in ops and ("plan_reject", "human") in ops and ("master_apply", "human") in ops

    # render -> verify -> report
    cli(*p, "render", variant)
    buf = io.StringIO()
    with redirect_stdout(buf):
        vcode = main([*p, "verify", variant])
    assert vcode in (0, 1) and "passed" in json.loads(buf.getvalue())
    r = cli(*p, "report", variant)
    rep = json.loads((proj / r["paths"]["json"]).read_text(encoding="utf-8"))
    ob = rep["objective_breakdown"]
    assert ob["status"] == "evaluated" and ob["source"] == "stored_proposal" and ob["proposal_id"] == pid
    keys = {(t["objective"], t["key"]) for t in ob["terms"]}
    assert {("comfort", "P-01"), ("comfort", "P-11"), ("bass_heavy", "P-07:sub+bass")} <= keys
    assert all("penalty" in t and "contribution" in t for t in ob["terms"])
    assert set(ob["score_by_objective"]) == {"comfort", "bass_heavy"}
    assert set(rep["decisions"]) == {"balance", "panning", "frequency", "depth", "dynamics", "interest"}
    assert any(d.get("status") == "depends_on_humans_and_references" for d in rep["decisions"]["interest"])
    assert rep["translation_gate"]["status"] == "incomplete"       # 2mix: lead checks need stems
    assert rep["objective_constraints"]["statuses"]["S-01"] == "pass"
    assert rep["measurements"]["objective_metrics"]
    assert any(n["code"] == "generic_prior" for n in rep["notes"])
    assert any(n["code"] == "normalization_tradeoff" for n in rep["notes"])
    md_en = (proj / r["paths"]["md_en"]).read_text(encoding="utf-8")
    md_ja = (proj / r["paths"]["md_ja"]).read_text(encoding="utf-8")
    s5 = md_en.split("## 5. ")[1].split("## 6. ")[0]
    assert "P-07:sub+bass" in s5 and "Contribution" in s5 and "comfort" in s5
    assert "incomplete is never a pass" in md_en.split("## 6. ")[1]
    assert "人間の指示とリファレンスに依存" in md_ja and "D-039" in md_ja

    # gate: incomplete is not a pass (exit 1)
    r = cli(*p, "gate", variant, expect=1)
    assert r["status"] == "incomplete" and r["source"] == "render"
    reasons = {c["id"]: c.get("reason") for c in r["checks"]}
    assert reasons["band_limited_lead_preserved"] == "not_evaluable_without_stems"

    # references: vector only, the audio is never copied (4.6, D-039)
    before = _audio_files(proj)
    refdir = tmp_path / "refs"
    refdir.mkdir()
    sf.write(str(refdir / "my_ref.wav"), _reference(), SR, subtype="PCM_24")
    r = cli(*p, "reference", "add", str(refdir / "my_ref.wav"), "--label", "My ref")
    rid = r["reference"]["id"]
    assert r["added"] is True and r["reference"]["vector"] == f"analysis/ref_{rid}.json"
    assert _audio_files(proj) == before
    assert (proj / "analysis" / f"ref_{rid}.json").is_file()
    lst = cli(*p, "reference", "list")
    assert lst["count"] == 1 and lst["target_source"] == "references"
    rep2 = cli(*p, "report", variant, "--lang", "en", "--no-write")["report"]
    assert any(n["code"] == "references_not_in_evaluation" for n in rep2["notes"])
    r = cli(*p, "reference", "remove", rid)
    assert r["removed"] == rid and r["remaining"] == 0
    assert not (proj / "analysis" / f"ref_{rid}.json").exists()

    # knowledge: the rule index is data
    r = cli("knowledge", "--id", "R-31")
    assert r["entries"][0]["kind"] == "rule" and "approve" in r["entries"][0]["data"]["text"]["en"]
    assert cli("knowledge", "mono", "fold", "--kind", "rule")["count"] >= 1


def test_m3_cli_input_errors(cli, tmp_path):
    proj = tmp_path / "e.mmx"
    cli("init", str(proj), "--title", "errors")
    p = ["-p", str(proj)]
    cli(*p, "objective", "set", "nope:0.5", expect=EXIT_INPUT_ERROR)
    cli(*p, "objective", "set", '{"blend": [{"id": "comfort", "weight": 1}], "overrides": {"comfort": {"S-01": 0}}}',
        expect=EXIT_INPUT_ERROR)
    cli(*p, "plan", "apply", "mpl_missing", expect=EXIT_INPUT_ERROR)
    cli(*p, "plan", "reject", "mpl_missing", "--reason", "x", expect=EXIT_INPUT_ERROR)
    cli(*p, "plan", "propose", "--stage", "mix", expect=EXIT_INPUT_ERROR)
    cli(*p, "reference", "remove", "nope", expect=EXIT_INPUT_ERROR)
    cli(*p, "reference", "add", str(tmp_path / "missing.wav"), expect=EXIT_INPUT_ERROR)
    cli(*p, "get", "/no/such", expect=EXIT_INPUT_ERROR)
    assert cli(*p, "get")["value"]["title"] == "errors"
