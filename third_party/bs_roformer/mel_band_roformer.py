"""Mel-Band RoFormer (inference only), compact port.

Original work: Phil Wang (lucidrains), https://github.com/lucidrains/BS-RoFormer
(``bs_roformer/mel_band_roformer.py``, ``bs_roformer/attend.py``) and the
rotary embedding of https://github.com/lucidrains/rotary-embedding-torch,
both MIT licensed (see LICENSE in this folder). The module layout and the
parameter names are kept so that checkpoints trained with that code (for
example with ZFTurbo's Music-Source-Separation-Training) load unchanged.

Changes against the original (see ORIGIN.md):

- inference only: training losses, multi-resolution STFT loss, linear
  attention, PoPE, gradient checkpointing and skip connections removed;
- the mel filter bank (librosa.filters.mel, Slaney scale and norm) is
  computed with numpy here, so librosa (and its LGPL soxr dependency) is
  not needed;
- the rotary embedding is inlined (fixed, non-learned frequencies);
- no beartype / einops dependency.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


# --- mel filter bank (numpy port of librosa.filters.mel, htk=False, norm="slaney") ---

def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, dtype=np.float64)
    f_sp = 200.0 / 3
    mels = f / f_sp
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = math.log(6.4) / 27.0
    return np.where(f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mels)


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float64)
    f_sp = 200.0 / 3
    freqs = f_sp * m
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = math.log(6.4) / 27.0
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), freqs)


def mel_filter_bank(sr: float, n_fft: int, n_mels: int) -> np.ndarray:
    """Slaney mel filter bank, float32, shape (n_mels, 1 + n_fft // 2)."""
    fmax = sr / 2.0
    fftfreqs = np.fft.rfftfreq(n=n_fft, d=1.0 / sr)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(0.0), _hz_to_mel(fmax), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fftfreqs)
    weights = np.zeros((n_mels, len(fftfreqs)), dtype=np.float32)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels])
    weights *= enorm[:, np.newaxis]
    return weights


# --- building blocks -----------------------------------------------------------------

class RMSNorm(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.scale = dim ** 0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return F.normalize(x, dim=-1) * self.scale * self.gamma


class RotaryEmbedding(nn.Module):
    def __init__(self, dim: int, theta: float = 10000.0):
        super().__init__()
        freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: dim // 2].float() / dim))
        self.freqs = nn.Parameter(freqs, requires_grad=False)

    def rotate(self, t: torch.Tensor) -> torch.Tensor:
        n = t.shape[-2]
        pos = torch.arange(n, device=t.device, dtype=self.freqs.dtype)
        f = torch.einsum("i,j->ij", pos, self.freqs)
        f = f.repeat_interleave(2, dim=-1)                   # (n, dim)
        cos, sin = f.cos().to(t.dtype), f.sin().to(t.dtype)
        rot_dim = f.shape[-1]
        t_rot, t_pass = t[..., :rot_dim], t[..., rot_dim:]
        x = t_rot.unflatten(-1, (-1, 2))
        x1, x2 = x.unbind(-1)
        half = torch.stack((-x2, x1), dim=-1).flatten(-2)
        out = t_rot * cos + half * sin
        return torch.cat((out, t_pass), dim=-1)


class FeedForward(nn.Module):
    def __init__(self, dim: int, mult: int = 4):
        super().__init__()
        inner = int(dim * mult)
        self.net = nn.Sequential(RMSNorm(dim), nn.Linear(dim, inner), nn.GELU(), nn.Dropout(0.0),
                                 nn.Linear(inner, dim), nn.Dropout(0.0))

    def forward(self, x):
        return self.net(x)


class Attention(nn.Module):
    def __init__(self, dim: int, heads: int, dim_head: int, rotary_embed: RotaryEmbedding):
        super().__init__()
        self.heads = heads
        inner = heads * dim_head
        self.rotary_embed = rotary_embed
        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, inner * 3, bias=False)
        self.to_gates = nn.Linear(dim, heads)
        self.to_out = nn.Sequential(nn.Linear(inner, dim, bias=False), nn.Dropout(0.0))

    def forward(self, x):
        x = self.norm(x)
        b, n, _ = x.shape
        qkv = self.to_qkv(x).view(b, n, 3, self.heads, -1).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]                      # (b, h, n, d)
        q = self.rotary_embed.rotate(q)
        k = self.rotary_embed.rotate(k)
        out = F.scaled_dot_product_attention(q, k, v)
        gates = self.to_gates(x).sigmoid().permute(0, 2, 1).unsqueeze(-1)   # (b, h, n, 1)
        out = out * gates
        out = out.permute(0, 2, 1, 3).reshape(b, n, -1)
        return self.to_out(out)


class Transformer(nn.Module):
    def __init__(self, *, dim, depth, dim_head, heads, rotary_embed, ff_mult=4):
        super().__init__()
        self.layers = nn.ModuleList([
            nn.ModuleList([Attention(dim, heads, dim_head, rotary_embed), FeedForward(dim, ff_mult)])
            for _ in range(depth)
        ])
        self.norm = RMSNorm(dim)

    def forward(self, x):
        for attn, ff in self.layers:
            x = attn(x) + x
            x = ff(x) + x
        return self.norm(x)


class BandSplit(nn.Module):
    def __init__(self, dim: int, dim_inputs: tuple[int, ...]):
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_features = nn.ModuleList([nn.Sequential(RMSNorm(d), nn.Linear(d, dim)) for d in dim_inputs])

    def forward(self, x):
        parts = x.split(self.dim_inputs, dim=-1)
        return torch.stack([f(p) for p, f in zip(parts, self.to_features)], dim=-2)


def _mlp(dim_in: int, dim_out: int, dim_hidden: int, depth: int) -> nn.Sequential:
    dims = (dim_in, *((dim_hidden,) * depth), dim_out)
    layers: list[nn.Module] = []
    for i, (a, b) in enumerate(zip(dims[:-1], dims[1:])):
        layers.append(nn.Linear(a, b))
        if i < len(dims) - 2:
            layers.append(nn.Tanh())
    return nn.Sequential(*layers)


class MaskEstimator(nn.Module):
    def __init__(self, dim: int, dim_inputs: tuple[int, ...], depth: int, mlp_expansion_factor: int = 4):
        super().__init__()
        self.dim_inputs = dim_inputs
        hidden = dim * mlp_expansion_factor
        self.to_freqs = nn.ModuleList([
            nn.Sequential(_mlp(dim, d * 2, hidden, depth), nn.GLU(dim=-1)) for d in dim_inputs
        ])

    def forward(self, x):
        bands = x.unbind(dim=-2)
        return torch.cat([fn(b) for b, fn in zip(bands, self.to_freqs)], dim=-1)


# --- model ---------------------------------------------------------------------------

class MelBandRoformer(nn.Module):
    def __init__(self, *, dim, depth, stereo=True, num_stems=1, time_transformer_depth=1,
                 freq_transformer_depth=1, num_bands=60, dim_head=64, heads=8, sample_rate=44100,
                 stft_n_fft=2048, stft_hop_length=512, stft_win_length=2048, stft_normalized=False,
                 mask_estimator_depth=1, mlp_expansion_factor=4, zero_dc=True, **_ignored):
        super().__init__()
        self.stereo = stereo
        self.audio_channels = 2 if stereo else 1
        self.num_stems = num_stems
        self.zero_dc = zero_dc

        self.layers = nn.ModuleList([])
        time_rot = RotaryEmbedding(dim=dim_head)
        freq_rot = RotaryEmbedding(dim=dim_head)
        for _ in range(depth):
            self.layers.append(nn.ModuleList([
                Transformer(dim=dim, depth=time_transformer_depth, dim_head=dim_head, heads=heads,
                            rotary_embed=time_rot),
                Transformer(dim=dim, depth=freq_transformer_depth, dim_head=dim_head, heads=heads,
                            rotary_embed=freq_rot),
            ]))

        self.stft_win_length = stft_win_length
        self.stft_kwargs = dict(n_fft=stft_n_fft, hop_length=stft_hop_length, win_length=stft_win_length,
                                normalized=stft_normalized)
        n_freqs = stft_n_fft // 2 + 1

        mel = torch.from_numpy(mel_filter_bank(sample_rate, stft_n_fft, num_bands))
        mel[0][0] = 1.0
        mel[-1, -1] = 1.0
        freqs_per_band = mel > 0
        if not bool(freqs_per_band.any(dim=0).all()):
            raise ValueError("mel bands do not cover every frequency")
        freq_indices = torch.arange(n_freqs).unsqueeze(0).expand(num_bands, -1)[freqs_per_band]
        if stereo:
            freq_indices = (freq_indices.unsqueeze(-1) * 2 + torch.arange(2)).reshape(-1)
        self.register_buffer("freq_indices", freq_indices, persistent=False)
        num_freqs_per_band = freqs_per_band.sum(dim=1)
        self.register_buffer("num_bands_per_freq", freqs_per_band.sum(dim=0), persistent=False)

        dim_inputs = tuple(2 * int(f) * self.audio_channels for f in num_freqs_per_band.tolist())
        self.band_split = BandSplit(dim, dim_inputs)
        self.mask_estimators = nn.ModuleList([
            MaskEstimator(dim, dim_inputs, mask_estimator_depth, mlp_expansion_factor) for _ in range(num_stems)
        ])

    def forward(self, raw_audio: torch.Tensor) -> torch.Tensor:
        """raw_audio (b, channels, t) -> (b, stems, channels, t') ; (b, channels, t') for one stem."""
        device = raw_audio.device
        if raw_audio.ndim == 2:
            raw_audio = raw_audio.unsqueeze(1)
        batch, channels, length = raw_audio.shape
        window = torch.hann_window(self.stft_win_length, device=device)

        flat = raw_audio.reshape(batch * channels, length)
        spec = torch.view_as_real(torch.stft(flat, **self.stft_kwargs, window=window, return_complex=True))
        n_f, n_t = spec.shape[1], spec.shape[2]
        spec = spec.reshape(batch, channels, n_f, n_t, 2)
        spec = spec.permute(0, 2, 1, 3, 4).reshape(batch, n_f * channels, n_t, 2)   # b (f s) t c

        x = spec[:, self.freq_indices]                                             # b f' t c
        x = x.permute(0, 2, 1, 3).reshape(batch, n_t, -1)                           # b t (f c)
        x = self.band_split(x)                                                      # b t bands d

        for time_tr, freq_tr in self.layers:
            b, t, f, d = x.shape
            x = x.permute(0, 2, 1, 3).reshape(b * f, t, d)
            x = time_tr(x)
            x = x.reshape(b, f, t, d).permute(0, 2, 1, 3).reshape(b * t, f, d)
            x = freq_tr(x)
            x = x.reshape(b, t, f, d)

        masks = torch.stack([fn(x) for fn in self.mask_estimators], dim=1)        # b n t (f c)
        n = masks.shape[1]
        masks = masks.reshape(batch, n, n_t, -1, 2).permute(0, 1, 3, 2, 4).contiguous()  # b n f t c
        masks = torch.view_as_complex(masks)

        spec_c = torch.view_as_complex(spec.contiguous()).unsqueeze(1)              # b 1 (f s) t
        masks = masks.to(spec_c.dtype)
        idx = self.freq_indices.view(1, 1, -1, 1).expand(batch, n, -1, n_t)
        summed = torch.zeros(batch, n, spec_c.shape[2], n_t, dtype=spec_c.dtype, device=device)
        summed = summed.scatter_add_(2, idx, masks)
        denom = self.num_bands_per_freq.repeat_interleave(channels).view(-1, 1)
        out = spec_c * (summed / denom.clamp(min=1e-8))
        out = out.reshape(batch * n, n_f, channels, n_t).permute(0, 2, 1, 3).reshape(batch * n * channels, n_f, n_t)
        if self.zero_dc:
            out[:, 0] = 0.0
        audio = torch.istft(out, **self.stft_kwargs, window=window, return_complex=False)
        audio = audio.reshape(batch, n, channels, -1)
        return audio[:, 0] if n == 1 else audio
