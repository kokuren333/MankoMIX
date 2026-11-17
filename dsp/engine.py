"""DSP engine: validates a processor chain and executes it on a backend (SPEC 3.1, 3.2, 6.5.2).

Rules enforced here:

- every step's parameters are validated against the processor definitions;
- stage rules (limiter: master only; resample / dither: export only);
- fixed mastering order when ``stage == "master"`` (S-06, SPEC 6.6.2), the
  limiter being the final step;
- nothing runs after dither, neither inside a chain nor on audio returned by a
  chain that dithered (S-05);
- NaN / inf after each step raises, length is preserved by every step except
  resample (S-09);
- float64 internally; the backend that executed each step is recorded for the
  render manifest (SPEC 3.2, 9.6).

Backend selection per step: the step's ``backend`` if given, else the first
entry of ``backend_preference`` implementing the type, else the first
available backend the processor declares (so ``aw.*`` steps run on
``native`` without being asked). When no backend can run a step (``aw.*``
with the native library unavailable) the step's ``fallback`` reference
processor is used and recorded (``step["fallback"]`` + a warning); without a
fallback a ``DSPError`` with rule ``backend`` is raised.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import processors as P
from . import reference
from .errors import ChainError, DSPError, NumericError, ParamError

_STEP_KEYS = {"id", "type", "params", "backend", "bypass", "note", "fallback"}


class DitheredAudio(np.ndarray):
    """Marker type for audio that has been dithered/quantised. No processor may run on it (S-05)."""


def _mark_dithered(a: np.ndarray) -> DitheredAudio:
    return a.view(DitheredAudio)


@dataclass
class RenderResult:
    audio: np.ndarray
    sr: int
    steps: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stage: str = "master"
    dithered: bool = False
    backends: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Manifest-friendly record (no audio)."""
        return {"stage": self.stage, "sample_rate": self.sr, "frames": int(self.audio.shape[0]),
                "channels": int(self.audio.shape[1]), "dithered": self.dithered,
                "steps": self.steps, "warnings": self.warnings, "backends": self.backends}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def seed_from_hash(project_hash: str | bytes) -> int:
    """Fixed dither seed derived from the project (SPEC 9.6): 63-bit integer from a hash string."""
    if isinstance(project_hash, bytes):
        digest = hashlib.sha256(project_hash).hexdigest()
    else:
        h = project_hash.split(":", 1)[-1].strip().lower()
        digest = h if len(h) >= 16 and all(c in "0123456789abcdef" for c in h) else \
            hashlib.sha256(project_hash.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _db(v: float) -> float | None:
    return round(20.0 * math.log10(v), 4) if v > 0 else None


def _peak_db(x: np.ndarray) -> float | None:
    return _db(float(np.max(np.abs(x)))) if x.size else None


def _prepare(x) -> np.ndarray:
    if isinstance(x, DitheredAudio):
        raise ChainError("S-05: audio has already been dithered; no processing may follow dither",
                         rule="S-05")
    a = np.array(x, dtype=np.float64, copy=True)
    if a.ndim == 1:
        a = a[:, None]
    if a.ndim != 2 or a.shape[1] < 1:
        raise ParamError("audio must be shaped (frames,) or (frames, channels)")
    if not np.all(np.isfinite(a)):
        raise NumericError("S-09: input contains NaN or infinity", rule="S-09")
    return a


def _backends() -> dict[str, dict]:
    reg = {"reference": reference.IMPLEMENTATIONS}
    try:
        from . import ffmpeg_backend
        if ffmpeg_backend.available():
            reg["ffmpeg"] = ffmpeg_backend.IMPLEMENTATIONS
    except Exception:  # pragma: no cover - ffmpeg probing must never break rendering
        pass
    try:
        from . import native_wiring
        table = native_wiring.implementations()
        if table:
            reg["native"] = table
    except Exception:  # pragma: no cover - native probing must never break rendering
        pass
    return reg


def _backend_version(name: str) -> dict:
    if name == "reference":
        return reference.version()
    if name == "ffmpeg":
        from . import ffmpeg_backend
        vi = ffmpeg_backend.version_info() or {}
        return {"backend": "ffmpeg", "version": vi.get("version"), "build": vi.get("build"),
                "configuration": vi.get("configuration")}
    if name == "native":
        from . import native_backend
        try:
            return native_backend.version_info()
        except Exception as exc:  # pragma: no cover
            return {"backend": "native", "error": str(exc)}
    return {"backend": name}


# ---------------------------------------------------------------------------
# chain validation
# ---------------------------------------------------------------------------

def validate_chain(chain: list[dict], stage: str) -> list[dict]:
    """Validate a chain for a stage and return normalised steps. Raises ValueError subclasses."""
    if stage not in P.STAGES:
        raise ChainError(f"unknown stage {stage!r}; expected one of {P.STAGES}", rule="stage")
    if not isinstance(chain, list):
        raise ChainError("chain must be a list of steps")
    steps: list[dict] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(chain):
        if not isinstance(raw, dict) or "type" not in raw:
            raise ChainError(f"step {i}: must be an object with a 'type'")
        extra = set(raw) - _STEP_KEYS
        if extra:
            raise ChainError(f"step {i}: unknown keys {sorted(extra)}")
        t = raw["type"]
        if t not in P.PROCESSORS:
            raise ParamError(f"step {i}: unknown processor type {t!r}")
        sid = str(raw.get("id") or f"{i:02d}_{t}")
        if sid in seen_ids:
            raise ChainError(f"step {i}: duplicate id {sid!r}")
        seen_ids.add(sid)
        try:
            params = P.validate_params(t, raw.get("params") or {})
        except ParamError as e:
            raise ParamError(f"step {sid}: {e}", step=sid) from None
        fallback = (_validate_fallback(raw["fallback"], t, params, sid)
                    if raw.get("fallback") is not None else None)
        steps.append({"id": sid, "type": t, "params": params, "backend": raw.get("backend"),
                      "bypass": bool(raw.get("bypass", False)), "note": raw.get("note"),
                      "fallback": fallback})

    # S-05 first: nothing after dither, whatever the stage
    for i, s in enumerate(steps):
        if s["type"] == "dither" and i != len(steps) - 1:
            raise ChainError(f"S-05: step {steps[i + 1]['id']} ({steps[i + 1]['type']}) follows dither; "
                             "dither must be the very last operation", rule="S-05", step=steps[i + 1]["id"])

    for s in steps:
        d = P.PROCESSORS[s["type"]]
        fb = s.get("fallback")
        if fb and stage not in P.PROCESSORS[fb["type"]]["stages"]:
            raise ChainError(f"step {s['id']}: fallback {fb['type']!r} is not allowed in stage {stage!r}",
                             rule="stage", step=s["id"])
        if stage not in d["stages"]:
            rule = "S-06" if s["type"] == "limiter" else "stage"
            raise ChainError(f"{rule}: processor {s['type']!r} (step {s['id']}) is not allowed in stage "
                             f"{stage!r}; allowed stages: {d['stages']}", rule=rule, step=s["id"])
        if not d["implemented"]:
            raise ChainError(f"processor {s['type']!r} (step {s['id']}) is declared but not implemented "
                             "in this engine version", rule="not_implemented", step=s["id"])

    if stage == "master":
        _check_master_order(steps)
    elif stage == "export":
        _check_export_order(steps)
    return steps


def _validate_fallback(spec, t: str, params: dict, sid: str) -> dict:
    """Normalise a step's ``fallback``: a type name or {"type": ..., "params": {...}}.

    A bare type (or an object without params) must be the processor's declared
    fallback; its parameters are then mapped from the step's own parameters.
    """
    from . import native_wiring

    if isinstance(spec, str):
        spec = {"type": spec}
    if (not isinstance(spec, dict) or not isinstance(spec.get("type"), str)
            or set(spec) - {"type", "params"}):
        raise ChainError(f"step {sid}: fallback must be a processor type or an object with "
                         "'type' and optional 'params'", step=sid)
    ft = spec["type"]
    if ft not in P.PROCESSORS or "reference" not in P.PROCESSORS[ft]["backends"]:
        raise ChainError(f"step {sid}: fallback {ft!r} must be a processor with a reference "
                         "implementation", rule="backend", step=sid)
    if P.PROCESSORS[ft].get("position") == "final" or ft in ("resample", "dither"):
        raise ChainError(f"step {sid}: {ft!r} cannot be a fallback", rule="backend", step=sid)
    declared = (P.PROCESSORS[t].get("fallback") or {}).get("type")
    try:
        if "params" in spec:
            fp, notes, mapping = P.validate_params(ft, spec["params"] or {}), [], "explicit"
        elif ft == declared:
            _, fp, notes = native_wiring.fallback_params(t, params)
            mapping = P.PROCESSORS[t]["fallback"].get("mapping", "declared")
        else:
            raise ChainError(f"step {sid}: fallback {ft!r} is not the declared fallback of {t!r} "
                             f"({declared!r}); give explicit params", rule="backend", step=sid)
    except ParamError as e:
        raise ParamError(f"step {sid}: fallback: {e}", step=sid) from None
    return {"type": ft, "params": fp, "notes": notes, "mapping": mapping}


def _check_master_order(steps: list[dict]) -> None:
    limiters = [i for i, s in enumerate(steps) if s["type"] == "limiter"]
    if len(limiters) > 1:
        raise ChainError("S-06: only one limiter is allowed in the mastering chain", rule="S-06")
    if limiters and limiters[0] != len(steps) - 1:
        nxt = steps[limiters[0] + 1]
        raise ChainError(f"S-06: the true-peak limiter must be the final mastering step, but "
                         f"{nxt['type']!r} (step {nxt['id']}) follows it", rule="S-06", step=nxt["id"])
    last_slot, last_step = 0, None
    for s in steps:
        slot = P.PROCESSORS[s["type"]]["master_slot"]
        if slot is None:
            continue  # neutral trims (gain) may sit anywhere before the limiter
        if slot < last_slot:
            raise ChainError(
                f"S-06: mastering order violated: {s['type']!r} (step {s['id']}, slot {slot} "
                f"{P.MASTER_SLOTS[slot]}) after {last_step['type']!r} (step {last_step['id']}, slot "
                f"{last_slot} {P.MASTER_SLOTS[last_slot]}); fixed order is "
                "EQ -> dynamics -> enhance -> stereo -> loudness reach/clipper -> limiter",
                rule="S-06", step=s["id"])
        last_slot, last_step = slot, s


def _check_export_order(steps: list[dict]) -> None:
    last = 0
    counts: dict[str, int] = {}
    for s in steps:
        counts[s["type"]] = counts.get(s["type"], 0) + 1
        slot = P.PROCESSORS[s["type"]].get("export_slot", 0)
        if slot < last:
            raise ChainError(f"export order violated at step {s['id']}: expected "
                             "loudness_gain -> resample -> dither", rule="S-05", step=s["id"])
        last = slot
    for t in ("resample", "dither"):
        if counts.get(t, 0) > 1:
            raise ChainError(f"S-05: {t} may run only once per export", rule="S-05")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _select(t: str, forced: str | None, preference: Iterable[str], reg: dict, warnings: list[str],
            sid: str):
    """Pick (implementation, backend) for a type; (None, None) when no backend can run it."""
    order = [forced] if forced else list(preference)
    for b in order:
        if b in reg and t in reg[b]:
            return reg[b][t], b
    for b in P.PROCESSORS[t]["backends"]:
        if b in reg and t in reg[b]:
            if forced:
                warnings.append(f"step {sid}: backend {forced!r} unavailable for {t!r}; used {b!r}")
            return reg[b][t], b
    return None, None


def render_chain(x, sr: int, chain: list[dict], *, stage: str, seed: int = 0,
                 backend_preference: tuple[str, ...] = ("reference",)) -> RenderResult:
    """Run a validated chain on ``x`` (frames[, channels]) at ``sr``. Returns a RenderResult."""
    audio = _prepare(x)
    sr = int(sr)
    steps = validate_chain(chain, stage)
    _xchain.check_channel_input(steps, audio)
    reg = _backends()
    warnings: list[str] = []
    records: list[dict] = []
    used: set[str] = set()
    dithered = False
    for s in steps:
        t, p, sid = s["type"], s["params"], s["id"]
        if s["bypass"]:
            records.append({"id": sid, "type": t, "backend": None, "params": p, "bypass": True,
                            "stats": {}, "in_peak": _peak_db(audio), "out_peak": _peak_db(audio)})
            _xchain.record_metadata(records[-1], s)
            continue
        fn, backend = _select(t, s["backend"], backend_preference, reg, warnings, sid)
        exec_t, exec_p, fb_rec = t, p, None
        if fn is None:
            reason = _unavailable_reason(t)
            fb = s.get("fallback")
            if not fb:
                raise DSPError(f"step {sid}: no available backend for {t!r} (declared "
                               f"{P.PROCESSORS[t]['backends']}): {reason}; declare a 'fallback' "
                               "reference processor to render without it", rule="backend", step=sid)
            exec_t, exec_p = fb["type"], fb["params"]
            fn, backend = reg["reference"][exec_t], "reference"
            fb_rec = {"type": exec_t, "params": exec_p, "mapping": fb["mapping"], "reason": reason,
                      "notes": list(fb["notes"])}
            extra = f"; {'; '.join(fb['notes'])}" if fb["notes"] else ""
            warnings.append(f"step {sid}: {t!r} needs backend {P.PROCESSORS[t]['backends']} "
                            f"({reason}); rendered with fallback {exec_t!r} on 'reference' "
                            f"(approximation){extra}")
        P.check_runtime(exec_t, exec_p, sr)
        in_peak = _peak_db(audio)
        n_in = audio.shape[0]
        fn = _xchain.seed_implementation(fn, exec_t, sid)
        if s.get("channel", "stereo") != "stereo":
            fn = _xchain.channel_implementation(fn, s)
        y, sr_out, stats = fn(audio, sr, exec_p, seed=seed)
        y = np.asarray(y, dtype=np.float64)
        if y.ndim == 1:
            y = y[:, None]
        if not np.all(np.isfinite(y)):
            raise NumericError(f"S-09: step {sid} ({t}) produced NaN or infinity", rule="S-09", step=sid)
        if t != "resample" and y.shape[0] != n_in:
            raise NumericError(f"S-09: step {sid} ({t}) changed the length {n_in} -> {y.shape[0]}",
                               rule="S-09", step=sid)
        if t == "resample":
            want = -(-n_in * int(sr_out) // sr)
            if y.shape[0] != want:
                raise NumericError(f"S-09: resample length {y.shape[0]} != expected {want}",
                                   rule="S-09", step=sid)
        used.add(backend)
        rec = {"id": sid, "type": t, "backend": backend, "params": p, "stats": stats,
               "in_peak": in_peak, "out_peak": _peak_db(y)}
        if fb_rec:
            rec["fallback"] = fb_rec
        if s.get("note"):
            rec["note"] = s["note"]
        records.append(rec)
        _xchain.record_metadata(rec, s)
        warnings += _step_warnings(stage, exec_t, exec_p, stats, sid)
        audio, sr = y, int(sr_out)
        if t == "dither":
            dithered = True
    if stage == "master" and not any(s["type"] == "limiter" for s in steps):
        warnings.append("master chain has no true-peak limiter: S-01 is not enforced by the DSP")
    if audio.size:
        dc = np.abs(np.mean(audio, axis=0))
        if np.any(dc > 10 ** (-60 / 20)):
            warnings.append(f"S-09: DC offset above -60 dBFS on output ({_db(float(np.max(dc)))} dBFS)")
    result = RenderResult(audio=_mark_dithered(audio) if dithered else audio, sr=sr, steps=records,
                          warnings=warnings, stage=stage, dithered=dithered,
                          backends={b: _backend_version(b) for b in sorted(used)})
    return result


def _unavailable_reason(t: str) -> str:
    if "native" in P.PROCESSORS[t]["backends"]:
        from . import native_wiring
        if not native_wiring.native_available():
            return f"native library unavailable: {native_wiring.unavailable_reason()}"
        return "processor missing from the native library build"
    return "backend unavailable"


def _step_warnings(stage: str, t: str, p: dict, stats: dict, sid: str) -> list[str]:
    w: list[str] = []
    if t == "eq" and stage == "master":
        if abs(p["gain_db"]) > 2.0 and p["shape"] != "notch":
            w.append(f"R-15: master EQ step {sid} moves {p['gain_db']:+.1f} dB (> 2 dB): "
                     "large corrections suggest a mix problem")
        if p["phase"] == "linear" and (p["gain_db"] > 0 or p["gain_db"] < -1.0):
            w.append(f"SPEC 6.6.3: linear-phase EQ step {sid} should be limited to cuts up to ~1 dB "
                     "(pre-ringing)")
    if t == "compressor" and stats.get("gr_scale") == "excessive":
        w.append(f"compressor step {sid}: gain reduction p95 > 10 dB (excessive)")
    if t == "limiter":
        gr = stats.get("gain_reduction", {})
        if gr.get("p95_db", 0.0) > 4.0:
            w.append(f"P-18: limiter step {sid} gain reduction p95 {gr['p95_db']:.1f} dB > 4 dB: "
                     "lower the target or send back to the mix")
        if stats.get("static_fallback_db", 0.0) > 0:
            w.append(f"limiter step {sid}: static fallback trim of {stats['static_fallback_db']} dB applied")
    if t == "dither" and stats.get("clipped_samples", 0) > 0:
        w.append(f"S-09: dither step {sid} clipped {stats['clipped_samples']} samples at full scale")
    if t == "loudness_gain" and stage == "export" and p["gain_db"] > 0:
        w.append(f"export step {sid}: positive loudness_gain after the limiter can break the TP ceiling")
    return w


# ---------------------------------------------------------------------------
# export module (SPEC 5.3)
# ---------------------------------------------------------------------------

_CONTAINERS = {".wav": "wav", ".flac": "flac", ".aif": "aiff", ".aiff": "aiff"}


def load_delivery_formats() -> dict[str, dict]:
    from mankomix import repo_data_root

    path = repo_data_root() / "profiles" / "delivery_formats.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f["id"]: f for f in data["formats"]}


def _as_list(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def wav_format_tag(path: str | Path) -> int | None:
    """Return the wFormatTag of a RIFF/WAVE file (1 = WAVE_FORMAT_PCM, 3 = IEEE float, 0xFFFE = extensible)."""
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        while True:
            ck = f.read(8)
            if len(ck) < 8:
                return None
            cid, size = ck[:4], struct.unpack("<I", ck[4:])[0]
            if cid == b"fmt ":
                return struct.unpack("<H", f.read(2))[0]
            f.seek(size + (size & 1), 1)


def export_audio(x, sr: int, delivery: dict | str, out_path: str | Path, *, seed: int,
                 sample_rate: int | None = None, dither: str | None = None,
                 backend_preference: tuple[str, ...] = ("reference",)) -> dict:
    """Write a delivery file (SPEC 5.3). The only place that resamples and reduces word length.

    ``delivery`` is a format entry from profiles/delivery_formats.json (or its id).
    ``sample_rate`` picks one rate when the format lists several (default: keep the
    source rate if listed, else the first). ``dither`` overrides the format's
    dither field ("tpdf" | "none"). Dither runs once, only when the word length
    decreases (float -> 24/16 bit), TPDF, no noise shaping.
    """
    if isinstance(x, DitheredAudio):
        raise ChainError("S-05: audio has already been dithered; export it as is or start from the master",
                         rule="S-05")
    if isinstance(delivery, str):
        formats = load_delivery_formats()
        if delivery not in formats:
            raise ParamError(f"unknown delivery format {delivery!r}")
        delivery = formats[delivery]
    out_path = Path(out_path)
    sr = int(sr)
    warnings: list[str] = []
    fmt_id = delivery.get("id")

    container = _CONTAINERS.get(out_path.suffix.lower())
    allowed = [c.lower() for c in _as_list(delivery.get("container", "wav"))]
    if container is None or container not in allowed:
        raise ParamError(f"delivery {fmt_id}: output extension {out_path.suffix!r} does not match "
                         f"container(s) {allowed}")

    rates = _as_list(delivery.get("sample_rate", "native"))
    if sample_rate is not None:
        if "native" not in rates and int(sample_rate) not in rates:
            raise ParamError(f"delivery {fmt_id}: sample rate {sample_rate} not in {rates}")
        target_sr = int(sample_rate)
    elif "native" in rates or sr in rates:
        target_sr = sr
    else:
        target_sr = int(rates[0])

    depth = delivery.get("bit_depth", "32f")
    if depth not in (16, 24, "32f"):
        raise ParamError(f"delivery {fmt_id}: unsupported bit_depth {depth!r}")
    if container == "flac" and depth == "32f":
        raise ParamError("FLAC cannot hold 32-bit float")

    audio = _prepare(x)
    want_ch = delivery.get("channels")
    if want_ch is not None and audio.shape[1] != want_ch:
        if audio.shape[1] == 1 and want_ch == 2:
            audio = np.concatenate([audio, audio], axis=1)
            warnings.append("mono source duplicated to 2 channels for the delivery format")
        else:
            raise ParamError(f"delivery {fmt_id}: needs {want_ch} channels, source has {audio.shape[1]}")

    reduces = depth in (16, 24)
    policy = (dither or delivery.get("dither") or "tpdf").lower()
    if policy not in ("tpdf", "none"):
        raise ParamError(f"unsupported dither policy {policy!r} (tpdf | none)")
    do_dither = reduces and policy == "tpdf"
    if reduces and not do_dither:
        warnings.append(f"word length reduced to {depth} bit without dither (delivery format "
                        f"{fmt_id} specifies dither='none'); rounding is used")

    chain: list[dict] = []
    if target_sr != sr:
        chain.append({"id": "export_resample", "type": "resample", "params": {"target_sr": target_sr}})
    if do_dither:
        chain.append({"id": "export_dither", "type": "dither", "params": {"bit_depth": depth}})
    res = render_chain(audio, sr, chain, stage="export", seed=seed, backend_preference=backend_preference)
    y = np.asarray(res.audio)
    warnings += [w for w in res.warnings if not w.startswith("S-09: DC")]

    from .reference.export import to_pcm_int
    clipped = 0
    if depth == "32f":
        data, subtype = y.astype(np.float32), "FLOAT"
        over = int(np.count_nonzero(np.abs(y) > 1.0))
        if over:
            warnings.append(f"{over} samples exceed 0 dBFS in the float file")
    else:
        if not do_dither:
            scale = 2.0 ** (depth - 1)
            k = np.rint(y * scale)
            clipped = int(np.count_nonzero((k > scale - 1) | (k < -scale)))
            y = np.clip(k, -scale, scale - 1) / scale
        else:
            clipped = int(res.steps[-1]["stats"].get("clipped_samples", 0))
        data, subtype = to_pcm_int(y, depth), f"PCM_{depth}"
        if clipped:
            warnings.append(f"S-09: {clipped} samples clipped at full scale during quantisation")

    from mankomix.core import audio_io
    fmt = {"wav": "WAV", "flac": "FLAC", "aiff": "AIFF"}[container]
    audio_io.write(out_path, data, target_sr, subtype=subtype, format=fmt)

    tag = wav_format_tag(out_path) if container == "wav" else None
    if container == "wav" and depth in (16, 24) and tag != 1:
        warnings.append(f"WAV written with format tag {tag}, not WAVE_FORMAT_PCM (SPEC 5.3)")
    tp = reference.true_peak_dbtp(y, target_sr)
    record = {
        "format_id": fmt_id,
        "file": out_path.name,
        "container": container,
        "sample_rate": target_sr,
        "bit_depth": depth,
        "channels": int(y.shape[1]),
        "frames": int(y.shape[0]),
        "duration_s": round(y.shape[0] / target_sr, 6),
        "wav_format_tag": ({1: "WAVE_FORMAT_PCM", 3: "WAVE_FORMAT_IEEE_FLOAT",
                            0xFFFE: "WAVE_FORMAT_EXTENSIBLE"}.get(tag, tag) if container == "wav" else None),
        "dithered": do_dither,
        "dither": ({"type": "tpdf", "seed": int(seed), "bit_depth": depth, "noise_shaping": "none",
                    "rng": "numpy.PCG64"} if do_dither else None),
        "quantization": ("tpdf_dither" if do_dither else "round" if reduces else "none"),
        "resampled_from": sr if target_sr != sr else None,
        "resample_backend": next((s["backend"] for s in res.steps if s["type"] == "resample"), None),
        "true_peak_dbtp": round(tp, 4) if math.isfinite(tp) else None,
        "sample_peak_dbfs": _peak_db(y),
        "clipped_samples": clipped,
        "steps": res.steps,
        "backends": res.backends,
        "warnings": warnings,
    }
    return record


__all__ = ["render_chain", "validate_chain", "export_audio", "RenderResult", "DitheredAudio",
           "seed_from_hash", "load_delivery_formats", "wav_format_tag"]

from mankomix.dspx import chain as _xchain

_validate_chain_base = validate_chain


def validate_chain(chain: list[dict], stage: str) -> list[dict]:
    return _xchain.validate_chain(chain, stage, _validate_chain_base)
