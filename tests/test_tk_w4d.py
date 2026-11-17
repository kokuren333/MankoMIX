"""Characterize W4d seam blockers; these are not op acceptance tests.

Remove or revise these probes when the shared edit contract is extended.
No production operation is registered here.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.core import mixrender as mr
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.director import commands as C, xops as X
from tests import test_upgrade2_duck as T


@pytest.fixture
def song(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    tone = .1 * np.sin(2 * np.pi * 220 * np.arange(T.SR) / T.SR)
    stereo = np.stack([tone, tone], axis=1)
    return T._make(tmp_path / 'song', {'bass': stereo, 'vocals': stereo * .5})


@pytest.mark.parametrize('fields', [
    {'fade_curve': 'linear'},
    {'fade_curve': 's_curve'},
    {'timeline_start': 100},
    {'source_start': 100},
    {'source_end': 1000},
])
def test_clip_plan_cannot_express_shape_or_cross_placement(song, fields):
    project = Project.open(song)
    clip = project.data['tracks'][0]['clips'][0]['id']
    plan = X.ClipPlan({clip: fields}, {})
    before = C._snapshot(song)
    with pytest.raises(ValueError, match='only existing clip fades/gain_db on its target'):
        X._apply_clips(song, {'id': 'dir_probe'},
                       {'id': 'm01', 'target': 'trk_bass', 'op': 'edit_fade'},
                       SimpleNamespace(code_version='probe-1'), plan, 'human')
    assert C._snapshot(song) == before


def test_clip_plan_cannot_apply_group_gain_to_another_track(song):
    project = Project.open(song)
    other = next(t for t in project.data['tracks'] if t['id'] == 'trk_vocals')
    plan = X.ClipPlan({other['clips'][0]['id']: {'gain_db': -3}}, {})
    before = C._snapshot(song)
    with pytest.raises(ValueError, match='only existing clip fades/gain_db on its target'):
        X._apply_clips(song, {'id': 'dir_probe'},
                       {'id': 'm01', 'target': 'trk_bass', 'op': 'edit_normalize'},
                       SimpleNamespace(code_version='probe-1'), plan, 'human')
    assert C._snapshot(song) == before


@pytest.mark.parametrize('shape', ['s_curve', 'exp', 'log'])
def test_native_clip_renderer_rejects_required_shapes(shape):
    with pytest.raises(InputError, match='unknown fade_curve'):
        mr._clip_envelope(np.arange(101), 101,
                          {'id': 'clp_probe', 'fade_in': 100, 'fade_curve': shape})


def test_native_default_midpoint_is_equal_power():
    envelope = mr._clip_envelope(np.array([0, 50, 100]), 101, {'fade_in': 100})
    assert envelope.tolist() == pytest.approx([0, 2 ** -.5, 1], abs=1e-15)
