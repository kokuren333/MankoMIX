"""W4f seam probes only: group no-op plans are not supported by W4_1.

These tests document the blocker; they are not alignment acceptance tests.
No production operation is registered. All audio and ledgers use tmp_path.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from mankomix.core.project import Project
from mankomix.director import commands as C, derived as B, edit as E, xops as X
from tests import test_upgrade2_duck as T


@pytest.fixture
def probe_song(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    tone = .1*np.sin(2*np.pi*220*np.arange(T.SR)/T.SR)
    audio = np.column_stack([tone, tone*.75])
    return T._make(tmp_path / 'song', {'bass': audio, 'vocals': audio*.5})


def identity(x, sr, params):
    return x.copy()


def attempt(root, plan):
    spec = X.OpSpec('edit', ('target', 'params'), lambda m, c: None,
                    derive=lambda r, m: plan, code_version='w4f-probe-1')
    move = {'id': 'm01', 'op': 'test_w4f_probe', 'target': 'trk_bass',
            'params': {'group': ['trk_vocals']}}
    return X.apply_edit(root, {'id': 'dir_w4f_probe'}, move, spec, actor='human')


@pytest.mark.parametrize('plan,error', [
    (None, 'expected an edit plan'),
    (X.ClipPlan({}, {}, {'reason': 'identity'}), 'group edits require a DerivedBundle'),
    (X.DerivedBundle({}, {'identity': True}), 'bundle must cover target'),
])
def test_group_no_asset_plan_rejected_readonly(probe_song, plan, error):
    before = C._snapshot(probe_song)
    with pytest.raises(ValueError, match=error) as caught:
        attempt(probe_song, plan)
    assert C._snapshot(probe_song) == before
    print(json.dumps({'plan': type(plan).__name__, 'error': str(caught.value),
                      'project_tree_unchanged': True}, sort_keys=True))


def test_identity_bundle_still_registers_derived_audio(probe_song):
    project = Project.open(probe_song)
    before_clips = {t['id']: copy.deepcopy(t['clips']) for t in project.data['tracks']}
    before_audio = {tid: E.raw_track(probe_song, tid)[0] for tid in before_clips}
    plans = {tid: X.DerivedPlan(0, T.SR, {}, identity) for tid in before_clips}
    result = attempt(probe_song, X.DerivedBundle(plans, {'map': [[0, 0], [T.SR, T.SR]]}))
    ledger = B._ledger(probe_song, 'dir_w4f_probe')
    assert result['kind'] == 'derived_group'
    assert len(ledger['derived']) == 2
    after = Project.open(probe_song)
    assert all(t['clips'] != before_clips[t['id']] for t in after.data['tracks'])
    assert all(member['clip'] for member in result['members'].values())
    for tid in before_clips:
        np.testing.assert_array_equal(E.raw_track(probe_song, tid)[0], before_audio[tid])
    print(json.dumps({'identity_bundle': True, 'derived_rows': len(ledger['derived']),
                      'derived_group_rows': len(ledger['derived_groups']),
                      'replacement_clips': len(result['members']),
                      'raw_audio_unchanged': True}, sort_keys=True))
