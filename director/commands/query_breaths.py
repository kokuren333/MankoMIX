"""Read-only breath candidates with stable project-sample IDs."""
from mankomix.core.errors import InputError
from mankomix.director.direction import _Project
from mankomix.director.xops import breath as B, _w4g as W


def add_args(parser):
    parser.add_argument('--target', required=True)
    parser.add_argument('--section')
    parser.add_argument('--sensitivity', type=float, default=.5)
    parser.add_argument('--min-ms', type=float, default=120)
    parser.add_argument('--max-ms', type=float, default=900)


def run(args):
    project = _Project(args.project or '.')
    move = {'target': args.target, 'section': args.section,
            'params': {'sensitivity': args.sensitivity, 'min_ms': args.min_ms, 'max_ms': args.max_ms}}
    errors = []
    from mankomix.director.xops import ValidationContext
    B.validate(move, ValidationContext(project, {}, '', lambda w, c, m: errors.append(m)))
    if errors:
        raise InputError('; '.join(errors))
    p = W.params(move, B.NUMERIC, B.ENUMS)
    x, sr = W.audio(project.root, args.target)
    a, b = W.scope(project, move, x, sr)
    rows = [r for r in B.detect(x, sr, p) if a <= r['start_sample'] < r['end_sample'] <= b]
    return W.clean({'kind': 'direction_query_breaths', 'target': args.target, 'sample_rate': sr,
                    'confidence': 'medium' if rows else 'low', 'breaths': rows[:2000], 'count': len(rows),
                    'feature_weights': B.WEIGHTS, 'calibration': 'synthetic_only',
                    'notes': ['Heuristic confidence; inspect candidates before using only/skip.'],
                    'section_samples': [a, b]})


COMMANDS = [{'path': ('query', 'breaths'), 'help': 'Measure breath candidates without applying automation',
             'add_args': add_args, 'run': run, 'writes': False}]
