"""T11-06 read-only BB-22/pYIN notes and original SMF0/480 writer.

SMF encoding follows the public MIDI 1.0 file format: big-endian chunks,
variable-length delta ticks, explicit channel status bytes and end-of-track.
No running status or third-party MIDI dependency is used.
"""
from pathlib import Path
import struct
import numpy as np
from mankomix.core.errors import InputError


def add_args(parser):
    from mankomix.dsp.processors import NOTE_VALUES
    parser.add_argument('--target', required=True)
    parser.add_argument('--kind', choices=['drums', 'mono'], required=True)
    parser.add_argument('--note', type=int, default=36)
    parser.add_argument('--map')
    parser.add_argument('--threshold-db', type=float, default=-30)
    parser.add_argument('--min-interval-ms', type=float, default=30)
    parser.add_argument('--velocity-range', nargs=2, type=int, default=[20, 127])
    parser.add_argument('--bpm', type=float)
    parser.add_argument('--origin', type=float, default=0)
    parser.add_argument('--quantize', choices=['off']+[v for v in NOTE_VALUES if v != 'none'], default='off')
    parser.add_argument('--min-note-ms', type=float, default=60)
    parser.add_argument('--lo-hz', type=float, default=70)
    parser.add_argument('--hi-hz', type=float, default=1000)
    parser.add_argument('--a4', type=float, default=440)
    parser.add_argument('--bend', choices=['off', 'on'], default='off', nargs='?', const='on')
    parser.add_argument('--section')
    parser.add_argument('--out')


def number(value, lo, hi, name):
    if isinstance(value, bool) or not np.isfinite(value) or not lo <= value <= hi:
        raise InputError(f'{name} must be in [{lo}, {hi}]')


def parse_map(value, sr):
    rows = []
    if value:
        try:
            for item in value.split(','):
                lo, hi, note = item.split(':')
                lo, hi, note = float(lo), float(hi), int(note)
                if not np.isfinite([lo, hi]).all() or not 0 <= lo < hi <= sr/2 or not 0 <= note <= 127:
                    raise ValueError
                rows.append([lo, hi, note])
            if len(rows) > 16:
                raise ValueError
        except ValueError:
            raise InputError('--map requires up to 16 lo:hi:note frequency bands within Nyquist') from None
    return rows


def drum_notes(x, sr, args):
    from mankomix.dspx.bb.drum_events import velocities, drum_onsets
    from scipy import fft
    rows = [r for r in drum_onsets(x, sr, min_interval_ms=args.min_interval_ms)
            if r['peak_dbfs'] is not None and r['peak_dbfs'] >= args.threshold_db]
    strength = velocities(rows)
    mapping = parse_map(args.map, sr)
    out = []
    for r, value in zip(rows, strength):
        note, ratios = args.note, []
        if mapping:
            seg = x[r['sample']:min(len(x), r['sample']+round(.03*sr))]
            size = fft.next_fast_len(max(8, len(seg)))
            power = np.sum(abs(fft.rfft(seg, size, axis=0, workers=1))**2, axis=1)
            freq = fft.rfftfreq(size, 1/sr)
            energy = [float(power[(freq >= lo) & (freq < hi)].sum()) for lo, hi, _ in mapping]
            ratios = (np.asarray(energy)/max(sum(energy), 1e-30)).tolist()
            note = mapping[int(np.argmax(energy))][2]
        lo, hi = args.velocity_range
        out.append({'id': r['id'], 'time_s': r['time_s'], 'duration_s': .05, 'note': note,
                    'velocity': int(round(lo+value*(hi-lo))), 'strength': float(value),
                    'confidence': r['confidence'], 'band_ratios': r['band_ratios'], 'map_ratios': ratios,
                    'bends': []})
    return out


def mono_notes(x, sr, args):
    from mankomix.director.xops._pitch_notes import observe
    from scipy import ndimage
    tr, rows = observe(x, sr, lo_hz=args.lo_hz, hi_hz=args.hi_hz, a4=args.a4)
    env = np.sqrt(np.maximum(0, ndimage.uniform_filter1d(np.mean(x*x, axis=1),
                                                       max(1, round(.002*sr)))))

    def boundary(sample, rising):
        a, b = max(0, sample-round(.06*sr)), min(len(x), sample+round(.06*sr))
        local = env[a:b]
        if not len(local):
            return sample
        mask = local >= max(1e-6, float(np.max(local))*.02)
        changes = np.flatnonzero(np.diff(mask.astype(int)) == (1 if rising else -1))+1+a
        return int(min(changes, key=lambda pos: abs(pos-sample))) if len(changes) else sample

    out = []
    for r in rows:
        if (r['end_sample']-r['start_sample'])*1000/sr < args.min_note_ms:
            continue
        note = int(np.clip(round(r['pitch_midi']), 0, 127))
        start, end = boundary(r['start_sample'], True), boundary(r['end_sample'], False)
        if end-start < args.min_note_ms*sr/1000:
            continue
        peak = float(np.max(np.abs(x[start:end]), initial=0))
        lo, hi = args.velocity_range
        bends = []
        if args.bend == 'on':
            for sample, hz, good in zip(tr.samples, tr.f0_hz, tr.voiced):
                if start <= sample < end and good:
                    semitones = 69+12*np.log2(hz/args.a4)-note
                    bends.append({'time_s': float(sample/sr),
                                  'value': int(np.clip(round(8192+4096*semitones), 0, 16383))})
        out.append({'id': r['id'], 'time_s': start/sr, 'duration_s': (end-start)/sr,
                    'note': note, 'velocity': int(round(lo+min(1., peak)*(hi-lo))),
                    'strength': min(1., peak), 'confidence': r['confidence'], 'bends': bends,
                    'note_boundaries': [r['start_sample'], r['end_sample']],
                    'boundary_refinement': 'nearby_energy_gap'})
    return out


def vlq(n):
    n = int(n)
    if not 0 <= n <= 0x0fffffff:
        raise InputError('MIDI delta exceeds SMF variable-length range')
    parts = [n & 127]
    while n >> 7:
        n >>= 7
        parts.insert(0, 128 | (n & 127))
    return bytes(parts)


def smf(notes, bpm, *, drums=False, bend=False):
    channel = 9 if drums else 0
    tempo = round(60_000_000/bpm)
    events = [(0, -3, b'\xff\x51\x03'+tempo.to_bytes(3, 'big'))]
    if bend and not drums:
        for index, (control, value) in enumerate([(101, 0), (100, 0), (6, 2), (38, 0), (101, 127), (100, 127)]):
            events.append((0, -2, bytes([0xb0+channel, control, value])))
    for r in notes:
        a, b = r['tick'], r['end_tick']
        events.extend([(a, 1, bytes([0x90+channel, r['note'], r['velocity']])),
                       (b, 0, bytes([0x80+channel, r['note'], 0]))])
        if bend and not drums:
            events.append((b, 0, bytes([0xe0+channel, 0, 64])))
            for point in r['bends']:
                value = point['value']
                events.append((point['tick'], 2, bytes([0xe0+channel, value & 127, value >> 7])))
    events.sort(key=lambda r: (r[0], r[1]))
    data, previous = bytearray(), 0
    for tick, _, payload in events:
        data.extend(vlq(tick-previous)+payload)
        previous = tick
    data.extend(b'\x00\xff\x2f\x00')
    return b'MThd'+struct.pack('>IHHH', 6, 0, 1, 480)+b'MTrk'+struct.pack('>I', len(data))+data


def run(args):
    from mankomix.director.direction import _Project
    from mankomix.director.commands._eq_reference import section_audio
    from mankomix.director.xops._w4g import clean
    from mankomix.director.edit import raw_track
    from mankomix.director.duck import floor_bpm
    from mankomix.dsp.processors import note_ms
    project = _Project(args.project or '.')
    if args.target not in project.tracks():
        raise InputError('--target requires an existing track')
    number(args.note, 0, 127, '--note')
    number(args.threshold_db, -80, 0, '--threshold-db')
    number(args.min_interval_ms, 5, 500, '--min-interval-ms')
    number(args.origin, 0, 36000, '--origin')
    number(args.min_note_ms, 20, 500, '--min-note-ms')
    number(args.a4, 400, 480, '--a4')
    for v in args.velocity_range:
        number(v, 1, 127, '--velocity-range')
    if args.velocity_range[0] > args.velocity_range[1]:
        raise InputError('--velocity-range must be ascending')
    bpm = args.bpm if args.bpm is not None else floor_bpm(project.floor_mxp) or project.data.get('timebase', {}).get('bpm') or 120
    number(bpm, 20, 400, '--bpm')
    x, sr, _ = raw_track(project.root, args.target)
    number(args.lo_hz, 20, sr/2-1, '--lo-hz')
    number(args.hi_hz, args.lo_hz+1, sr/2-1, '--hi-hz')
    _, interval = section_audio(x, sr, project.root, args.section)
    # Validate map even for silence; malformed options never disappear silently.
    parse_map(args.map, sr)
    rows = drum_notes(x, sr, args) if args.kind == 'drums' else mono_notes(x, sr, args)
    rows = [r for r in rows if r['time_s'] < interval[1] and r['time_s']+r['duration_s'] > interval[0]]
    tempo = round(60_000_000/bpm)
    tick_rate = 480*1_000_000/tempo
    rows = [r for r in rows if r['time_s']+r['duration_s'] > args.origin]
    for r in rows:
        absolute = r['time_s']
        source_time = absolute
        if args.quantize != 'off':
            grid = note_ms(args.quantize, bpm)/1000
            absolute = args.origin+round((absolute-args.origin)/grid)*grid
        if absolute < args.origin:
            r['duration_s'] = max(1/tick_rate, r['duration_s']-(args.origin-absolute))
            absolute = args.origin
        r.update(source_time_s=source_time, time_s=absolute,
                 tick=max(0, round((absolute-args.origin)*tick_rate)))
        r['end_tick'] = r['tick']+max(1, round(r['duration_s']*tick_rate))
        for point in r['bends']:
            point['time_s'] += absolute-source_time
            point['tick'] = min(r['end_tick']-1, max(r['tick'], round((point['time_s']-args.origin)*tick_rate)))
    content = smf(rows, bpm, drums=args.kind == 'drums', bend=args.bend == 'on')
    if args.out:
        out = Path(args.out)
        if out.exists() and out.is_dir():
            raise InputError('--out must name one MIDI file')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    return clean({'kind': 'direction_extract_midi', 'notes': rows, 'confidence': 'medium' if rows else 'low',
                  'sample_rate': sr, 'bpm': bpm, 'tempo_us_per_quarter': tempo, 'origin_s': args.origin,
                  'division': 480, 'format': 0, 'section_s': interval, 'written': bool(args.out),
                  'method': 'BB22_flux_peak' if args.kind == 'drums' else 'BB12_pYIN_T08_notes_energy_boundaries',
                  'caveats': ['Monophonic melody only; band-ratio drum classification is heuristic.']})


COMMANDS = [{'path': ('extract', 'midi'), 'help': 'Measure drum/monophonic notes and optionally write one SMF',
             'add_args': add_args, 'run': run, 'writes': 'out_only'}]
