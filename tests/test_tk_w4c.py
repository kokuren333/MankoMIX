"""W4c alignment, onset gate, SMF and reinforcement acceptance tests."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import struct

import numpy as np
import pytest
from scipy import signal

from mankomix.cli.main import main
from mankomix.core.errors import InputError
from mankomix.core.project import Project
from mankomix.core import mixrender as mr
from mankomix.director import commands as C, direction as D, edit as E, derived as B
from mankomix.director.commands import suggest_align as A, extract_midi as M
from mankomix.director.xops import drum_replace as R
from mankomix.dsp import processors as P
from mankomix.dsp.errors import ParamError
from mankomix.dspx.bb.samples import SAMPLES, synthetic_sample, synthetic_bytes
from mankomix.dspx.bb.drum_events import drum_events, DETECT
from mankomix.dspx.bb.delayline import fractional_delay
from tests import toolimpl_harness as H, test_upgrade2_duck as T
from tests.test_tk_w4_0 import doc, move

SR = T.SR


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))


def args(module, root, *flags):
    parser = argparse.ArgumentParser()
    module.add_args(parser)
    ns = parser.parse_args(list(flags))
    ns.project = str(root)
    return ns


def train(count=20, *, sr=SR, kind='kick', interval=.3, levels=None):
    positions = np.rint((.15+np.arange(count)*interval)*sr).astype(int)
    x = np.zeros((positions[-1]+round(.5*sr), 1))
    for i, pos in enumerate(positions):
        if kind == 'kick':
            t = np.arange(round(.18*sr))/sr
            wave = (.5*np.sin(2*np.pi*60*t)*np.exp(-t/.045))[:, None]
            wave[:max(1, round(.0003*sr)), 0] += .1
        else:
            wave = H.drum(kind, dbfs=-6, sr=sr, seconds=.18, seed=70+i)
        x[pos:pos+len(wave)] += wave*(levels[i % len(levels)] if levels else 1)
    return x, positions


def render(x, params=None, sr=SR):
    return H.render('drum_gate', x, sr, params, stage='track')


def test_registration():
    assert 'drum_replace' in D.X.specs(D.OPS)
    rows = {r['path']: r for r in C.declarations()}
    assert rows[('suggest', 'align')]['writes'] is False
    assert rows[('extract', 'midi')]['writes'] == 'out_only'
    for cmd in ('direction suggest align', 'direction extract midi'):
        assert cmd in C.cli_only()
    p = P.describe('drum_gate')
    assert p['implemented'] is True
    assert p['stages'] == ['track'] and p['offline_only'] and not p['realtime']['block_ok']
    assert 'drum_gate' in D.TIME_VARYING


def aligned_material(tmp_path, unrelated=False):
    rng = np.random.Generator(np.random.PCG64(71))
    x = signal.sosfilt(signal.butter(3, [60, 7000], btype='bandpass', fs=SR, output='sos'), rng.normal(size=2*SR))*.04
    waves = []
    for i, delay in enumerate((0, 1.37, 4.02)):
        y = fractional_delay(x[:, None], delay*SR/1000, 'sinc256')[:, 0]
        if i == 1:
            y = -signal.lfilter([1, .1], [1], y)
        y += rng.normal(size=len(x))*np.std(y)*.1
        waves.append(y[:, None])
    if unrelated:
        waves[1] = rng.normal(size=(len(x), 1))*.03
    root = T._make(tmp_path/'song', dict(zip(('a', 'b', 'c'), waves)))
    return root, x


def test_alignment_accuracy_readonly_candidates_and_sum(tmp_path, capsys):
    root, x = aligned_material(tmp_path)
    flags = ['--tracks', 'trk_a,trk_b,trk_c']
    ns = args(A, root, *flags)
    before = C._snapshot(root)
    first = C.execute(A.COMMANDS[0], ns, root)
    assert first == C.execute(A.COMMANDS[0], ns, root)
    assert first['confidence'] == 'high' and first['reference'] == 'trk_c'
    expected = [4.02, 2.65, 0]
    for row, delay in zip(first['tracks'], expected):
        assert row['delay_ms'] == pytest.approx(delay, abs=.02)
    assert [r['polarity_invert'] for r in first['tracks']] == [False, True, False]
    parsed = doc(tmp_path, first['candidates'])
    assert D.validate(parsed, root)['ok']
    assert main(['direction', 'suggest', 'align', *flags, '--project', str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert C._snapshot(root) == before
    summed = np.zeros((len(x), 1))
    for r in first['candidates']:
        wave = E.raw_track(root, r['target'])[0][:, :1]
        summed += H.render('time_align', wave, SR, r['params'], stage='track').audio
    ideal = fractional_delay(x[:, None], 4.02*SR/1000, 'sinc256')*3
    assert abs(H.band_level(summed, SR, 100, 4000)['dbfs']-H.band_level(ideal, SR, 100, 4000)['dbfs']) <= .5
    print('alignment_delay_ms', [r['delay_ms'] for r in first['tracks']])


def test_unrelated_and_phase_evidence(tmp_path):
    root, _ = aligned_material(tmp_path, unrelated=True)
    out = A.run(args(A, root, '--tracks', 'trk_a,trk_b', '--mode', 'phase'))
    assert out['confidence'] == 'low' and len(out['candidates']) == 2
    assert out['phase_fit'] and A.CAUTION in out['notes']
    assert out['pairs'][0]['segments'][0]['peak_sharpness'] >= 0


def test_drums_align_per_hit(tmp_path):
    x, positions = train(6, interval=.45)
    oh = fractional_delay(x, .004*SR, 'sinc256')
    root = T._make(tmp_path/'song', {'drums': x, 'vocals': oh})
    out = A.run(args(A, root, '--tracks', 'kick:trk_drums,oh:trk_vocals', '--preset', 'drums'))
    assert out['tracks'][0]['delay_ms'] == pytest.approx(4, abs=.05)
    assert out['tracks'][1]['delay_ms'] == pytest.approx(0, abs=.02)
    assert len(out['pairs'][0]['segments']) == 6


@pytest.mark.parametrize('flags', [ ['--max-ms', '101'], ['--max-ms', 'nan'],
    ['--reference', 'trk_x'], ['--reference', 'trk_a'], ['--band-hz', '8000', '40']])
def test_alignment_invalid_readonly(tmp_path, flags):
    root, _ = aligned_material(tmp_path)
    before = C._snapshot(root)
    with pytest.raises(InputError):
        C.execute(A.COMMANDS[0], args(A, root, '--tracks', 'trk_a,trk_b,trk_c', *flags), root)
    assert C._snapshot(root) == before


def test_gate_kicks_bleed_open_bits_and_closed_range():
    x, positions = train(20, interval=.65)
    t = np.arange(round(.12*SR))/SR
    rng = np.random.Generator(np.random.PCG64(9))
    bleed = (.07*np.sin(2*np.pi*200*t)+.12*rng.normal(size=len(t)))*np.exp(-t/.025)
    for pos in positions+round(.32*SR):
        x[pos:pos+len(bleed), 0] += bleed
    p = {'reject_lo_hz': 250, 'reject_hi_hz': 9000, 'reject_ratio_db': 0,
         'velocity_sense': 0, 'hold_ms': 60, 'release_ms': 10, 'decay_follow': 0}
    y = render(x, p).audio
    rows, _ = drum_events(x, SR, P.validate_params('drum_gate', p))
    accepted = [r for r in rows if r['opened']]
    assert len(accepted) == 20
    assert len(rows) >= 40 and all(not r['opened'] for r in rows if min(abs(r['sample']-positions)) > .1*SR)
    for pos in positions:
        assert y[pos:pos+round(.005*SR)].tobytes() == x[pos:pos+round(.005*SR)].tobytes()
    # A low-level test bed gives a finite closed-region gain measurement.
    bed = H.sine(1000, -70, sr=SR, seconds=.4)
    closed = render(bed, p).audio
    assert H.rms_dbfs(closed)-H.rms_dbfs(bed) == pytest.approx(-40, abs=.5)
    print('gate_opened_rejected', len(accepted), len(rows)-len(accepted))


def test_decay_follow_monotonic_and_stats():
    from mankomix.dspx.procs.drum_gate import drum_gate
    closes = []
    for decay in (.025, .12):
        x = np.zeros((SR, 1))
        t = np.arange(round(.7*SR))/SR
        x[round(.1*SR):round(.8*SR), 0] = .6*np.sin(2*np.pi*60*t)*np.exp(-t/decay)
        p = P.validate_params('drum_gate', {'decay_follow': 1, 'velocity_sense': 0})
        y, _, stats = drum_gate(x, SR, p)
        hit = next(r for r in stats['hits'] if r['opened'])
        closes.append(hit['close_start_sample'])
        pos = hit['sample']
        assert np.array_equal(x[pos:pos+120], y[pos:pos+120])
    assert closes[1] > closes[0]
    print('gate_close_start_samples', closes)


def test_gate_common_and_literal_defaults():
    expected = [
        ('threshold_db', -80, 0, -30), ('detect_lo_hz', 20, 20000, 40),
        ('detect_hi_hz', 20, 20000, 200), ('reject_lo_hz', 0, 20000, 0),
        ('reject_hi_hz', 0, 20000, 0), ('reject_ratio_db', -12, 24, 6),
        ('range_db', -90, 0, -40), ('lookahead_ms', 0, 20, 5),
        ('attack_ms', .05, 20, .5), ('hold_ms', 0, 2000, 60),
        ('release_ms', 10, 3000, 200), ('decay_follow', 0, 1, .6),
        ('velocity_sense', 0, 1, .3), ('min_interval_ms', 5, 500, 30),
        ('resonance_cut', 0, 1, 0)]
    assert [(v['id'], v['min'], v['max'], v['default'])
            for v in P.describe('drum_gate')['params']] == expected
    def probe(x, y, sr, p):
        measured = H.rms_dbfs(y)-H.rms_dbfs(x)
        return {'passed': abs(measured-p['range_db']) < .01, 'closed_gain_db': measured}
    H.assert_common_tests('drum_gate', neutral={'range_db': 0, 'velocity_sense': 0},
                          sr_probe=probe, invalid_params=[{'detect_lo_hz': 200, 'detect_hi_hz': 100},
                                                        {'reject_lo_hz': 20, 'reject_hi_hz': 0}], seconds=.1)
    assert P.validate_params('drum_gate', {}) == {k: d for k, _, _, d in expected}
    x = H.sine(100, -12, sr=48000, seconds=.05)
    defaults = P.validate_params('drum_gate', {})
    for k, lo, hi, _ in expected:
        for value in (lo, hi):
            p = dict(defaults, **{k: value})
            if k == 'detect_lo_hz':
                p['detect_hi_hz'] = min(20000, value+1)
                if value == 20000:
                    with pytest.raises(ParamError):
                        P.validate_params('drum_gate', p)
                    continue
            if k == 'detect_hi_hz' and value == 20:
                with pytest.raises(ParamError):
                    P.validate_params('drum_gate', p)
                continue
            if k in ('reject_lo_hz', 'reject_hi_hz') and value:
                p.update(reject_lo_hz=20 if k == 'reject_hi_hz' else value,
                         reject_hi_hz=value if k == 'reject_hi_hz' else 20000)
                if p['reject_lo_hz'] >= p['reject_hi_hz']:
                    with pytest.raises(ParamError):
                        P.validate_params('drum_gate', p)
                    continue
            assert np.isfinite(render(x, p, 48000).audio).all()


@pytest.mark.parametrize('sr', [44100, 48000, 96000])
def test_gate_measured_hold_release_and_velocity(sr):
    from mankomix.dspx.procs.drum_gate import drum_gate
    x, truth = train(1, sr=sr)
    x += np.where(np.arange(len(x))[:, None] % 2, 1e-6, -1e-6)
    p = P.validate_params('drum_gate', {'decay_follow': 0, 'velocity_sense': 0})
    y, _, stats = drum_gate(x, sr, p)
    hit = next(r for r in stats['hits'] if r['opened'])
    assert hit['close_start_sample']-hit['trigger_end_sample'] == round(.060*sr)
    sample = hit['close_start_sample']+round(.2*sr)-1
    measured = 20*np.log10(abs(y[sample, 0]/x[sample, 0]))
    assert measured == pytest.approx(-40*(1-np.exp(-1)), abs=.03)
    print('gate_hold_release', sr, 1000*(hit['close_start_sample']-hit['trigger_end_sample'])/sr, measured)


def test_gate_velocity_and_open_audio():
    from mankomix.dspx.procs.drum_gate import drum_gate
    x, truth = train(2, levels=[.25, 1], interval=.4)
    p = P.validate_params('drum_gate', {'velocity_sense': 1, 'decay_follow': 0})
    y, _, stats = drum_gate(x, SR, p)
    hits = [r for r in stats['hits'] if r['opened']]
    assert len(hits) == 2 and hits[0]['open_gain_db'] < hits[1]['open_gain_db'] == 0
    assert hits[0]['open_gain_db'] == pytest.approx(-12.0412, abs=.05)
    assert y[truth[1]:truth[1]+120].tobytes() == x[truth[1]:truth[1]+120].tobytes()












def test_sample_registry_license_pinning_byo(tmp_path):
    assert len(SAMPLES.catalog()['samples']) == 3
    for id in ('synth_kick_a', 'synth_snare_a', 'synth_hat_a'):
        data, entry, notes = SAMPLES.load(id)
        assert data == synthetic_bytes(id) and not notes
        assert entry['origin']['type'] == 'synthetic' and entry['license']['usage_restrictions'] == 'none'
    with pytest.raises(ParamError, match='unregistered'):
        SAMPLES.load('missing')
    f = tmp_path/'byo.wav'
    f.write_bytes(synthetic_bytes('synth_snare_a'))
    with pytest.raises(ParamError, match='license'):
        SAMPLES.register_file(f, id='local', license_spdx='')
    SAMPLES.register_file(f, id='local', license_spdx='unknown')
    assert SAMPLES.load('local')[2]
    f.write_bytes(b'corrupt')
    with pytest.raises(ParamError, match='sha256'):
        SAMPLES.load('local')


def replacement(root, **p):
    m = move('drum_replace', target='trk_drums', sample='synth_snare_a', detect_lo_hz=200, detect_hi_hz=8000,
             threshold_db=-60, align='onset', **p)
    return m, R.expand(D._Project(root), m)


def test_replace_40_hits_layers_gains_only_skip_and_phase(tmp_path):
    x, positions = train(40, kind='snare', levels=[.2, .4, .7, 1], interval=.2)
    root = T._make(tmp_path/'song', {'drums': x})
    m, plan = replacement(root)
    hits = plan.record['hits']
    assert len(hits) == 40
    assert max(abs(r['sample']-pos) for r, pos in zip(hits, positions)) <= .002*SR
    assert all(abs(r['position']-pos) <= .0005*SR for r, pos in zip(hits, positions))
    for r in hits:
        assert r['velocity_gain_db'] == pytest.approx(-18+18*r['strength'], abs=.1)
    m['params'].pop('sample')
    m['params']['samples'] = [{'id': 'synth_kick_a', 'min_velocity': 0}, {'id': 'synth_snare_a', 'min_velocity': .6}]
    layered = R.expand(D._Project(root), m)
    for r in layered.record['hits']:
        assert r['sample_id'] == ('synth_snare_a' if r['strength'] >= .6 else 'synth_kick_a')
    m['params']['samples'] = [{'id': 'synth_snare_a', 'min_velocity': .8}]
    m['params']['velocity_curve'] = [[.5, -6]]
    sparse = R.expand(D._Project(root), m)
    assert 0 < len(sparse.record['hits']) < 40
    assert all(r['strength'] >= .8 and r['velocity_gain_db'] == -6 for r in sparse.record['hits'])
    m['params'].pop('velocity_curve')
    m['params']['samples'] = [{'id': 'synth_kick_a', 'min_velocity': 0}, {'id': 'synth_snare_a', 'min_velocity': 0}]
    m['params'].update(round_robin=True, tune_semitones=12, humanize_db=3, blend_db=[-12, -6])
    rr = R.expand(D._Project(root), m)
    assert [r['sample_id'] for r in rr.record['hits'][:4]] == ['synth_kick_a', 'synth_snare_a']*2
    assert all(r['speed'] == 2 for r in rr.record['hits'])
    assert rr.record['params']['blend_db'] == -9
    assert rr.record == R.expand(D._Project(root), m).record
    m['params'].update(only=[hits[0]['id'], hits[1]['id']], skip=[hits[0]['id']])
    assert [r['id'] for r in R.expand(D._Project(root), m).record['hits']] == [hits[1]['id']]
    wave = synthetic_sample('synth_snare_a', SR)
    source = np.zeros((SR, 1))
    source[1000+17:1000+17+len(wave)] = -wave
    offset, polarity = R.phase_offset(source, wave, 1000, SR)
    assert offset == 17 and polarity == -1
    print('replace_max_onset_ms', max(abs(r['sample']-pos) for r, pos in zip(hits, positions))/SR*1000)


def test_replace_plan_apply_trace_regenerate_length_and_revert(tmp_path):
    x, _ = train(3, interval=.4)
    root = T._make(tmp_path/'song', {'drums': x})
    m = move('drum_replace', target='trk_drums', sample='synth_kick_a', mode='replace',
             align='onset', humanize_db=2, seed=14, velocity_curve=[[0, -12], [1, 0]])
    parsed = doc(tmp_path, [m])
    assert D.validate(parsed, root)['ok']
    floor = tmp_path/'floor'
    shutil.copytree(root, floor)
    T._render(floor)
    before_audio = mr.render_mix(Project.open(root))[0]
    before = C._snapshot(root)
    first = D.build_proposal(D._Project(root), parsed)
    assert first == D.build_proposal(D._Project(root), parsed)
    assert C._snapshot(root) == before
    plan = R.expand(D._Project(root), m)
    for a, b in plan.record['replace_intervals']:
        assert np.interp((a+b)//2, *np.asarray(plan.points).T) == -90
    result = D.apply(root, parsed['path'])
    assert result['applied'], result
    project = Project.open(root)
    assert len(project.data['tracks']) == 2
    assert project.data['timebase']['length_samples'] == len(x)
    assert len(project.data['tracks'][-1]['clips']) == 3
    assert project.data['tracks'][-1]['output'] == project.data['tracks'][0]['output']
    T._render(root)
    assert D.check(root, floor, parsed['path'])['move_ref']['ok']
    ledger = B._ledger(root, parsed['id'])
    name, row = next(iter(ledger['nodes']['m01']['assets'].items()))
    dest = project.asset_path(row['asset'])
    data = dest.read_bytes()
    dest.unlink()
    (root/'cache'/'derived'/f"{row['key']}.node.wav").unlink()
    asset = next(a for a in plan.nodes.assets if a.name == name)
    assert B.regenerate_node(root, parsed['id'], 'm01', name, audio=asset.audio)['regenerated']
    assert dest.read_bytes() == data
    assert E.revert(root, parsed['id'])['reverted_moves'] == ['m01']
    assert mr.render_mix(Project.open(root))[0].tobytes() == before_audio.tobytes()


@pytest.mark.parametrize('bad', [ {'sample': 'missing'}, {'sample': None}, {'velocity_curve': [[0, 0], [1, -12]]},
    {'samples': [{}]}, {'only': ['bad']}, {'seed': 1.5}, {'round_robin': 1}, {'detect_hi_hz': 20}, {'bogus': 1}])
def test_replace_validation_bad_params(tmp_path, bad):
    x, _ = train(2)
    root = T._make(tmp_path/'song', {'drums': x})
    p = {'sample': 'synth_kick_a', **bad}
    parsed = doc(tmp_path, [move('drum_replace', target='trk_drums', **p)])
    before = C._snapshot(root)
    assert not D.validate(parsed, root)['ok']
    assert C._snapshot(root) == before




def test_existing_onset_ids_retained_and_sustained_tone_not_triggered():
    from mankomix.dspx.bb.onsets import detect_onsets
    from mankomix.dspx.bb.drum_events import drum_onsets
    x, _ = train(4, kind='snare')
    primary = detect_onsets(x, SR)
    extended = drum_onsets(x, SR)
    assert {r['id'] for r in primary} <= {r['id'] for r in extended}
    for hz in (60, 1000):
        assert drum_onsets(H.sine(hz, -12, sr=SR, seconds=.4), SR) == []
