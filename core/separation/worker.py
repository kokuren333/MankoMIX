"""Separation worker, run as a separate process (SPEC 6.2, 13.1, S-10).

    python -m mankomix.core.separation.worker --request <request.json>

The core process never imports torch or any model code: it writes a request
file, starts this worker, and reads ``result.json`` from the output folder.
This keeps GPU memory, native crashes and any third-party library with a
weaker license boundary (torchaudio's sox bindings, for example) out of the
core process.

Request (JSON object):

    protocol      1
    backend       "mankomix_torch" | "fake_filter" (tests only)
    architecture  "mel_band_roformer" | "scnet" | "open_unmix" | ...
    config        runtime.config of the registry entry
    weights       {file name: local path}   (already verified by the core)
    roles         {file name: stem role | null}
    input         path of a float WAV at the model sample rate
    output_dir    folder for <stem>.wav files and result.json
    device        "auto" | "cpu" | "cuda"

Result (``result.json``): ``{"protocol": 1, "ok": true, "stems": {stem: file},
"sample_rate": int, "device": str, "elapsed_s": float, "versions": {...}}``
or ``{"ok": false, "error": str, "kind": "input"|"environment"}``.

The worker never downloads anything: hub / Hugging Face downloads are
disabled before any model code is imported.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

PROTOCOL = 1
EXIT_OK, EXIT_INPUT, EXIT_ENV = 0, 2, 3
FAKE_ENV = "MANKOMIX_SEPARATION_FAKE"


class WorkerError(Exception):
    def __init__(self, message: str, kind: str = "environment"):
        super().__init__(message)
        self.kind = kind


def _block_downloads() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import torch.hub as hub
    except Exception:  # torch missing: the backend reports it
        return

    def _refuse(*_a, **_k):
        raise WorkerError("automatic downloads are disabled in the separation worker (S-10)")

    hub.load_state_dict_from_url = _refuse
    hub.download_url_to_file = _refuse
    hub.load = _refuse


def _read_audio(path: str):
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return np.ascontiguousarray(data.T), int(sr)          # (channels, frames)


def _write_audio(path: Path, x, sr: int) -> None:
    import numpy as np
    import soundfile as sf

    sf.write(str(path), np.ascontiguousarray(np.asarray(x, dtype="float32").T), sr, subtype="FLOAT")


# --- backends -----------------------------------------------------------------------------

def _fake_filter(req: dict, mix, sr: int) -> dict:
    """Test backend: splits the mix into complementary FFT bands (sums back exactly)."""
    import numpy as np

    if os.environ.get(FAKE_ENV) != "1":
        raise WorkerError(f"the fake_filter backend is only available with {FAKE_ENV}=1", "input")
    cfg = req.get("config") or {}
    bands = cfg.get("bands") or {"bass": [0, 200], "vocals": [200, 4000], "other": [4000, None]}
    delay = int(cfg.get("delay_samples", 0))
    n = mix.shape[-1]
    spec = np.fft.rfft(mix, axis=-1)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    out = {}
    for stem, (lo, hi) in bands.items():
        hi = float("inf") if hi is None else float(hi)
        mask = (freqs >= float(lo)) & (freqs < hi)
        y = np.fft.irfft(spec * mask, n=n, axis=-1).astype("float32")
        if delay:
            y = np.concatenate([np.zeros((y.shape[0], delay), "float32"), y[:, :-delay]], axis=-1)
        out[stem] = y
    return out


def _device(torch, wanted: str):
    if wanted == "cpu":
        return torch.device("cpu")
    if wanted == "cuda":
        if not torch.cuda.is_available():
            raise WorkerError("CUDA was requested but is not available")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _torch_backend(req: dict, mix, sr: int, info: dict) -> dict:
    try:
        import torch
    except ImportError as exc:
        raise WorkerError("PyTorch is not installed in the separation environment") from exc
    from . import archs

    device = _device(torch, req.get("device") or "auto")
    info["device"] = device.type
    info["versions"]["torch"] = torch.__version__
    arch = req.get("architecture")
    runner = archs.RUNNERS.get(arch)
    if runner is None:
        raise WorkerError(f"architecture '{arch}' is not supported by backend mankomix_torch", "input")
    with torch.inference_mode():
        return runner(req, mix, sr, device, info)


BACKENDS = {"fake_filter": lambda req, mix, sr, info: _fake_filter(req, mix, sr),
            "mankomix_torch": _torch_backend}


# --- main ----------------------------------------------------------------------------------------

def run(req: dict) -> dict:
    if req.get("protocol") != PROTOCOL:
        raise WorkerError(f"unsupported request protocol {req.get('protocol')!r}", "input")
    out_dir = Path(req["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = BACKENDS.get(req.get("backend"))
    if backend is None:
        raise WorkerError(f"unknown backend '{req.get('backend')}'", "input")
    for name, p in (req.get("weights") or {}).items():
        if not Path(p).is_file():
            raise WorkerError(f"weights file missing: {name}", "input")
    mix, sr = _read_audio(req["input"])
    info: dict = {"device": "cpu", "versions": {"python": sys.version.split()[0]}}
    t0 = time.perf_counter()
    stems = backend(req, mix, sr, info)
    elapsed = time.perf_counter() - t0
    files = {}
    for stem, y in stems.items():
        fname = f"{stem}.wav"
        _write_audio(out_dir / fname, y, sr)
        files[stem] = fname
    return {"protocol": PROTOCOL, "ok": True, "stems": files, "sample_rate": sr,
            "device": info["device"], "elapsed_s": round(elapsed, 3), "versions": info["versions"],
            "notes": info.get("notes", [])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mankomix-separation-worker")
    ap.add_argument("--request", required=True)
    args = ap.parse_args(argv)
    _block_downloads()
    req_path = Path(args.request)
    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read request: {exc}", file=sys.stderr)
        return EXIT_INPUT
    out_dir = Path(req.get("output_dir") or req_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run(req)
        code = EXIT_OK
    except WorkerError as exc:
        result = {"protocol": PROTOCOL, "ok": False, "error": str(exc), "kind": exc.kind}
        code = EXIT_INPUT if exc.kind == "input" else EXIT_ENV
    except Exception as exc:  # report, never hang
        traceback.print_exc()
        result = {"protocol": PROTOCOL, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "kind": "environment"}
        code = EXIT_ENV
    (out_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
