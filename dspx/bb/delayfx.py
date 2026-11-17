"""Shared whole-context delay composition, built on BB-09/13/14.

dl_parameters(**overrides): fresh DL+SD declarations; overrides map IDs to
declaration fields. duration(p, maximum=4000): resolved milliseconds.
validate_delay(p, maximum=4000, longest=None, gain=1): tempo and CT-8 bound.
feedback_audio(x, delays, feedback, factory=None, method='lagrange3'):
zero-state wet output; factory() supplies a fresh stateful loop callback.
Short centred reads use a whole-context fixed-point solve, never a delay clamp.
TapeLoop(sr, channels, p, dub=False): stateful unity-bounded loop processing.
tape_wet(x,sr,p,delays,dub=False): 2x BB-13 loop when drive is nonzero;
delays is callable(frames, operating_sr) returning sample delays.
finish(dry,wet,sr,p,stats=None): SD then linear mixing and R-10 measurements.
All functions require float64 frames x channels and full history from zero.
Independent equations; scipy.signal public filter APIs (BSD-3-Clause).
"""
import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError


def dl_parameters(**overrides):
    from mankomix.dspx.bb.delayline import dl_params
    from mankomix.dspx.bb.selfduck import sd_params
    out = [dict(s) for s in dl_params() if not s['id'].startswith('duck_')] + sd_params()
    for s in out:
        s.update(overrides.get(s['id'], {}))
    return out


def definition(kind, params, *, implemented=False):
    return dict(type=kind, implemented=implemented, description=kind.replace('_', ' '),
                params=params, stages=['track', 'bus'], master_slot=None,
                realtime=dict(block_ok=False, allocates=True, latency_samples=0),
                offline_only=False, backends=['reference'], channel_ok=False)


def duration(p, maximum=4000):
    from mankomix.dspx.bb.curves import period_ms
    ms = period_ms(p['time_ms'], note=p['note'], bpm=p['bpm'])
    if ms > maximum:
        raise ParamError(f'note duration exceeds {maximum} ms')
    return ms


def validate_delay(p, maximum=4000, *, longest=None, gain=1):
    """Reject time/feedback pairs outside the established 60-second bound.

    The scalar ranges remain spec ranges. Like W1's validate_feedback, this
    is a relationship restriction, not a silent change to the feedback value.
    Supports the dub endpoint .98 and normalised head/filter peak bounds.
    """
    ms = duration(p, maximum) if longest is None else longest
    duration(p, maximum)
    repeats = max(1, int(np.floor(59000 / ms)) - 1)
    f = abs(p['feedback'])
    if f and gain * f**repeats / (1-f) >= 1e-6*(1-1e-9):
        raise ParamError('feedback/time combination cannot meet 60 s / -120 dB CT-8 bound')


def feedback_audio(x, delays, feedback, factory=None, method='lagrange3'):
    from mankomix.dspx.bb.delayline import DelayLine, fractional_delay
    if not len(x):
        return x.copy()
    d = np.broadcast_to(np.asarray(delays, dtype=np.float64), x.shape)
    if not feedback:
        return fractional_delay(x, d, method)
    reserve = {'integer': 1, 'lagrange3': 3, 'sinc8': 5}[method]
    if np.all((d >= reserve) | ((d == np.rint(d)) & (d >= 1))):
        return DelayLine(float(np.max(d)), x.shape[1], method).process(
            x, d, abs(feedback), None if factory is None else factory(),
            matrix=np.eye(x.shape[1])*np.sign(feedback))
    wet = np.zeros_like(x)
    for _ in range(2048):
        loop = None if factory is None else factory()
        v = wet if loop is None else loop(wet)
        updated = fractional_delay(x + feedback*v, d, method)
        if np.max(np.abs(updated-wet), initial=0) < 2e-14:
            return updated
        wet = updated
    raise ParamError('short fractional feedback solve did not converge')


class TapeLoop:
    """Stateful tanh, head EQ / dub narrowing, and optional allpass diffusion.

    tanh(g*x)/g has derivative one at zero. The head peak is divided by its
    theoretical maximum amplitude, so its loop gain stays at most one.
    The oversampling wrapper operates on the complete line, not each chunk.
    """
    def __init__(self, sr, channels, p, dub=False):
        from mankomix.dspx.bb.delayline import LoopFilter
        self.drive = 10**(p.get('drive_db', 0)/20)
        self.saturate = bool(p.get('drive_db', 0))
        low = min(p['lowcut_hz'], .49*sr)
        self.eq = LoopFilter(sr, channels, low, p['highcut_hz'])
        self.extra = LoopFilter(sr, channels, low, p['highcut_hz']) if dub else None
        self.narrow = p.get('narrow', 0) if dub else 0
        self.head = None
        self.head_gain = 1.
        if not dub and p.get('head_bump_db', 0):
            from mankomix.dsp.reference.filters import rbj_biquad
            self.head = rbj_biquad('peak', min(100, .1*sr), p['head_bump_db'], 1, sr)
            self.zi = np.zeros((len(self.head), 2, channels))
            self.head_gain = 10**(-p['head_bump_db']/20)
        self.diffusers = []
        if dub and p.get('diffusion', 0):
            from mankomix.dspx.bb.reverb import Allpass
            self.diffusers = [Allpass(max(1, round(sr*t)), .6*p['diffusion'], channels)
                              for t in (.0017, .0031)]

    def __call__(self, x):
        y = np.tanh(self.drive*x)/self.drive if self.saturate else x
        if self.head is not None and len(x):
            y, self.zi = signal.sosfilt(self.head, y, axis=0, zi=self.zi)
            y = y*self.head_gain
        y = self.eq(y)
        if self.extra is not None:
            filtered = self.extra(y)
            y = (1-self.narrow)*y + self.narrow*filtered
        for diffuser in self.diffusers:
            y = diffuser.process(y)
        return y


def tape_wet(x, sr, p, delays, *, dub=False):
    from mankomix.dspx.bb.nonlinear import oversampled
    factor = 2 if p['drive_db'] else 1
    def render(up):
        rate = sr*factor
        d = delays(len(up), rate)
        return feedback_audio(up, d, p['feedback'],
                              lambda: TapeLoop(rate, x.shape[1], p, dub), 'lagrange3')
    return oversampled(x, factor, render)


def finish(dry, wet, sr, p, stats=None, *, dry_gain=None):
    from mankomix.dspx.bb.selfduck import duck_wet
    from mankomix.dspx.bb.delayline import spatial_stats
    if p['mix'] == 0:
        return dry.copy(), sr, spatial_stats(dry, sr)
    wet = duck_wet(dry, wet, sr, p)
    aligned = np.repeat(dry, wet.shape[1], axis=1) if dry.shape[1] == 1 and wet.shape[1] > 1 else dry
    if dry_gain is not None:
        aligned = aligned*dry_gain
    y = wet if p['mix'] == 1 else (1-p['mix'])*aligned + p['mix']*wet
    result = spatial_stats(y, sr, p.get('time_ms', p.get('delay_ms')))
    result.update(stats or {})
    result.update(latency_samples=0, duck_db=p.get('duck_db', 0))
    return y, sr, result


def render_with_history(fn, x, sr, p, *, seed=0, history=None):
    """Replay a supplied prefix; returns the same excerpt as full rendering."""
    if history is None:
        return fn(x, sr, p, seed=seed)
    y, rate, stats = fn(np.concatenate((history, x)), sr, p, seed=seed)
    return y[len(history):], rate, stats
