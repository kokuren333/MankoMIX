"""Read-only multitrack GCC-PHAT delay, polarity and residual-phase evidence."""
import itertools
import numpy as np
from scipy import fft, signal
from mankomix.core.errors import InputError

CAUTION = '相関が最大になる位置が、音として最良とは限らない（オーバーヘッドとスネアの関係など）。合算の帯域別変化を見て決める'


def add_args(parser):
    parser.add_argument('--tracks', required=True)
    parser.add_argument('--reference', default='auto')
    parser.add_argument('--max-ms', type=float, default=30)
    parser.add_argument('--section')
    parser.add_argument('--band-hz', nargs=2, type=float, default=[40, 8000])
    parser.add_argument('--mode', choices=['delay', 'delay_polarity', 'phase'], default='delay_polarity')
    parser.add_argument('--preset', choices=['drums'])


def mono(x):
    # Preserve anti-phase stereo by selecting the higher-energy channel.
    return x[:, int(np.argmax(np.sum(x*x, axis=0)))]


def measure_pair(a, b, sr, max_ms, band, positions=None):
    from mankomix.dspx.bb.align import estimate_segments, estimate_delay
    if positions is None:
        return estimate_segments(a, b, sr, max_delay_ms=max_ms, band_hz=band)
    rows = []
    for pos in positions:
        left, right = max(0, pos-round(.03*sr)), min(len(a), pos+round(.03*sr))
        if right-left >= 8:
            window = signal.windows.tukey(right-left, alpha=.5)
            rows.append(dict(start_s=left/sr, hit_sample=pos,
                             **estimate_delay(a[left:right]*window, b[left:right]*window, sr,
                                              max_delay_ms=max_ms, band_hz=band)))
    good = [r for r in rows if r['reliable']]
    values = np.array([r['delay_samples'] for r in good])
    center = float(np.median(values)) if len(values) else 0.
    return {'delay_samples': center, 'delay_ms': center*1000/sr,
            'mad_samples': float(np.median(abs(values-center))) if len(values) else 0.,
            'polarity': -1 if sum(r['polarity'] for r in good) < 0 else 1,
            'confidence': 'high' if good else 'low', 'segments': rows}


def band_changes(a, b, after_a, after_b, sr, band):
    size = fft.next_fast_len(max(1, len(a)))
    freq = fft.rfftfreq(size, 1/sr)
    before = abs(fft.rfft(a+b, size, workers=1))**2
    after = abs(fft.rfft(after_a+after_b, size, workers=1))**2
    phase_before = fft.rfft(b, size, workers=1)*np.conj(fft.rfft(a, size, workers=1))
    phase_after = fft.rfft(after_b, size, workers=1)*np.conj(fft.rfft(after_a, size, workers=1))
    rows = []
    center = 1000*2**(-18/3)
    while center <= min(band[1], sr/2):
        lo, hi = center/2**(1/6), center*2**(1/6)
        mask = (freq >= max(lo, band[0])) & (freq < min(hi, band[1]))
        if mask.any():
            old, new = float(before[mask].sum()), float(after[mask].sum())
            rows.append({'center_hz': float(center), 'change_db':
                         float(10*np.log10(max(new, 1e-30)/max(old, 1e-30))),
                         'phase_before_deg': float(np.angle(phase_before[mask].sum(), deg=True)),
                         'phase_after_deg': float(np.angle(phase_after[mask].sum(), deg=True))})
        center *= 2**(1/3)
    return rows


def phase_choice(x, reference, sr):
    """Fit first-order allpass candidates by measured remaining correlation."""
    def corr(a, b):
        return float(np.sum(a*b)/max(np.linalg.norm(a)*np.linalg.norm(b), 1e-30))
    base, best = corr(x, reference), (0., 1, x)
    score = base
    for hz in np.geomspace(20, min(20000, .45*sr), 28):
        alpha = (np.tan(np.pi*hz/sr)-1)/(np.tan(np.pi*hz/sr)+1)
        y = x
        for stages in range(1, 5):
            y = signal.lfilter([alpha, 1], [1, alpha], y)
            c = corr(y, reference)
            if c > score+.002:
                score, best = c, (float(hz), stages, y)
    return best, {'before': base, 'after': score}


def run(args):
    from mankomix.director.direction import _Project
    from mankomix.director.commands._eq_reference import section_audio
    from mankomix.director.xops._w4g import audio, clean
    from mankomix.dspx.bb.align import solve_delays, estimate_delay
    from mankomix.dspx.bb.delayline import fractional_delay
    from mankomix.dspx.bb.drum_events import drum_onsets
    project = _Project(args.project or '.')
    entries = args.tracks.split(',')
    roles, tracks = {}, []
    for entry in entries:
        role, tid = entry.split(':', 1) if ':' in entry else ('', entry)
        if args.preset == 'drums' and role not in ('kick', 'snare', 'tom', 'oh', 'room'):
            raise InputError('drums tracks require kick/snare/tom/oh/room roles')
        roles[tid] = role
        tracks.append(tid)
    if not 2 <= len(tracks) <= 16 or len(set(tracks)) != len(tracks) or any(t not in project.tracks() for t in tracks):
        raise InputError('--tracks requires 2..16 unique existing tracks')
    if args.reference != 'auto' and args.reference not in tracks:
        raise InputError('--reference must be auto or a selected track')
    if not np.isfinite(args.max_ms) or not .1 <= args.max_ms <= 100:
        raise InputError('--max-ms must be in [0.1,100]')
    sr = project.rate
    lo, hi = args.band_hz
    if not np.isfinite([lo, hi]).all() or not 0 <= lo < hi <= sr/2:
        raise InputError('--band-hz requires 0 <= lo < hi <= Nyquist')
    waves, hits = [], {}
    for tid in tracks:
        x, rate = audio(project.root, tid)
        x, interval = section_audio(x, rate, project.root, args.section)
        waves.append(mono(x))
        if args.preset == 'drums' and roles[tid] in ('kick', 'snare', 'tom'):
            hits[tid] = [r['sample'] for r in drum_onsets(x, sr)]
    pairs, graph = [], []
    for i, j in itertools.combinations(range(len(tracks)), 2):
        positions = hits.get(tracks[i], hits.get(tracks[j])) if args.preset else None
        row = measure_pair(waves[i], waves[j], sr, args.max_ms, (lo, hi), positions)
        pairs.append(dict(tracks=[tracks[i], tracks[j]], **row))
        graph.append((i, j, row['delay_samples'], 1 if row['confidence'] == 'high' else .01))
    fitted = solve_delays(len(tracks), graph)
    reference = int(np.argmax(fitted['arrival_samples'])) if args.reference == 'auto' else tracks.index(args.reference)
    if args.preset == 'drums' and args.reference == 'auto':
        distant = [i for i, tid in enumerate(tracks) if roles[tid] in ('oh', 'room')]
        if not distant:
            raise InputError('drums preset requires an overhead or room track')
        reference = max(distant, key=lambda i: fitted['arrival_samples'][i])
    causal = max(fitted['arrival_samples'])
    reference_arrival = fitted['arrival_samples'][reference]
    if reference_arrival < causal-.02*sr/1000 and args.reference != 'auto':
        raise InputError('selected reference arrives earlier; time_align cannot advance other tracks; use auto')
    aligned, settings = [], []
    for i, tid in enumerate(tracks):
        amount = min(100., max(0., (causal-fitted['arrival_samples'][i])*1000/sr))
        pair = estimate_delay(waves[reference], waves[i], sr, max_delay_ms=args.max_ms, band_hz=(lo, hi))
        measured = next((r for r in pairs if set(r['tracks']) == {tracks[reference], tid}), None)
        polarity = measured['polarity'] if measured and measured['confidence'] == 'high' else pair['polarity']
        invert = args.mode != 'delay' and polarity < 0
        y = fractional_delay(waves[i][:, None], amount*sr/1000, 'sinc256')[:, 0]*(-1 if invert else 1)
        settings.append({'track': tid, 'role': roles[tid], 'delay_ms': amount,
                         'polarity_invert': bool(invert), 'allpass_hz': 0., 'allpass_stages': 1})
        aligned.append(y)
    phase = []
    if args.mode == 'phase':
        for i, tid in enumerate(tracks):
            if i != reference:
                (hz, stages, y), scores = phase_choice(aligned[i], aligned[reference], sr)
                settings[i].update(allpass_hz=hz, allpass_stages=stages)
                aligned[i] = y
                phase.append({'track': tid, 'correlation': scores})
    for row, (i, j) in zip(pairs, itertools.combinations(range(len(tracks)), 2)):
        before = estimate_delay(waves[i], waves[j], sr, max_delay_ms=0, band_hz=(lo, hi))
        after = estimate_delay(aligned[i], aligned[j], sr, max_delay_ms=0, band_hz=(lo, hi))
        row.update(correlation_before=before['correlation_before'], correlation_after=after['correlation_before'],
                   sum_band_changes=band_changes(waves[i], waves[j], aligned[i], aligned[j], sr, (lo, hi)))
    confidence = 'high' if all(r['confidence'] == 'high' for r in pairs) else 'low'
    from mankomix.director.commands._eq_reference import move
    candidates = [move(r['track'], 'time_align',
                      {k: r[k] for k in ('delay_ms', 'polarity_invert', 'allpass_hz', 'allpass_stages')},
                      i+1, basis='measured pairwise GCC-PHAT delay and polarity')
                  for i, r in enumerate(settings)]
    notes = [CAUTION]
    if confidence == 'low':
        notes.append('Low correlation or insufficient matching hits; inspect the measured candidates.')
    if args.preset:
        notes.append('どちらに合わせる案もある。近接を遅らせ、オーバーヘッドはそのまま。進める案は time_align では出さない。')
    return clean({'kind': 'direction_suggest_align', 'confidence': confidence, 'reference': tracks[reference],
                  'tracks': settings, 'pairs': pairs, 'candidates': candidates, 'phase_fit': phase,
                  'residual_rms_samples': fitted['residual_rms_samples'], 'section_s': interval,
                  'notes': notes, 'method': 'BB17_GCC_PHAT_10s_or_BB22_hits', 'band_hz': [lo, hi]})


COMMANDS = [{'path': ('suggest', 'align'), 'help': 'Measure causal delay/polarity alignment candidates',
             'add_args': add_args, 'run': run, 'writes': False}]
