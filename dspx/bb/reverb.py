"""BB-10: independent orthogonal FDN and allpass reverberation primitives.

Formula sources (no third-party implementation copied): J. O. Smith,
Physical Audio Signal Processing, Artificial Reverberation,
https://www.dsprelated.com/freebooks/pasp/Artificial_Reverberation.html ;
Valimaki et al., Fifty Years of Artificial Reverberation, TASLP 20 (2012).
Velvet IR construction follows the pulse-cell definition in Valimaki et al.,
Applied Sciences 7, 483 (2017), https://doi.org/10.3390/app7050483 .

Public API: orthogonal_matrix(8|16); delay_lengths(sr, size_m, lines, seed);
rt60_gain(delay_samples, sr, rt60_s); absorption_sos(delay, sr, rt_tuple,
low_xover=250, high_xover=4000, order=2); Allpass(delay, gain, channels).process(x);
AllpassTank(sr, rt60_s=2, diffusion=.6, seed=0).process(stereo);
FDN(sr, params, chamber=False, seed=0, absorption_order=2).process(stereo, mod_depth=None);
early_reflections(sr, frames, size_m, seed=0); render_ir(sr, params,
chamber=False, seed=0, frames=None, absorption_order=2); process_reverb(x, sr, params,
chamber=False, seed=0, execution=None, absorption_order=2); velvet_ir(sr, duration_ms, params,
shape='flat', seed=0); measure_ir(h, sr, params, modulation_stopped=False).
validate_decay_rv(params) adds the hall/chamber-only 24 s longest-band limit;
validate_rv(params) and the existing rendering APIs retain their default behavior.
absorption_order=4 opts into flatter shelves used by hall/chamber only.
FDN/process_reverb also accept mod_interpolation='sinc8' (legacy default);
hall opts into 'lagrange3' to avoid gain above unity in the feedback reads.
IRs have shape (frames, input=2, output=2); processors preserve mono/stereo.
All states start at zero. DelayLine supplies feedback and fractional reads;
BB-07 supplies FFT convolution. lti and unmodulated tv use identical kernels.
"""
from __future__ import annotations

import math
from functools import lru_cache
import numpy as np
from scipy import signal

from mankomix.dsp.errors import ParamError
from mankomix.dspx.params import _f, _i
from mankomix.dspx.bb.curves import modulation_seed
from mankomix.dspx.bb.delayline import DelayLine, LoopFilter, fractional_delay, integer_feedback
from mankomix.dspx.bb.fir import fft_convolve
from mankomix.dspx.bb.selfduck import sd_params, duck_wet

NOTE_VALUES = ["none"] + [f"1/{d}{m}" for d in (1, 2, 4, 8, 16, 32, 64) for m in ("", "d", "t")]


def rv_params(rt_min=.3, rt_max=10, rt_default=2, predelay=20, *, sd=True, pre=True):
    p = [_f("rt60_s", "s", rt_min, rt_max, rt_default, "Mid-band reverberation time."),
         _f("mix", None, 0, 1, .2, "Dry/wet; zero bypasses exactly."),
         _f("lowcut_hz", "Hz", 20, 2000, 300, "Wet highpass."),
         _f("highcut_hz", "Hz", 1000, 20000, 8000, "Wet lowpass; bypass above .45 sr."),
         _f("bpm", "BPM", 0, 400, 0, "Tempo for note records."),
         _i("seed", None, 0, 65535, 0, "Deterministic room seed.")]
    if pre:
        p.insert(1, _f("predelay_ms", "ms", 0, 250, predelay, "Wet predelay."))
    return p + (sd_params() if sd else [])


def definition(kind, params, *, implemented=False, offline=False):
    return {"type": kind, "description": kind.replace("_", " "), "stages": ["track", "bus"],
            "master_slot": None, "params": params, "implemented": implemented,
            "offline_only": offline, "backends": ["reference"], "channel_ok": False,
            "realtime": {"block_ok": False, "latency_samples": 0, "allocates": True}}


def validate_rv(p):
    if 0 < p.get("bpm", 0) < 20:
        raise ParamError("bpm must be zero or at least 20")
    if p.get("low_xover_hz", 250) >= p.get("high_xover_hz", 4000):
        raise ParamError("low crossover must be below high crossover")


def validate_decay_rv(p):
    """Hall/chamber RV validation, with a measured CT-8 decay limit.

    Keep the shared RV validator and all rendering primitives unrestricted.
    A 24 s longest band gives 150 dB nominal decay over 60 s, leaving
    30 dB for excitation, routing and the peak rather than RMS criterion.
    """
    validate_rv(p)
    longest = p["rt60_s"] * max(1, p.get("rt60_low_mult", 1), p.get("rt60_high_mult", 1))
    if longest > 24:
        raise ParamError("rt60_s * max(1, rt60_low_mult, rt60_high_mult) must be <= 24 s "
                         "(60 s / -120 dBFS CT-8 decay limit)")


def orthogonal_matrix(lines=16):
    if lines not in (8, 16):
        raise ValueError("FDN requires 8 or 16 lines")
    h = np.ones((1, 1))
    while len(h) < lines:
        h = np.block([[h, h], [h, -h]])
    return h / math.sqrt(lines)


def delay_lengths(sr, size_m, lines=16, seed=0):
    """Distinct primes near geometry-scaled lengths; pairwise coprime."""
    rng = np.random.Generator(np.random.PCG64(seed))
    base = size_m / 343 * (0.35 if lines == 16 else .45)
    result = []
    for t in np.linspace(.65, 1.65, lines) * rng.uniform(.97, 1.03, lines):
        n = max(5, round(base * t * sr))
        while n in result or any(n % d == 0 for d in range(2, math.isqrt(n) + 1)):
            n += 1
        result.append(n)
    return np.array(result, dtype=int)


def rt60_gain(delay_samples, sr, rt60_s):
    """Amplitude attenuation per traversal: exp(-ln(1000)*D/(sr*T60))."""
    if sr <= 0 or np.any(np.asarray(rt60_s) <= 0):
        raise ValueError("positive sr and RT60 required")
    return np.exp(-math.log(1000) * np.asarray(delay_samples) / (sr * rt60_s))


def absorption_sos(delay, sr, rt_tuple, low_xover=250, high_xover=4000, *, order=2):
    """Per-traversal absorption; order=2 preserves the original biquad design.

    order=4 uses Butterworth shelves with flatter band interiors. Each shelf
    has the specified asymptotic gains and their geometric mean at crossover.
    """
    from mankomix.dsp.reference.filters import rbj_biquad
    db = -60 * delay / (sr * np.asarray(rt_tuple))
    low_xover, high_xover = min(low_xover, .2*sr), min(high_xover, .4*sr)
    if order == 4:
        def shelf(freq, low_db, high_db):
            # Scale a normalized Butterworth pole set separately for zeros
            # and poles, then use the prewarped bilinear transform.
            _, poles, _ = signal.buttap(order)
            corner = 2*sr*math.tan(math.pi*freq/sr)
            ratio = 10**((low_db-high_db)/(40*order))
            z, a, gain = signal.bilinear_zpk(poles*corner*ratio, poles*corner/ratio,
                                            10**(high_db/20), fs=sr)
            return signal.zpk2sos(z, a, gain)
        sos = np.vstack([shelf(low_xover, db[0]-db[1], 0),
                         shelf(high_xover, 0, db[2]-db[1])])
        sos[0, :3] *= 10 ** (db[1] / 20)
        return sos
    if order != 2:
        raise ValueError("absorption order must be 2 or 4")
    sos = np.vstack([rbj_biquad("low_shelf", low_xover, db[0]-db[1], 1.9, sr),
                     rbj_biquad("high_shelf", high_xover, db[2]-db[1], 1.9, sr)])
    sos[0, :3] *= 10 ** (db[1] / 20)
    return sos


class Allpass:
    """H(z)=(-g+z^-D)/(1-g*z^-D), state retained across calls."""
    def __init__(self, delay, gain, channels=2):
        if not 0 <= gain < 1:
            raise ValueError("allpass gain must be in [0,1)")
        self.delay, self.gain = int(delay), float(gain)
        self.history = np.zeros((self.delay, channels))

    def process(self, x):
        # Independent residue classes of the delayed recurrence. Preserve the
        # untouched residues in a partial final row, then rotate to the next
        # absolute sample. This avoids a Python loop for sub-ms diffusers.
        n, channels = x.shape
        if not n:
            return x.copy()
        d = self.delay
        padded = np.zeros((math.ceil(n/d)*d, channels))
        padded[:n] = x
        rows = padded.reshape(-1, d, channels)
        v, _ = signal.lfilter([1.], [1., -self.gain], rows, axis=0, zi=self.gain*self.history[None])
        delayed = np.concatenate((self.history[None], v[:-1])).reshape(-1, channels)[:n]
        state = v[-1].copy()
        remainder = n % d
        if remainder:
            state[remainder:] = v[-2, remainder:] if len(v) > 1 else self.history[remainder:]
        self.history = np.roll(state, -remainder, axis=0)
        return -self.gain*x + (1-self.gain**2)*delayed


class AllpassTank:
    """Two cross-coupled allpass loops, exposed for subsequent tank types."""
    def __init__(self, sr, rt60_s=2, diffusion=.6, seed=0):
        rng = np.random.Generator(np.random.PCG64(seed))
        self.delays = np.rint(sr*np.array([.031, .037])*rng.uniform(.97, 1.03, 2)).astype(int)
        self.line = DelayLine(max(self.delays), 2, "integer")
        self.ap = Allpass(max(1, round(.0047*sr)), .2+.5*diffusion, 2)
        self.gains = rt60_gain(self.delays, sr, rt60_s)

    def process(self, x):
        return self.line.process(x, self.delays, 1., lambda v: self.ap.process(v)*self.gains,
                                 np.array([[0., -1.], [1., 0.]]))


class FDN:
    """8/16 delay lines with analytic per-band absorption and fixed routing."""
    def __init__(self, sr, params, *, chamber=False, seed=0, absorption_order=2,
                 mod_interpolation="sinc8"):
        p = params
        self.sr, self.p, self.chamber = sr, dict(p), chamber
        self.lines = 8 if chamber else 16
        self.seed = modulation_seed(seed, "bb10", p.get("seed", 0))
        self.delays = delay_lengths(sr, p.get("size_m", 6 if chamber else 25), self.lines, self.seed)
        self.matrix = orthogonal_matrix(self.lines)
        self.inject = self.matrix[[1, 2]]
        self.output = self.matrix[[5, 7]]
        depth = p.get("mod_depth", 0)
        self.rate = p.get("mod_rate_hz", .5)
        self.excursion = sr*.00008/max(.5, self.rate)
        self.line = DelayLine(max(self.delays)+self.excursion+1, self.lines,
                              mod_interpolation if depth else "integer")
        rt = (p["rt60_s"]*p.get("rt60_low_mult", 1), p["rt60_s"], p["rt60_s"]*p.get("rt60_high_mult", 1))
        self.sos = [absorption_sos(d, sr, rt, p.get("low_xover_hz", 250), p.get("high_xover_hz", 4000),
                                   order=absorption_order) for d in self.delays]
        self.zi = [np.zeros((len(sos), 2)) for sos in self.sos]
        diffusion = p.get("density", .9) if chamber else p.get("diffusion", .7)
        ms = [.13, .19, .29, .43, .61, .89, 1.27, 1.79] if chamber else [.73, 1.13, 1.79, 2.71, 4.13, 6.17]
        self.diffusers = [Allpass(max(1, round(t*sr/1000)), .25+.45*diffusion) for t in ms]
        self.phases = np.random.Generator(np.random.PCG64(self.seed)).uniform(0, 2*np.pi, self.lines)
        self.position = 0

    def _absorb(self, block):
        out = np.empty_like(block)
        for i in range(self.lines):
            out[:, i], self.zi[i] = signal.sosfilt(self.sos[i], block[:, i], zi=self.zi[i])
        return out

    def process(self, stereo, *, mod_depth=None, offline_diffusion=False):
        depth = self.p.get("mod_depth", 0) if mod_depth is None else mod_depth
        u = np.asarray(stereo, dtype=np.float64)
        for ap in self.diffusers:
            if offline_diffusion:
                u = -ap.gain*u + (1-ap.gain**2)*integer_feedback(u, ap.delay, ap.gain)
            else:
                u = ap.process(u)
        injected = np.zeros((len(u), self.lines))
        for i in range(2):
            injected += u[:, i, None]*self.inject[i]
        ds = self.delays
        if depth:
            t = (self.position+np.arange(len(u))) / self.sr
            ds = ds + depth*self.excursion*np.sin(2*np.pi*self.rate*t[:, None]+self.phases)
        reads = self.line.process(injected, ds, 1., self._absorb, self.matrix)
        self.position += len(u)
        out = np.zeros((len(u), 2))
        for i in range(self.lines):
            out += reads[:, i, None]*self.output[:, i]
        # Delay-independent energy scaling (same scale for lti and tv).
        return out * math.sqrt(2*float(np.mean(self.delays))/self.sr)


def early_reflections(sr, frames, size_m, seed=0):
    """Geometry-scaled seeded taps, no direct sound."""
    h = np.zeros((frames, 2, 2))
    rng = np.random.Generator(np.random.PCG64(seed))
    for k, ratio in enumerate(np.linspace(.08, .9, 24)):
        for inp in range(2):
            pan = rng.uniform(-1, 1)
            for out in range(2):
                n = round(size_m/343 * ratio * sr) + out*max(1, round(.0003*sr))
                if n < frames:
                    angle = (pan+1)*np.pi/4
                    h[n, inp, out] += np.exp(-k/9) * (np.cos(angle) if out == 0 else np.sin(angle))*.15
    return h


def _stereo(x):
    if x.shape[1] not in (1, 2):
        raise ParamError("reverb requires mono or stereo")
    return np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x


def _wet_filter(x, sr, p):
    return LoopFilter(sr, x.shape[1], p.get("lowcut_hz", 300),
                      p.get("highcut_hz", 8000) if p.get("highcut_hz", 8000) < .45*sr else 0)(x)


def _late(x, sr, p, chamber, seed, depth=None, absorption_order=2, mod_interpolation="sinc8"):
    out = FDN(sr, p, chamber=chamber, seed=seed, absorption_order=absorption_order,
              mod_interpolation=mod_interpolation).process(
        x, mod_depth=depth, offline_diffusion=True)
    if chamber:
        rise = round(.04*p.get("distance", .5)*sr)
        if rise:
            out *= np.minimum(1., np.arange(len(out))/rise)[:, None]
    return out


def render_ir(sr, params, *, chamber=False, seed=0, frames=None, return_scales=False, absorption_order=2):
    """Unmodulated MIMO IR; default length is 140 dB of the slowest decay."""
    p = params
    validate_rv(p)
    pre = round(p.get("predelay_ms", 20)*sr/1000)
    max_rt = p["rt60_s"]*max(1, p.get("rt60_low_mult", 1), p.get("rt60_high_mult", 1))
    n = max(1, int(math.ceil((max_rt*140/60+.15)*sr))+pre) if frames is None else max(1, int(frames))
    h = np.zeros((n, 2, 2))
    count = max(0, n-pre)
    late_gain, er_gain = 1., 1.
    if count:
        for i in range(2):
            pulse = np.zeros((count, 2)); pulse[0, i] = 1
            h[pre:, i, :] = _late(pulse, sr, {**p, "mod_depth": 0}, chamber, seed, 0,
                                  absorption_order=absorption_order)
        energy = float(np.sum(h*h)/2)
        late_gain = 1/math.sqrt(energy) if energy else 1.
        h *= late_gain
        if not chamber:
            er = early_reflections(sr, count, p.get("size_m", 25), modulation_seed(seed, "er", p.get("seed", 0)))
            er_energy = float(np.sum(er*er)/2)
            ratio = 10**(p.get("er_late_db", 0)/10)
            er_gain = math.sqrt(ratio/(1+ratio)/er_energy) if er_energy else 1.
            late_gain /= math.sqrt(1+ratio)
            h /= math.sqrt(1+ratio)
            h[pre:] += er*er_gain
    h = _wet_filter(h.reshape(n, 4), sr, p).reshape(n, 2, 2)
    return (h, late_gain, er_gain) if return_scales else h


@lru_cache(maxsize=2)
def _cached_design(sr, items, chamber, seed, absorption_order=2):
    h, late, early = render_ir(sr, dict(items), chamber=chamber, seed=seed, return_scales=True,
                              absorption_order=absorption_order)
    h.setflags(write=False)
    return h, late, early


def measure_ir(h, sr, params, *, modulation_stopped=False):
    """R-10 vector. T20 is also independently checked by the test harness."""
    from mankomix.dsp.reference.space import schroeder_rt60, mono_fold
    h = np.asarray(h)
    pair = h.sum(axis=1) if h.ndim == 3 else h
    mid = pair.mean(axis=1, keepdims=True)
    pair = mid + params.get("width", 1)*(pair-mid)
    energy = float(np.sum(pair*pair)/2)
    split = round((params.get("predelay_ms", 0)/1000+.08)*sr)
    early, late = float(np.sum(pair[:split]**2)), float(np.sum(pair[split:]**2))
    mix = params.get("mix", .2)
    def band_time(f):
        values = [schroeder_rt60(pair[:, i], sr, f) for i in range(2)]
        return float(np.mean(values)) if all(v is not None for v in values) else None
    return {"rt60_measured_s": {str(f): band_time(f) if f < .45*sr else None for f in (125, 250, 1000, 4000, 8000)},
            "er_late_measured_db": 10*math.log10(early/late) if early and late else None,
            "wet_energy_db": 10*math.log10(energy) if energy else None,
            "dr_db_white": 20*math.log10((1-mix)/mix)-10*math.log10(energy) if 0 < mix < 1 and energy else None,
            "mono": mono_fold(pair[:, 0], pair[:, 1]),
            "measurement_modulation_stopped": bool(modulation_stopped), "ir_samples": len(h)}


def finish(dry, wet, sr, p, stats):
    """Wet-only SD then linear dry/wet; zero mix bypasses exactly."""
    wet = duck_wet(dry, wet, sr, p)
    mix = p["mix"]
    stats.update(latency_samples=0, tail_truncated_at_end=True, mix=mix, send_mode=mix == 1)
    if p.get("bpm", 0):
        from mankomix.dsp.reference.space import nearest_note
        stats["rt60_note"] = nearest_note(p["rt60_s"]*1000, p["bpm"])
        stats["predelay_note"] = nearest_note(p.get("predelay_ms", 0), p["bpm"])
    return (1-mix)*dry+mix*wet, sr, stats


def process_reverb(x, sr, params, *, chamber=False, seed=0, execution=None, absorption_order=2,
                   mod_interpolation="sinc8"):
    p = params
    validate_rv(p)
    if not p["mix"]:
        return x.copy(), sr, {"latency_samples": 0, "bypass": True}
    execution = execution or ("tv" if p.get("mod_depth", 0) else "lti")
    if execution not in ("lti", "tv"):
        raise ValueError("execution must be lti or tv")
    # Fixed measurement context, independent of input length; avoid hiding slow
    # tails in a truncated input. No cache keyed by mutable dictionaries.
    design = tuple(sorted((k, v) for k, v in p.items() if k not in
                          {"mix", "width", "bpm", "mod_depth", "mod_rate_hz"} and not k.startswith("duck_")))
    h, late_gain, er_gain = _cached_design(sr, design, chamber, seed, absorption_order)
    stereo = _stereo(x)
    if execution == "lti":
        wet = fft_convolve(stereo, h[:max(1, len(x))], "same")
    else:
        wet = _late(stereo, sr, p, chamber, seed, absorption_order=absorption_order,
                    mod_interpolation=mod_interpolation)*late_gain
        if not chamber:
            er = early_reflections(sr, max(1, round(.2*sr)), p.get("size_m", 25), modulation_seed(seed, "er", p.get("seed", 0)))
            wet += fft_convolve(stereo, er, "same")*er_gain
        wet = fractional_delay(wet, round(p.get("predelay_ms", 20)*sr/1000), "integer")
        wet = _wet_filter(wet, sr, p)
    if x.shape[1] == 1:
        wet = wet.mean(axis=1, keepdims=True)
    else:
        mid = wet.mean(axis=1, keepdims=True)
        wet = mid + p.get("width", 1)*(wet-mid)
    stats = measure_ir(h, sr, p, modulation_stopped=bool(p.get("mod_depth", 0)))
    stats.update(execution=execution, fdn_lines=8 if chamber else 16,
                 rt60_set_s={"low": p["rt60_s"]*p.get("rt60_low_mult", 1), "mid": p["rt60_s"], "high": p["rt60_s"]*p.get("rt60_high_mult", 1)})
    return finish(x, wet, sr, p, stats)


def velvet_ir(sr, duration_ms, params, *, shape="flat", seed=0):
    """One randomly positioned signed pulse per cell, then damping/envelope."""
    n = max(1, round(duration_ms*sr/1000))
    rng = np.random.Generator(np.random.PCG64(modulation_seed(seed, "velvet", params.get("seed", 0))))
    h = np.zeros((n, 2, 2))
    cell = max(1, round(sr/(500+params.get("density", .8)*15000)))
    for i in range(2):
        for o in range(2):
            starts = np.arange(0, n, cell)
            at = starts + rng.integers(0, cell, len(starts))
            at = at[at < n]
            h[at, i, o] = rng.choice([-1., 1.], len(at))
    cutoff = params.get("damping_hz", 8000)
    if cutoff < .45*sr:
        h = signal.sosfilt(signal.butter(2, cutoff, fs=sr, output="sos"), h, axis=0)
    u = np.arange(n)/max(1, n-1)
    env = np.ones(n) if shape == "flat" else (np.exp(-3*u) if shape == "decay" else u)
    nf = min(n, max(1, round(.005*sr)))
    env[-nf:] *= np.linspace(1, 0, nf)
    h *= env[:, None, None] / math.sqrt(max(1, n/cell))
    return h
