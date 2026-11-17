"""BB-12: fixed-grid YIN/pYIN via librosa 1.0.0 (ISC).

No third-party source is copied. The existing librosa public yin/pyin APIs
are called lazily. detect_pitch returns PitchTrack with absolute sample/time
centers, Hz (NaN when unvoiced), voiced mask and probability. hop_ms is rounded
once to an integer hop; frame centers are k*hop, including sample zero, strictly
before input end. sample_pitch uses nearest-center decisions without bridging
unvoiced gaps. Supply full audio for offline context, then slice the track.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
from mankomix.dsp.errors import ParamError


@dataclass(frozen=True)
class PitchTrack:
    samples: np.ndarray
    times_s: np.ndarray
    f0_hz: np.ndarray
    voiced: np.ndarray
    probability: np.ndarray
    sr: int
    hop_samples: int
    frame_length: int
    method: str


def detect_pitch(x, sr, *, method='pyin', fmin=50.0, fmax=1000.0,
                 hop_ms=10.0, frame_length=None, silence_db=-60.0,
                 voiced_threshold=None):
    """Analyze mono/(frames,channels); choose the highest-energy channel.

    YIN voicing uses normalized squared difference at the estimated lag
    (1-CMNDF), plus an explicit frame-energy floor. pYIN uses its public
    voiced probability and Viterbi decision, with the same energy floor.
    Default confidence thresholds are 0.5 (YIN) and 0.1 (pYIN probability).
    """
    if voiced_threshold is None:
        voiced_threshold = 0.1 if method == 'pyin' else 0.5
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if (a.ndim != 2 or a.shape[1] < 1 or not np.isfinite(a).all() or
            isinstance(sr, bool) or int(sr) != sr or sr <= 0 or
            not 0 < fmin < fmax < sr/2 or not math.isfinite(hop_ms) or hop_ms <= 0 or
            not math.isfinite(silence_db) or not 0 <= voiced_threshold <= 1 or
            method not in ('yin', 'pyin')):
        raise ParamError('invalid pitch input, range, grid or method')
    hop = max(1, int(round(hop_ms*sr/1000)))
    if frame_length is None:
        frame_length = 2**math.ceil(math.log2(max(256, 4*sr/fmin)))
    if (isinstance(frame_length, bool) or int(frame_length) != frame_length or
            frame_length < math.ceil(2*sr/fmin) + 1):
        raise ParamError('frame_length must cover at least two lowest periods')
    frame_length = int(frame_length)
    samples = np.arange(0, len(a), hop, dtype=np.int64)
    count = len(samples)
    f0 = np.full(count, np.nan)
    probability = np.zeros(count, dtype=np.float64)
    voiced = np.zeros(count, dtype=bool)
    if count and np.any(a):
        import librosa
        mono = a[:, int(np.argmax(np.sum(a*a, axis=0)))]
        pad = np.pad(mono, (frame_length//2, frame_length - frame_length//2))
        frames = np.lib.stride_tricks.sliding_window_view(pad, frame_length)[::hop][:count]
        cumulative = np.r_[0.0, np.cumsum(pad*pad)]
        energy = np.sqrt(np.maximum(0, cumulative[samples+frame_length]-cumulative[samples])/frame_length)
        kwargs = dict(sr=sr, fmin=fmin, fmax=fmax, frame_length=frame_length,
                      hop_length=hop, center=True, pad_mode='constant')
        if method == 'pyin':
            hz, flags, probs = librosa.pyin(mono, **kwargs, resolution=0.05)
            f0, probability = hz[:count].copy(), probs[:count].copy()
            voiced = flags[:count] & (probability >= voiced_threshold)
        else:
            f0 = librosa.yin(mono, **kwargs)[:count].copy()
            # The YIN confidence is estimated independently of librosa internals.
            for i, (frame, hz) in enumerate(zip(frames, f0)):
                lag = int(round(sr/hz))
                width = frame_length - math.ceil(sr/fmin) - 1
                diff = np.array([np.sum((frame[:width] - frame[t:t+width])**2)
                                 for t in range(1, lag+1)])
                denom = float(np.sum(diff))
                probability[i] = max(0.0, 1 - lag*diff[-1]/denom) if denom else 0
            voiced = probability >= voiced_threshold
        voiced &= (energy > 10**(silence_db/20)) & np.isfinite(f0)
        probability[energy <= 10**(silence_db/20)] = 0
        f0[~voiced] = np.nan
    return PitchTrack(samples, samples/sr, f0, voiced, probability, int(sr),
                      hop, frame_length, method)


def sample_pitch(track, samples):
    """Nearest fixed-grid (Hz, voiced, probability); out-of-range is unvoiced."""
    q = np.asarray(samples)
    if not np.isfinite(q).all():
        raise ParamError('pitch positions must be finite')
    if not len(track.samples):
        return np.full(q.shape, np.nan), np.zeros(q.shape, bool), np.zeros(q.shape)
    i = np.clip(np.floor(q/track.hop_samples + 0.5).astype(np.int64), 0, len(track.samples)-1)
    valid = (q >= 0) & (q <= track.samples[-1])
    return (np.where(valid, track.f0_hz[i], np.nan), valid & track.voiced[i],
            np.where(valid, track.probability[i], 0.0))
