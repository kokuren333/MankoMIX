"""Model runners for the separation worker (imported only inside the worker process).

Each runner takes ``(request, mix[channels, frames] float32, sample_rate,
torch.device, info)`` and returns ``{stem: array[channels, frames]}``.
Model code comes from ``third_party/`` (MIT, see the LICENSE / ORIGIN.md
files there) or from the MIT-licensed ``openunmix`` package. Hyper-parameters
come from the registry entry (``runtime.config``), never from code defaults.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import numpy as np

from mankomix import repo_data_root


def _third_party(sub: str) -> Path:
    p = repo_data_root() / "third_party" / sub
    if not p.is_dir():
        raise RuntimeError(f"third_party/{sub} is missing from this installation")
    return p


def _load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_package(name: str, folder: Path):
    """Load a folder of vendored modules (no __init__.py) as a package, so relative imports work."""
    if name not in sys.modules:
        spec = importlib.machinery.ModuleSpec(name, None, is_package=True)
        spec.submodule_search_locations = [str(folder)]
        sys.modules[name] = importlib.util.module_from_spec(spec)
    return sys.modules[name]


def _single_weight(req: dict) -> str:
    weights = req.get("weights") or {}
    if len(weights) != 1:
        raise ValueError("this architecture expects exactly one weights file")
    return next(iter(weights.values()))


def _overlap_add(fn, mix, segment: int, step: int, device):
    """Chunked inference with triangular cross-fades. fn: tensor[1, C, segment] -> [1, S, C, segment]."""
    import torch

    c, n = mix.shape
    pad = segment - step
    x = torch.from_numpy(np.ascontiguousarray(mix)).float()[None]
    # reflect-pad the head (when long enough) so that the first samples are not seen only by a window edge
    x = torch.nn.functional.pad(x, (pad, 0), mode="reflect" if n > pad else "constant")
    x = torch.nn.functional.pad(x, (0, pad + segment))[0]
    total = x.shape[-1]
    window = torch.cat([torch.arange(1, segment // 2 + 1, dtype=torch.float32),
                        torch.arange(segment - segment // 2, 0, -1, dtype=torch.float32)])
    window = window / window.max()
    out = None
    weight = torch.zeros(total)
    start = 0
    while start < n + pad:
        chunk = x[:, start:start + segment]
        if chunk.shape[-1] < segment:
            chunk = torch.nn.functional.pad(chunk, (0, segment - chunk.shape[-1]))
        y = fn(chunk[None].to(device))[0].float().cpu()       # (S, C, segment)
        if out is None:
            out = torch.zeros(y.shape[0], c, total)
        length = min(segment, total - start)
        out[..., start:start + length] += y[..., :length] * window[:length]
        weight[start:start + length] += window[:length]
        start += step
    out = out / weight.clamp(min=1e-8)
    return out[..., pad:pad + n].numpy()


# --- Mel-Band RoFormer -------------------------------------------------------------------

def run_mel_band_roformer(req, mix, sr, device, info):
    import torch

    cfg = req.get("config") or {}
    mod = _load_file_module("mmx_tp_mel_band_roformer", _third_party("bs_roformer") / "mel_band_roformer.py")
    model = mod.MelBandRoformer(**cfg["model"])
    state = torch.load(_single_weight(req), map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    if mix.shape[0] == 1 and cfg["model"].get("stereo", True):
        mix = np.repeat(mix, 2, axis=0)
    segment = int(cfg.get("chunk_size", 352800))
    step = segment // int(cfg.get("num_overlap", 2))

    def fn(chunk):
        y = model(chunk)
        return y[:, None] if y.ndim == 3 else y

    est = _overlap_add(fn, mix, segment, step, device)
    outputs = cfg.get("outputs") or ["vocals"]
    stems = {name: est[i].astype("float32") for i, name in enumerate(outputs)}
    residual = cfg.get("residual")
    if residual:
        stems[residual] = (mix - sum(stems.values())).astype("float32")
    info["versions"]["model_code"] = "third_party/bs_roformer"
    return stems


# --- SCNet -----------------------------------------------------------------------------------

def run_scnet(req, mix, sr, device, info):
    import torch

    cfg = req.get("config") or {}
    _load_package("mmx_tp_scnet", _third_party("scnet"))
    scnet_mod = importlib.import_module("mmx_tp_scnet.SCNet")
    model = scnet_mod.SCNet(**cfg["model"])
    state = torch.load(_single_weight(req), map_location="cpu", weights_only=True)
    key = cfg.get("state_key")
    if key and isinstance(state, dict) and key in state:
        state = state[key]
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    if mix.shape[0] == 1:
        mix = np.repeat(mix, 2, axis=0)
    mean = std = None
    x = mix
    if cfg.get("normalize_input", True):
        mono = mix.mean(axis=0)
        mean, std = float(mono.mean()), float(mono.std()) or 1.0
        x = (mix - mean) / std
    segment = int(round(float(cfg.get("segment_s", 11)) * sr))
    step = int((1.0 - float(cfg.get("overlap", 0.5))) * segment)
    est = _overlap_add(model, x.astype("float32"), segment, step, device)
    if mean is not None:
        est = est * std + mean
    sources = cfg["model"].get("sources") or ["drums", "bass", "other", "vocals"]
    info["versions"]["model_code"] = "third_party/scnet"
    return {name: est[i].astype("float32") for i, name in enumerate(sources)}


# --- Open-Unmix --------------------------------------------------------------------------------

def run_open_unmix(req, mix, sr, device, info):
    import torch

    try:
        import openunmix
        from openunmix import utils as umx_utils
        from openunmix.model import OpenUnmix, Separator
    except ImportError as exc:
        raise RuntimeError("the 'openunmix' package (MIT) is needed for Open-Unmix models") from exc
    cfg = req.get("config") or {}
    mcfg = cfg.get("model") or {}
    n_fft = int(cfg.get("n_fft", 4096))
    max_bin = umx_utils.bandwidth_to_max_bin(rate=float(sr), n_fft=n_fft,
                                             bandwidth=float(mcfg.get("max_bin_bandwidth_hz", 16000)))
    targets = {}
    for name, path in (req.get("weights") or {}).items():
        role = (req.get("roles") or {}).get(name)
        if not role:
            raise ValueError(f"weights file {name} has no stem role")
        net = OpenUnmix(nb_bins=int(mcfg.get("nb_bins", n_fft // 2 + 1)), nb_channels=int(mcfg.get("nb_channels", 2)),
                        hidden_size=int(mcfg.get("hidden_size", 512)), max_bin=max_bin)
        net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=False)
        net.eval()
        targets[role] = net
    sep = Separator(targets, niter=int(cfg.get("niter", 1)), residual=False, n_fft=n_fft,
                    n_hop=int(cfg.get("n_hop", 1024)), nb_channels=int(mcfg.get("nb_channels", 2)),
                    sample_rate=float(sr), wiener_win_len=cfg.get("wiener_win_len", 300)).to(device)
    sep.freeze()
    if mix.shape[0] == 1:
        mix = np.repeat(mix, 2, axis=0)
    audio = torch.from_numpy(np.ascontiguousarray(mix)).float()[None].to(device)
    est = sep(audio)[0].cpu().numpy()                       # (targets, channels, frames)
    names = list(sep.target_models.keys())
    info["versions"]["openunmix"] = getattr(openunmix, "__version__", "unknown")
    return {name: est[i][:, : mix.shape[-1]].astype("float32") for i, name in enumerate(names)}


RUNNERS = {
    "mel_band_roformer": run_mel_band_roformer,
    "scnet": run_scnet,
    "open_unmix": run_open_unmix,
}
