"""W4 registration seams, inert legacy paths, BB-18 edits and CLI write guards."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.cli import main as cli
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.director import commands as C, direction as D, duck as K, edit as E, xops as X
from tests import test_upgrade2_duck as T


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(X, 'OPS', {})
    monkeypatch.setattr(C, 'COMMANDS', [])
    monkeypatch.setattr(C, '_loaded', True)


@pytest.fixture
def song(tmp_path):
    t = np.arange(T.SR) / T.SR
    tone = .1 * np.sin(2 * np.pi * 220 * t)
    stereo = np.stack([tone, tone * .75], axis=1)
    return T._make(tmp_path / 'song', {'bass': stereo, 'vocals': stereo * .5})


def move(op, mid='m01', target='trk_bass', **params):
    return {'id': mid, 'op': op, 'aim': 'a1', 'target': target, 'params': params,
            'basis': 'measured test', 'origin': 'new'}


def doc(tmp_path, moves):
    return D.parse_document(T._doc(tmp_path / 'doc', T._block(moves)))


def validate_move(m, ctx):
    if not isinstance(m.get('params'), dict) or m['params'].get('amount') != -1:
        ctx.err('bad_value', 'amount must be -1')


def expand(proj, m):
    return X.MixResult(record={'measurement': {'before': 0, 'after': -1}},
                       points=[[0, 0], [100, -1], [200, 0]],
                       chain=[{'type': 'gain', 'params': {'gain_db': -1}}])


def invert(x, sr, params):
    return x * params['amount']


def derive(root, m):
    return X.DerivedPlan(100, 1000, dict(m['params']), invert,
                         record={'measurements': {'polarity': -1}})


def install(monkeypatch):
    monkeypatch.setattr(X, 'OPS', {
        'test_mix': X.OpSpec('mix', ('target', 'params'), validate_move, expand=expand, time_varying=True),
        'test_edit': X.OpSpec('edit', ('target', 'params'), validate_move, derive=derive, code_version='test-1')})


def test_ops_discovery_sorted_and_duplicate_atomic(monkeypatch):
    monkeypatch.setattr(X, '_loaded', False)
    monkeypatch.setattr(X, 'iter_modules', lambda path: [SimpleNamespace(name='z'), SimpleNamespace(name='a')])
    spec = X.OpSpec('mix', ('target',), validate_move, expand=expand)
    modules = {'a': SimpleNamespace(OPS={'test_a': spec}), 'z': SimpleNamespace(OPS={'test_z': spec})}
    seen = []

    def importer(name):
        name = name.rsplit('.', 1)[1]
        seen.append(name)
        return modules[name]

    monkeypatch.setattr(X, 'import_module', importer)
    assert list(X.load(D.OPS)) == ['test_a', 'test_z']
    assert seen == ['a', 'z']
    monkeypatch.setattr(X, 'OPS', {})
    monkeypatch.setattr(X, '_loaded', False)
    modules['z'].OPS = {'test_a': spec}
    with pytest.raises(ImportError, match='duplicate'):
        X.load(D.OPS)
    assert X.OPS == {}
    modules['z'].OPS = {'gain': spec}
    with pytest.raises(ImportError, match='duplicate'):
        X.load(D.OPS)


@pytest.mark.parametrize('spec', [
    {'stage': 'other', 'required': (), 'validate': validate_move},
    {'stage': 'mix', 'required': (), 'validate': validate_move},
    {'stage': 'edit', 'required': ('target',), 'validate': validate_move, 'derive': derive},
    {'stage': 'mix', 'required': [], 'validate': validate_move, 'expand': expand},
])
def test_invalid_spec_is_import_error(monkeypatch, spec):
    monkeypatch.setattr(X, 'OPS', {'test_bad': spec})
    with pytest.raises(ImportError):
        X.specs(D.OPS)


def test_extension_validate_required_stage_and_tiers(song, tmp_path, monkeypatch):
    install(monkeypatch)
    good = doc(tmp_path, [move('test_mix', amount=-1), move('test_edit', 'm02', 'trk_vocals', amount=-1)])
    v = D.validate(good, song)
    assert v['ok'], v['errors']
    assert v['tiers'] == {'m01': 'E2', 'm02': 'E3'}
    bad = copy.deepcopy(good)
    bad['block']['moves'][0].update(stage='edit', params={})
    codes = {r['code'] for r in D.validate(bad, song)['errors']}
    assert {'bad_stage', 'bad_value', 'missing_field'} <= codes
    bad['block']['moves'][1]['target'] = 'bus_mix'
    assert 'bad_target' in {r['code'] for r in D.validate(bad, song)['errors']}
    good['block']['moves'][0]['target'] = 'trk_vocals'
    assert D.validate(good, song)['tiers']['m01'] == 'E3'


def test_mix_composes_after_ducks_before_curve_and_traces(song, tmp_path, monkeypatch):
    install(monkeypatch)
    project = Project.open(song)
    tracks = copy.deepcopy(project.data['tracks'])
    tracks[0]['automation'] = {'gain_db': [[0, .1], [300, .2]], 'owner': 'planner'}
    project.set('/tracks', tracks, actor='human')
    duck_points = [[0, 0], [100, -.2], [300, 0]]
    monkeypatch.setattr(K, 'plan', lambda *args: {'points': duck_points, 'record': {'op': 'duck', 'hits': 1}, 'notes': []})
    from mankomix.director import curve
    curve_points = [[0, 0], [200, .3], [300, 0]]
    monkeypatch.setattr(curve, 'points', lambda *args: curve_points)
    section = move('gain', 'm03', delta_db=.4)
    section['section'] = {'t0_s': 0, 't1_s': .5}
    moves = [move('test_mix', amount=-1), move('duck', 'm02', key='trk_vocals'), section,
             move('gain_curve', 'm04', segments=[{'t0_s': 0, 't1_s': .01, 'delta_db': .3, 'why': 'test'}])]
    parsed = doc(tmp_path, moves)
    calls, merge = [], K.merge_automation

    def capture(a, b):
        calls.append(copy.deepcopy(b))
        return merge(a, b)

    monkeypatch.setattr(K, 'merge_automation', capture)
    prop, record, _ = D.build_proposal(D._Project(song), parsed)
    assert calls[-3:] == [duck_points, expand(None, None).points, curve_points]
    automation = prop['changes']['tracks']['trk_bass']['automation']
    expected = tracks[0]['automation']['gain_db']
    for points in (D._automation(T.SR, [(0, .5, .4)], None), duck_points, expand(None, None).points, curve_points):
        expected = merge(expected, points)
    assert automation['gain_db'] == expected
    assert automation['move_ref'] == [f"{parsed['id']}/{m}" for m in ('m03', 'm02', 'm01', 'm04')]
    item = prop['changes']['tracks']['trk_bass']['chain'][-1]
    assert item['move_ref'] == f"{parsed['id']}/m01"
    assert record['moves']['m01']['trace'] == ['automation:trk_bass', item['id']]
    assert record['moves']['m01']['measurement'] == {'before': 0, 'after': -1}


def test_mix_apply_check_and_missing_trace(song, tmp_path, monkeypatch):
    install(monkeypatch)
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    parsed = doc(tmp_path, [move('test_mix', amount=-1)])
    assert D.apply(song, parsed['path'])['applied']
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    p = Project.open(song)
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[0]['automation']['move_ref'] = []
    p.set('/tracks', tracks, actor='human')
    result = D.check(song, floor, parsed['path'])['move_ref']
    assert result['moves_without_trace'] == ['m01']


def test_edit_bb18_apply_check_and_bit_identical_revert(song, tmp_path, monkeypatch):
    install(monkeypatch)
    before = E.raw_track(song, 'trk_bass')[0]
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    parsed = doc(tmp_path, [move('test_edit', amount=-1)])
    result = D.apply(song, parsed['path'])
    assert result['applied'] and result['edits']['derived'] == 1
    expected = before.copy()
    expected[100:1000] *= -1
    assert E.raw_track(song, 'trk_bass')[0].tobytes() == expected.tobytes()
    ledger = json.loads(E.ledger_path(song, parsed['id']).read_text(encoding='utf-8'))
    row = ledger['derived']['m01']
    assert row['code_version'] == 'test-1' and row['status'] == 'applied'
    assert row['result'] == result['record']['moves']['m01']['result']
    assert row['details'] == {'measurements': {'polarity': -1}}
    assert result['record']['moves']['m01']['measurements'] == {'polarity': -1}
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']
    assert E.raw_track(song, 'trk_bass')[0].tobytes() == before.tobytes()
    assert E.revert(song, parsed['id'])['reverted_moves'] == []


def test_mixed_builtin_and_derived_edits_revert_in_reverse_stage_order(tmp_path, monkeypatch):
    from tests import test_upgrade2_edit as U
    install(monkeypatch)
    root = U._make(tmp_path / 'mixed', {
        'bass': U._st(U._sine(1, -13), U._noise(1, -65, 1)),
        'vocals': U._st(U._sine(2, -16))})
    before = E.raw_track(root, 'trk_bass')[0].tobytes()
    trim = move('edit_trim', 'm02', side='tail', threshold_db=-36, hold_ms=50, fade_ms=20)
    parsed = doc(tmp_path, [move('test_edit', amount=-1), trim])
    result = D.apply(root, parsed['path'])
    assert result['record']['moves']['m02']['status'] == 'applied'
    assert result['record']['moves']['m01']['kind'] == 'derived'
    # Reverting the native edit first would destroy BB-18's recorded after-layout.
    result = E.revert(root, parsed['id'])
    assert result['derived_reverted_moves'] == ['m01']
    assert result['reverted_moves'] == ['m02']
    assert E.raw_track(root, 'trk_bass')[0].tobytes() == before
    assert json.loads(E.ledger_path(root, parsed['id']).read_text(encoding='utf-8'))['reverted']


def test_clip_only_edit_seam_and_interleaved_derived_revert(song, tmp_path, monkeypatch):
    install(monkeypatch)

    def plan(root, m):
        clips = Project.open(root).data['tracks'][0]['clips']
        return X.ClipPlan({c['id']: {'gain_db': -1.0} for c in clips}, m['params'])

    X.OPS['test_clip'] = X.OpSpec('edit', ('target', 'params'), validate_move, derive=plan, code_version='test-1')
    before = E.raw_track(song, 'trk_bass')[0].tobytes()
    parsed = doc(tmp_path, [move('test_clip', amount=-1), move('test_edit', 'm02', amount=-1),
                            move('test_clip', 'm03', amount=-1)])
    assert D.apply(song, parsed['path'])['edits']['clip_edits'] == 2
    ledger = json.loads(E.ledger_path(song, parsed['id']).read_text(encoding='utf-8'))
    assert ledger['xop_order'] == ['m01', 'm02', 'm03']
    assert ledger['clip_edits']['m01']['kind'] == 'clip_edit'
    with pytest.raises(E.EditError, match='later moves'):
        E.revert(song, parsed['id'], 'm01')
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01', 'm02', 'm03']
    assert E.raw_track(song, 'trk_bass')[0].tobytes() == before


def test_clip_only_edit_does_not_write_audio(song, tmp_path, monkeypatch):
    install(monkeypatch)
    def plan(root, m):
        cid = Project.open(root).data['tracks'][0]['clips'][0]['id']
        return X.ClipPlan({cid: {'fade_in': 100, 'gain_db': -1}}, m['params'])
    X.OPS['test_clip'] = X.OpSpec('edit', ('target', 'params'), validate_move, derive=plan, code_version='test-1')
    before = C._snapshot(song / 'assets')
    parsed = doc(tmp_path, [move('test_clip', amount=-1)])
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    assert D.apply(song, parsed['path'])['applied']
    assert C._snapshot(song / 'assets') == before
    assert not (song / 'cache' / 'derived').exists()
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    assert E.revert(song, parsed['id'])['ledger_reverted']


def test_builtin_paths_identical_with_seam_disabled_and_extensions_installed(song, tmp_path, monkeypatch):
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
    install(monkeypatch)
    assert capture(twin) == before
    from mankomix.director import calibrate
    assert calibrate.knobs(doc(tmp_path, [move('test_edit', amount=[-1, 1])])) == []


def command(path=('suggest', 'test'), run=lambda args: {'z': 1, 'a': 2}, writes=False):
    def add_args(p):
        p.add_argument('--out')
    return {'path': path, 'help': 'test command', 'add_args': add_args, 'run': run, 'writes': writes}


def invoke(row, song, extra=()):
    C.COMMANDS[:] = [row]
    parser = cli.build_parser()
    args = parser.parse_args(['direction', *row['path'], '--project', str(song), *extra])
    return args.func(args)


def test_readonly_command_deterministic_json_and_cli_only(song, monkeypatch, capsys):
    row = command()
    C.COMMANDS[:] = [row]
    before = C._snapshot(song)
    argv = ['direction', 'suggest', 'test', '--project', str(song)]
    assert cli.main(argv) == 0
    first = capsys.readouterr().out
    assert cli.main(argv) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first) == {'a': 2, 'z': 1}
    assert C._snapshot(song) == before
    planned, reason = C.cli_only()['direction suggest test']
    assert planned == 'direction_suggest_test' and 'CLI only' in reason


@pytest.mark.parametrize('path', ['project.json', 'journal.jsonl', 'directions/new.json', 'cache/leak'])
@pytest.mark.parametrize('raises', [False, True])
def test_readonly_write_guard_even_on_exception(song, path, raises):
    def run(args):
        target = song / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('changed', encoding='utf-8')
        if raises:
            raise RuntimeError('test failure')
        return {}
    with pytest.raises(InputError, match='write contract'):
        invoke(command(run=run), song)


def test_out_only_explicit_destination_and_no_ledger_writes(song, tmp_path):
    def run(args):
        if not args.out:
            return {'written': False}
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'preview.txt').write_text('preview', encoding='utf-8')
        return {'written': True}
    row = command(('preview', 'test'), run, 'out_only')
    before = C._snapshot(song)
    assert invoke(row, song, ['--out', str(tmp_path / 'preview')]) == {'written': True}
    assert C._snapshot(song) == before
    assert invoke(row, song) == {'written': False}
    assert C._snapshot(song) == before
    for target in (song, song / 'directions', song / 'directions' / 'new.json', song / 'project.json'):
        with pytest.raises(InputError, match='overlaps'):
            invoke(row, song, ['--out', str(target)])
    assert invoke(row, song, ['--out', str(song / 'previews' / 'one')])['written']
    def bad(args):
        (song / 'journal.jsonl').write_text('oops', encoding='utf-8')
        return {}
    with pytest.raises(InputError, match='write contract'):
        invoke(command(('preview', 'test'), bad, 'out_only'), song, ['--out', str(tmp_path / 'another')])


def test_out_only_rejects_external_sibling_writes(song, tmp_path):
    def run(args):
        (tmp_path / 'leak.txt').write_text('leak', encoding='utf-8')
        return {}
    with pytest.raises(InputError, match='outside --out'):
        invoke(command(('extract', 'test'), run, 'out_only'), song, ['--out', str(tmp_path / 'only.txt')])


def test_query_extension_preserves_legacy_positionals(song, tmp_path):
    C.COMMANDS[:] = [command(('query', 'test'))]
    parser = cli.build_parser()
    args = parser.parse_args(['direction', 'query', 'test', '--project', str(song)])
    assert args.func(args) == {'a': 2, 'z': 1}
    legacy = parser.parse_args(['direction', 'query', 'audio.wav', '{"primitive":"crest"}'])
    assert legacy.func is cli.cmd_direction_query
    assert legacy.audio == 'audio.wav' and json.loads(legacy.spec)['primitive'] == 'crest'
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(['direction', 'query', '--help'])
    assert exc.value.code == 0


@pytest.mark.parametrize('path', [('validate',), ('ref', 'list'), ('edit', 'revert'), ('apply', 'test')])
def test_existing_command_cannot_be_overwritten(path):
    C.COMMANDS[:] = [command(path)]
    with pytest.raises(ImportError):
        cli.build_parser()


def test_command_discovery_and_declaration_validation(monkeypatch):
    monkeypatch.setattr(C, '_loaded', False)
    monkeypatch.setattr(C, 'iter_modules', lambda path: [SimpleNamespace(name='test')])
    monkeypatch.setattr(C, 'import_module', lambda name: SimpleNamespace(COMMANDS=[command()]))
    assert C.declarations()[0]['path'] == ('suggest', 'test')
    assert len(C.declarations()) == 1
    C.COMMANDS.append(command())
    with pytest.raises(ImportError, match='duplicate'):
        C.declarations()


def test_mcp_coverage_auto_adds_only_declared_cli_commands():
    import runpy
    rows = [command(('suggest', 'test')), command(('ref', 'test')), command(('preview', 'deep', 'test'))]
    C.COMMANDS[:] = rows
    tables = runpy.run_path(str(Path(__file__).with_name('test_mcp_e2e.py')))
    for row in rows:
        name = 'direction ' + ' '.join(row['path'])
        assert name in tables['CLI_TO_MCP'] and 'CLI only' in tables['KNOWN_CLI_ONLY'][name]
    assert 'direction preview deep' in tables['NESTED_GROUPS']
    assert tables['CLI_TO_MCP']['direction validate'] == 'direction_validate'
