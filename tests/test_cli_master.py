"""CLI end-to-end for the M2 full-mix mastering path (init -> import -> master -> render -> verify -> report)."""
from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout

import numpy as np
import pytest
import soundfile as sf

from mankomix.cli.main import main
from mankomix.core.errors import EXIT_OK


def _cli(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(list(argv))
    return code, json.loads(buf.getvalue())


def _mix(sr=48000, seconds=6.0, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(sr * seconds)) / sr
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-((t % 0.5) * 12.0))
    pad = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 440 * t + 0.3)
    hats = 0.05 * rng.standard_normal(t.size) * np.exp(-((t % 0.25) * 40.0))
    mono = 0.5 * kick + pad + hats
    x = np.stack([mono, 0.95 * mono + 0.02 * rng.standard_normal(t.size)], axis=1)
    return 0.3 * x / np.max(np.abs(x))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_cli_master_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    src = tmp_path / "in"
    src.mkdir()
    sf.write(str(src / "song_2mix.wav"), _mix(), 48000, subtype="FLOAT")
    proj = str(tmp_path / "song.mmx")

    code, r = _cli("init", proj, "--title", "cli test")
    assert code == EXIT_OK
    code, r = _cli("-p", proj, "import", str(src / "song_2mix.wav"))
    assert code == EXIT_OK
    code, r = _cli("-p", proj, "route")
    assert code == EXIT_OK and r["route"] in ("full_mix", "stem_sum")
    code, r = _cli("-p", proj, "master", "plan", "--profile", "spotify", "--delivery", "distributor_44k16", "--apply")
    assert code == EXIT_OK, r
    variant = r["proposal"]["variant"]
    code, r = _cli("-p", proj, "render", variant)
    assert code == EXIT_OK, r
    code, r = _cli("-p", proj, "verify", variant)
    assert code in (0, 1)
    assert "passed" in r
    code, r = _cli("-p", proj, "report", variant)
    assert code == EXIT_OK, r
    text = json.dumps(r, ensure_ascii=False)
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text
