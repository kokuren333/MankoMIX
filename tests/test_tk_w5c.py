"""T10-03 routing, offline errors, BB-18 recipes/revert and opt-in real inference."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from mankomix.core import config, registry
from mankomix.core.errors import EnvironmentProblem, InputError, ValidationError
from mankomix.core.hashing import sha256_file
from mankomix.core.project import Project
from mankomix.director import commands as C, derived, direction as D, edit, xops as X
from mankomix.director.xops import edit_isolate as I, _isolate as A
from tests import test_upgrade2_duck as T


def move(**params):
    return {'id': 'm01', 'op': 'edit_isolate', 'target': 'trk_bass', 'aim': 'a1',
            'origin': 'new', 'basis': 'synthetic routing test', 'params': params}


def document(tmp_path, m):
    return D.parse_document(T._doc(tmp_path / 'doc', T._block([m])))


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('MANKOMIX_SEPARATION_FAKE', '1')
    # The existing fake worker also supports installations without PyTorch.
    # Exercise that contract even on developer machines with heavy torch DLLs;
    # production worker startup and its download guard remain unchanged.
    no_runtime = tmp_path / 'no_model_runtime'
    no_runtime.mkdir()
    (no_runtime / 'torch.py').write_text("raise ImportError('no model runtime in this test')\n", encoding='utf-8')
    python_path = os.environ.get('PYTHONPATH')
    monkeypatch.setenv('PYTHONPATH', str(no_runtime) + (os.pathsep + python_path if python_path else ''))
    config.clear_cache()

    def no_download(*args, **kwargs):
        raise AssertionError('edit_isolate must never download')

    monkeypatch.setattr(registry, '_open_url', no_download)
    yield
    config.clear_cache()


@pytest.fixture
def fake(tmp_path, local):
    path = tmp_path / 'weights.bin'
    path.write_bytes(b'local test weights')
    registry.model_register(path, id='fake_isolate', license_weights='MIT', usage_restrictions='none',
                            evidence_url='https://example.invalid/license', architecture='fake',
                            stems=['vocals', 'other'], attribution='synthetic test model',
                            runtime={'backend': 'fake_filter', 'cpu_ok': True, 'sample_rate': 44100,
                                     'config': {'bands': {'vocals': [200, 4000], 'other': [0, 200]}}})
    return path


@pytest.fixture(scope='module')
def song_template(tmp_path_factory):
    folder = tmp_path_factory.mktemp('w5c_template')
    t = np.arange(T.SR) / T.SR
    x = .2*np.sin(2*np.pi*100*t) + .1*np.sin(2*np.pi*1000*t)
    stereo = np.stack([x, .75*x], axis=1)
    return T._make(folder / 'song', {'bass': stereo, 'vocals': stereo*.2})


@pytest.fixture
def song(tmp_path, local, song_template):
    return Path(shutil.copytree(song_template, tmp_path / 'song'))


INVALID_PARAMS = [
    {'keep': 'other'}, {'keep': []}, {'strength': -.01}, {'strength': 1.01},
    {'strength': True}, {'strength': float('nan')}, {'strength': [0, 1]},
    {'residual_db': -91}, {'residual_db': .1}, {'residual_db': float('inf')},
    {'model': 'absent'}, {'model': []}, {'fallback': 'passthrough'}, {'unknown': 0},
    {'section': {'t0_s': 0, 't1_s': 2}}, {'section': {'t0_s': .5, 't1_s': .2}},
    {'section': {'t0_s': 0, 't1_s': .1}}, {'section': 'missing'},
]


def test_validation_rejects_invalid_params(song, fake):
    for params in INVALID_PARAMS:
        errors = []
        ctx = SimpleNamespace(project=D._Project(song), err=lambda code, message: errors.append((code, message)))
        I.validate(move(model='fake_isolate') | {'params': {'model': 'fake_isolate', **params}}, ctx)
        assert errors, params


def test_defaults_ranges_targets_and_metadata_only_validation(song, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(registry, 'default_model', lambda mode: 'fake_isolate' if mode == 'full' else None)
    validation = D.validate(document(tmp_path, move()), song)
    assert validation['ok'], validation['errors']
    for strength in (0, 1):
        for residual in (-90, 0):
            errors = []
            ctx = SimpleNamespace(project=D._Project(song), err=lambda *args: errors.append(args))
            I.validate(move(strength=strength, residual_db=residual), ctx)
            assert not errors
    fake.unlink()  # Validation never executes or requires local weights.
    assert D.validate(document(tmp_path, move()), song)['ok']
    for target in ('bus_mix', 'trk_missing', None):
        m = move()
        m['target'] = target
        assert not D.validate(document(tmp_path, m), song)['ok']
    plan = I.derive(song, move(strength=0))
    assert isinstance(plan, X.ClipPlan)
    assert plan.params['keep'] == 'voice' and plan.params['residual_db'] == -90


def test_wrong_task_or_missing_vocals_is_rejected(song, fake, monkeypatch):
    for change in ({'task': 'denoise'}, {'stems': ['other']}, {'runtime': {}}):
        entry = registry.model_show('fake_isolate')['entry']
        entry.update(change)
        with monkeypatch.context() as patch:
            patch.setattr(registry, 'model_show', lambda mid: {'entry': entry})
            errors = []
            I.validate(move(model='fake_isolate'), SimpleNamespace(project=None, err=lambda *v: errors.append(v)))
            assert errors


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'candidate', 'worker'])
def test_errors_leave_project_and_ledgers_untouched(song, fake, tmp_path, monkeypatch, kind):
    m = move(model='fake_isolate')
    expected = EnvironmentProblem
    if kind == 'missing':
        fake.unlink()
    elif kind == 'corrupt':
        fake.write_bytes(b'changed weights')
        expected = ValidationError
    elif kind == 'candidate':
        m['params']['model'] = 'uvr_mdx_net_inst_hq_3'
        expected = InputError
    else:
        monkeypatch.delenv('MANKOMIX_SEPARATION_FAKE')
        expected = InputError
    doc = document(tmp_path, m)
    before = C._snapshot(song)
    with pytest.raises(expected):
        X.apply_edit(song, doc, m, I.OPS['edit_isolate'], actor='human')
    assert C._snapshot(song) == before
    assert not edit.ledger_path(song, doc['id']).exists()


def test_zero_strength_has_no_inference_or_derived_asset(song, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'separate_segment', lambda *a: pytest.fail('neutral must bypass inference'))
    fake.unlink()
    m = move(model='fake_isolate', strength=0)
    doc = document(tmp_path, m)
    before = edit.raw_track(song, 'trk_bass')[0].tobytes()
    assets = copy.deepcopy(Project.open(song).data['assets'])
    row = X.apply_edit(song, doc, m, I.OPS['edit_isolate'], actor='human')
    assert row['kind'] == 'clip_edit' and row['bypassed']
    assert not derived._ledger(song, doc['id'])['derived']
    assert Project.open(song).data['assets'] == assets
    assert edit.raw_track(song, 'trk_bass')[0].tobytes() == before
    edit.revert(song, doc['id'], actor='human')
    assert edit.raw_track(song, 'trk_bass')[0].tobytes() == before


def test_bb18_apply_accounting_regenerate_check_and_revert(song, fake, tmp_path):
    before, sr, data = edit.raw_track(song, 'trk_bass')
    peer = edit.raw_track(song, 'trk_vocals')[0].tobytes()
    original_hashes = {a['id']: sha256_file(song / a['path']) for a in data['assets']}
    floor = tmp_path / 'floor'
    shutil.copytree(song, floor)
    T._render(floor)
    m = move(model='fake_isolate')
    m['section'] = {'t0_s': .2, 't1_s': .8}
    doc = document(tmp_path, m)
    assert D.validate(doc, song)['ok']
    result = D.apply(song, doc['path'])
    assert result['applied'] and result['edits']['derived'] == 1
    row = derived._ledger(song, doc['id'])['derived']['m01']
    detail = row['details']
    assert detail['provider'] == 'cpu'
    assert detail['model_sha256'] == sha256_file(fake)
    assert detail['kept_energy'] > 0 and detail['discarded_energy'] > detail['kept_energy']
    # This is a non-residual model. Its measured rate-conversion error must be
    # recorded, not misreported as exact complementary reconstruction.
    assert detail['reconstruction_error_rel_db'] < -50
    print('isolate_accounting', json.dumps(detail, sort_keys=True))
    assert detail['license']['weights'] == 'MIT' and not detail['fallback_used']
    assert row['params']['model_recipe']['threads'] == {'intra_op': 1, 'inter_op': 1}
    assert row['params']['model_recipe']['runtime']['config']['bands']
    assert row['code_version'] == I.VERSION and row['fit'] == 'keep_length'
    assert row['result']['fitted_frames'] == round(.6*sr)
    assert str(tmp_path) not in json.dumps(row)
    after = edit.raw_track(song, 'trk_bass')[0]
    assert after[:round(.2*sr)].tobytes() == before[:round(.2*sr)].tobytes()
    assert after[round(.8*sr):].tobytes() == before[round(.8*sr):].tobytes()
    assert np.max(abs(after-before)) > .1
    assert edit.raw_track(song, 'trk_vocals')[0].tobytes() == peer
    assert Project.open(song).data['timebase'] == data['timebase']
    for asset in data['assets']:
        assert sha256_file(song / asset['path']) == original_hashes[asset['id']]
    T._render(song)
    assert D.check(song, floor, doc['path'])['move_ref']['ok']
    # Force a genuine recalculation from recorded source and model dependencies.
    asset = next(a for a in Project.open(song).data['assets'] if a['sha256'] == row['result']['sha256'])
    (song / asset['path']).unlink()
    cache = (song / 'cache' / 'derived').resolve()
    assert cache.is_relative_to(tmp_path.resolve())
    shutil.rmtree(cache)
    derived.regenerate(song, doc['id'], 'm01', calculate=I.calculate)
    assert sha256_file(song / asset['path']) == row['result']['sha256']
    assert edit.revert(song, doc['id'])['reverted_moves'] == ['m01']
    assert edit.raw_track(song, 'trk_bass')[0].tobytes() == before.tobytes()
    assert edit.revert(song, doc['id'])['reverted_moves'] == []


@pytest.mark.parametrize('sr,channels', [(44100, 1), (48000, 2), (96000, 1)])
def test_worker_shape_repeat_complement_and_strength(fake, sr, channels, monkeypatch):
    # Unit coverage of all rate/shape/mix cases uses the existing test backend
    # in process. The BB-18 and failure tests above cover the actual subprocess.
    from mankomix.core.separation import worker
    monkeypatch.setattr(A, 'run_worker', lambda req, work: worker.run(req))
    t = np.arange(sr//2) / sr
    x = np.tile((.2*np.sin(2*np.pi*100*t) + .1*np.sin(2*np.pi*1000*t))[:, None], (1, channels))
    resolved = registry.resolve_for_run('fake_isolate')
    p = {'model': 'fake_isolate', 'keep': 'voice', 'strength': 1., 'residual_db': -90.}
    voice, rec = I.process(x, sr, p, resolved)
    repeated, again = I.process(x, sr, p, resolved)
    assert voice.tobytes() == repeated.tobytes() and rec == again
    background, _ = I.process(x, sr, dict(p, keep='background'), resolved)
    assert voice.shape == x.shape and voice.dtype == np.float64 and np.isfinite(voice).all()
    gain = 10**(-90/20)
    assert np.sqrt(np.mean(((voice+background)/(1+gain)-x)**2)) < 2e-4
    # Exercise formula endpoints with the actual worker estimates cached in memory.
    stems, run = A.separate_segment(x, sr, resolved)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(A, 'separate_segment', lambda *args: (copy.deepcopy(stems), run))
        half, _ = I.process(x, sr, dict(p, strength=.5), resolved)
        both, _ = I.process(x, sr, dict(p, residual_db=0), resolved)
        residual = copy.deepcopy(resolved)
        residual['entry']['runtime']['config']['residual'] = 'other'
        corrected, corrected_record = I.process(x, sr, p, residual)
        corrected_background, _ = I.process(x, sr, dict(p, keep='background'), residual)
    np.testing.assert_allclose(half, .5*x+.5*voice, atol=1e-15)
    np.testing.assert_allclose(both, stems['vocals']+stems['other'], atol=1e-15)
    np.testing.assert_allclose((corrected+corrected_background)/(1+gain), x, atol=1e-15)
    assert corrected_record['background_mode'] == 'input_minus_vocals'


def test_recipe_and_source_changes_are_refused(song, fake):
    before = C._snapshot(song)
    plan = I.derive(song, move(model='fake_isolate'))
    assert C._snapshot(song) == before
    x, sr, _ = edit.raw_track(song, 'trk_bass')
    bad = copy.deepcopy(plan.params)
    bad['model_recipe']['runtime']['sample_rate'] = 48000
    with pytest.raises(InputError, match='settings changed'):
        I.calculate(x, sr, bad)
    with pytest.raises(InputError, match='source segment changed'):
        I.calculate(x*.5, sr, plan.params)
    with pytest.raises(InputError, match='planned input'):
        plan.calculate(x, sr, bad)


@pytest.mark.parametrize('kind', ['silence', 'short', 'below_loudness_gate'])
def test_worker_accepts_silent_short_and_very_quiet_inputs(fake, monkeypatch, kind):
    from mankomix.core.separation import worker
    monkeypatch.setattr(A, 'run_worker', lambda req, work: worker.run(req))
    n = 4410 if kind == 'short' else 22050
    x = (.1*np.sin(2*np.pi*1000*np.arange(n)/44100))[:, None]
    if kind == 'silence':
        x[:] = 0
    elif kind == 'below_loudness_gate':
        x *= 1e-5
    p = {'model': 'fake_isolate', 'keep': 'voice', 'strength': 1., 'residual_db': -90.}
    y, record = I.process(x, 44100, p)
    assert y.shape == x.shape and np.isfinite(y).all()
    assert record['provider'] == 'cpu' and not record['fallback_used']
    if kind == 'silence':
        assert not np.any(y)
    else:
        assert record['preprocess']['normalization'] == 'peak_only'


def test_unused_op_keeps_validation_proposal_and_record_bytes(song, tmp_path, monkeypatch):
    m = move()
    m.update(op='gain', params={'delta_db': -1})
    doc = document(tmp_path, m)
    first = D.validate(doc, song), D.build_proposal(D._Project(song), doc)
    with monkeypatch.context() as patch:
        patch.setattr(X, 'OPS', {key: value for key, value in X.OPS.items() if key != 'edit_isolate'})
        second = D.validate(doc, song), D.build_proposal(D._Project(song), doc)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_worker_startup_is_cpu_deterministic_and_parent_never_loads_torch(tmp_path, monkeypatch):
    def launch(cmd, **kwargs):
        assert cmd[1:3] == ['-c', A.CPU_STARTUP]
        assert 'torch.set_num_interop_threads(1)' in cmd[2]
        assert kwargs['env']['OMP_NUM_THREADS'] == '1'
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        assert kwargs['env']['PYTHONHASHSEED'] == '0'
        (tmp_path / 'result.json').write_text(json.dumps({'ok': True, 'protocol': 1, 'device': 'cpu'}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(A.subprocess, 'run', launch)
    assert A.run_worker({'backend': 'mankomix_torch', 'output_dir': str(tmp_path)}, tmp_path)['ok']
    # Use an independent process so other tests cannot mask an import leak.
    real_run = subprocess.Popen
    proc = real_run([sys.executable, '-c',
                    "import sys; import mankomix.director.xops.edit_isolate; assert 'torch' not in sys.modules"],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    assert proc.returncode == 0, stderr.decode()


def test_worker_result_errors_and_timeout_are_explicit(tmp_path, monkeypatch):
    cases = [(None, 1, EnvironmentProblem),
             ({'ok': False, 'kind': 'input', 'error': 'rejected'}, 2, InputError),
             ({'ok': False, 'kind': 'environment', 'error': 'unavailable'}, 3, EnvironmentProblem),
             ({'ok': True, 'protocol': 2, 'device': 'cpu'}, 0, EnvironmentProblem),
             ({'ok': True, 'protocol': 1, 'device': 'cuda'}, 0, EnvironmentProblem)]
    for index, (result, code, error) in enumerate(cases):
        work = tmp_path / str(index)
        work.mkdir()
        def launch(cmd, **kwargs):
            if result is not None:
                (work / 'result.json').write_text(json.dumps(result), encoding='utf-8')
            return SimpleNamespace(returncode=code)
        monkeypatch.setattr(A.subprocess, 'run', launch)
        with pytest.raises(error):
            A.run_worker({'backend': 'fake_filter', 'output_dir': str(work)}, work)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker', 1)
    monkeypatch.setattr(A.subprocess, 'run', timeout)
    with pytest.raises(EnvironmentProblem, match='could not finish'):
        A.run_worker({'backend': 'fake_filter', 'output_dir': str(tmp_path)}, tmp_path)


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get('MANKOMIX_RUN_SEPARATION') != '1',
                    reason='set MANKOMIX_RUN_SEPARATION=1 with local verified weights to run')
def test_real_model_repeat_and_known_input_hash(tmp_path, monkeypatch):
    config.clear_cache()
    model = os.environ.get('MANKOMIX_SEPARATION_MODEL', 'scnet_4stem')
    t = np.arange(44100*2) / 44100
    x = np.stack([.2*np.sin(2*np.pi*220*t)+.1*np.sin(2*np.pi*880*t)]*2, axis=1)
    p = {'model': model, 'keep': 'voice', 'strength': 1., 'residual_db': -90.}
    first, rec = I.process(x, 44100, p)
    second, _ = I.process(x, 44100, p)
    assert first.tobytes() == second.tobytes()
    output_hash = hashlib.sha256(first.astype('<f8').tobytes()).hexdigest()
    print(json.dumps({'model': model, 'input_sha256': I._hash(x), 'output_sha256': output_hash,
                      'reconstruction_error_rel_db': rec['reconstruction_error_rel_db']}, sort_keys=True))
    expected = os.environ.get('MANKOMIX_ISOLATE_EXPECTED_SHA256')
    if expected:
        assert output_hash == expected
    if (registry.model_show(model)['entry']['runtime'].get('config') or {}).get('residual'):
        assert rec['reconstruction_error_rel_db'] is None or rec['reconstruction_error_rel_db'] <= -60
