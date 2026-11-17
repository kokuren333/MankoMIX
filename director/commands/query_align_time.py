"""T11-01: read-only guide alignment map and measured before/after evidence."""
import json
from mankomix.core.errors import InputError
from mankomix.director.xops import _alignment as A


def add_args(parser):
    parser.add_argument('--target', required=True)
    parser.add_argument('--guide', required=True)
    parser.add_argument('--section')
    for k, (_, _, default) in A.TIME_NUMERIC.items():
        parser.add_argument('--'+k.replace('_', '-'), type=float, default=default)
    for k, (choices, default) in A.TIME_ENUMS.items():
        parser.add_argument('--'+k, choices=choices, default=default)
    parser.add_argument('--anchors', default='[]', help='JSON [target_s, guide_s] pairs, relative to selected interval')


def run(args):
    from mankomix.director.direction import _Project
    from mankomix.director.xops import ValidationContext
    try:
        anchors = json.loads(args.anchors)
    except (ValueError, TypeError):
        raise InputError('--anchors must be a JSON array') from None
    p = {k: getattr(args, k) for k in A.TIME_NUMERIC | A.TIME_ENUMS}
    p.update(guide=args.guide, anchors=anchors)
    move = {'target': args.target, 'params': p}
    if args.section:
        move['section'] = args.section
    errors = []
    A.validate(move, ValidationContext(_Project(args.project or '.'), {}, '', lambda w, c, m: errors.append(m)))
    if errors:
        raise InputError('; '.join(errors))
    try:
        plan = A.derive(args.project or '.', move)
    except ValueError as e:
        raise InputError(str(e)) from None
    return A.clean({'kind': 'direction_query_align_time', 'target': args.target, 'guide': args.guide,
                    **plan.record, 'params': p, 'candidate': {'op': 'edit_align_time', **move}})


COMMANDS = [{'path': ('query', 'align_time'), 'help': 'Measure a guide-based timing map without applying it',
             'add_args': add_args, 'run': run, 'writes': False}]
