"""tools/build_samples.py: the official sample set built from the tool's own commands
(docs/SPEC.md 15.1-15.4, D-036, D-037, D-040, D-061).

A 2 s synthetic folder shaped like the conform set (the 12 stems of ``synth.song_stems``,
``fullmix_conformed.wav``, plus the derived ``other`` / ``no_vocals`` sums and an unaligned
``0_fullmix``) is built twice with a two-variant subset (#1 main, #8 cd) and small iteration caps.
The builder runs ``python -m mankomix.cli run`` per variant; MP3 listening copies are checked
only when ffmpeg with libmp3lame is available.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.fixtures import synth

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "build_samples.py"
SR = 48000
SECONDS = 1.5
SUBSET = "1,8"
CONFORM_STEMS = ("backing_vocals", "bass", "brass", "drums", "fx", "guitar", "keyboard", "percussion",
                 "strings", "synth", "vocals", "woodwinds")


def _has_mp3_encoder() -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL)
    return re.search(r"^\s*A\S*\s+libmp3lame\s", r.stdout or "", re.MULTILINE) is not None


HAS_MP3 = _has_mp3_encoder()


def _tool():
    spec = importlib.util.spec_from_file_location("build_samples", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write_conform_set(folder: Path) -> dict:
    stems = synth.song_stems(sr=SR, seconds=SECONDS, seed=0)
    folder.mkdir(parents=True, exist_ok=True)
    for name in CONFORM_STEMS:
        synth.write_wav(folder / f"{name}.wav", stems[name], SR)
    total = synth.stem_sum(stems)
    synth.write_wav(folder / "fullmix_conformed.wav", total * 0.8, SR)
    # derived sums (D-037) and the unaligned download: present in the folder, never inputs
    other = sum(stems[n] for n in CONFORM_STEMS if n not in ("vocals", "backing_vocals", "drums", "bass"))
    synth.write_wav(folder / "other.wav", other, SR)
    synth.write_wav(folder / "no_vocals.wav", sum(stems[n] for n in CONFORM_STEMS if n != "vocals"), SR)
    synth.write_wav(folder / "0_fullmix.wav", np.concatenate([np.zeros((480, 2)), total * 0.8]), SR)
    (folder / "notes.md").write_text("not audio\n", encoding="utf-8")
    return stems


def _build(src: Path, root: Path, *extra: str) -> tuple[subprocess.CompletedProcess, dict | None]:
    cmd = [sys.executable, "-I", str(TOOL), "--source", str(src), "--variants", SUBSET,
           "--work", str(root / "work"), "--public", str(root / "public"), "--release", str(root / "release"),
           "--jobs", "2", "--mix-max-iter", "0", "--max-iter", "0", *extra]
    if not HAS_MP3:
        cmd.append("--no-mp3")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=1200, cwd=str(REPO))
    mf = root / "public" / "manifest.json"
    return r, (json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else None)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("samples")
    src = base / "conform set"
    stems = _write_conform_set(src)
    a = base / "a"
    r, man = _build(src, a)
    assert r.returncode == 0, r.stdout + r.stderr
    assert man is not None
    return {"base": base, "src": src, "stems": stems, "root": a, "manifest": man, "stdout": r.stdout}


def _forbidden(base: Path) -> list[str]:
    out = []
    for p in (base, Path.home(), REPO):
        s = str(p.resolve())
        out += [s, s.replace("\\", "/"), s.replace("\\", "\\\\")]
    return [x.lower() for x in out if len(x) > 3]


# ---------------------------------------------------------------------------


def test_manifest_shape(built):
    m = built["manifest"]
    assert m["kind"] == "official_sample_manifest" and m["schema_version"] == 1
    assert m["genre"] == "hiphop" and m["references"] == [] and m["intensity"] == 0.5
    assert "Apache-2.0" in m["terms"]["en"] and "AI training" in m["terms"]["en"] and m["terms"]["ja"]   # D-062
    assert m["variants_built"] == ["v01", "v08"] and m["complete"] is False
    assert m["generator"]["engine_version"]
    # inputs: exactly the 12 stems and the conformed full mix, with the original content hashes
    src = built["src"]
    assert [i["file"] for i in m["source"]["inputs"]] == [f"{n}.wav" for n in CONFORM_STEMS] + ["fullmix_conformed.wav"]
    for i in m["source"]["inputs"]:
        assert i["sha256"] == _sha(src / i["file"])
    assert {e["file"]: e["code"] for e in m["source"]["excluded"]} == {
        "other.wav": "derived_sum", "no_vocals.wav": "derived_sum", "0_fullmix.wav": "unaligned_fullmix"}
    assert m["source"]["folder"] == "$MANKOMIX_SAMPLE_DIR" and m["source"]["passed_as_is"] is False
    # variants
    v1, v8 = m["variants"]
    assert (v1["objective"], v1["profile"], v1["role"]) == ("comfort", "streaming_universal", "main")
    assert v1["deliveries"] == ["hires_native", "distributor_44k16"]
    assert (v8["objective"], v8["profile"], v8["deliveries"]) == ("comfort", "cd", ["cd_redbook"])
    for v in m["variants"]:
        assert v["intensity"] == 0.5
        assert v["run"]["exit_code"] in (0, 1) and v["run"]["route"] == "stem_mix"
        assert v["verification"]["overall"] in ("pass", "fail", "incomplete")
        assert v["translation_gate"]["status"] in ("pass", "fail", "incomplete")
        assert v["report"]["status"] == "ok"
        assert v["report"]["states"]["no_references_note"] is True     # D-039 stated in the report
        for key in ("json", "md_ja", "md_en", "verification"):
            assert (built["root"] / "public" / v["report"]["files"][key]).is_file()
        for ms in v["masters"]:
            assert ms["measured"]["lufs_i"] is not None and ms["measured"]["true_peak_dbtp"] is not None
            assert set(ms["measured"]["band_balance_ratio_db"]) >= {"sub", "bass", "mid"}
    fmt = {ms["delivery"]: ms["format"] for v in m["variants"] for ms in v["masters"]}
    assert fmt["distributor_44k16"]["sample_rate"] == 44100 and fmt["distributor_44k16"]["subtype"] == "PCM_16"
    assert fmt["cd_redbook"]["sample_rate"] == 44100 and fmt["hires_native"]["sample_rate"] == SR
    # verification-only profiles: the main master against the five -14 LUFS profiles
    vo = m["verification_only_profiles"]
    assert vo["status"] == "ok" and vo["of"] == "v01" and vo["project_unchanged"] is True
    assert [r["profile"] for r in vo["rows"]] == ["spotify", "youtube", "amazon_music", "tidal", "sns_safe"]
    assert all(isinstance(r["passed"], bool) for r in vo["rows"])
    assert {o["delivery"] for r in vo["rows"] for o in r["outputs"]} == {"hires_native", "distributor_44k16"}
    assert (built["root"] / "public" / vo["report"]).is_file()
    amazon = next(r for r in vo["rows"] if r["profile"] == "amazon_music")
    assert all(o["codecs"] in ([], ["opus"]) for o in amazon["outputs"])          # D-064
    # regeneration commands: relative, with placeholders; the conform set as an explicit file list
    cmds = m["regeneration"]["per_variant"]["v01"]
    files = " ".join(f'"$MANKOMIX_SAMPLE_DIR/{n}.wav"' for n in CONFORM_STEMS)
    assert cmds[1].startswith(f'python -m mankomix.cli run {files} "$MANKOMIX_SAMPLE_DIR/fullmix_conformed.wav" '
                              f'--project "$WORK/v01/song.mmx"')
    assert "--genre hiphop" in cmds[1] and "comfort:0.5" in cmds[1]
    assert "other.wav" not in json.dumps(m["regeneration"]) and "0_fullmix" not in json.dumps(m["regeneration"])
    assert m["regeneration"]["main_delta"] == ['python -m mankomix.cli clean delta stems --project "$WORK/v01/song.mmx"']
    assert m["listening_copies"]["masters"] is False and m["listening_copies"]["committed"] is False


def test_release_staging_holds_only_verified_masters(built):
    m = built["manifest"]
    rel = built["root"] / "release"
    staged = sorted(p.name for p in rel.iterdir())
    expected = sorted(ms["release_file"] for v in m["variants"] for ms in v["masters"] if ms["release_file"])
    assert staged == expected
    for v in m["variants"]:
        for ms in v["masters"]:
            if v["verification"]["passed"]:
                assert ms["release_file"] and _sha(rel / ms["release_file"]) == ms["sha256"]
            else:
                assert ms["release_file"] is None and ms["withheld"]


def test_no_absolute_paths_in_outputs(built):
    bad = _forbidden(built["base"])
    pub = built["root"] / "public"
    files = [p for p in pub.rglob("*") if p.is_file() and p.suffix in (".json", ".md")]
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8").lower()
        for b in bad:
            assert b not in text, f"absolute path in {f.relative_to(pub)}"
        assert not re.search(r"(?<![a-z0-9])[a-z]:[\\/]", text), f"drive path in {f.relative_to(pub)}"
    assert Path.home().name.lower() not in (pub / "manifest.json").read_text(encoding="utf-8").lower()
    for b in bad:
        assert b not in built["stdout"].lower()


def test_before_is_the_exact_unity_stem_sum(built):
    from mankomix.core import api
    m = built["manifest"]
    proj = built["root"] / "work" / "v01" / "song.mmx"
    aset = api.audio_set(str(proj), m["variants"][0]["project_variant"])
    bf = proj / aset["files"]["before"]
    assert _sha(bf) == m["audio"]["before"]["lossless"]["sha256"]
    assert m["before_consistency"]["identical_in_every_project"] is True
    x, sr = sf.read(str(bf), dtype="float32", always_2d=True)
    assert sr == SR
    ref = np.zeros_like(x, dtype=np.float64)
    for name in CONFORM_STEMS:   # gain 0 dB, stereo as-is, no processing; nothing else summed
        s, _ = sf.read(str(built["src"] / f"{name}.wav"), dtype="float64", always_2d=True)
        ref[: s.shape[0]] += s
    assert np.array_equal(x, ref.astype(np.float32))


def test_level_match_gains_follow_measured_loudness(built):
    m = built["manifest"]
    lb = m["audio"]["before"]["measured"]["lufs_i"]
    for v in m["variants"]:
        la = v["masters"][0]["measured"]["lufs_i"]
        lm = v["level_match"]
        assert lm["gain_db"] <= 0.0
        assert lm["target"] == ("before" if lb > la else "after")
        assert abs(lm["gain_db"] - (-abs(lb - la))) <= 0.011
        core = lm["core_audio_set"]
        # the core's own figure uses the archive_f32 master (the delivery master may differ by the
        # export loop), so only its sign convention is checked here
        assert core["gain_db"] <= 0.0 and core["target"] in ("before", "after")
    pair = m["audio"]["level_matched_pair"]
    assert pair["pair"] == ["before", "v01"] and pair["gain_db"] == m["variants"][0]["level_match"]["gain_db"]
    assert pair["lowered"] == m["variants"][0]["level_match"]["target"]


def test_delta_of_the_main_sample(built):
    d = built["manifest"]["audio"]["delta"]
    if d.get("status") == "not_generated":
        pytest.skip("cleanup removed nothing from the synthetic stems")
    assert d["of"] == "v01" and d["stems"] and all(s.startswith("ast_") for s in d["stems"])
    assert "fullmix" not in " ".join(d["stems"])
    assert d["made_by"].startswith("core clean delta stems")
    core_file = built["root"] / "work" / "v01" / "song.mmx" / "renders" / "delta" / "stem_sum_delta.wav"
    assert _sha(core_file) == d["lossless"]["sha256"]


@pytest.mark.skipif(not HAS_MP3, reason="ffmpeg with libmp3lame not available")
def test_listening_copies(built):
    m = built["manifest"]
    pub = built["root"] / "public"
    files = {v["listening_copy"]["file"] for v in m["variants"]}
    files |= {a["file"] for a in m["audio"].values() if a.get("file")}
    assert {"audio/before.mp3", "audio/fullmix_reference.mp3", "audio/v01_comfort__streaming_universal.mp3",
            "audio/v08_comfort__cd.mp3"} <= files
    lm = m["audio"]["level_matched_pair"]["file"]
    assert lm in ("audio/before_level_matched.mp3", "audio/v01_level_matched.mp3")
    on_disk = {p.relative_to(pub).as_posix() for p in (pub / "audio").iterdir()}
    assert on_disk == files
    for f in files:
        info = sf.info(str(pub / f))
        assert info.format == "MP3"
    # the level-matched copy sits within a fraction of a LU of the quieter side
    pair = m["audio"]["level_matched_pair"]
    quiet = min(m["audio"]["before"]["measured"]["lufs_i"], m["variants"][0]["masters"][0]["measured"]["lufs_i"])
    assert abs(pair["mp3_measured"]["lufs_i"] - quiet) < 0.5


@pytest.mark.slow
def test_two_builds_are_identical_except_timings(built):
    tool = _tool()
    r, man_b = _build(built["src"], built["base"] / "b")
    assert r.returncode == 0, r.stdout + r.stderr
    a, b = tool.strip_timings(built["manifest"]), tool.strip_timings(man_b)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert "timings" in built["manifest"]


def test_bad_inputs_exit_2(tmp_path):
    folder = tmp_path / "incomplete"
    folder.mkdir()
    synth.write_wav(folder / "vocals.wav", np.zeros((SR, 2)), SR)
    r = subprocess.run([sys.executable, "-I", str(TOOL), "--source", str(folder), "--work", str(tmp_path / "w"),
                        "--public", str(tmp_path / "p"), "--release", str(tmp_path / "r"), "--no-mp3"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       cwd=str(REPO), timeout=300)
    assert r.returncode == 2 and "incomplete" in r.stderr
    assert str(tmp_path).lower() not in (r.stdout + r.stderr).lower()
    r = subprocess.run([sys.executable, "-I", str(TOOL), "--source", str(folder), "--variants", "99", "--no-mp3"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       cwd=str(REPO), timeout=300)
    assert r.returncode == 2 and "unknown sample numbers" in r.stderr
