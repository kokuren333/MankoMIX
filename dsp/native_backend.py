"""ctypes binding of the native DSP core (``dsp/native/``, docs/SPEC.md 3.2).

The shared library is looked up in this order:

1. the file named by the environment variable ``MANKOMIX_NATIVE_LIB``;
2. ``dsp/build/lib/mankomix_dsp.{dll,so,dylib}`` (output of
   ``python -I tools/build_native.py``).

Importing this module never fails because the library is missing or broken:
:func:`available` then returns ``False`` and :func:`load_error` says why.

Sample convention: callers pass ``float64`` arrays shaped ``(frames, channels)``
(or ``(frames,)`` for mono). The C ABI processes planar doubles in place; the
binding converts and never modifies the caller's array.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

ENV_VAR = "MANKOMIX_NATIVE_LIB"
EXPECTED_ABI = 1
MAX_CHANNELS = 8

_STATUS_TEXT = {
    -1: "null handle or pointer",
    -2: "unknown parameter id",
    -3: "parameter value is NaN or infinite",
    -4: "invalid argument",
}

_lock = threading.Lock()
_lib: ctypes.CDLL | None = None
_lib_path: Path | None = None
_load_error: str | None = None
_loaded = False


class NativeBackendError(RuntimeError):
    """Raised when the native library is unavailable or rejects a call."""


def _library_filename() -> str:
    if sys.platform.startswith("win"):
        return "mankomix_dsp.dll"
    if sys.platform == "darwin":
        return "mankomix_dsp.dylib"
    return "mankomix_dsp.so"


def _candidate_paths() -> list[Path]:
    env = os.environ.get(ENV_VAR)
    if env:
        return [Path(env)]
    return [Path(__file__).resolve().parent / "build" / "lib" / _library_filename()]


def _bind(lib: ctypes.CDLL) -> None:
    c_char_p, c_int, c_double, c_void_p = ctypes.c_char_p, ctypes.c_int, ctypes.c_double, ctypes.c_void_p
    lib.mmx_version.restype = c_char_p
    lib.mmx_version.argtypes = []
    lib.mmx_abi_version.restype = c_int
    lib.mmx_abi_version.argtypes = []
    lib.mmx_build_info.restype = c_char_p
    lib.mmx_build_info.argtypes = []
    lib.mmx_processor_count.restype = c_int
    lib.mmx_processor_count.argtypes = []
    lib.mmx_processor_info.restype = c_int
    lib.mmx_processor_info.argtypes = [c_int, c_char_p, ctypes.c_size_t]
    lib.mmx_create.restype = c_void_p
    lib.mmx_create.argtypes = [c_char_p, c_double, c_int]
    lib.mmx_set_param.restype = c_int
    lib.mmx_set_param.argtypes = [c_void_p, c_char_p, c_double]
    lib.mmx_get_param.restype = c_int
    lib.mmx_get_param.argtypes = [c_void_p, c_char_p, ctypes.POINTER(c_double)]
    lib.mmx_latency.restype = c_int
    lib.mmx_latency.argtypes = [c_void_p]
    lib.mmx_process.restype = c_int
    lib.mmx_process.argtypes = [c_void_p, c_void_p, ctypes.c_int64]
    lib.mmx_reset.restype = c_int
    lib.mmx_reset.argtypes = [c_void_p]
    lib.mmx_destroy.restype = None
    lib.mmx_destroy.argtypes = [c_void_p]
    # optional utility kernels (library >= 0.2.0); older builds simply lack them
    if hasattr(lib, "mmx_smooth_attack_release"):
        lib.mmx_smooth_attack_release.restype = c_int
        lib.mmx_smooth_attack_release.argtypes = [c_void_p, ctypes.c_int64, c_double, c_double,
                                                  c_double, c_double, ctypes.POINTER(c_double)]


def _load() -> ctypes.CDLL | None:
    global _lib, _lib_path, _load_error, _loaded
    with _lock:
        if _loaded:
            return _lib
        _loaded = True
        for path in _candidate_paths():
            if not path.is_file():
                _load_error = f"native library not found ({path.name}); run: python -I tools/build_native.py"
                continue
            try:
                lib = ctypes.CDLL(str(path))
                _bind(lib)
                abi = int(lib.mmx_abi_version())
            except (OSError, AttributeError) as exc:
                _load_error = f"cannot load {path.name}: {exc}"
                continue
            if abi != EXPECTED_ABI:
                _load_error = f"{path.name} has ABI {abi}, this binding expects {EXPECTED_ABI}"
                continue
            _lib, _lib_path, _load_error = lib, path, None
            return lib
        return None


def _require() -> ctypes.CDLL:
    lib = _load()
    if lib is None:
        raise NativeBackendError(_load_error or "native library unavailable")
    return lib


def available() -> bool:
    """True when the native library is present, loadable and ABI-compatible."""
    return _load() is not None


def load_error() -> str | None:
    """Why :func:`available` is False (None when the library loaded)."""
    _load()
    return _load_error


def version_info() -> dict[str, Any]:
    """Backend identity for render manifests (docs/SPEC.md 9.6).

    Contains no filesystem path; ``library_sha256`` identifies the binary.
    """
    lib = _require()
    assert _lib_path is not None
    digest = hashlib.sha256(_lib_path.read_bytes()).hexdigest()
    return {
        "backend": "native",
        "version": lib.mmx_version().decode("ascii"),
        "abi": int(lib.mmx_abi_version()),
        "build": json.loads(lib.mmx_build_info().decode("utf-8")),
        "library_file": _lib_path.name,
        "library_sha256": digest,
    }


def processors() -> list[dict[str, Any]]:
    """JSON descriptions of all processors compiled into the library."""
    lib = _require()
    out = []
    for index in range(int(lib.mmx_processor_count())):
        size = int(lib.mmx_processor_info(index, None, 0))
        if size < 0:
            raise NativeBackendError(f"mmx_processor_info({index}) failed with {size}")
        buf = ctypes.create_string_buffer(size + 1)
        lib.mmx_processor_info(index, buf, size + 1)
        out.append(json.loads(buf.value.decode("utf-8")))
    return out


def processor_info(processor_id: str) -> dict[str, Any]:
    for info in processors():
        if info["id"] == processor_id:
            return info
    raise KeyError(f"unknown native processor: {processor_id}")


def _check(status: int, what: str) -> int:
    if status < 0:
        raise NativeBackendError(f"{what}: {_STATUS_TEXT.get(status, f'status {status}')}")
    return status


class NativeProcessor:
    """One processor instance; keeps signal state between :meth:`process` calls."""

    def __init__(self, processor_id: str, sample_rate: float, channels: int,
                 params: Mapping[str, float] | None = None) -> None:
        self._lib = _require()
        self.processor_id = processor_id
        self.sample_rate = float(sample_rate)
        self.channels = int(channels)
        if not 1 <= self.channels <= MAX_CHANNELS:
            raise ValueError(f"channels must be 1..{MAX_CHANNELS}, got {channels}")
        handle = self._lib.mmx_create(processor_id.encode("utf-8"), self.sample_rate, self.channels)
        if not handle:
            raise NativeBackendError(
                f"mmx_create failed for {processor_id!r} (unknown id or unsupported sample rate/channels)"
            )
        self._handle: int | None = handle
        for key, value in (params or {}).items():
            self.set_param(key, value)

    # -- parameters -------------------------------------------------------
    def set_param(self, param_id: str, value: float) -> bool:
        """Set a parameter; returns True when the value was clamped into range."""
        status = self._lib.mmx_set_param(self._live(), param_id.encode("utf-8"), float(value))
        if status == -2:
            raise KeyError(f"{self.processor_id}: unknown parameter {param_id!r}")
        return _check(status, f"set_param({param_id})") == 1

    def get_param(self, param_id: str) -> float:
        value = ctypes.c_double()
        status = self._lib.mmx_get_param(self._live(), param_id.encode("utf-8"), ctypes.byref(value))
        if status == -2:
            raise KeyError(f"{self.processor_id}: unknown parameter {param_id!r}")
        _check(status, f"get_param({param_id})")
        return float(value.value)

    @property
    def latency(self) -> int:
        return _check(int(self._lib.mmx_latency(self._live())), "latency")

    # -- processing -------------------------------------------------------
    def process_planar(self, planar: np.ndarray) -> None:
        """Process a float64 array shaped (channels, frames) in place.

        Each channel row must be contiguous (a column slice of a C-contiguous
        planar array qualifies, which is how block rendering avoids copies).
        """
        if planar.dtype != np.float64 or planar.ndim != 2:
            raise ValueError("planar buffer must be float64 shaped (channels, frames)")
        if planar.shape[1] > 1 and planar.strides[1] != planar.itemsize:
            raise ValueError("each channel row of the planar buffer must be contiguous")
        if planar.shape[0] != self.channels:
            raise ValueError(f"expected {self.channels} channels, got {planar.shape[0]}")
        if not planar.flags.writeable:
            raise ValueError("planar buffer must be writeable")
        frames = planar.shape[1]
        if frames == 0:
            return
        base, stride = planar.ctypes.data, planar.strides[0]
        pointers = (ctypes.c_void_p * self.channels)(*[base + c * stride for c in range(self.channels)])
        _check(self._lib.mmx_process(self._live(), pointers, frames), "process")

    def process(self, x: np.ndarray) -> np.ndarray:
        """Process (frames, channels) float64 audio; returns a new array of the same shape."""
        x = np.asarray(x, dtype=np.float64)
        mono = x.ndim == 1
        frames_first = x[:, None] if mono else x
        if frames_first.ndim != 2:
            raise ValueError("audio must be shaped (frames,) or (frames, channels)")
        planar = np.ascontiguousarray(frames_first.T, dtype=np.float64).copy()
        self.process_planar(planar)
        out = planar.T
        return np.ascontiguousarray(out[:, 0] if mono else out)

    def reset(self) -> None:
        _check(self._lib.mmx_reset(self._live()), "reset")

    # -- lifetime ---------------------------------------------------------
    def _live(self) -> int:
        if self._handle is None:
            raise NativeBackendError("processor instance is closed")
        return self._handle

    def close(self) -> None:
        if getattr(self, "_handle", None) is not None:
            self._lib.mmx_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> "NativeProcessor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass


def has_smoother() -> bool:
    """True when the loaded library exports the attack/release smoother kernel (>= 0.2.0)."""
    lib = _load()
    return lib is not None and hasattr(lib, "mmx_smooth_attack_release")


def smooth_attack_release(x: np.ndarray, a_att: float, ia_att: float, a_rel: float, ia_rel: float,
                          state: float = 0.0) -> np.ndarray:
    """Decoupled attack/release one-pole smoother over a 1-D float64 trace (new array).

    ``y = a_att*y + ia_att*x[n]`` while ``x[n] > y``, else ``a_rel*y + ia_rel*x[n]``,
    starting from ``state``. Bit-identical to the same loop written in Python.
    """
    lib = _require()
    if not hasattr(lib, "mmx_smooth_attack_release"):
        raise NativeBackendError("native library lacks mmx_smooth_attack_release (rebuild: "
                                 "python -I tools/build_native.py)")
    buf = np.array(x, dtype=np.float64, copy=True, order="C").reshape(-1)
    st = ctypes.c_double(float(state))
    if buf.size:
        _check(lib.mmx_smooth_attack_release(buf.ctypes.data, buf.size, float(a_att), float(ia_att),
                                             float(a_rel), float(ia_rel), ctypes.byref(st)),
               "smooth_attack_release")
    return buf


def _blocks(frames: int, block_size: int | Iterable[int] | None) -> Iterable[tuple[int, int]]:
    if block_size is None:
        yield 0, frames
        return
    sizes = [int(block_size)] if isinstance(block_size, (int, np.integer)) else [int(b) for b in block_size]
    if not sizes or any(b <= 0 for b in sizes):
        raise ValueError("block sizes must be positive")
    start, i = 0, 0
    while start < frames:
        n = min(sizes[i % len(sizes)], frames - start)
        yield start, start + n
        start += n
        i += 1


def process(type_id: str, x: np.ndarray, sr: float, params: Mapping[str, float] | None = None,
            block_size: int | Iterable[int] | None = None) -> np.ndarray:
    """Render ``x`` (float64, (frames, channels) or (frames,)) through one native processor.

    ``type_id`` is the processor id (e.g. ``"aw.purest_drive"``). Unknown
    parameter ids raise ``KeyError``; out-of-range values are clamped.
    ``block_size`` (an int or a repeating sequence of ints) splits the render
    into blocks; the result is bit-identical to a single-block render.
    The output keeps the input length; processor latency is not compensated
    (see :attr:`NativeProcessor.latency`).
    """
    x = np.asarray(x, dtype=np.float64)
    mono = x.ndim == 1
    frames_first = x[:, None] if mono else x
    if frames_first.ndim != 2:
        raise ValueError("audio must be shaped (frames,) or (frames, channels)")
    frames, channels = frames_first.shape
    planar = np.ascontiguousarray(frames_first.T).copy()
    with NativeProcessor(type_id, sr, channels, params) as proc:
        for start, stop in _blocks(frames, block_size):
            proc.process_planar(planar[:, start:stop])
    out = planar.T
    return np.ascontiguousarray(out[:, 0] if mono else out)
