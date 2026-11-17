"""T11-02: single-pass pitch-synchronous pitch and timing alignment."""
from . import OpSpec
from . import _alignment as A


def validate(move, ctx):
    A.validate(move, ctx, pitch=True)


def derive(root, move):
    return A.derive(root, move, pitch=True)


OPS = {'edit_align_pitch': OpSpec('edit', ('target', 'params'), validate,
        derive=derive, code_version='w4f-align-pitch-1', time_varying=True)}
