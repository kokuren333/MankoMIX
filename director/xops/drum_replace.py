"""T11-05 deterministic sample reinforcement with W4_1 node resources."""
import copy
import hashlib
import numpy as np
from mankomix.director.xops import OpSpec, MixResult, AudioPlan, NodePlan
from mankomix.dspx.bb.drum_events import DETECT
from mankomix.dsp.errors import ParamError

NUMERIC = {k: (*v, False) for k, v in DETECT.items()}
NUMERIC.update(blend_db=(-24, 6, -6, True), original_db=(-90, 0, -90, False),
               tune_semitones=(-12, 12, 0, False), humanize_db=(0, 3, 0, False), seed=(0, 65535, 0, False))
ENUMS = {'mode': (('add', 'replace'), 'add'), 'align': (('onset', 'phase'), 'phase')}
EXTRA = ('sample', 'samples', 'velocity_curve', 'round_robin', 'only', 'skip')


def layers(p):
    if ('sample' in p) == ('samples' in p):
        raise ParamError('supply exactly one of sample or samples')
    if 'sample' in p:
        if not isinstance(p['sample'], str) or not p['sample']:
            raise ParamError('sample must be a registered ID')
        return [{'id': p['sample'], 'min_velocity': 0.}]
    rows = p['samples']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ParamError('samples requires 1..8 velocity layers')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'min_velocity'} or not isinstance(row['id'], str):
            raise ParamError('sample layer needs id and min_velocity')
        value = row['min_velocity']
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value) or not 0 <= value <= 1:
            raise ParamError('min_velocity must be finite in [0,1]')
    return copy.deepcopy(rows)


def curve(p):
    points = p.get('velocity_curve', [[0, -18], [1, 0]])
    if not isinstance(points, list) or not 1 <= len(points) <= 16:
        raise ParamError('velocity_curve requires 1..16 points')
    previous = (-1., -25.)
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in point):
            raise ParamError('velocity_curve points must be [velocity,gain_db]')
        x, y = point
        if not np.isfinite(point).all() or not 0 <= x <= 1 or not -24 <= y <= 0 or x <= previous[0] or y < previous[1]:
            raise ParamError('velocity_curve requires ascending x and nondecreasing dB within bounds')
        previous = (x, y)
    return copy.deepcopy(points)


def validate(move, ctx):
    from . import _w4g as W
    from mankomix.dspx.bb.drum_events import check_bands
    from mankomix.dspx.bb.samples import SAMPLES
    p = W.validate(move, ctx, NUMERIC, ENUMS, extra=EXTRA)
    if not isinstance(move.get('params'), dict):
        return
    try:
        resolved = W.params(move, NUMERIC, ENUMS)
        if all(W.number(resolved[k]) for k in DETECT):
            check_bands(resolved)
        if not isinstance(p.get('round_robin', False), bool):
            raise ParamError('round_robin must be boolean')
        seed = p.get('seed', 0)
        if not W.number(seed) or int(seed) != seed:
            raise ParamError('seed must be an integer')
        curve(p)
        for key in ('only', 'skip'):
            ids = p.get(key, [])
            if not isinstance(ids, list) or len(ids) > 1024 or any(not isinstance(i, str) or not i.startswith('o_') or not i[2:].isdigit() for i in ids):
                raise ParamError(key+' requires up to 1024 BB-22 onset IDs')
        for row in layers(p):
            SAMPLES.load(row['id'])  # Hash, metadata and license are checked before planning.
    except (ParamError, LookupError, TypeError, ValueError) as exc:
        ctx.err('bad_value', str(exc))


def phase_offset(source, sample, pos, sr):
    """Exact integer correlation maximum within +/-2 ms, including polarity."""
    from scipy import signal, fft
    radius = round(.002*sr)
    a = max(0, pos-radius)
    b = min(len(source), pos+len(sample)+radius)
    raw = np.mean(source[a:b], axis=1)
    hit = np.mean(sample, axis=1)
    with fft.set_workers(1):
        corr = signal.correlate(raw, hit, mode='full', method='fft')
    lags = signal.correlation_lags(len(raw), len(hit), mode='full')+a-pos
    allowed = abs(lags) <= radius
    index = np.flatnonzero(allowed)[int(np.argmax(abs(corr[allowed])))]
    return int(lags[index]), -1 if corr[index] < 0 else 1


def onset_position(x, sample, sr):
    """Refine a BB-22 tangent against a preceding silent floor; retain its ID.

    Noise/overlapping tails retain the measured BB-22 position. A truly silent
    lead-in permits sample-accurate placement without the RMS-window bias.
    """
    a, b = max(0, sample-round(.003*sr)), min(len(x), sample+round(.004*sr))
    env = np.max(abs(x[a:b]), axis=1)
    if not len(env):
        return sample
    peak = max(float(np.max(env)), 1e-30)
    if np.max(env[:max(1, round(.0005*sr))]) < peak*1e-5:
        indices = np.flatnonzero(env > peak*1e-4)
        if len(indices):
            return a+int(indices[0])
    return sample


def expand(project, move):
    from . import _w4g as W
    from mankomix.dspx.bb.drum_events import drum_events, velocities
    from mankomix.dspx.bb.samples import load_sample
    from mankomix.dspx.bb.curves import modulation_seed
    p = W.params(move, NUMERIC, ENUMS)
    p.update(velocity_curve=curve(p), round_robin=p.get('round_robin', False),
             only=p.get('only', []), skip=p.get('skip', []))
    selected_layers = layers(p)
    x, sr = W.audio(project.root, move['target'])
    events, _ = drum_events(x, sr, p)
    accepted = [r for r in events if r['opened']]
    strengths = velocities(accepted)
    # Compute velocities before only/skip so hand selection does not rescale hits.
    rng_seed = modulation_seed(project.data.get('seed', 0), move['id'], int(p['seed']))
    rng = np.random.Generator(np.random.PCG64(rng_seed))
    speed = 2**(p['tune_semitones']/12)
    loaded, assets, clips, hits, intervals, counters = {}, {}, [], [], [], {}
    records = {}
    for row in selected_layers:
        if row['id'] not in loaded:
            wave, record, notes = load_sample(row['id'], sr)
            records[row['id']] = record
            count = max(1, round(len(wave)/speed))
            positions = np.arange(count)*speed
            loaded[row['id']] = np.column_stack([np.interp(positions, np.arange(len(wave)), c, right=0) for c in wave.T])[:len(x)]
    track = project.tracks()[move['target']]
    source_ids = {c['asset_id'] if 'asset_id' in c else c.get('asset') for c in track.get('clips', [])}
    sources = [{'id': a['id'], 'sha256': a['sha256']} for a in project.data.get('assets', []) if a['id'] in source_ids]
    for row, velocity in zip(accepted, strengths):
        jitter = float(rng.uniform(-p['humanize_db'], p['humanize_db']))
        if (p['only'] and row['id'] not in p['only']) or row['id'] in p['skip']:
            continue
        eligible = [r['min_velocity'] for r in selected_layers if r['min_velocity'] <= velocity+1e-12]
        if not eligible:
            row['sample_skipped_reason'] = 'below_layer_min_velocity'
            continue
        threshold = max(eligible)
        choices = [r['id'] for r in selected_layers if r['min_velocity'] == threshold]
        counter = counters.get(threshold, 0)
        id = choices[counter % len(choices)] if p['round_robin'] else choices[0]
        counters[threshold] = counter+1
        wave = loaded[id]
        onset = onset_position(x, row['sample'], sr)
        shift, polarity = phase_offset(x, wave, onset, sr) if p['align'] == 'phase' else (0, 1)
        asset_name = 'hit_'+hashlib.sha256(id.encode('utf-8')).hexdigest()[:16]+('_neg' if polarity < 0 else '_pos')
        if asset_name not in assets:
            resolved = copy.deepcopy(p)
            resolved.update(speed=speed, polarity=polarity, effective_seed=rng_seed,
                            sample_record=records[id], source_track=move['target'])
            assets[asset_name] = AudioPlan(asset_name, wave*polarity, sr, resolved, 'drum_replace-1', sources)
        gain = float(np.interp(velocity, *np.asarray(p['velocity_curve']).T))
        # The op's blend level is relative to the original hit's local peak.
        gain += p['blend_db']+jitter+(row['peak_dbfs'] if row['peak_dbfs'] is not None else -300)-20*np.log10(max(np.max(abs(wave)), 1e-30))
        pos = onset+shift
        start, source_start = max(0, pos), max(0, -pos)
        length = min(len(wave)-source_start, len(x)-start)
        if length <= 0:
            continue
        clips.append({'track': 'reinforcement', 'asset': asset_name, 'timeline_start': start,
                      'source_start': source_start, 'length': length, 'gain_db': gain})
        hits.append({'id': row['id'], 'sample': row['sample'], 'time_s': row['time_s'], 'strength': float(velocity),
                     'sample_id': id, 'asset_name': asset_name, 'gain_db': gain,
                     'velocity_gain_db': float(np.interp(velocity, *np.asarray(p['velocity_curve']).T)),
                     'onset_sample': onset, 'shift_samples': shift, 'polarity': polarity, 'speed': speed, 'length': length,
                     'position': start, 'source_start': source_start})
        intervals.append([max(0, row['sample']), min(len(x), row['sample']+length)])
    points = []
    if p['mode'] == 'replace' and intervals:
        merged = []
        for a, b in sorted(intervals):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        points = [[0, 0.]]
        for a, b in merged:
            if a:
                points.append([a-1, 0.])
            points.extend([[a, p['original_db']], [b-1, p['original_db']], [b, 0.]])
        points.append([len(x), 0.])
        points = [list(row) for row in sorted(dict(points).items())]
    nodes = NodePlan(tracks=[{'name': 'reinforcement', 'role': 'drums', 'output': track['output']}],
                     assets=list(assets.values()), clips=clips) if clips else None
    return MixResult(record=W.clean({'hits': hits, 'events': events, 'params': p, 'sample_records': records,
                                     'effective_seed': rng_seed, 'confidence': 'medium' if hits else 'low',
                                     'replace_intervals': intervals, 'reason': 'BB22 onsets, band detection and sample correlation'}),
                     points=points, nodes=nodes,
                     notes=['Velocity and band selection are heuristic; original assets remain unchanged.'])


OPS = {'drum_replace': OpSpec('mix', ('target', 'params'), validate, expand=expand, time_varying=True)}
