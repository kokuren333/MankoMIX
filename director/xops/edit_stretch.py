"""BB-11 time stretching, including a piecewise linear source time map."""
import numpy as np
from scipy import fft, signal
from mankomix.dspx.bb import pitchtime as P
from . import OpSpec, DerivedPlan, ClipPlan
from . import _clip_edit as H


def resolve(move):
    p = H.resolve(move, {'ratio': (.25, 4, None), 'bpm_from': (20, 400, None),
                          'bpm_to': (20, 400, None), 'transients': (0, 1, .7)},
                  {'quality': (['standard', 'high'], 'high'),
                   'fit': (['keep_start', 'keep_length'], 'keep_start')}, {'section', 'map'})
    mapping = p.setdefault('map', [])
    if not isinstance(mapping, list) or len(mapping) > 1024 or any(
            not isinstance(v, list) or len(v) != 2 or not all(H.number(n) and n >= 0 for n in v) for v in mapping):
        raise ValueError('map needs at most 1024 nonnegative [source_s, output_s] pairs')
    if mapping and (len(mapping) < 2 or any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(mapping, mapping[1:]))):
        raise ValueError('map must increase strictly on both axes')
    bpm = 'bpm_from' in p or 'bpm_to' in p
    if bpm and not all(k in p for k in ('bpm_from', 'bpm_to')):
        raise ValueError('bpm_from and bpm_to must be supplied together')
    if ('ratio' in p)+bpm+bool(mapping) != 1:
        raise ValueError('choose exactly one of ratio, BPM pair or map')
    if bpm:
        p['ratio'] = p['bpm_from']/p['bpm_to']
        if not .25 <= p['ratio'] <= 4:
            raise ValueError('BPM pair gives ratio outside .25..4')
    return p


def validate(move, ctx):
    H.validate(move, ctx, resolve)
    if ctx.project is not None:
        try:
            p = resolve(move)
            a, b = H.interval(ctx.project.data, move['target'], p, ctx.project.rate)
            if p['map']:
                endpoints(p['map'], b-a, ctx.project.rate)
        except (ValueError, TypeError, KeyError) as exc:
            ctx.err('bad_value', str(exc))


def endpoints(mapping, n, sr):
    knots = np.asarray(mapping)*sr
    if abs(knots[0]).max() > .5 or abs(knots[-1, 0]-n) > .5:
        raise ValueError('map must cover [0,0] through the exact source duration')
    return knots


def mapped_high(x, sr, positions, transients):
    """BB-11c phase locking with analysis positions driven by the inverse map.

    Equations and primitives are the repository's BB-11 implementation. Phase
    advances on the synthesis clock; channels share the same peak rotations.
    """
    residual, events = P._separate_transients(x, sr) if transients > 0 else (x, [])
    size = P.latency_samples(sr, 'high')
    hop = max(1, size//8)
    spec, win = P._stft(residual, size, hop)
    ref = P._stft(P._reference(residual)[:, None], size, hop)[0][:, :, 0]
    omega = 2*np.pi*np.arange(size//2+1)/size
    delta = np.angle(ref[1:]*np.conj(ref[:-1]))-omega*hop
    frequency = omega+((delta+np.pi) % (2*np.pi)-np.pi)/hop
    phase, previous_peaks = np.angle(ref[0]), np.empty(0, int)
    previous_frequency, previous_mag = omega.copy(), abs(ref[0])
    out = np.zeros((len(positions)+size*2, x.shape[1]))
    norm = np.zeros(len(out))
    bins = np.arange(len(omega))
    for a in range(0, len(positions)+size//2, hop):
        source = positions[min(a, len(positions)-1)]
        if a >= len(positions) and len(positions) > 1:
            source += (a-len(positions)+1)*(positions[-1]-positions[-2])
        t = min(max(0., source/hop), len(spec)-1.0000001)
        i, u = int(t), t-int(t)
        mag = (1-u)*abs(spec[i])+u*abs(spec[i+1])
        refmag = (1-u)*abs(ref[i])+u*abs(ref[i+1])
        inphase = np.angle(ref[i])+u*hop*frequency[i]
        ft = max(0., min(t-.5, len(frequency)-1.))
        fi = min(int(ft), max(0, len(frequency)-2))
        fu = ft-fi
        freq = (1-fu)*frequency[fi]+fu*frequency[min(fi+1, len(frequency)-1)]
        flux = np.sum(np.maximum(refmag-previous_mag, 0))/max(float(previous_mag.sum()), 1e-20)
        reset = a == 0 or (transients > 0 and np.mean(refmag > refmag.max(initial=0)*.1) > .2
                           and flux > 1.05-transients)
        peaks = signal.find_peaks(refmag)[0]
        peaks = peaks[refmag[peaks] > refmag.max(initial=0)*1e-4]
        if len(peaks):
            if reset or not len(previous_peaks):
                peakphase = inphase[peaks]
            else:
                old = previous_peaks[np.searchsorted((previous_peaks[:-1]+previous_peaks[1:])/2, peaks)]
                peakphase = phase[old]+hop*.5*(previous_frequency[old]+freq[peaks])+np.pi*(peaks-old)
            nearest = peaks[np.searchsorted((peaks[:-1]+peaks[1:])/2, bins)]
            locked = peakphase[np.searchsorted((peaks[:-1]+peaks[1:])/2, bins)]+inphase-inphase[nearest]
        else:
            locked = inphase.copy() if reset else phase+hop*freq
        phase, previous_peaks, previous_frequency, previous_mag = locked.copy(), peaks, freq.copy(), refmag
        d = np.angle(spec[i+1]*np.conj(spec[i]))-hop*omega[:, None]
        chphase = np.angle(spec[i])+u*(hop*omega[:, None]+((d+np.pi) % (2*np.pi)-np.pi))
        block = fft.irfft(mag*np.exp(1j*(locked[:, None]+chphase-inphase[:, None])), n=size, axis=0, workers=1)
        out[a:a+size] += block*win[:, None]
        norm[a:a+size] += win*win
    out /= np.maximum(norm, 1e-15)[:, None]
    return P._restore_transients(out[size//2:size//2+len(positions)], events, 1, positions)


def calculate(x, sr, p):
    if p['map']:
        knots = endpoints(p['map'], len(x), sr)
        positions = np.interp(np.arange(round(knots[-1, 1])), knots[:, 1], knots[:, 0])
        if len(positions) == 0:
            raise ValueError('map output is shorter than one sample')
        if p['quality'] == 'standard':
            return P.wsola(x, sr, len(positions)/len(x), source_positions=positions)
        return mapped_high(x, sr, positions, p['transients'])
    if p['quality'] == 'standard':
        return P.wsola(x, sr, p['ratio'])
    return P.phase_vocoder(x, sr, p['ratio'], transients=p['transients'])


def derive(root, move):
    p = resolve(move)
    x, sr, data, a, b = H.source(root, move, p)
    p.update(seed=0, requested_fit=p['fit'], fit='keep_length')
    if not p['map'] and p['ratio'] == 1:
        return ClipPlan({}, p, H.record(x[a:b], x[a:b], sr, reason='unity ratio; no derived asset'))
    y = calculate(x[a:b].copy(), sr, p)
    rec = H.record(x[a:b], H.fitted(y, b-a), sr, natural_frames=len(y), requested_fit=p['requested_fit'])
    rec['calculated_frames'] = len(y)
    return DerivedPlan(a, b, p, calculate, record=rec)


OPS = {'edit_stretch': OpSpec('edit', ('target', 'params'), validate,
                               derive=derive, code_version='w4d-stretch-1', time_varying=True)}
