"""T08-02: inspect monophonic notes without writing project or analysis caches."""
from mankomix.core.errors import InputError
from mankomix.director.xops._pitch_notes import observe, clean


def section_arg(value):
    if not value.lstrip().startswith('{'):
        return value
    import json
    import argparse
    try:
        return json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('section must be an ID or JSON object') from exc


def add_args(parser):
    parser.add_argument('--target', required=True)
    parser.add_argument('--section', type=section_arg)
    parser.add_argument('--lo-hz', type=float, default=70)
    parser.add_argument('--hi-hz', type=float, default=1000)
    parser.add_argument('--a4', type=float, default=440)


def run(args):
    from mankomix.director.direction import _Project
    from mankomix.director.edit import raw_track
    from mankomix.director.query import section_range, QueryError
    project = _Project(args.project or '.')
    if args.target not in project.tracks():
        raise InputError('target must be an existing track')
    x, sr, _ = raw_track(project.root, args.target)
    try:
        a, b = section_range(args.section, project.sections(), len(x)/sr)
    except QueryError as exc:
        raise InputError(str(exc)) from None
    a, b = round(a*sr), round(b*sr)
    track, rows = observe(x, sr, lo_hz=args.lo_hz, hi_hz=args.hi_hz, a4=args.a4)
    # Analyze the complete timeline to preserve IDs and edge context in sections.
    rows = [r for r in rows if r['end_sample'] > a and r['start_sample'] < b]
    import numpy as np
    ix = (track.samples >= a) & (track.samples < b)
    return clean({'kind': 'direction_pitch_notes', 'target': args.target, 'sample_rate': sr,
                  'notes': rows, 'count': len(rows), 'section_samples': [a, b],
                  'confidence': float(np.mean(track.probability[ix])) if np.any(ix) else 0.,
                  'measurements': {'hop_samples': track.hop_samples,
                                   'voiced_fraction': float(np.mean(track.voiced[ix])) if np.any(ix) else 0.,
                                   'lo_hz': args.lo_hz, 'hi_hz': args.hi_hz, 'a4_hz': args.a4},
                  'caveats': ['Monophonic pYIN estimate; overlapping voices and chords are ambiguous.',
                              'Section results retain complete intersecting note boundaries.',
                              'Vibrato width is peak-to-peak in the 4..8 Hz component.']})


COMMANDS = [{'path': ('pitch', 'notes'), 'help': 'Inspect monophonic note measurements',
             'add_args': add_args, 'run': run, 'writes': False}]
