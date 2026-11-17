"""W4_2 optional project commands and atomic clip-only groups."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil

import numpy as np
import pytest

from mankomix.cli import main as cli
from mankomix.core import api, audio_io, mixrender as mr
from mankomix.core.errors import InputError, MankoError
from mankomix.core.project import Project
from mankomix.director import commands as C, derived as B, direction as D, edit as E, xops as X
from mankomix.director.xops import _group
from tests.test_tk_w4_0 import isolated, song, doc, move
from tests.test_tk_w4_1 import install
from tests import test_upgrade2_duck as T


def file_command(mode='optional', run=None, writes='out_only'):
    def add_args(p):
        p.add_argument('--audio', required=True)
        p.add_argument('--out')
    def default(a):
        if a.out:
            p = Path(a.out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(Path(a.audio).read_bytes())
        return {'bytes': len(Path(a.audio).read_bytes())}
    return {'path': ('preview', 'probe_file'), 'help': 'file probe', 'add_args': add_args,
            'run': run or default, 'writes': writes, 'project': mode}


def invoke(row, args):
    C.COMMANDS.append(row)
    try:
        ns = cli.build_parser().parse_args(['direction', *row['path'], *map(str, args)])
        for key, value in cli.GLOBAL_DEFAULTS.items():
            if not hasattr(ns, key):
                setattr(ns, key, value)
        return ns.func(ns)
    finally:
        C.COMMANDS.remove(row)


@pytest.mark.parametrize('mode', ['optional', 'none'])
@pytest.mark.parametrize('out', [False, True])
def test_file_command_without_project(tmp_path, monkeypatch, mode, out):
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'input')
    dest = tmp_path / 'new' / 'nested' / 'output.dat'
    before = C._snapshot(tmp_path)
    assert invoke(file_command(mode), ['--audio', src, *(['--out', dest] if out else [])]) == {'bytes': 5}
    if out:
        assert dest.read_bytes() == b'input'
        assert src.read_bytes() == b'input'
        assert C._snapshot(cwd) == {'.': ('dir',)}
    else:
        assert C._snapshot(tmp_path) == before


def test_default_still_requires_project_and_none_skips_resolver(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row = file_command()
    row.pop('project')
    with pytest.raises(InputError, match='no project'):
        invoke(row, ['--audio', 'input.dat'])
    monkeypatch.setattr(cli, '_project', lambda a: pytest.fail('project resolver must not run'))
    src = tmp_path / 'input.dat'
    src.write_bytes(b'x')
    assert invoke(file_command('none'), ['--audio', src, '--project', 'unused']) == {'bytes': 1}


@pytest.mark.parametrize('mode', ['optional', 'bad'])
def test_project_declaration_validation(mode):
    row = file_command(mode)
    if mode == 'bad':
        with pytest.raises(ImportError, match='project must'):
            C._validate([row])
    else:
        assert C._validate([row]) == [row]


@pytest.mark.parametrize('bad_path', ['input', 'cwd', 'sibling'])
@pytest.mark.parametrize('raises', [False, True])
def test_projectless_write_guard_on_success_and_failure(tmp_path, monkeypatch, bad_path, raises):
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'input')
    dest = tmp_path / 'new' / 'nested' / 'out.dat'
    paths = {'input': src, 'cwd': cwd / 'leak', 'sibling': tmp_path / 'new' / 'leak'}
    def run(a):
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'allowed')
        paths[bad_path].write_bytes(b'bad')
        if raises:
            raise RuntimeError('callback failed')
        return {}
    with pytest.raises(InputError, match='write contract'):
        invoke(file_command(run=run), ['--audio', src, '--out', dest])


def test_no_out_guard_and_input_overlap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'input')
    def run(a):
        (tmp_path / 'leak').write_text('bad')
        return {}
    with pytest.raises(InputError, match='write contract'):
        invoke(file_command(run=run), ['--audio', src])
    for output in (src, tmp_path):
        with pytest.raises(InputError, match='overlaps'):
            invoke(file_command(), ['--audio', src, '--out', output])
    assert src.read_bytes() == b'input'


def test_optional_project_retains_project_guard(song, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'x')
    def run(a):
        (song / 'journal.jsonl').write_text('bad')
        return {}
    with pytest.raises(InputError, match='write contract'):
        invoke(file_command(run=run), ['--audio', src, '--project', song])
    with pytest.raises(InputError, match='overlaps input'):
        invoke(file_command(), ['--audio', src, '--project', song, '--out', src])


def test_optional_cwd_project_and_external_input_guard(song, tmp_path, monkeypatch):
    monkeypatch.chdir(song)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'x')
    assert invoke(file_command(), ['--audio', src]) == {'bytes': 1}
    def run(a):
        src.write_bytes(b'changed')
        raise RuntimeError('callback failed')
    with pytest.raises(InputError, match='input file write contract'):
        invoke(file_command(run=run), ['--audio', src])


def test_custom_input_argument_and_cli_entry_point(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / 'input.dat'
    src.write_bytes(b'input')
    row = file_command()
    row['inputs'] = ('files',)
    def add_args(p):
        p.add_argument('--files', nargs='+')
        p.add_argument('--out')
    row['add_args'] = add_args
    row['run'] = lambda a: {'count': len(a.files)}
    C.COMMANDS.append(row)
    assert cli.main(['direction', 'preview', 'probe_file', '--files', str(src)]) == 0
    assert '"count": 1' in capsys.readouterr().out
    def bad(a):
        src.write_bytes(b'bad')
        return {}
    row['run'] = bad
    assert cli.main(['direction', 'preview', 'probe_file', '--files', str(src)]) == 2
    assert 'write contract' in capsys.readouterr().out


def test_real_preview_codec_audio_only(tmp_path, monkeypatch):
    from mankomix.director.commands import preview_codec as P
    monkeypatch.chdir(tmp_path)
    src = tmp_path / 'input.wav'
    sr = 48000
    x = .05*np.sin(2*np.pi*220*np.arange(sr//2)/sr)
    audio_io.write(src, np.column_stack((x, x)), sr, subtype='DOUBLE')
    before = C._snapshot(tmp_path)
    monkeypatch.setattr(P, 'roundtrip', lambda *a: None)
    result = invoke(P.COMMANDS[0], ['--audio', src])
    assert result['kind'] == 'direction_preview_codec'
    assert len(result['rows']) == 4 and not result['available']
    assert C._snapshot(tmp_path) == before
    monkeypatch.setattr(P, 'roundtrip', lambda x, sr, *a: (x.copy(), sr, {'encoder': 'probe'}))
    dest = tmp_path / 'listen'
    result = invoke(P.COMMANDS[0], ['--audio', src, '--codec', 'aac', '--out', dest])
    assert result['available'] and len(result['files']) == 4
    assert src.read_bytes() and all((dest / name).is_file() for name in result['files'])
    assert C._snapshot(tmp_path)['input.wav'] == before['input.wav']


def clip_bundle(root, m):
    tracks = {t['id']: t for t in Project.open(root).data['tracks']}
    plans = {tid: X.ClipPlan({c['id']: {'fade_in': 100, 'fade_out': 80, 'gain_db': -2}
                             for c in tracks[tid]['clips']}, {'amount': 2})
             for tid in [m['target'], *m['params']['group']]}
    return X.ClipBundle(plans, {'identity': True}, {'confidence': 'high'})


def setup_group(song, tmp_path, monkeypatch, planner=clip_bundle):
    install(monkeypatch, 'probe_clip_group', derive=planner)
    return doc(tmp_path, [move('probe_clip_group', group=['trk_vocals'])])


@pytest.mark.parametrize('noop', [False, True])
def test_clip_bundle_no_assets_check_and_bit_exact_revert(song, tmp_path, monkeypatch, noop):
    def plan(root, m):
        bundle = clip_bundle(root, m)
        if noop:
            for p in bundle.plans.values():
                p.changes = {}
        return bundle
    parsed = setup_group(song, tmp_path, monkeypatch, plan)
    original = copy.deepcopy(Project.open(song).data)
    audio = mr.render_mix(Project.open(song))[0].tobytes()
    assets = C._snapshot(song / 'assets')
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    result = D.apply(song, parsed['path'])['record']['moves']['m01']
    ledger = B._ledger(song, parsed['id'])
    assert ledger['xop_order'] == ['m01'] and not ledger.get('derived')
    assert ledger['derived_groups']['m01']['plan_kind'] == 'clip'
    assert len(ledger['clip_edits']) == 2 and _group.check(song, parsed['id'], 'm01', result)
    assert all(c['params']['group_mapping'] == {'identity': True} for c in ledger['clip_edits'].values())
    assert C._snapshot(song / 'assets') == assets
    assert not (song / 'cache' / 'derived').exists()
    assert B.regenerate_group(song, parsed['id'], 'm01') == {}
    if noop:
        assert Project.open(song).data == original
        assert mr.render_mix(Project.open(song))[0].tobytes() == audio
    T._render(song)
    assert D.check(song, floor, parsed['path'])['move_ref']['ok']
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01']
    assert Project.open(song).data['tracks'] == original['tracks']
    assert mr.render_mix(Project.open(song))[0].tobytes() == audio
    ledger = B._ledger(song, parsed['id'])
    assert ledger['derived_groups']['m01']['status'] == 'reverted'
    assert all(c['status'] == 'reverted' for c in ledger['clip_edits'].values())


@pytest.mark.parametrize('bad', ['missing', 'field', 'range', 'mapping', 'kind'])
def test_invalid_later_clip_member_is_atomic(song, tmp_path, monkeypatch, bad):
    def plan(root, m):
        bundle = clip_bundle(root, m)
        peer = bundle.plans['trk_vocals']
        cid = next(iter(peer.changes))
        if bad == 'missing':
            bundle.plans.pop('trk_vocals')
        elif bad == 'field':
            peer.changes[cid] = {'timeline_start': 2}
        elif bad == 'range':
            peer.changes[cid] = {'fade_in': -1}
        elif bad == 'mapping':
            peer.params['group_mapping'] = {'different': True}
        else:
            bundle.plans['trk_vocals'] = X.DerivedPlan(0, 100, {}, lambda x, s, p: x)
        return bundle
    parsed = setup_group(song, tmp_path, monkeypatch, plan)
    before = Project.open(song).data
    assets = C._snapshot(song / 'assets')
    with pytest.raises((ValueError, MankoError)):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before and C._snapshot(song / 'assets') == assets
    assert not E.ledger_path(song, parsed['id']).exists()


@pytest.mark.parametrize('fail_at', [1, 2])
def test_clip_bundle_ledger_failure_compensates_patch(song, tmp_path, monkeypatch, fail_at):
    parsed = setup_group(song, tmp_path, monkeypatch)
    before = Project.open(song).data
    save, calls = B._save, []
    def fail(*args):
        calls.append(True)
        if len(calls) == fail_at:
            raise OSError('ledger failed')
        return save(*args)
    monkeypatch.setattr(B, '_save', fail)
    with pytest.raises(OSError, match='ledger failed'):
        D.apply(song, parsed['path'])
    assert Project.open(song).data == before
    assert not E.ledger_path(song, parsed['id']).exists()


def test_clip_bundle_revert_ledger_failure_is_atomic(song, tmp_path, monkeypatch):
    parsed = setup_group(song, tmp_path, monkeypatch)
    D.apply(song, parsed['path'])
    before = Project.open(song).data
    ledger = E.ledger_path(song, parsed['id']).read_bytes()
    monkeypatch.setattr(B, '_save', lambda *a: (_ for _ in ()).throw(OSError('ledger failed')))
    with pytest.raises(OSError, match='ledger failed'):
        E.revert(song, parsed['id'])
    assert Project.open(song).data == before
    assert E.ledger_path(song, parsed['id']).read_bytes() == ledger


def test_clip_bundle_foreign_peer_preflight(song, tmp_path, monkeypatch):
    install(monkeypatch, 'probe_single', derive=lambda r, m: X.ClipPlan({}, {}))
    foreign = doc(tmp_path, [move('probe_single', target='trk_vocals')])
    X.apply_edit(song, foreign, foreign['block']['moves'][0], X.OPS['probe_single'], actor='human')
    calls = []
    def plan(root, m):
        calls.append(True)
        return clip_bundle(root, m)
    parsed = setup_group(song, tmp_path, monkeypatch, plan)
    parsed = copy.deepcopy(parsed)
    parsed['id'] = 'other'
    before = Project.open(song).data
    with pytest.raises(ValueError, match='another direction'):
        X.apply_edit(song, parsed, parsed['block']['moves'][0], X.OPS['probe_clip_group'], actor='human')
    assert not calls and Project.open(song).data == before


def test_clip_bundle_stale_peer_check_and_atomic_revert(song, tmp_path, monkeypatch):
    parsed = setup_group(song, tmp_path, monkeypatch)
    result = D.apply(song, parsed['path'])['record']['moves']['m01']
    p = Project.open(song)
    tracks = copy.deepcopy(p.data['tracks'])
    tracks[1]['clips'][0]['gain_db'] = -3
    p.set('/tracks', tracks, actor='human')
    before = Project.open(song).data
    assert not _group.check(song, parsed['id'], 'm01', result)
    with pytest.raises(E.EditError, match='layout changed'):
        E.revert(song, parsed['id'])
    assert Project.open(song).data == before
    assert B._ledger(song, parsed['id'])['derived_groups']['m01']['status'] == 'applied'


@pytest.mark.parametrize('tamper', ['source', 'params', 'version', 'mapping', 'link'])
def test_clip_bundle_check_detects_tampering(song, tmp_path, monkeypatch, tamper):
    parsed = setup_group(song, tmp_path, monkeypatch)
    result = D.apply(song, parsed['path'])['record']['moves']['m01']
    ledger = B._ledger(song, parsed['id'])
    child = ledger['clip_edits'][result['members']['trk_vocals']['move']]
    if tamper == 'source':
        Project.open(song).asset_path(child['source']['assets'][0]['id']).write_bytes(b'corrupt')
    elif tamper == 'params':
        child['params']['amount'] = 7
    elif tamper == 'version':
        child['code_version'] = 'different'
    elif tamper == 'mapping':
        ledger['derived_groups']['m01']['mapping'] = {'different': True}
    else:
        child['group'] = 'different'
    B._save(E.ledger_path(song, parsed['id']), ledger)
    assert not _group.check(song, parsed['id'], 'm01', result)


def test_clip_bundle_mixed_revert_order(song, tmp_path, monkeypatch):
    parsed = setup_group(song, tmp_path, monkeypatch)
    install(monkeypatch, 'probe_single', derive=lambda r, m: X.DerivedPlan(100, 1000, {}, lambda x, s, p: -x))
    parsed = doc(tmp_path, [move('probe_clip_group', group=['trk_vocals']),
                            move('probe_single', 'm02', 'trk_vocals')])
    before = mr.render_mix(Project.open(song))[0].tobytes()
    result = D.apply(song, parsed['path'])['record']['moves']['m01']
    assert _group.check(song, parsed['id'], 'm01', result)
    with pytest.raises(E.EditError, match='later moves'):
        E.revert(song, parsed['id'], 'm01')
    assert E.revert(song, parsed['id'])['reverted_moves'] == ['m01', 'm02']
    assert mr.render_mix(Project.open(song))[0].tobytes() == before


def test_help_names_include_underscores_without_partial_matches():
    from tests.test_mcp_e2e import _subcommands
    text = 'positional arguments:\n  SUBCOMMAND\n    limiter_headroom  measure\n    a-b_2  valid\n    bad!name invalid\noptions:\n'
    assert _subcommands(text, 'SUBCOMMAND') == ['limiter_headroom', 'a-b_2']
