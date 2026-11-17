"""W4_1 optional seams; all synthetic ops/commands are registered only in tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

from mankomix.core import api, mixrender as mr
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.director import derived as B, direction as D, edit as E, xops as X
from mankomix.dspx import assets
from tests.test_tk_w4_0 import isolated, song, command, doc, invoke, move
from tests import test_upgrade2_duck as T


def install(monkeypatch, name, *, expand=None, derive=None):
    monkeypatch.setitem(X.OPS, name, X.OpSpec('mix' if expand else 'edit', ('target',),
                                            lambda m, c: None, expand=expand, derive=derive,
                                            code_version='probe-1'))


def control(x, sr, params):
    # A deterministic four-band envelope with source-dependent amplitude.
    return {'kind': 'control', 'values': np.full((201, 4), float(np.max(np.abs(x)))),
            'hop_s': .005, 'centers_hz': np.geomspace(100, 8000, 4)}


def control_mix(project, m):
    return X.MixResult({'evidence': 'probe'}, controls=[
        X.ControlPlan('env', 'trk_vocals', 0, T.SR, {}, control, 'probe-1')], chain=[
        {'type': 'band_envelope', 'params': {'bands': 4, 'envelopes': {'control': 'env'}}}])


def node_mix(project, m):
    # Two overlapping hits must remain additive, rather than muting each other.
    x = np.zeros((240, 2), dtype=np.float64)
    x[5:200] = .02
    return X.MixResult({'hits': 2}, nodes=X.NodePlan(
        tracks=[{'name': 'reinforce', 'role': 'drums', 'output': project.tracks()[m['target']]['output']}],
        assets=[X.AudioPlan('hit', x, project.rate, {'polarity': 1, 'speed': 1}, 'probe-1')],
        clips=[{'track': 'reinforce', 'asset': 'hit', 'timeline_start': pos, 'length': 240, 'gain_db': -3}
               for pos in (100, 200)]))


def invert(x, sr, params):
    assert params['group_mapping'] == {'map': [[0, 0], [1000, 1000]], 'cuts': [100, 1000]}
    return -x


def group_plan(root, m):
    return X.DerivedBundle(
        {tid: X.DerivedPlan(100, 1000, {}, invert) for tid in [m['target'], *m['params']['group']]},
        {'map': [[0, 0], [1000, 1000]], 'cuts': [100, 1000]}, {'confidence': 'high'})


def ledger(song, parsed):
    return B._ledger(song, parsed['id'])


def test_underscore_command_and_legacy_query(song):
    from mankomix.cli import main as cli
    from mankomix.director import commands as C
    row = command(('query', 'limiter_headroom'))
    before = C._snapshot(song)
    assert invoke(row, song) == {'a': 2, 'z': 1}
    p = cli.build_parser().parse_args(['direction', 'query', 'old.wav', '{}'])
    assert p.func is cli.cmd_direction_query
    assert 'direction query limiter_headroom' in C.cli_only()
    assert C._snapshot(song) == before


@pytest.mark.parametrize('out', [False, True])
@pytest.mark.parametrize('raises', [False, True])
def test_optional_out_checks_writes_even_on_failure(song, tmp_path, out, raises):
    def run(args):
        (song / 'journal.jsonl').write_text('leak', encoding='utf-8')
        if raises:
            raise RuntimeError('probe')
        return {'json_only': not args.out}
    with pytest.raises(InputError, match='write contract'):
        invoke(command(('extract', 'probe_midi'), run, 'out_only'), song,
               ['--out', str(tmp_path / 'out.mid')] if out else [])


def test_optional_out_json_only_and_explicit_file(song, tmp_path):
    from mankomix.director import commands as C
    def run(args):
        if args.out:
            Path(args.out).write_bytes(b'MThd-probe')
        return {'written': bool(args.out)}
    row = command(('extract', 'probe_midi'), run, 'out_only')
    before = C._snapshot(song)
    assert invoke(row, song) == {'written': False}
    assert C._snapshot(song) == before
    target = tmp_path / 'notes.mid'
    assert invoke(row, song, ['--out', str(target)]) == {'written': True}
    assert target.read_bytes() == b'MThd-probe'
    assert C._snapshot(song) == before


def test_nodes_build_readonly_apply_overlap_trace_check_revert(song, tmp_path, monkeypatch):
    from mankomix.director import commands as C
    from mankomix.director.xops import _resources
    install(monkeypatch, 'probe_nodes', expand=node_mix)
    parsed = doc(tmp_path, [move('probe_nodes')])
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    before_data = Project.open(song).data
    before_audio = mr.render_mix(Project.open(song))[0]
    before = C._snapshot(song)
    a = D.build_proposal(D._Project(song), parsed)
    b = D.build_proposal(D._Project(song), parsed)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert C._snapshot(song) == before
    result = D.apply(song, parsed['path'])
    assert result['applied'], result
    p = Project.open(song)
    track = next(t for t in p.data['tracks'] if t.get('move_ref'))
    assert track['role'] == 'drums' and track['output'] == before_data['tracks'][0]['output']
    assert len(track['clips']) == 2 and not any(c['muted'] for c in track['clips'])
    y = E.raw_track(song, track['id'])[0]
    assert y[210, 0] == pytest.approx(.04 * 10**(-3/20))
    assert p.data['timebase']['length_samples'] == before_data['timebase']['length_samples']
    resources = result['record']['moves']['m01']['resources']
    assert _resources.check(song, parsed['id'], 'm01', resources)
    node_asset = ledger(song, parsed)['nodes']['m01']['assets']['hit']
    dest = Project.open(song).asset_path(node_asset['asset'])
    contents = dest.read_bytes()
    dest.unlink()
    assert B.regenerate_node(song, parsed['id'], 'm01', 'hit')['regenerated']
    assert dest.read_bytes() == contents
    dest.unlink()
    (song / 'cache' / 'derived' / f"{node_asset['key']}.node.wav").unlink()
    audio = node_mix(D._Project(song), move('probe_nodes')).nodes.assets[0].audio
    assert B.regenerate_node(song, parsed['id'], 'm01', 'hit', audio=audio)['regenerated']
    assert dest.read_bytes() == contents
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    # Ownership/ref and audio integrity are both checked.
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[-1]['clips'][0]['move_ref'] = 'wrong/move'
    p.set('/tracks', tracks, actor='human')
    assert not _resources.check(song, parsed['id'], 'm01', resources)
    Project.open(song).set('/tracks', p.data['tracks'][:-1] + [track], actor='human')
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']
    assert mr.render_mix(Project.open(song))[0].tobytes() == before_audio.tobytes()
    assert len(Project.open(song).data['tracks']) == len(before_data['tracks'])
    assert E.revert(song, parsed['id'], 'm01')['reverted_moves'] == []


def test_nodes_refuse_timeline_extension_readonly(song, tmp_path, monkeypatch):
    from mankomix.director import commands as C
    def bad(p, m):
        result = node_mix(p, m)
        result.nodes.clips[0]['timeline_start'] = T.SR - 10
        return result
    install(monkeypatch, 'probe_nodes', expand=bad)
    parsed = doc(tmp_path, [move('probe_nodes')])
    before = C._snapshot(song)
    with pytest.raises(ValueError, match='timeline'):
        D.build_proposal(D._Project(song), parsed)
    assert C._snapshot(song) == before


def test_nodes_compensate_core_failure(song, tmp_path, monkeypatch):
    from mankomix.core import remix
    install(monkeypatch, 'probe_nodes', expand=node_mix)
    parsed = doc(tmp_path, [move('probe_nodes')])
    before = Project.open(song).data
    commit = remix._commit
    def fail(project, data, **kwargs):
        if kwargs.get('op') == 'direction_node_place':
            raise RuntimeError('placement failed')
        return commit(project, data, **kwargs)
    monkeypatch.setattr(remix, '_commit', fail)
    with pytest.raises(RuntimeError, match='placement failed'):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before
    assert not E.ledger_path(song, parsed['id']).is_file()


def test_control_build_apply_persistent_resolver_regenerate_check_revert(song, tmp_path, monkeypatch):
    from mankomix.director import commands as C
    from mankomix.director.xops import _resources
    install(monkeypatch, 'probe_control', expand=control_mix)
    parsed = doc(tmp_path, [move('probe_control')])
    before = C._snapshot(song)
    prop, rec, _ = D.build_proposal(D._Project(song), parsed)
    assert C._snapshot(song) == before
    aid = rec['moves']['m01']['resources']['controls']['env']['result']['asset']
    assert prop['changes']['tracks']['trk_bass']['chain'][-1]['params']['envelopes'] == aid
    original = mr.render_mix(Project.open(song))[0]
    result = D.apply(song, parsed['path'])
    assert result['applied'], result
    resources = result['record']['moves']['m01']['resources']
    row = ledger(song, parsed)['controls']['m01__env']
    assert row['kind'] == 'control' and row['move_ref'] == f"{parsed['id']}/m01"
    assert not any(a['id'] == aid for a in Project.open(song).data['assets'])
    assert _resources.check(song, parsed['id'], 'm01', resources)
    wet = mr.render_mix(Project.open(song))[0]
    assert wet.tobytes() != original.tobytes()
    # No director import/bootstrap in the child: the normal core render resolves it.
    code = ('import sys,hashlib; from mankomix.core.project import Project; '
            'from mankomix.core.mixrender import render_mix; '
            'print(hashlib.sha256(render_mix(Project.open(sys.argv[1]))[0].tobytes()).hexdigest())')
    child = subprocess.run([sys.executable, '-B', '-c', code, str(song)], capture_output=True,
                           text=True, timeout=60, check=True)
    import hashlib
    assert child.stdout.strip() == hashlib.sha256(wet.tobytes()).hexdigest()
    dest, cache = B._control_paths(song, row)
    contents = dest.read_bytes()
    dest.unlink()
    assert B.regenerate_control(song, parsed['id'], 'm01', 'env')['regenerated']
    assert dest.read_bytes() == contents
    dest.unlink()
    cache.unlink()
    assert B.regenerate_control(song, parsed['id'], 'm01', 'env', calculate=control)['regenerated']
    assert dest.read_bytes() == contents
    dest.write_text('{}', encoding='utf-8')
    with pytest.raises(B.DerivedError, match='sha256'):
        B.regenerate_control(song, parsed['id'], 'm01', 'env', calculate=control)
    assert not _resources.check(song, parsed['id'], 'm01', resources)
    dest.write_bytes(contents)
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']
    assert mr.render_mix(Project.open(song))[0].tobytes() == original.tobytes()


def test_control_regeneration_wrong_version_hash_and_project_copy(song, tmp_path, monkeypatch):
    install(monkeypatch, 'probe_control', expand=control_mix)
    parsed = doc(tmp_path, [move('probe_control')])
    D.apply(song, parsed['path'])
    copied = tmp_path / 'copied'
    shutil.copytree(song, copied)
    row = ledger(song, parsed)['controls']['m01__env']
    aid = row['result']['asset']
    with B.control_context(copied):
        assert assets.resolve('derived', aid)['kind'] == 'control'
    dest, cache = B._control_paths(song, row)
    dest.unlink()
    cache.unlink()
    def wrong(x, sr, params):
        out = control(x, sr, params)
        out['values'] *= 2
        return out
    with pytest.raises(B.DerivedError, match='differs'):
        B.regenerate_control(song, parsed['id'], 'm01', 'env', calculate=wrong)
    assert not dest.exists() and not cache.exists()


def test_group_apply_shared_mapping_regenerate_check_revert(song, tmp_path, monkeypatch):
    from mankomix.director.xops import _group
    install(monkeypatch, 'probe_group', derive=group_plan)
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals'])])
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    original = {tid: E.raw_track(song, tid)[0] for tid in ('trk_bass', 'trk_vocals')}
    frames = Project.open(song).data['timebase']['length_samples']
    result = D.apply(song, parsed['path'])['record']['moves']['m01']
    assert result['kind'] == 'derived_group' and len(result['members']) == 2
    assert _group.check(song, parsed['id'], 'm01', result)
    p = Project.open(song)
    before_tracks = copy.deepcopy(p.data['tracks'])
    tampered = copy.deepcopy(before_tracks)
    for c in tampered[0]['clips']:
        c.pop('move_ref', None)
    p.set('/tracks', tampered, actor='human')
    assert not _group.check(song, parsed['id'], 'm01', result)
    Project.open(song).set('/tracks', before_tracks, actor='human')
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    for tid, old in original.items():
        expected = old.copy()
        expected[100:1000] *= -1
        assert E.raw_track(song, tid)[0].tobytes() == expected.tobytes()
    assert Project.open(song).data['timebase']['length_samples'] == frames
    for tid, member in result['members'].items():
        Project.open(song).asset_path(member['result']['asset']).unlink(missing_ok=True)
        (song / 'cache' / 'derived' / f"{member['key']}.wav").unlink(missing_ok=True)
    repaired = B.regenerate_group(song, parsed['id'], 'm01', calculators={t: invert for t in original})
    assert all(r['regenerated'] for r in repaired.values())
    assert _group.check(song, parsed['id'], 'm01', result)
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']
    for tid, old in original.items():
        assert E.raw_track(song, tid)[0].tobytes() == old.tobytes()
    assert ledger(song, parsed)['derived_groups']['m01']['status'] == 'reverted'


def test_group_failure_rolls_back_all_members_and_ledger(song, tmp_path, monkeypatch):
    def plan(root, m):
        bundle = group_plan(root, m)
        def fail(*args):
            raise RuntimeError('second member failed')
        bundle.plans['trk_vocals'].calculate = fail
        return bundle
    install(monkeypatch, 'probe_group', derive=plan)
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals'])])
    before = Project.open(song).data
    with pytest.raises(RuntimeError, match='second member'):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before
    assert not E.ledger_path(song, parsed['id']).exists()


def test_group_preflights_foreign_peer_before_calculating(song, tmp_path, monkeypatch):
    calls = []
    B.apply(song, 'foreign', 'foreign_move', 'trk_vocals', 100, 1000,
            op='foreign', params={}, code_version='1', calculate=lambda x, s, p: -x)
    def plan(root, m):
        calls.append(True)
        return group_plan(root, m)
    install(monkeypatch, 'probe_group', derive=plan)
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals'])])
    before = Project.open(song).data
    with pytest.raises(D.DirectionError, match='another direction'):
        D.apply(song, parsed['path'])
    assert not calls and Project.open(song).data == before


def test_group_revert_stale_peer_is_atomic(song, tmp_path, monkeypatch):
    install(monkeypatch, 'probe_group', derive=group_plan)
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals'])])
    D.apply(song, parsed['path'])
    p = Project.open(song)
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[1]['clips'][-1]['gain_db'] = -2
    p.set('/tracks', tracks, actor='human')
    before = Project.open(song).data
    with pytest.raises(E.EditError, match='layout changed'):
        E.revert(song, parsed['id'])
    assert Project.open(song).data == before
    assert ledger(song, parsed)['derived_groups']['m01']['status'] == 'applied'


def test_group_interleaved_single_revert_and_bad_mapping(song, tmp_path, monkeypatch):
    install(monkeypatch, 'probe_group', derive=group_plan)
    install(monkeypatch, 'probe_single', derive=lambda r, m: X.ClipPlan(
        {E.raw_track(r, m['target'])[2]['tracks'][1]['clips'][-1]['id']: {'gain_db': -2}}, {}))
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals']), move('probe_single', 'm02', 'trk_vocals')])
    before = {t: E.raw_track(song, t)[0] for t in ('trk_bass', 'trk_vocals')}
    D.apply(song, parsed['path'])
    with pytest.raises(E.EditError, match='later moves'):
        E.revert(song, parsed['id'], 'm01')
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01', 'm02']
    for tid, x in before.items():
        assert E.raw_track(song, tid)[0].tobytes() == x.tobytes()


def test_nodes_automation_revert_and_apply_failure(song, tmp_path, monkeypatch):
    def expand(p, m):
        result = node_mix(p, m)
        result.points = [[0, 0], [100, -1], [300, 0]]
        return result
    install(monkeypatch, 'probe_nodes', expand=expand)
    parsed = doc(tmp_path, [move('probe_nodes')])
    original = mr.render_mix(Project.open(song))[0]
    D.apply(song, parsed['path'])
    E.revert(song, parsed['id'])
    assert mr.render_mix(Project.open(song))[0].tobytes() == original.tobytes()


def test_mix_apply_failure_compensates_nodes_and_controls(song, tmp_path, monkeypatch):
    def expand(p, m):
        result = node_mix(p, m)
        c = control_mix(p, m)
        result.controls, result.chain = c.controls, c.chain
        return result
    install(monkeypatch, 'probe_both', expand=expand)
    parsed = doc(tmp_path, [move('probe_both')])
    before = Project.open(song).data
    monkeypatch.setattr(api, 'plan_apply', lambda *a, **k: {'error': 'probe failure'})
    with pytest.raises(D.DirectionError, match='probe failure'):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before
    assert not E.ledger_path(song, parsed['id']).exists()
    assert not list((tmp_path / 'home' / 'derived').glob('*.json'))


@pytest.mark.parametrize('peers', [8, 16])
def test_group_capacity_and_one_fixed_map(song, tmp_path, monkeypatch, peers):
    project = Project.open(song)
    tracks = copy.deepcopy(project.data['tracks'])
    for i in range(peers - 1):
        t = copy.deepcopy(tracks[1])
        t['id'] = f'trk_peer_{i}'
        t['is_lead'] = False
        for j, c in enumerate(t['clips']):
            c['id'] = f'clp_peer_{i}_{j}'
        tracks.append(t)
    project.set('/tracks', tracks, actor='human')
    names = [t['id'] for t in tracks[1:]]
    install(monkeypatch, 'probe_group', derive=group_plan)
    parsed = doc(tmp_path, [move('probe_group', group=names)])
    original = {tid: E.raw_track(song, tid)[0] for tid in ['trk_bass', *names]}
    D.apply(song, parsed['path'])
    row = ledger(song, parsed)['derived_groups']['m01']
    assert len(row['members']) == peers + 1
    assert all(ledger(song, parsed)['derived'][r['move']]['params']['group_mapping'] == row['mapping']
               for r in row['members'].values())
    E.revert(song, parsed['id'])
    assert all(E.raw_track(song, tid)[0].tobytes() == x.tobytes() for tid, x in original.items())


@pytest.mark.parametrize('problem', ['placement', 'mapping', 'coverage'])
def test_invalid_group_is_atomic(song, tmp_path, monkeypatch, problem):
    def derive(root, m):
        p = group_plan(root, m)
        if problem == 'placement':
            p.plans['trk_vocals'].start += 1
        elif problem == 'mapping':
            p.plans['trk_vocals'].params['group_mapping'] = {'different': True}
        else:
            del p.plans['trk_vocals']
        return p
    install(monkeypatch, 'probe_group', derive=derive)
    parsed = doc(tmp_path, [move('probe_group', group=['trk_vocals'])])
    before = Project.open(song).data
    with pytest.raises(D.DirectionError):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before
    assert not E.ledger_path(song, parsed['id']).exists()


def test_unused_new_seams_are_byte_identical(song, tmp_path, monkeypatch):
    install(monkeypatch, 'probe_nodes', expand=node_mix)
    install(monkeypatch, 'probe_control', expand=control_mix)
    install(monkeypatch, 'probe_group', derive=group_plan)
    twin, floor = tmp_path / 'twin', tmp_path / 'floor'
    shutil.copytree(song, twin)
    shutil.copytree(song, floor)
    T._render(floor)
    parsed = doc(tmp_path, [move('gain', delta_db=-1)])
    def capture(root):
        validation = D.canonical_block(D.validate(parsed, root)).encode()
        proposal = D.canonical_block(D.build_proposal(D._Project(root), parsed)).encode()
        D.apply(root, parsed['path'])
        apply_bytes = (root / 'directions' / f"{parsed['id']}.apply.json").read_bytes()
        T._render(root)
        outcome = D.canonical_block(D.check(root, floor, parsed['path'])).encode()
        check_bytes = (root / 'directions' / f"{parsed['id']}.outcome.json").read_bytes()
        return validation, proposal, apply_bytes, outcome, check_bytes
    with monkeypatch.context() as disabled:
        disabled.setattr(X, 'specs', lambda builtins=(): {})
        before = capture(song)
    assert capture(twin) == before
