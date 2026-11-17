"""T05-07: file-only Ambisonics, numeric criteria and CLI isolation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct

import numpy as np
import pytest
from scipy.special import lpmv
import soundfile as sf

from mankomix.cli import main as cli
from mankomix.dspx.bb import ambisonics as A


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MANKOMIX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


def invoke(capsys, *args, expect=0):
    assert cli.main(["spatial", "ambi", *map(str, args)]) == expect
    result = json.loads(capsys.readouterr().out)
    if expect:
        assert result["error"] == "input_error", result
    return result


def audio(path, channels=1, frames=128):
    rng = np.random.Generator(np.random.PCG64(123))
    x = rng.normal(0, .1, (frames, channels))
    sf.write(path, x, 48000, subtype="DOUBLE")
    return x


@pytest.mark.parametrize("order", (1, 2, 3))
def test_sn3d_against_independent_legendre_definition(order):
    from math import factorial
    az, el = 41., -29.
    expected = []
    for n in range(order+1):
        for m in range(-n, n+1):
            k = abs(m)
            norm = np.sqrt((2 if k else 1)*factorial(n-k)/factorial(n+k))
            trig = np.sin(k*np.radians(az)) if m < 0 else np.cos(k*np.radians(az))
            expected.append(norm*(-1)**k*lpmv(k, n, np.sin(np.radians(el)))*trig)
    np.testing.assert_allclose(A.harmonics(order, az, el), expected, atol=1e-14)


@pytest.mark.parametrize("order", (1, 2, 3))
@pytest.mark.parametrize("azimuth", (-180, -90, -37, 0, 83, 180))
def test_encode_rotate_null(order, azimuth):
    x = np.linspace(-.25, .25, 31)[:, None]
    turned = A.encode(x, order, azimuth) @ A.rotation_matrix(order, -azimuth).T
    assert np.max(np.abs(turned-A.encode(x, order))) <= 1e-6


@pytest.mark.parametrize("order", (1, 2, 3))
def test_rotation_orthogonality_and_three_axis_order(order):
    rng = np.random.Generator(np.random.PCG64(789))
    for yaw, pitch, roll in rng.uniform(-720, 720, (20, 3)):
        matrix = A.rotation_matrix(order, yaw, pitch, roll)
        assert np.max(np.abs(matrix @ matrix.T-np.eye((order+1)**2))) <= 1e-12
        separate = (A.rotation_matrix(order, yaw=yaw) @ A.rotation_matrix(order, pitch=pitch)
                    @ A.rotation_matrix(order, roll=roll))
        np.testing.assert_allclose(matrix, separate, atol=1e-12)
    # Positive pitch turns the front vector down, positive roll turns left up.
    np.testing.assert_allclose(A.rotation_matrix(order, pitch=90) @ A.harmonics(order, 0, 0),
                               A.harmonics(order, 0, -90), atol=1e-14)
    np.testing.assert_allclose(A.rotation_matrix(order, roll=90) @ A.harmonics(order, 90, 0),
                               A.harmonics(order, 0, 90), atol=1e-14)
    np.testing.assert_array_equal(A.rotation_matrix(order), np.eye((order+1)**2))


def test_fuma_mapping_and_round_trip():
    x = np.array([[.25, .125, -.5, .0625], [-.5, 0, .25, -.125]])
    y = A.convert(x, "fuma", "ambix")
    np.testing.assert_array_equal(y[:, 1:], x[:, [2, 3, 1]])
    np.testing.assert_array_equal(y[:, 0], x[:, 0]*np.sqrt(2))
    np.testing.assert_array_equal(A.convert(y, "ambix", "fuma"), x)
    # Irrational W scaling necessarily rounds on general float64 samples.
    rng = np.random.Generator(np.random.PCG64(123))
    x = rng.normal(0, .1, (1000, 4))
    restored = A.convert(A.convert(x, "fuma", "ambix"), "ambix", "fuma")
    np.testing.assert_array_equal(restored[:, 1:], x[:, 1:])
    assert np.max(np.abs(restored-x)) <= 6e-17


@pytest.mark.parametrize("order", (1, 2, 3))
@pytest.mark.parametrize("angle", (0, 30, 90, 180))
def test_cardioid_response(order, angle):
    x = np.array([[.25]])
    front = A.stereo(A.encode(x, order), angle)
    np.testing.assert_array_equal(front[:, 0], front[:, 1])
    np.testing.assert_allclose(front, .25*.5*(1+np.cos(np.radians(angle))))
    left = A.stereo(A.encode(x, order, 90), angle)
    expected = .25*.5*(1+np.sin(np.radians([angle, -angle])))
    np.testing.assert_allclose(left[0], expected, atol=1e-16)


@pytest.mark.parametrize("order", (1, 2, 3))
def test_cli_pipeline_only_explicit_outputs(tmp_path, capsys, monkeypatch, order):
    x = audio(tmp_path / "in.wav", channels=2)
    # An unusable project must never be opened, even when explicitly supplied.
    (tmp_path / "project.json").write_text("not JSON", encoding="utf-8")
    (tmp_path / "assets" / "derived").mkdir(parents=True)
    monkeypatch.setattr(cli.api, "open_project", lambda *a, **k: pytest.fail("project read"), raising=False)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    invoke(capsys, "encode", "--in", "in.wav", "--azimuth", 57, "--order", order,
           "--out", "encoded.wav", "--project", tmp_path)
    invoke(capsys, "rotate", "--in", "encoded.wav", "--yaw", -57, "--out", "rotated.wav")
    invoke(capsys, "encode", "--in", "in.wav", "--order", order, "--out", "front.wav")
    a, sr = sf.read("rotated.wav", always_2d=True)
    b, _ = sf.read("front.wav", always_2d=True)
    assert sr == 48000 and a.shape == (len(x), (order+1)**2)
    assert np.max(np.abs(a-b)) <= 1e-6
    report = invoke(capsys, "info", "--in", "front.wav")
    assert report["order"] == order and len(report["components"]) == (order+1)**2
    assert report["normalization"]["confidence"] == "undetermined"
    invoke(capsys, "decode", "--in", "front.wav", "--to", "stereo", "--out", "stereo.wav")
    stereo, _ = sf.read("stereo.wav", always_2d=True)
    np.testing.assert_allclose(stereo[:, 0], np.mean(x, axis=1)*.5, atol=1e-15)
    np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])
    assert set(p.name for p in tmp_path.glob("*.wav")) == {
        "in.wav", "encoded.wav", "rotated.wav", "front.wav", "stereo.wav"}
    for p, data in before.items():
        assert (tmp_path / p).read_bytes() == data


def _chunks(path):
    data = path.read_bytes()
    cursor, ids = 12, []
    while cursor+8 <= len(data):
        key, size = struct.unpack_from("<4sI", data, cursor)
        ids.append(key)
        cursor += 8+size+(size % 2)
    return ids


@pytest.mark.parametrize("operation,options", [
    ("encode", ["--order", 3, "--azimuth", 37]),
    ("rotate", ["--yaw", 37, "--pitch", -23, "--roll", 9]),
    ("convert", ["--from", "ambix", "--to", "fuma"]),
    ("decode", ["--to", "stereo"]),
    ("decode", ["--to", "binaural"]),
])
def test_bit_identical_files_without_timestamp(tmp_path, capsys, operation, options):
    audio(tmp_path / "input.wav", 1 if operation == "encode" else 4)
    reports = [invoke(capsys, operation, "--in", "input.wav", *options, "--out", name)
               for name in ("first.wav", "second.wav")]
    assert reports[0] == reports[1]
    assert (tmp_path / "first.wav").read_bytes() == (tmp_path / "second.wav").read_bytes()
    assert b"PEAK" not in _chunks(tmp_path / "first.wav")
    assert sf.info("first.wav").subtype == "DOUBLE"


@pytest.mark.parametrize("order", (1, 2, 3))
def test_binaural_matches_existing_hrtf_sum(order):
    from mankomix.dspx.bb.hrtf import load_hrtf
    from scipy.signal import convolve
    x = A.encode(np.eye(1, 128).T*.1, order, 45, 20)
    actual, details = A.binaural(x, 48000)
    dataset, provenance = load_hrtf("model_sphere", 48000)
    az, el = A.speaker_directions()
    degree = np.array([int(np.sqrt(k)) for k in range(x.shape[1])])
    decoder = A.harmonics(order, az, el)*(2*degree+1)*A.speaker_weights()[:, None]
    expected = np.zeros_like(actual)
    feeds = x @ decoder.T
    for i, (a, e) in enumerate(zip(az, el)):
        kernel = dataset.kernel(-a, e, 48000)
        for ear in range(2):
            expected[:, ear] += convolve(feeds[:, i], kernel[:, ear], method="direct")[:len(x)]
    np.testing.assert_allclose(actual, expected, atol=1e-15)
    assert details["source_sha256"] == provenance["source_sha256"]
    assert details["virtual_speakers"] == 32
    assert np.isfinite(actual).all() and np.max(np.abs(actual)) > 0


def test_regular_polyhedra_and_third_order_quadrature():
    from scipy.spatial import ConvexHull
    az, el = A.speaker_directions()
    xyz = np.column_stack((np.cos(np.radians(el))*np.cos(np.radians(az)),
                           np.cos(np.radians(el))*np.sin(np.radians(az)), np.sin(np.radians(el))))
    ico = xyz[:12]
    centres = np.array([np.mean(ico[face], axis=0) for face in ConvexHull(ico).simplices])
    centres /= np.linalg.norm(centres, axis=1)[:, None]
    assert max(min(np.linalg.norm(xyz[12:]-q, axis=1)) for q in centres) < 1e-14
    b = A.harmonics(3, az, el)
    gram = b.T @ (A.speaker_weights()[:, None]*b)
    degree = np.array([int(np.sqrt(k)) for k in range(16)])
    np.testing.assert_allclose(gram, np.diag(1/(2*degree+1)), atol=1e-14)


def test_cli_byo_hrtf_and_tamper_rejection(tmp_path, capsys):
    from mankomix.dspx.bb.hrtf import HRTFS
    from mankomix.dspx.bb.asset_registry import sha256
    az, el = A.speaker_directions()
    h = np.zeros((len(az), 16, 2))
    h[:, 0] = [.4, .8]
    asset = tmp_path / "fixture.npz"
    np.savez(asset, azimuth_deg=az, elevation_deg=el, hrir=h, sr=np.int64(48000))
    HRTFS.register_file(asset, id="fixture", license_spdx="unknown")
    sf.write("ambi.wav", A.encode(np.eye(1, 128).T*.1, 3), 48000, subtype="DOUBLE")
    settings = {p: p.read_bytes() for p in (tmp_path / "home").rglob("*") if p.is_file()}
    before = asset.read_bytes()
    result = invoke(capsys, "decode", "--in", "ambi.wav", "--to", "binaural",
                    "--hrtf", "fixture", "--out", "out.wav")
    assert result["source_sha256"] == sha256(before)
    assert result["asset"]["tier"] == "byo" and "path" not in result["asset"]
    assert result["warnings"]
    actual, _ = sf.read("out.wav")
    expected = np.zeros((128, 2)); expected[0] = [.04, .08]
    np.testing.assert_allclose(actual, expected, atol=1e-14)
    assert asset.read_bytes() == before
    assert {p: p.read_bytes() for p in (tmp_path / "home").rglob("*") if p.is_file()} == settings
    asset.write_bytes(before+b"changed")
    invoke(capsys, "decode", "--in", "ambi.wav", "--to", "binaural", "--hrtf", "fixture",
           "--out", "tampered.wav", expect=2)
    assert not (tmp_path / "tampered.wav").exists()


@pytest.mark.parametrize("sr", (8000, 48000, 192000))
def test_binaural_preserves_rate_and_length(tmp_path, capsys, sr):
    sf.write("ambi.wav", A.encode(np.eye(1, 32).T, 1), sr, subtype="DOUBLE")
    report = invoke(capsys, "decode", "--in", "ambi.wav", "--to", "binaural", "--out", "out.wav")
    assert report["sample_rate_hz"] == sr and report["frames"] == 32
    assert sf.info("out.wav").frames == 32 and sf.info("out.wav").samplerate == sr


def test_cli_fuma_file_round_trip(tmp_path, capsys):
    x = np.array([[.25, -.125, .0625, 0], [-.5, .25, 0, .125]])
    sf.write("fuma.wav", x, 48000, subtype="DOUBLE")
    invoke(capsys, "convert", "--in", "fuma.wav", "--from", "fuma", "--to", "ambix", "--out", "ambix.wav")
    invoke(capsys, "convert", "--in", "ambix.wav", "--from", "ambix", "--to", "fuma", "--out", "back.wav")
    np.testing.assert_array_equal(sf.read("back.wav")[0], x)


@pytest.mark.parametrize("channels", (1, 2, 3, 5, 8, 10, 15, 25))
@pytest.mark.parametrize("op,options", [("rotate", []), ("decode", ["--to", "stereo"]), ("info", [])])
def test_non_ambisonic_channel_count(tmp_path, capsys, channels, op, options):
    audio(tmp_path / "bad.wav", channels)
    output = [] if op == "info" else ["--out", "out.wav"]
    result = invoke(capsys, op, "--in", "bad.wav", *options, *output, expect=2)
    assert "(N+1)^2" in result["message"]
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize("op,options,channels", [
    ("encode", ["--order", 0], 1), ("encode", ["--order", 4], 1),
    ("encode", ["--azimuth", 181], 1), ("encode", ["--elevation", -91], 1),
    ("encode", ["--azimuth", "nan"], 1), ("encode", [], 4),
    ("rotate", ["--yaw", "inf"], 4), ("decode", ["--to", "stereo", "--angle", 181], 4),
    ("decode", ["--to", "binaural", "--hrtf", "unknown_hrtf"], 4),
    ("convert", ["--from", "fuma", "--to", "ambix"], 9),
])
def test_invalid_parameters_do_not_write(tmp_path, capsys, op, options, channels):
    audio(tmp_path / "in.wav", channels)
    invoke(capsys, op, "--in", "in.wav", *options, "--out", "out.wav", expect=2)
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.parametrize("kind", ("same", "relative", "hardlink", "symlink"))
def test_input_alias_is_never_overwritten(tmp_path, capsys, kind):
    source = tmp_path / "input.wav"
    audio(source)
    before = source.read_bytes()
    target = source
    if kind == "relative":
        target = Path(".") / "input.wav"
    elif kind in ("hardlink", "symlink"):
        target = tmp_path / "alias.wav"
        if kind == "hardlink":
            os.link(source, target)
        else:
            try:
                target.symlink_to(source)
            except OSError:
                pytest.skip("symlink creation unavailable")
    invoke(capsys, "encode", "--in", source, "--out", target, expect=2)
    assert source.read_bytes() == before


def test_missing_io_and_nonfinite(tmp_path, capsys):
    invoke(capsys, "encode", "--in", "missing.wav", "--out", "out.wav", expect=2)
    audio(tmp_path / "in.wav")
    invoke(capsys, "encode", "--in", "in.wav", expect=2)
    for output in ("out.flac", "missing/out.wav"):
        invoke(capsys, "encode", "--in", "in.wav", "--out", output, expect=2)
    sf.write("nan.wav", np.array([[np.nan]]), 48000, subtype="DOUBLE")
    invoke(capsys, "encode", "--in", "nan.wav", "--out", "out.wav", expect=2)
    assert not (tmp_path / "out.wav").exists()


def test_readonly_info_and_defaults(tmp_path, capsys):
    audio(tmp_path / "in.wav")
    result = invoke(capsys, "encode", "--in", "in.wav", "--out", "ambix.wav")
    assert result["order"] == 1 and result["output_channels"] == 4
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = invoke(capsys, "info", "--in", "ambix.wav")
    assert result["order"] == 1
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_info_silence_is_finite_json(tmp_path, capsys):
    sf.write("silent.wav", np.zeros((8, 9)), 48000, subtype="DOUBLE")
    result = invoke(capsys, "info", "--in", "silent.wav")
    assert all(row["rms_dbfs"] is None and row["rms"] == 0 for row in result["components"])


def test_top_level_only_and_cli_only_table(capsys):
    from tests.test_mcp_e2e import CLI_TO_MCP, KNOWN_CLI_ONLY, NESTED_GROUPS
    from mankomix.dsp.processors import PROCESSORS
    parser = cli.build_parser()
    for op in ("encode", "rotate", "decode", "convert", "info"):
        name = "spatial ambi "+op
        assert CLI_TO_MCP[name] == "spatial_ambi_"+op
        assert "W4h" in KNOWN_CLI_ONLY[name]
    assert "spatial ambi" in NESTED_GROUPS
    assert "ambisonics" not in PROCESSORS and "ambi" not in PROCESSORS
    with pytest.raises(Exception, match="invalid choice"):
        parser.parse_args(["direction", "spatial", "ambi"])
