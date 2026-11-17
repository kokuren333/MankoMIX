"""Long-window random-phase overlap-add, independently written from its equations."""
import numpy as np
from scipy import fft, signal, ndimage
from mankomix.dspx.bb.curves import modulation_seed
from . import OpSpec, DerivedPlan
from . import _clip_edit as H


def resolve(move):
    p = H.resolve(move, {'ratio': (2, 200, 8), 'window_s': (.05, 2, .25),
                          'onset': (0, 1, 0), 'seed': (0, 65535, 0), 'max_out_s': (1, 3600, 600)},
                  {'fit': (['keep_start', 'keep_length'], 'keep_start')}, {'section'})
    if type(p['seed']) is not int:
        raise ValueError('seed must be an integer')
    return p


def validate(move, ctx):
    H.validate(move, ctx, resolve)
    if ctx.project is not None:
        try:
            p = resolve(move)
            a, b = H.interval(ctx.project.data, move['target'], p, ctx.project.rate)
            if round((b-a)*p['ratio']) > round(p['max_out_s']*ctx.project.rate):
                raise ValueError('max_out_s exceeded')
        except (ValueError, TypeError, KeyError) as exc:
            ctx.err('bad_value', str(exc))


def calculate(x, sr, p):
    nout = round(len(x)*p['ratio'])
    if nout > round(p['max_out_s']*sr):
        raise ValueError('max_out_s exceeded')
    if not np.any(x):
        return np.zeros((nout, x.shape[1]))
    size = max(16, round(p['window_s']*sr)//2*2)
    hop = max(1, size//8)
    out = np.zeros((nout+2*size, x.shape[1]))
    norm = np.zeros(len(out))
    padded = np.pad(x, ((size, size), (0, 0)))
    previous = None
    for index, center in enumerate(range(-size//2, nout+size//2, hop)):
        at = int(np.clip(round(center/p['ratio']), 0, len(x)-1))
        block = padded[at+size-size//2:at+size+size//2]
        magnitude = abs(fft.rfft(block*signal.windows.hann(size, sym=False)[:, None], axis=0, workers=1))
        flux = 0 if previous is None else np.sum(np.maximum(magnitude-previous, 0))/max(float(previous.sum()), 1e-30)
        previous = magnitude
        local_size = max(16, round(size/(1+3*p['onset']*min(1., flux)))//2*2)
        win = signal.windows.hann(local_size, sym=False)
        block = padded[at+size-local_size//2:at+size+local_size//2]*win[:, None]
        spectrum = fft.rfft(block, axis=0, workers=1)
        rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([p['resolved_seed'], index])))
        phase = rng.uniform(-np.pi, np.pi, (len(spectrum), 1))
        # A shared random rotation retains channel phase relationships.
        rotation = np.exp(1j*phase)
        rotation[0] = 1
        rotation[-1] = 1
        wet = fft.irfft(spectrum*rotation, n=local_size, axis=0, workers=1)*win[:, None]
        a = center-local_size//2+size
        out[a:a+local_size] += wet
        norm[a:a+local_size] += win*win
    y = out[size:size+nout]/np.sqrt(np.maximum(norm[size:size+nout], 1e-30))[:, None]
    # Random phase interference changes local energy. Normalize the OLA energy
    # to the mapped source RMS, retaining source dynamics and exact silence.
    width = max(1, round(sr*.01))
    target = ndimage.uniform_filter1d(np.mean(x*x, axis=1), width, mode='nearest')
    target = np.interp(np.arange(nout)/p['ratio'], np.arange(len(x)), target)
    for _ in range(3):
        power = ndimage.uniform_filter1d(np.mean(y*y, axis=1), width, mode='nearest')
        y *= np.sqrt(target/np.maximum(power, 1e-30))[:, None]
    return y


def derive(root, move):
    p = resolve(move)
    x, sr, data, a, b = H.source(root, move, p)
    p.update(resolved_seed=modulation_seed(data.get('seed', 0), move['id'], p['seed']),
             requested_fit=p['fit'], fit='keep_length')
    y = calculate(x[a:b].copy(), sr, p)
    rec = H.record(x[a:b], H.fitted(y, b-a), sr, natural_frames=len(y), requested_fit=p['requested_fit'])
    rec['calculated_frames'] = len(y)
    return DerivedPlan(a, b, p, calculate, record=rec)


OPS = {'edit_stretch_extreme': OpSpec('edit', ('target',), validate,
                                       derive=derive, code_version='w4d-extreme-1', time_varying=True)}
