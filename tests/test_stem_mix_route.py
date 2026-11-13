"""Stem-mix mastering route (SPEC 6.6.1, 9.4; R-21): the master input is the rendered mix.

The master input of the ``stem_mix`` route is ``mixrender.render_mix`` of the
project (track chains, faders, pan, sends, buses, cleaned stems) with the
variant's track / bus overrides, so a mix change reaches the rendered master
and two variants with different mixes get different masters.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from mankomix.core import api, routes
from mankomix.core import mixrender as mr
from mankomix.core.project import Project
from tests.test_cli_stages import SR, write_song


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    src = write_song(tmp_path / "src", seconds=3.0, roles=("vocals", "drums", "bass"))
    root = tmp_path / "song.mmx"
    api.init_project(root, title="route")
    api.import_files(root, [str(src)])
    # a mix-stage result: an HPF on the vocals (the route becomes stem_mix)
    p = Project.open(root)
    i = next(k for k, t in enumerate(p.data["tracks"]) if t["id"] == "trk_vocals")
    api.patch(root, [{"op": "add", "path": f"/tracks/{i}/chain", "value": [
        {"id": "prc_voc_hpf", "type": "filter", "params": {"kind": "hpf", "freq_hz": 120.0}, "reason": "test"}]}],
        "human", reason="mix")
    return root


def _master(root, variant: str) -> dict:
    api.master_plan(root, profile="spotify", delivery="hires_native", variant=variant, apply=True)
    return api.render(root, variant)


def test_master_input_is_the_rendered_mix(proj):
    p = Project.open(proj)
    assert routes.select_route(p)["route"] == "stem_mix"
    x, sr = routes.load_master_input(p, "stem_mix")
    y, ysr, _ = mr.render_mix(p, seed=0, measure=False)
    assert sr == ysr == SR and x.tobytes() == y.tobytes()
    # not the static clip sum: the vocal HPF and the pan law are in it
    s, _ = routes.load_master_input(p, "stem_sum")
    assert not np.allclose(x, s[: x.shape[0]])


def test_track_chain_change_changes_the_master(proj):
    first = _master(proj, "var_a")
    f = proj / first["outputs"][0]["file"]
    before = _sha(f)
    p = Project.open(proj)
    i = next(k for k, t in enumerate(p.data["tracks"]) if t["id"] == "trk_bass")
    api.patch(proj, [{"op": "add", "path": f"/tracks/{i}/chain", "value": [
        {"id": "prc_bass_gain", "type": "gain", "params": {"gain_db": -6.0}, "reason": "test"}]}],
        "human", reason="bass down")
    api.render(proj, "var_a")                                   # same master chain, new mix
    assert _sha(f) != before


def test_variants_with_different_track_overrides_differ(proj):
    _master(proj, "var_a")
    _master(proj, "var_b")
    p = Project.open(proj)
    i = next(k for k, v in enumerate(p.data["variants"]) if v["id"] == "var_b")
    api.patch(proj, [{"op": "add", "path": f"/variants/{i}/track_overrides",
                      "value": {"trk_bass": {"gain_db": -9.0}}}], "human", reason="variant mix")
    p = Project.open(proj)
    xa, _ = routes.load_master_input(p, "stem_mix", variant_id="var_a")
    xb, _ = routes.load_master_input(p, "stem_mix", variant_id="var_b")
    assert not np.array_equal(xa, xb)
    ra, rb = api.render(proj, "var_a"), api.render(proj, "var_b")
    fa, fb = proj / ra["archive"]["file"], proj / rb["archive"]["file"]
    import soundfile as sf
    a, _ = sf.read(str(fa))
    b, _ = sf.read(str(fb))
    assert a.shape == b.shape and not np.array_equal(a, b)
    # bus overrides of a variant reach its master input too
    mix_bus = next(b["id"] for b in p.data["buses"] if b["kind"] == "mix")
    api.patch(proj, [{"op": "add", "path": f"/variants/{i}/bus_overrides",
                      "value": {mix_bus: {"gain_db": -3.0}}}], "human", reason="bus")
    xb2, _ = routes.load_master_input(Project.open(proj), "stem_mix", variant_id="var_b")
    assert np.allclose(xb2, xb * 10 ** (-3.0 / 20.0))
    # verify measures the variant's own mix (S-08 baseline on the same signal)
    v = api.verify(proj, "var_b")
    assert v["overall"] in ("pass", "fail", "incomplete")
    assert json.loads((proj / v["path"]).read_text(encoding="utf-8"))["variant"] == "var_b"
