"""Independent dispersive waveguide IR design, float64, fixed initial rest.

Sources: Valimaki, Parker & Abel, JAES 58 (2010), pp. 547-562 (structure);
DAFx-11, 39_e.pdf, section 2 (stretched allpass low/high paths).
https://www.dafx.de/paper-archive/2011/Papers/39_e.pdf
No implementation source or measured commercial response was used.
SciPy 1.18.1 FFT/signal public APIs, BSD-3-Clause, no source port.

API: spring_lines(sr,p,seed=0) returns independently seeded round-trip
sample lengths. spectral_delay(z,sr,p,high=False) evaluates a cascade of
32 low / 8 high stretched allpasses at complex z^-1. render_spring_ir(sr,p,
seed=0) returns (frames,2,2) IR plus R-10 stats, with immutable cached IR.
propagation_delay(sr,p,total,high=False) subtracts the allpass group delay
at 200 Hz from the requested total round-trip delay.
Poles are contracted by exp(-ln(1000)/(sr*rt60_s)): distributed loss per
sample, including allpass states and the delay line. This avoids an
unstable inverse or an incorrect scalar gain ignoring allpass delay.
"""
import numpy as np
from scipy import signal
from scipy.fft import irfft, next_fast_len
from functools import lru_cache


def spring_lines(sr, p, seed=0):
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), int(p['seed'])])))
    # Disjoint narrow intervals keep all line periods within +/- 5 percent.
    ratios = np.linspace(.965, 1.035, p['springs']) if p['springs'] > 1 else np.ones(1)
    ratios += rng.uniform(-.0002, .0002, p['springs'])
    return np.maximum(1, np.rint(sr*p['delay_ms']*.001*ratios).astype(int))


def spectral_delay(z, sr, p, high=False):
    if not p['dispersion']:
        return np.ones_like(z)
    stretch = max(1, int(sr/(2*p['chirp_hz']))) if not high else 1
    stages = 8 if high else 32
    a = (.15 if high else .65)*p['dispersion']
    w = z**stretch
    return ((a+w)/(1+a*w))**stages


def propagation_delay(sr, p, total, high=False):
    """Delay line after subtracting allpass group delay at 200 Hz."""
    if not p['dispersion']:
        return int(total)
    stretch = max(1, int(sr/(2*p['chirp_hz']))) if not high else 1
    sections, a = (8,.15*p['dispersion']) if high else (32,.65*p['dispersion'])
    phase = 2*np.pi*200*stretch/sr
    base = sections*stretch*(1-a*a)/(1+a*a+2*a*np.cos(phase))
    return max(1, int(total)-round(base))


@lru_cache(maxsize=12)
def _design(sr, items, seed):
    from mankomix.dspx.bb.reverb import measure_ir
    p = dict(items)
    duration = 3*p['rt60_s']+1+p['predelay_ms']*.001
    frames = int(np.ceil(duration*sr))
    count = next_fast_len(2*frames)
    f = np.arange(count//2+1)*sr/count
    omega = 2*np.pi*f/sr
    radius = np.exp(-np.log(1000)/(sr*p['rt60_s']))
    z = radius*np.exp(-1j*omega)
    low = spectral_delay(z, sr, p)
    high = spectral_delay(z, sr, p, high=True)
    split = 1/np.sqrt(1+(f/p['chirp_hz'])**8)
    spectrum = np.zeros((len(z), 2), dtype=np.complex128)
    lines = spring_lines(sr, p, seed)
    rng = np.random.Generator(np.random.PCG64(int(seed)+p['seed']+917))
    for i, length in enumerate(lines):
        for side in range(2):
            # Allpass output decorrelation preserves magnitude and decay.
            pan = .95+.01*rng.random()
            ql = z**propagation_delay(sr,p,length)*low
            qh = z**propagation_delay(sr,p,length,high=True)*high
            response = split*ql/(1-ql)+.18*(1-split)*qh/(1+qh)
            c = .2+.3*rng.random()
            response *= (c+z)/(1+c*z)
            spectrum[:, side] += pan*response/np.sqrt(p['springs'])
    pair = irfft(spectrum, n=count, axis=0, workers=1)[:frames]
    # Excitation/output damping sets spectral colour; loss is distributed
    # in the propagation structure, preserving the declared decay constant.
    for freq, kind in [(p['lowcut_hz'], 'highpass'),
                       (min(p['damping_hz'], p['highcut_hz']), 'lowpass')]:
        if kind == 'lowpass' and freq >= .45*sr:
            continue
        pair = signal.sosfilt(signal.butter(2, min(freq,.49*sr), kind, fs=sr, output='sos'), pair, axis=0)
    delay = round(p['predelay_ms']*.001*sr)
    if delay:
        pair = np.pad(pair, ((delay,0),(0,0)))[:frames]
    # Fixed gain, no normalization depending on input or rendered duration.
    pair *= .2
    h = np.zeros((frames,2,2))
    h[:,0,0], h[:,1,1] = pair[:,0], pair[:,1]
    stats = measure_ir(h, sr, p)
    stats.update(spring_delays_samples=lines.tolist(), dispersion_sections_low=32,
                 dispersion_sections_high=8, decay_design='distributed_pole_contraction',
                 group_delay_direction='increasing_below_chirp', execution='lti')
    h.setflags(write=False)
    return h, stats


def render_spring_ir(sr, p, seed=0):
    keys = ('rt60_s','delay_ms','chirp_hz','dispersion','damping_hz','springs',
            'seed','lowcut_hz','highcut_hz','predelay_ms','mix')
    h, stats = _design(sr, tuple((k,p[k]) for k in keys), int(seed))
    from copy import deepcopy
    return h, deepcopy(stats)
