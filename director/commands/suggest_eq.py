"""Deterministic resonance, masking, sub-fundamental and reference-tilt candidates."""
import numpy as np
from scipy.signal import find_peaks
from mankomix.core.errors import InputError
from mankomix.director import stemobs as S
from . import _eq_reference as E


def add_args(p):
    p.add_argument('--target', required=True)
    p.add_argument('--against', default='all')
    p.add_argument('--max-candidates', type=int, default=6)
    p.add_argument('--min-excess-db', type=float, default=6.)
    p.add_argument('--band-hz', nargs=2, type=float, default=[20., 20000.])
    E.add_section(p)
    E.add_references(p)


def resonance(x, sr, lo, hi, excess):
    from mankomix.dspx.bb.stft import analyze, window_samples
    from mankomix.dspx.bb.spectral_control import spectral_envelope
    a = analyze(x, sr, window=window_samples(4096, sr))
    power = np.mean(abs(a.spectra)**2, axis=2, keepdims=True)
    active = power.sum(axis=1)[:, 0] > max(1e-20, float(power.sum(axis=1).max(initial=0))*1e-6)
    if not active.any():
        return [], {'active_frames': 0}
    p = power[active]
    env = spectral_envelope(p, a.frequencies_hz, .5)
    above = 10*np.log10(np.maximum(p, 1e-30))-env
    occurrence = np.mean(above[:, :, 0] >= excess, axis=0)
    median = np.median(above[:, :, 0], axis=0)
    peaks, _ = find_peaks(median)
    candidates = []
    f = a.frequencies_hz
    for k in sorted(peaks, key=lambda k: (-occurrence[k], -median[k], f[k])):
        if not lo <= f[k] <= min(hi, .45*sr) or occurrence[k] < .5 or median[k] < excess:
            continue
        if any(abs(np.log2(f[k]/c['freq_hz'])) < .1 for c in candidates):
            continue
        left, right = k, k
        while left > 1 and median[left-1] > excess/2:
            left -= 1
        while right+1 < len(f) and median[right+1] > excess/2:
            right += 1
        width = float(np.clip(np.log2((f[right]+sr/len(a.window)/2)/max(10., f[left]-sr/len(a.window)/2)), .02, 6))
        candidates.append({'kind': 'resonance', 'freq_hz': float(f[k]), 'bw_oct': width,
                           'gain_db': [-min(12., float(median[k])), -min(3., float(median[k])/2)],
                           'confidence': 'high', 'evidence': {'excess_db': float(median[k]),
                           'occurrence': float(occurrence[k]), 'envelope_oct': .5, 'window_samples': len(a.window)}})
    return candidates, {'active_frames': int(active.sum()), 'total_frames': len(active),
                        'excess_definition': 'T02-03 spectral_envelope log_mean, 0.5 oct; median and occurrence'}


def masking(args, lo, hi):
    from mankomix.core.analysis.stems import masking_matrix
    from mankomix.director.relate import BANDS, _band_mean
    src = S.StemSource(E.project_root(args))
    try:
        src.check_track(args.target)
        stems, sr = src.dry()
        hi = min(hi, sr*.45)
        ids = sorted(stems) if args.against == 'all' else sorted({args.target, args.against})
        for tid in ids:
            src.check_track(tid)
        if len(ids) < 2:
            return [], None
        cut = {tid: E.section_audio(stems[tid], sr, E.project_root(args), args.section)[0] for tid in ids}
        meta, genre = src.masking_context(ids)
    except S.StemObsError as e:
        raise InputError(str(e)) from None
    mm = masking_matrix(cut, sr, meta, genre=genre)
    rows = []
    target = mm.get('per_target', {}).get(args.target, {})
    for name, a, b in BANDS:
        if a >= hi or b <= lo:
            continue
        buried = _band_mean(mm.get('bands_hz', []), target.get('buried_db_by_band', []), max(a, lo), min(b, hi))
        if buried is None or buried <= .5:
            continue
        maskers = sorted(((tid, value) for tid, value in mm.get('matrix', {}).get(args.target, {}).items()
                          if value is not None and value > 0), key=lambda r: (-r[1], r[0]))
        if not maskers:
            continue
        other = maskers[0][0]
        f = float(np.sqrt(max(a, lo)*min(b, hi)))
        width = float(np.clip(np.log2(min(b, hi)/max(a, lo)), .02, 6.))
        for tid in (args.target, other):
            rows.append({'kind': 'masking', 'target': tid, 'freq_hz': f, 'bw_oct': width,
                         'gain_db': [-min(6., buried), -min(1., buried)], 'confidence': 'low',
                         'evidence': {'model': 'P-02', 'band': name, 'buried_db': buried,
                                      'pair': [args.target, other], 'choice': 'either_side_not_a_priority'}})
    return rows, {'model': 'P-02', 'overall': mm.get('overall'), 'tracks': ids,
                  'note': 'Candidate generation and masking evidence use the same model, not independent validation.'}


def sub_fundamental(x, sr, spec, lo, hi):
    from mankomix.dspx.bb.pitch import detect_pitch
    track = detect_pitch(x, sr, fmin=30., fmax=min(1000., sr*.4), hop_ms=50., voiced_threshold=.5)
    voiced = track.f0_hz[track.voiced & np.isfinite(track.f0_hz)]
    if not len(voiced):
        return [], {'voiced_frames': 0, 'lowest_active_f0_hz': None}
    lowest = float(np.min(voiced))
    cutoff = min(hi, lowest/2)
    total = E.power(spec, 20, 20000)
    ceiling = min(hi, lowest)
    fraction = E.power(spec, lo, ceiling)/total if ceiling > lo and total else 0.
    conservative_fraction = E.power(spec, lo, cutoff)/total if cutoff > lo and total else 0.
    evidence = {'voiced_frames': len(voiced), 'lowest_active_f0_hz': lowest,
                'below_lowest_f0_energy_fraction': fraction,
                'below_half_f0_energy_fraction': conservative_fraction, 'method': 'BB-12 pYIN'}
    if fraction < .01 or cutoff <= lo:
        return [], evidence
    return [{'kind': 'sub_fundamental', 'freq_hz': cutoff, 'bw_oct': 1.,
             'gain_db': [-6., -1.], 'confidence': 'low', 'evidence': evidence}], evidence


def run(args):
    E.number(args.max_candidates, 1, 12, '--max-candidates')
    E.number(args.min_excess_db, 3, 12, '--min-excess-db')
    lo, hi = E.band_arg(args.band_hz)
    if not args.target.startswith('trk_') or args.against != 'all' and not args.against.startswith('trk_'):
        raise InputError('EQ suggestions require track IDs (against may be all)')
    if args.against == args.target:
        raise InputError('--against must differ from --target')
    x, sr, info = E.source(args)
    spec = E.spectrum(x, sr)
    res, evidence = resonance(x, sr, lo, hi, args.min_excess_db)
    mask, mask_evidence = masking(args, lo, hi)
    sub, pitch_evidence = sub_fundamental(x, sr, spec, lo, hi)
    candidates = res + sub
    # Keep masking alternatives together when enforcing the candidate budget.
    room = args.max_candidates-len(candidates)
    candidates += mask[:max(0, room//2*2)]
    tilt_evidence = None
    if args.ref_kb or args.refsheet:
        from mankomix.core.reference import measure_reference
        refs = E.references(args)
        current = E.RS._tilt(measure_reference(x, sr).get('ltas_erb'))
        slopes = [r.get('values', {}).get('tilt_db_per_oct') for r in refs]
        # Raw audio references use the identical refstudy ERB tilt quantity.
        for i, path in enumerate(E.reference_paths(args)):
            if i < len(refs) and E.audio_io.is_audio_file(path):
                audio, rate = E.RS.read_audio(path)
                slopes[i] = E.RS._tilt(measure_reference(audio, rate).get('ltas_erb'))
        tilt_evidence = E.distribution(current, slopes)
        delta = tilt_evidence.get('outside_db')
        if delta is not None and abs(delta) > .1 and lo < min(hi, sr*.45):
            candidates.append({'kind': 'reference_tilt', 'freq_hz': max(lo, min(4000., hi, sr*.4)), 'bw_oct': 2.,
                               'gain_db': sorted([float(np.clip(-delta, -6, 6)), 0.]),
                               'confidence': E.confidence(tilt_evidence['n']), 'evidence': tilt_evidence})
    candidates = candidates[:args.max_candidates]
    for i, c in enumerate(candidates):
        target = c.get('target', args.target)
        if c['kind'] == 'sub_fundamental':
            proc, params = 'filter', {'kind': 'hpf', 'freq_hz': c['freq_hz'], 'slope_db_oct': 12}
        else:
            proc, params = 'eq', {'shape': 'high_shelf' if c['kind'] == 'reference_tilt' else 'peak',
                                  'freq_hz': c['freq_hz'], 'bw_oct': c['bw_oct'], 'gain_db': c['gain_db']}
        c['chain_add'] = E.move(target, proc, params, i+1)
    return E.clean({'kind': 'direction_suggest_eq', 'confidence': 'high' if res else 'low' if spec['active_frames'] else 'unknown',
                    'provenance': info, 'candidates': candidates,
                    'measurements': {'resonance': evidence, 'masking': mask_evidence, 'pitch': pitch_evidence,
                                     'reference_tilt': tilt_evidence},
                    'notes': ['Masking alternatives give both sides; the director decides which yields.',
                              'Pitch is a monophonic estimate; sub-fundamental energy may be intentional.']})


COMMANDS = [{'path': ('suggest', 'eq'), 'help': 'Propose measured EQ candidates without changing the project',
             'add_args': add_args, 'run': run, 'writes': False}]
