"""Observe tonal distributions and low-band crest, without recommending EQ."""
from mankomix.core.errors import InputError
from . import _eq_reference as E


def add_args(p):
    p.add_argument('--audio')
    E.add_references(p, audio=True, required=True)
    p.add_argument('--bands', choices=['4', 'third', 'sixth'], default='4')
    p.add_argument('--normalize', choices=['lufs', 'mid_band'], default='lufs')
    p.add_argument('--over-time', type=float)
    E.add_section(p)


def compare(spec, refs, mode):
    values = E.levels(spec, mode)
    edges = E.bands(mode, spec['sample_rate'])
    # Integrate references on exactly the target's grid, including clipped Nyquist bands.
    ref_values = []
    for r in refs:
        s = r['spectrum']
        base = E.power(s, 20, 20000)
        ref_values.append([E.db(E.power(s, lo, hi)/base) if base > 0 and hi <= s['sample_rate']/2 else None
                           for lo, hi in edges])
    return [{'band_hz': [lo, hi], **E.distribution(values[i], [r[i] for r in ref_values])}
            for i, (lo, hi) in enumerate(edges)]


def normalized(spec, mode):
    if mode == 'mid_band':
        base = E.power(spec, 300, 3000)
        if base <= 0:
            raise InputError('mid_band normalization requires active 300 Hz to 3 kHz energy')
        return {**spec, 'power_density': [p/base for p in spec['power_density']]}
    return spec


def run(args):
    if args.over_time is not None:
        E.number(args.over_time, .4, float('inf'), '--over-time')
    refs = E.references(args)
    E.require_spectra(refs)
    x, sr, info = E.source(args)
    spec = E.spectrum(x, sr)
    result = {'kind': 'direction_ref_balance', 'confidence': E.confidence(len(refs)),
              'reference_count': len(refs), 'provenance': info, 'normalize': args.normalize,
              'bands': compare(spec, refs, args.bands),
              'low_crest': E.distribution(E.low_crest(x, sr), [r.get('low_crest_db') for r in refs]),
              'target_spectrum': normalized(spec, args.normalize),
              'reference_spectra': [normalized(r['spectrum'], args.normalize) for r in refs],
              'notes': ['Band levels are dB fractions of total 20 Hz to 20 kHz power; common level normalization cancels in these ratios.',
                        'Reference quartiles describe these recordings; they do not prescribe a balance.', E.LOW_NOTE]}
    if args.over_time is not None:
        width = round(args.over_time*sr)
        windows = []
        for i in range(0, len(x), width):
            segment = x[i:i+width]
            if len(segment) < round(.4*sr):
                continue
            local = E.spectrum(segment, sr)
            windows.append({'start_s': info['section_s'][0]+i/sr,
                            'end_s': info['section_s'][0]+(i+len(segment))/sr,
                            'bands': compare(local, refs, args.bands),
                            'low_crest': E.distribution(E.low_crest(segment, sr), [r.get('low_crest_db') for r in refs])})
        result['over_time'] = windows
    return E.clean(result)


COMMANDS = [{'path': ('ref', 'balance'), 'help': 'Observe tonal-band and low-crest reference distributions',
             'add_args': add_args, 'run': run, 'writes': False}]
