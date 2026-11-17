"""T11-01: guide-based timing alignment through BB-23 and BB-18."""
from . import OpSpec
from . import _alignment as A

OPS = {'edit_align_time': OpSpec('edit', ('target', 'params'), A.validate,
        derive=A.derive, code_version='w4f-align-time-1', time_varying=True)}
