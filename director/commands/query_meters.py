"""Numerical meters, without thresholds or quality judgments.

New definitions: RMS/crest use 300 ms windows; Welch levels integrate channel
mean PSD with fractional edge-bin weights. Vectorscope tilt is the covariance
principal axis in M/S coordinates (zero=mid); spread=E_S/(E_M+E_S).
Display bins aggregate the requested hop; peaks/max-hold retain maxima.
"""
import math
import numpy as np
from scipy import signal
from mankomix.core.measure import loudness as L
from mankomix.core.measure.spectral import _crest_values
from mankomix.core.measure.bands import third_octave_grid
from mankomix.dspx.bb import meters
from mankomix.director import _observations_w4b as O
from . import _measurement as W

WHAT = ('loudness', 'peak', 'rms_crest', 'spectrum', 'spectrogram',
        'correlation', 'vectorscope', 'balance', 'dynamics')


def add_args(parser):
    W.add_source(parser)
    parser.add_argument('--what', choices=WHAT, nargs='+', default=list(WHAT))
    parser.add_argument('--step-ms', type=float, default=100)
    parser.add_argument('--max-points', type=int, default=2000)
    parser.add_argument('--points', type=int, default=0)
    parser.add_argument('--octave', choices=('3', '6', '12'), default='3')


def db(p):
    return 10*np.log10(np.maximum(p, 1e-30))


def welch_bands(x, sr, edges):
    if len(x) < 4:
        x = np.pad(x, ((0, 4-len(x)), (0, 0)))
    n = min(len(x), 65536)
    f, p = signal.welch(x, sr, window='hann', nperseg=n, noverlap=n//2, axis=0)
    p = p.mean(axis=1)
    df = f[1]-f[0]
    weights = np.maximum(0, np.minimum(f[None, :]+df/2, edges[:, 1:])
                         -np.maximum(f[None, :]-df/2, edges[:, :1]))
    return weights.dot(p)


def run(args):
    W.number(args.step_ms, 10, 1000, '--step-ms')
    W.number(args.max_points, 1, 100000, '--max-points')
    W.number(args.points, 0, 100000, '--points')
    x, sr, a, b, meta = W.source(args)
    x = x[a:b]
    hop = max(1, round(args.step_ms*sr/1000))
    factor = max(1, math.ceil(math.ceil(len(x)/hop)/args.max_points))
    step = hop*factor
    starts = np.arange(0, len(x), step)
    out = {'kind': 'direction_query_meters', **meta, 'confidence': 'high',
           'requested_step_ms': args.step_ms, 'effective_step_ms': step/sr*1000,
           'decimation_factor': factor, 'step_widened': factor > 1,
           'times_s': (starts+a)/sr, 'end_times_s': (np.minimum(starts+step, len(x))+a)/sr,
           'max_points': args.max_points}
    requested = set(args.what)
    summary = L.loudness_summary(x, sr)
    out['summary'] = summary
    if 'peak' in requested:
        timeline = meters.timeline(x, sr, hop_ms=args.step_ms)
        out['peak'] = {'sample_peak_dbfs': meters.decimate(timeline['sample_peak_dbfs'], factor, peak=True),
                       'true_peak_dbtp': meters.decimate(timeline['true_peak_dbtp'], factor, peak=True),
                       'note': 'True peaks retain BB-25 overlapping-hop context; bins retain maxima.'}
    if requested & {'loudness', 'dynamics'}:
        mom, short = L.momentary(x, sr), L.short_term(x, sr)
        groups = {}
        for name, values, seconds in [('momentary', mom, .4), ('short_term', short, 3.)]:
            samples = np.arange(len(values))*round(.1*sr)
            means, maxima, histograms = [], [], []
            edges = np.arange(-100, 1, 1, dtype=float)
            for i in starts:
                vals = values[(samples >= i) & (samples < i+step)]
                active = vals[np.isfinite(vals)]
                means.append(float(active.mean()) if len(active) else None)
                maxima.append(float(active.max()) if len(active) else None)
                histograms.append(np.histogram(active, bins=edges)[0].tolist())
            groups[name] = {'mean_lufs': means, 'max_lufs': maxima, 'window_s': seconds,
                            'support': 'time is window start, original meter hop is 100 ms'}
            if name == 'short_term' and 'dynamics' in requested:
                out['dynamics'] = {'edges_lufs': edges, 'counts': histograms,
                                   'below_range': int(np.sum(short < edges[0])),
                                   'above_range': int(np.sum(short > edges[-1]))}
        if 'loudness' in requested:
            out['loudness'] = {**groups, 'integrated_lufs': summary['integrated_lufs'], 'lra_lu': summary['lra_lu']}
    if 'rms_crest' in requested:
        window = round(.3*sr)
        powers, peaks = [], []
        for start in range(0, len(x), hop):
            seg = x[start:min(len(x), start+window)]
            powers.append(np.mean(seg**2))
            peaks.append(np.max(np.abs(seg)))
        power = meters.decimate(powers, factor)
        peak = meters.decimate(peaks, factor, peak=True)
        measured = [_crest_values(float(pk), float(pw)) for pk, pw in zip(peak, power)]
        out['rms_crest'] = {'rms_dbfs': [m['rms_dbfs'] for m in measured],
                            'crest_db': [m['crest_db'] for m in measured],
                            'window_ms': 300, 'plr_db': summary['plr_db'], 'psr_db': summary['psr_db'],
                            'tail': 'final windows use remaining samples'}
    if 'correlation' in requested:
        bands = O.correlation(x, sr)
        for row in bands:
            values = np.array(row.pop('values'))
            row['times_s'] = (a+np.arange(0, len(values), max(1, math.ceil(len(values)/args.max_points)))*round(.4*sr))/sr
            n = max(1, math.ceil(len(values)/args.max_points))
            row['values'] = [float(np.median(v[np.isfinite(v)])) if np.isfinite(v).any() else None
                             for v in (values[i:i+n] for i in range(0, len(values), n))]
            row['aggregation_windows'] = n
        out['correlation'] = {'full': meters.stereo_bands(x, sr)['full_band']['correlation'],
                              'bands': bands, 'window_ms': 400}
    if requested & {'vectorscope', 'balance'}:
        vectors, balance = [], []
        for i in starts:
            seg = x[i:i+step]
            mid, side = (seg[:, 0]+seg[:, 1])/2, (seg[:, 0]-seg[:, 1])/2
            em, es, cross = np.mean(mid**2), np.mean(side**2), np.mean(mid*side)
            # side is L-R: negative tilt is right, positive is left.
            vectors.append({'mid_dbfs': db(em), 'side_dbfs': db(es),
                            'tilt_degrees': float(np.degrees(.5*np.arctan2(2*cross, em-es))) if em+es else None,
                            'spread': float(es/(em+es)) if em+es else None,
                            'side_mid_db': db(es)-db(em)})
            el, er = np.mean(seg[:, 0]**2), np.mean(seg[:, 1]**2)
            balance.append(float(db(er)-db(el)) if el+er else None)
        if 'vectorscope' in requested:
            out['vectorscope'] = {'windows': vectors, 'definition': 'M=(L+R)/2, S=(L-R)/2; spread=E_S/(E_M+E_S)'}
            if args.points:
                ids = np.unique(np.linspace(0, len(x)-1, min(args.points, len(x)), dtype=int))
                out['vectorscope']['points_lr'] = x[ids]
                out['vectorscope']['point_samples'] = ids+a
        if 'balance' in requested:
            out['balance'] = {'right_minus_left_db': balance}
    if requested & {'spectrum', 'spectrogram'}:
        if args.octave == '3':
            edges = np.array([[v.lo_hz, v.hi_hz] for v in third_octave_grid(sr)])
        else:
            count = int(args.octave)
            e = 20*2**(np.arange(math.ceil(count*np.log2(min(20000, sr/2)/20))+1)/count)
            e[-1] = min(20000, sr/2)
            edges = np.column_stack([e[:-1], e[1:]])
        if 'spectrum' in requested:
            powers = np.array([welch_bands(x[i:min(len(x), i+max(step, round(.4*sr)))], sr, edges) for i in starts])
            out['spectrum'] = {'bands_hz': edges, 'levels_dbfs': db(powers),
                               'ltas_dbfs': db(welch_bands(x, sr, edges)),
                               'max_hold_dbfs': db(powers.max(axis=0)),
                               'method': 'Welch Hann, 50 percent overlap, channel-mean PSD integrated over each band'}
        if 'spectrogram' in requested:
            sp = meters.spectrogram(x, sr)
            f = sp['frequencies_hz']
            e = np.geomspace(20, min(20000, sr/2), 97)
            power = sp['power'].mean(axis=2)
            bins = np.column_stack([power[:, (f >= lo) & (f < hi)].sum(axis=1) for lo, hi in zip(e[:-1], e[1:])])
            rows = []
            for i in starts:
                p = bins[(sp['samples'] >= i) & (sp['samples'] < i+step)]
                rows.append(p.mean(axis=0) if len(p) else np.zeros(96))
            out['spectrogram'] = {'edges_hz': e, 'levels_dbfs': db(np.array(rows)), 'bands': 96,
                                  'window_samples': sp['window_samples'], 'hop_samples': sp['hop_samples']}
    return W.clean(out)


COMMANDS = [{'path': ('query', 'meters'), 'help': 'Read deterministic meter timelines',
             'add_args': add_args, 'run': run, 'writes': False}]
