"""T10-14: delayed-source power estimates and conservative Wiener attenuation."""
import hashlib
import numpy as np
from mankomix.dspx.bb.align import estimate_delay
from mankomix.dspx.bb.delayline import fractional_delay
from mankomix.dspx.bb.stft import analyze, apply_gains, window_samples
from mankomix.dspx.bb.noise import suppression_gains
from mankomix.core.measure import loudness as L
from . import OpSpec, DerivedPlan
from . import _w4g as W

NUMERIC = {'reduction_db': (0, 30, 9, False), 'max_delay_ms': (0, 50, 20, False),
           'time_smooth_ms': (0, 300, 50, False), 'protect': (0, 1, .6, False)}


def validate(move, ctx):
    p = W.validate(move, ctx, NUMERIC, extra=('sources', 'section'))
    sources = p.get('sources')
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 8 or
            any(not isinstance(s, str) or not s.startswith('trk_') for s in sources)):
        ctx.err('bad_value', 'sources needs 1..8 track IDs')
        return
    if len(set(sources)) != len(sources) or move.get('target') in sources:
        ctx.err('bad_target', 'sources must be distinct and exclude target')
    if ctx.project is not None and any(s not in ctx.project.tracks() for s in sources):
        ctx.err('unknown_target', 'unknown source track')
    if 'section' in p and 'section' in move:
        ctx.err('bad_value', 'write section on the move or in params, not both')
    section = p.get('section')
    if section is not None and not isinstance(section, (str, dict)):
        ctx.err('bad_value', 'section must be an ID or {t0_s,t1_s}')


def audio_hash(x):
    return hashlib.sha256(np.ascontiguousarray(x, dtype='<f8').tobytes()).hexdigest()


def accounting(x, y, sr, rows):
    # Reuse restoration's event, band-energy and existing loudness/peak meters.
    from mankomix.dspx.procs.denoise import _account
    return {'sources': rows, **_account(x, y, sr),
            'before_lufs': float(L.integrated(x, sr)), 'after_lufs': float(L.integrated(y, sr)),
            'before_peak_dbfs': float(L.sample_peak_dbfs(x)), 'after_peak_dbfs': float(L.sample_peak_dbfs(y))}


def process(x, sources, sr, p):
    if not np.any(x):
        return x.copy(), accounting(x, x, sr, [])
    window = window_samples(2048, sr)
    target = analyze(x, sr, window=window)
    power = abs(target.spectra)**2
    noise = np.zeros_like(power)
    rows = []
    target_energy = np.sum(power, axis=(1, 2))
    for sid, source in sources:
        # Correlation is independent of stereo polarity/cancellation.
        ch = int(np.argmax(np.mean(source*source, axis=0)))
        tch = int(np.argmax(np.mean(x*x, axis=0)))
        # Bound the oversampled correlation FFT on long projects. Prefer a
        # source-active / target-quiet four-second cell, retaining its edges.
        size = min(len(x), 4*sr)
        cells = list(range(0, len(x)-size+1, max(1, size//2)))
        cells.append(max(0, len(x)-size))
        source_energy = [float(np.mean(source[a:a+size, ch]**2)) for a in cells]
        peak = max(source_energy)
        usable = [i for i, power in enumerate(source_energy) if power >= max(peak*.1, 1e-20)]
        first = min(usable, key=lambda i: (float(np.mean(x[cells[i]:cells[i]+size, tch]**2))/(source_energy[i]+1e-30), i)) if usable else 0
        offset = cells[first]
        delay = estimate_delay(source[offset:offset+size, ch], x[offset:offset+size, tch], sr,
                               max_delay_ms=p['max_delay_ms'], method='gcc_phat')
        lag = delay['delay_samples']
        if lag >= 0:
            aligned = fractional_delay(source, lag, 'sinc256')
        else:
            advance = min(len(source), int(np.ceil(-lag)))
            aligned = np.r_[source[advance:], np.zeros((advance, source.shape[1]))]
            aligned = fractional_delay(aligned, advance+lag, 'sinc256')
        if aligned.shape[1] != x.shape[1]:
            aligned = np.repeat(np.mean(aligned, axis=1, keepdims=True), x.shape[1], axis=1)
        ref = analyze(aligned, sr, window=window)
        source_power = abs(ref.spectra)**2
        energy = np.sum(source_power, axis=(1, 2))
        high = energy > max(float(np.percentile(energy, 40)), 1e-20)
        # Only quiet target / active source cells train the leakage transfer.
        use = high & (target_energy <= np.percentile(target_energy, 95)*.25)
        count = int(use.sum())
        transfer = np.zeros(power.shape[1:])
        coherent_bins = 0
        if count >= 4:
            ps = np.mean(source_power[use], axis=0)
            pt = np.mean(power[use], axis=0)
            cross = np.mean(target.spectra[use]*np.conj(ref.spectra[use]), axis=0)
            coherence = abs(cross)**2/(pt*ps+1e-30)
            supported = (coherence >= .8) & (ps > np.max(ps, axis=0, keepdims=True)*1e-5)
            transfer = np.where(supported, abs(cross)**2/(ps*ps+1e-30), 0.)
            coherent_bins = int(supported.sum())
        noise += source_power*transfer
        weights = np.sum(source_power, axis=0)
        leak = float(W.db(np.sum(transfer*weights)/(np.sum(weights)+1e-30)))
        rows.append({'track': sid, 'delay_samples': delay['delay_samples'], 'delay_ms': delay['delay_ms'],
                     'leakage_db': leak, 'estimation_frames': count, 'coherent_bins': coherent_bins,
                     'correlation_after': delay['correlation_after'], 'delay_region_samples': [offset, offset+size],
                     'delay_confidence': delay['confidence'],
                     'confidence': 'high' if count >= 20 and coherent_bins else 'low'})
    if not np.any(noise) or p['reduction_db'] == 0:
        return x.copy(), accounting(x, x, sr, rows)
    gains = suppression_gains(power, noise, sr, target.hop_samples, target.frequencies_hz,
                              method='wiener', reduction_db=p['reduction_db'],
                              time_smooth_ms=p['time_smooth_ms'], freq_smooth_oct=0,
                              transient_protect=0, decision_alpha=0)
    # Protect target-dominant bins. The leakage-only ratio remains unprotected.
    own = np.clip((power-noise)/(power+1e-30), 0, 1)
    protection = p['protect']*np.clip((own-.2)/.8, 0, 1)
    gains += (1-gains)*protection
    y, _ = apply_gains(target, gains)
    return y, accounting(x, y, sr, rows)


def make_calculator(root, params):
    """Rebuild a BB-18 calculator, refusing changed source audio dependencies."""
    from mankomix.director import edit
    sources = []
    for dependency in params['source_dependencies']:
        x, sr, _ = edit.raw_track(root, dependency['track'])
        if audio_hash(x) != dependency['raw_sha256'] or sr != params['sample_rate']:
            raise ValueError('debleed source dependency changed')
        sources.append((dependency['track'], x[params['start']:params['end']]))

    def calculate(x, sr, p):
        return process(x, sources, sr, p)[0]
    return calculate


def derive(root, move):
    from mankomix.director.direction import _Project
    from mankomix.director import edit
    p = W.params(move, NUMERIC)
    x, sr, _ = edit.raw_track(root, move['target'])
    a, b = W.scope(_Project(root), move, x, sr)
    sources, dependencies = [], []
    for sid in p['sources']:
        source, rate, _ = edit.raw_track(root, sid)
        if rate != sr or len(source) != len(x):
            raise ValueError('source timelines must match the target')
        dependencies.append({'track': sid, 'raw_sha256': audio_hash(source)})
        sources.append((sid, source[a:b]))
    p.update(source_dependencies=dependencies, sample_rate=sr, start=a, end=b)
    _, record = process(x[a:b], sources, sr, p)
    record['section_samples'] = [a, b]
    for row in record['sources']:
        row['delay_region_samples'] = [v+a for v in row['delay_region_samples']]
    return DerivedPlan(a, b, W.clean(p), make_calculator(root, p), fit='keep_length', record=W.clean(record))


OPS = {'edit_debleed': OpSpec('edit', ('target', 'params'), validate, derive=derive, code_version='w4g-debleed-1')}
