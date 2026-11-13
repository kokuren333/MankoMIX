"""Mix-stage planner (core/mixplan.py; SPEC 6.5, 6.6.1, 6.8, 7.2; R-04..R-13, R-22, R-25, R-28, R-29, R-31).

One plan of the 8 s synthetic twelve-stem song (tests/fixtures/synth.py
song_stems) is shared by most tests; the R-22 and determinism checks use
smaller stem sets so the file stays well under a minute and a half.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pytest

from mankomix.core import config, journal, mixplan
from mankomix.core import mixrender as mr
from mankomix.core import objectives as O
from mankomix.core.adapters.file import FileAdapter
from mankomix.core.analysis.perceptual import sibilance
from mankomix.core.analysis.stems import measure_stem_context
from mankomix.core.project import Project
from tests.fixtures import synth

SR = 48000


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))


def _project(root, stems: dict, *, genre: str = "jpop") -> Project:
    src = root / "src"
    for role, x in stems.items():
        synth.write_wav(src / f"{role}.wav", x, SR)
    proj = Project.create(root / "song.mmx", title="mixplan test", genre=genre)
    FileAdapter().fetch(src, proj, actor="human")
    return proj


@pytest.fixture(scope="module")
def song(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MANKOMIX_HOME", str(tmp_path_factory.mktemp("home")))
        proj = _project(tmp_path_factory.mktemp("song"), synth.song_stems(sr=SR, seconds=8.0, seed=0))
        prop = mixplan.plan_mix(proj)
        yield proj, prop


def _kept(prop, **match):
    return [m for m in prop["moves"] if m["status"] == "kept" and all(m.get(k) == v for k, v in match.items())]


def _lead_chain(prop):
    return prop["changes"]["tracks"][prop["lead"]]["chain"]


def _context(proj):
    so: dict = {}
    _, sr, _ = mr.render_mix(proj, stems_out=so)
    meta = {t: {"role": m["role"], "is_lead": m["is_lead"], "importance": m["importance"]}
            for t, m in O.stems_meta(proj.data).items() if t in so}
    return measure_stem_context(so, sr, meta, genre=proj.data.get("genre"))


# --------------------------------------------------------------------------
# fixed order and proposal shape (R-04, R-31)


def test_fixed_order_and_proposal_shape(song):
    _, prop = song
    assert prop["stage"] == "mix" and prop["proposal_id"].startswith("mxp_")
    assert [s["id"] for s in prop["order"]] == list(mixplan.STEP_IDS)
    assert [s["n"] for s in prop["order"]] == list(range(1, 8))
    for s in prop["order"]:  # measured after every step
        assert s["measured_after"]["score"] is not None and "P-10" in s["measured_after"]
    # moves appear in the fixed order unless a recorded reordering retouched an earlier step
    steps = [m["step"] for m in prop["moves"]]
    if not prop["reorderings"]:
        assert steps == sorted(steps)
    assert prop["order"][1]["status"] == "suggestions_only"
    assert not any(m["step"] == 2 for m in prop["moves"])
    for m in prop["moves"]:
        assert m["rules"] and all(re.fullmatch(r"R-\d\d", r) for r in m["rules"])
        assert m["action"]["ja"] and m["action"]["en"]
        assert m["alternatives"] and isinstance(m["measured"], dict) and m["expected"] is not None
        assert m["status"] in ("kept", "rejected") and m["result"]["verdict"]
    assert prop["operations"] == ["approve_and_apply", "reject_and_request_alternative"]
    assert prop["route"]["rule"] == "R-21" and prop["route"]["route"] == "stem_mix"
    # static balance comes first and acts on levels only
    assert {m["kind"] for m in _kept(prop, step=1)} <= {"gain", "pan"}
    assert prop["objective_evaluation"]["scope"] == "full_length"
    for a in prop["arrangement"]:
        assert a["rule"] == "R-28" and a["status"] in ("recommended", "not_needed", "conditional")


def test_lead_gets_the_vocal_template(song):
    proj, prop = song
    lead = prop["lead"]
    assert lead == "trk_vocals"
    chain = _lead_chain(prop)
    types = [p["type"] for p in chain]
    hpf = [p for p in chain if p["type"] == "filter" and p["params"]["kind"] == "hpf"]
    assert hpf and 60.0 <= hpf[0]["params"]["freq_hz"] <= 100.0  # R-07 + SPEC 6.5.4 stage 1
    comps = [p for p in chain if p["type"] == "compressor"]
    assert len(comps) == 2  # two-stage compression (stage 2)
    assert comps[0]["params"]["attack_ms"] < comps[1]["params"]["attack_ms"]
    for c in comps:  # release recorded as a note value at the tempo (R-11)
        assert c["note_values"]["release"]["note"] and c["note_values"]["release"]["rule"] == "R-11"
    assert types.index("filter") < types.index("compressor")  # subtractive before dynamics
    # de-esser exactly when the lead is sibilant (P-17 on the lead itself)
    x, sr, _ = mr.render_track(proj, lead)
    assert ("deesser" in types) == ((sibilance(x, sr).get("penalty") or 0.0) > 0.0)
    # plate-like reverb on an FX bus, the lead sends least (depth order)
    bus = next(b for b in prop["changes"]["buses"] if b["kind"] == "fx")
    rv = bus["chain"][0]
    assert rv["type"] == "reverb" and rv["params"]["mix"] == 1.0
    assert rv["params"]["lowcut_hz"] == 600.0 and rv["params"]["highcut_hz"] == 6000.0
    sends = {t: s for t, d in prop["changes"]["tracks"].items() for s in d.get("sends") or [] if s["bus"] == bus["id"]}
    assert lead in sends
    assert all(sends[lead]["level_db"] <= s["level_db"] for s in sends.values())
    assert not any(t in sends for t in ("trk_drums", "trk_bass"))  # low end and rhythm core stay dry


def test_accompaniment_yields_1_to_3_khz(song):
    _, prop = song
    yields = []
    for tid, d in prop["changes"]["tracks"].items():
        if tid == prop["lead"]:
            continue
        for p in d.get("chain") or []:
            q = p["params"]
            if p["type"] == "eq" and q["shape"] == "peak" and 1000.0 <= q["freq_hz"] <= 3000.0 and -2.0 <= q["gain_db"] <= -1.5:
                yields.append(tid)
    assert yields
    assert any(m.get("template_stage") == 4 for m in _kept(prop, step=3))


def test_no_eq_move_exceeds_3_db(song):
    _, prop = song
    eqs = [p for d in prop["changes"]["tracks"].values() for p in d.get("chain") or [] if p["type"] == "eq"]
    eqs += [p for p in prop["changes"]["mix_chain"] if p["type"] == "eq"]
    assert eqs
    for p in eqs:  # R-06 per move, widths in octaves and minimum phase (R-12)
        assert abs(p["params"]["gain_db"]) <= 3.0 + 1e-9
        assert p["params"]["bw_oct"] > 0 and p["params"]["phase"] == "minimum"
    for m in prop["moves"]:
        proc = m.get("processor") or {}
        if proc.get("type") == "eq":
            assert abs(proc["params"]["gain_db"]) <= 3.0 + 1e-9


def test_decision_texts_six_elements(song):
    _, prop = song
    texts = mixplan.decisions_six_elements(prop)
    assert set(texts) == {"balance", "pan", "frequency", "depth", "dynamics", "interest"}
    assert texts == prop["decision_texts"]
    words = set()
    for t in config.load_vocabulary()["terms"]:
        words.update(t["ja"])
        words.update(w for w in t["en"] if len(w) > 3)
    words.update(v for k, v in mixplan.mix_rules()["vocabulary_en"].items() if k != "note")
    paired = 0
    for el, v in texts.items():
        assert v["ja"] and v["en"] and len(v["ja"]) == len(v["en"])
        for lang in ("ja", "en"):
            for line in v[lang]:
                assert line.count("→") == 4  # measured -> rule -> action -> alternatives -> result
                if any(w in line for w in words):
                    paired += 1
                    assert re.search(r"\d", line), line  # vocabulary always paired with numbers
    assert paired >= 4
    assert any("sone" in line for line in texts["balance"]["en"])  # R-25
    assert any("知覚倍率" in line for line in texts["balance"]["ja"])
    assert any("human" in line for line in texts["interest"]["en"])
    assert any("人間" in line for line in texts["interest"]["ja"])


def test_apply_improves_lead_masking_and_p10(song):
    proj, prop = song
    before = _context(proj)
    mixplan.apply_mix_plan(proj, prop, actor="planner")
    assert journal.list_entries(proj.root, limit=1)[-1]["op"] == "mix_apply"
    reopened = Project.open(proj.root)
    assert reopened.validate() == [] or all(i["level"] != "error" for i in reopened.validate())
    data = reopened.data
    assert data["mix"]["applied"]["proposal_id"] == prop["proposal_id"]
    assert set(data["mix"]["decisions"]) == set(O.ELEMENTS)
    lead = next(t for t in data["tracks"] if t["id"] == prop["lead"])
    assert any(p["type"] == "compressor" for p in lead["chain"])
    stored = json.loads((proj.root / "cache" / "proposals" / f"{prop['proposal_id']}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "applied" and stored["decisions"]
    after = _context(reopened)
    vb, va = before["P-02"]["vs_lead"]["value"], after["P-02"]["vs_lead"]["value"]
    assert va < vb  # masking against the lead went down
    assert after["P-10"]["penalty"] < before["P-10"]["penalty"]
    assert after["P-10"]["verdict"] == "ok" and before["P-10"]["verdict"] == "buried"


# --------------------------------------------------------------------------
# R-22 and determinism (small stem sets)


def _small(seconds: float, roles=("vocals", "bass", "synth")) -> dict:
    st = synth.song_stems(sr=SR, seconds=seconds, seed=0)
    return {r: st[r] for r in roles}


def test_separated_stems_get_balance_moves_only(tmp_path):
    proj = _project(tmp_path, _small(4.0))
    ops = [{"op": "replace", "path": f"/assets/{i}/origin", "value": "separated"}
           for i, _ in enumerate(proj.data["assets"])]
    proj.apply_patch(ops, actor="human")
    prop = mixplan.plan_mix(proj)
    assert prop["balance_only"] is True
    assert set(prop["restrictions"]) == {t["id"] for t in proj.data["tracks"]}
    assert all(r["rule"] == "R-22" and r["operations"] == ["balance"] for r in prop["restrictions"].values())
    assert {m["kind"] for m in prop["moves"]} <= {"gain"}
    assert all(abs(m["change"]["delta_db"]) <= 3.0 + 1e-9 for m in prop["moves"])
    for d in prop["changes"]["tracks"].values():
        assert set(d) <= {"gain_db"}
    assert prop["changes"]["buses"] == [] and not prop["changes"]["mix_chain_changed"]
    assert [s["status"] for s in prop["order"][2:]] == ["skipped_r22"] * 5
    assert any(r["rule"] == "R-22" for el in prop["decisions"].values() for r in el)
    assert prop["route"]["origins"] == ["separated"]
    mixplan.apply_mix_plan(proj, prop, actor="planner")
    assert all(t["restrictions"]["rule"] == "R-22" for t in proj.data["tracks"])
    assert all(not t.get("chain") for t in proj.data["tracks"])


def test_plan_is_deterministic(tmp_path):
    proj = _project(tmp_path, _small(2.5, ("vocals", "synth")))
    a = mixplan.plan_mix(proj)
    b = mixplan.plan_mix(proj)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["moves"] and any(m["step"] >= 3 and m["status"] == "kept" for m in a["moves"])
    # re-planning a mixed project replaces the planner's own processors / sends / bus instead of stacking them
    mixplan.apply_mix_plan(proj, a, actor="planner")
    assert any(s.get("owner") == "mixplan" for t in proj.data["tracks"] for s in t.get("sends") or [])
    c = json.loads(json.dumps(a))  # a later plan that decided against the reverb
    c["proposal_id"] = "mxp_replan_test"
    c["changes"]["buses"] = []
    for d in c["changes"]["tracks"].values():
        d.pop("sends", None)
    mixplan.apply_mix_plan(proj, c, actor="planner")
    assert not any(t.get("sends") for t in proj.data["tracks"])
    mixplan.apply_mix_plan(proj, a, actor="planner")
    ids = [p["id"] for t in proj.data["tracks"] for p in t.get("chain") or []]
    ids += [p["id"] for b in proj.data["buses"] for p in b.get("chain") or []]
    assert len(ids) == len(set(ids))
    assert sum(1 for b in proj.data["buses"] if b.get("owner") == "mixplan") <= 1
    assert all(i["level"] != "error" for i in proj.validate())


def test_rejects_non_mix_proposal(song):
    proj, _ = song
    with pytest.raises(Exception):
        mixplan.apply_mix_plan(proj, {"stage": "master"}, actor="planner")
    assert np.isclose(mixplan.sone_ratio(10.0), 2.0)
