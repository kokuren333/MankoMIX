"""W4b: exact existing meters, stable hit IDs and read-only CLI contracts."""
import argparse
import hashlib
import json
import subprocess
import types

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import audio_io, mastering as M, mixrender as MR, render as R
from mankomix.core.errors import InputError
from mankomix.core.measure import loudness as L
from mankomix.core.measure.stereo import band_stereo
from mankomix.core.measure.bands import Spectrum
from mankomix.core.project import Project
from mankomix.director import commands as C, query as Q, stemobs as S
from mankomix.director import _observations_w4b as O
from mankomix.director.commands import _measurement as W, query_mono as MONO
from mankomix.director.commands import query_onsets as ON, query_meters as MET
from mankomix.director.commands import preview_codec as CODEC, query_limiter_headroom as HEAD
from mankomix.dsp.engine import render_chain
from tests import test_upgrade2_duck as T, toolimpl_harness as H
from tests.test_tk_w2i import drum_sequence, match_events

SR = T.SR


def args(module, root, *flags):
    p = argparse.ArgumentParser()
    module.add_args(p)
    ns = p.parse_args(list(flags))
    ns.project = str(root)
    return ns


@pytest.fixture
def material(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path/'home'))
    t = np.arange(round(1.2*SR))/SR
    mid = .04*np.sin(2*np.pi*220*t)
    side = H.white_noise(-20, sr=SR, seconds=1.2, seed=57)[:, 0]
    root = T._make(tmp_path/'song', {'good': np.column_stack([mid, mid]),
                                    'bad': np.column_stack([side, -side])})
    p = Project.open(root)
    p.set('/variants/0/master', {'profile': 'streaming_universal', 'route': 'stem_mix',
                                'chain': [M.limiter_proc(-1, 'preview fixture')]}, actor='human')
    return root


def execute(module, ns, root):
    return C.execute(module.COMMANDS[0], ns, root)


def test_registration():
    rows = {d['path']: d for d in C.declarations()}
    for name in ('mono', 'meters', 'onsets', 'limiter_headroom'):
        assert rows[('query', name)]['writes'] is False
        assert 'direction query '+name in C.cli_only()
    assert rows[('preview', 'codec')]['writes'] == 'out_only'


@pytest.mark.parametrize('module,flags', [(MONO, []), (MET, ['--what', 'loudness', 'peak', 'correlation']),
                                        (ON, []), (CODEC, ['--codec', 'aac'])])
def test_readonly_repeat_cli(material, module, flags, monkeypatch, capsys):
    monkeypatch.setattr(CODEC.FB, 'available', lambda: False)
    ns = args(module, material, *flags)
    before = C._snapshot(material)
    one = execute(module, ns, material)
    assert execute(module, ns, material) == one
    assert main(['direction', *module.COMMANDS[0]['path'], *flags, '--project', str(material)]) == 0
    assert json.loads(capsys.readouterr().out) == one
    assert C._snapshot(material) == before


def test_legacy_observation_bytes():
    # Original committed implementation is an independent regression oracle.
    src = subprocess.check_output(['git', 'show', 'HEAD:director/query.py']).decode('utf-8')
    old = types.ModuleType('mankomix.director._old_query')
    exec(compile(src, '<committed query>', 'exec'), old.__dict__)
    x = H.white_noise(-24, sr=48000, seconds=3.2, channels=2, seed=81)
    observations = [{'primitive': p, 'band_hz': [200, 4000], 'ref_band_hz': [40, 200]}
                    for p in old.PRIMITIVES]
    observations += [{'primitive': 'loudness', 'stat': s} for s in old.LOUDNESS_STATS]
    for obs in observations:
        for gain in (0, -2.3):
            for view in ('stereo', 'mono', 'side'):
                o = dict(obs, view=view)
                if view == 'side' and o['primitive'] not in old.SIDE_PRIMITIVES:
                    continue
                if view == 'mono' and o['primitive'] in old.STEREO_ONLY_PRIMITIVES:
                    continue
                before = json.dumps(old.observe(x, 48000, o, gain_db=gain), sort_keys=True)
                after = json.dumps(Q.observe(x, 48000, o, gain_db=gain), sort_keys=True)
                assert after.encode() == before.encode()


@pytest.mark.parametrize('sign', [1, -1])
def test_mono_exact_existing_and_polarity(sign):
    x = H.white_noise(-12, sr=48000, seconds=1.2, seed=78)
    x = np.column_stack([x[:, 0], x[:, 0]*sign])
    r = Q.observe(x, 48000, {'primitive': 'mono_loss'})
    expected = band_stereo(Spectrum(x, 48000))['full_band']
    assert r['value'] == expected['level_change_db']
    assert r['stereo'] == expected
    if sign == 1:
        assert r['value'] == 0
    else:
        assert r['value'] is None and r['stereo']['cancelled']
    bands = Q.observe(x, 48000, {'primitive': 'correlation_bands'})['bands']
    for band in bands:
        assert band['median'] == pytest.approx(sign, abs=1e-9)
        assert band['negative_fraction'] == (0 if sign == 1 else 1)


def test_mono_delay_comb_and_bytrack(material):
    x = H.white_noise(-12, sr=48000, seconds=3, seed=12)
    y = np.column_stack([x[:, 0], np.roll(x[:, 0], 24)])
    for center in (1000, 3000, 5000):
        loss = O.mono(y, 48000, center)['level_change_db']
        left = O.mono(y, 48000, center/2**(1/3))['level_change_db']
        right = O.mono(y, 48000, center*2**(1/3))['level_change_db']
        assert loss < left and loss < right
    r = execute(MONO, args(MONO, material, '--by-track'), material)
    assert r['by_track'][0]['track'] == 'trk_bad'
    assert r['by_track'][0]['improvement_db'] > 0


@pytest.mark.parametrize('raw', [{'threshold': float('nan')}, {'threshold': True}, {'threshold': 1.1},
                               {'min_interval_ms': 4}, {'kind': 'invalid'}, {'band': 'invalid'},
                               {'grid_note': '1/16'}, {'bpm': 120}, {'bpm': 500, 'grid_note': '1/4'},
                               {'unknown': 1}, []])
def test_bad_onset_params(raw):
    errs = S.spec_errors({'primitive': 'onsets', 'params': raw})
    assert errs and errs[0][1] == 'bad_value'
    with pytest.raises(Q.QueryError):
        Q.observe(np.zeros((48000, 2)), 48000, {'primitive': 'onsets', 'params': raw})


@pytest.mark.parametrize('band', [True, 'nonsense', [200, 100], [0, float('inf')], 0, 21000])
def test_bad_mono_bands(band):
    with pytest.raises(Q.QueryError):
        Q.observe(np.zeros((48000, 2)), 48000, {'primitive': 'mono_loss', 'params': {'band': band}})


def test_onsets_acceptance_grid_and_section_ids():
    sr = 48000
    x, truth = drum_sequence(sr)
    p = O.params('onsets', {})
    events = O.onset_events(x, sr, p)
    f, err = match_events([e['sample'] for e in events], truth, sr*.01)
    assert f >= .95 and np.median(abs(err))/sr*1000 <= 2
    print('W4b onset acceptance:', json.dumps({'f_score': f, 'median_error_ms': float(np.median(abs(err))/sr*1000)}))
    all_result = Q.observe(x, sr, {'primitive': 'onsets'})
    assert all_result['count'] == len(events)
    a, b = 4*sr, 8*sr
    selected = O.onset_events(x, sr, p, offset=a, end=b)
    assert selected == [e for e in events if a <= e['sample'] < b]
    grid = O.params('onsets', {'grid_note': '1/16', 'bpm': 120, 'origin_s': 0})
    known = [{'time_s': .125*k+delta/1000} for k, delta in enumerate([-20, -10, 0, 10, 20], 1)]
    np.testing.assert_allclose(O.grid_deviations(known, grid), [-20, -10, 0, 10, 20], atol=1e-10)


def test_onset_cli_against_and_primitive_track(material):
    r = execute(ON, args(ON, material, '--target', 'trk_bad', '--against', 'trk_good'), material)
    assert 'comparison' in r
    o = {'primitive': 'onsets', 'target': 'mix'}
    assert S.observe(S.StemSource(material, 'var_x'), o)['status'] == 'ok'
    o['primitive'] = 'correlation_bands'
    assert S.observe(S.StemSource(material, 'var_x'), o)['value'] is None


def test_meters_exact_and_peak_retention(material):
    ns = args(MET, material, '--what', 'loudness', 'peak', 'correlation', '--step-ms', '10', '--max-points', '2')
    r = execute(MET, ns, material)
    x, sr, a, b, _ = W.source(ns)
    x = x[a:b]
    summary = L.loudness_summary(x, sr)
    assert r['summary'] == W.clean(summary)
    assert r['correlation']['full'] == band_stereo(Spectrum(x, sr))['full_band']['correlation']
    assert len(r['times_s']) <= 2 and r['step_widened']
    assert max(r['peak']['sample_peak_dbfs']) == L.sample_peak_dbfs(x)
    from mankomix.dspx.bb import meters
    base = meters.timeline(x, sr, hop_ms=10)
    assert max(r['peak']['true_peak_dbtp']) == max(base['true_peak_dbtp'])


def test_all_meter_shapes_and_vectorscope(material):
    ns = args(MET, material, '--max-points', '3', '--points', '17')
    r = execute(MET, ns, material)
    assert set(MET.WHAT) <= set(r)
    assert len(r['spectrogram']['edges_hz']) == 97
    assert len(r['spectrogram']['levels_dbfs'][0]) == 96
    assert len(r['vectorscope']['points_lr']) == 17
    assert len(r['spectrum']['levels_dbfs']) <= 3
    r = execute(MET, args(MET, material, '--target', 'trk_good', '--what', 'vectorscope'), material)
    for w in r['vectorscope']['windows']:
        assert w['spread'] == 0 and w['tilt_degrees'] == 0
    r = execute(MET, args(MET, material, '--target', 'trk_bad', '--what', 'vectorscope'), material)
    assert all(w['spread'] == 1 for w in r['vectorscope']['windows'])


def test_bus_tap_matches_core_mix(material):
    ns = args(MET, material, '--target', 'bus_mix', '--what', 'peak')
    x, sr, _, _, _ = W.source(ns)
    p = Project.open(material)
    expected, rate, _ = MR.render_mix(p, variant_id='var_x', measure=False)
    assert rate == sr
    np.testing.assert_array_equal(x, expected)


def test_welch_tone_and_pink():
    sr = 48000
    edges = np.array([[b.lo_hz, b.hi_hz] for b in MET.third_octave_grid(sr)])
    x = H.sine(1000, dbfs=-12, sr=sr, seconds=3)
    levels = MET.db(MET.welch_bands(x, sr, edges))
    assert edges[np.argmax(levels), 0] < 1000 < edges[np.argmax(levels), 1]
    x = H.pink_noise(-12, sr=sr, seconds=40, seed=83)
    levels = MET.db(MET.welch_bands(x, sr, edges))
    middle = levels[(edges[:, 0] >= 100) & (edges[:, 1] <= 16000)]
    assert np.max(abs(middle-np.median(middle))) <= .5


def test_codec_no_encoders_and_validation(material, monkeypatch):
    monkeypatch.setattr(CODEC.FB, 'available', lambda: False)
    before = C._snapshot(material)
    r = execute(CODEC, args(CODEC, material, '--codec', 'aac', 'opus'), material)
    assert not r['available'] and r['reason'] == '使えるものなし'
    assert all(row['status'] == 'unavailable' for row in r['rows'])
    assert C._snapshot(material) == before
    for flags in [('--bitrate-kbps', '31'), ('--normalize-lufs', '-7'), ('--normalize-lufs', 'nan')]:
        with pytest.raises(InputError):
            execute(CODEC, args(CODEC, material, *flags), material)


def test_codec_lossless_mock_tp_normalize_and_explicit_out(material, tmp_path, monkeypatch):
    monkeypatch.setattr(CODEC.FB, 'available', lambda: True)
    calls = []
    def identity(x, sr, codec, br, return_info=False):
        calls.append((codec, br, return_info))
        return x.copy(), sr, {'encoder': 'test_lossless', 'delay_samples': 0, 'ffmpeg': 'test'}
    monkeypatch.setattr(CODEC.FB, 'encode_decode_roundtrip', identity)
    ns = args(CODEC, material, '--codec', 'aac', '--normalize-lufs', '-30')
    before = C._snapshot(material)
    r = execute(CODEC, ns, material)
    row = r['rows'][0]
    assert row['difference_rms_dbfs'] <= -120
    x, sr, a, b, _ = W.source(args(MONO, material))
    down = max(0, L.integrated(x[a:b], sr)+30)
    assert row['normalization_down_db'] == down
    exact = R.codec_true_peaks(x[a:b], sr, ['aac'], 0, {'s02_codec': {'bitrates': {'aac': '256k'}}})
    assert row['true_peak_dbtp'] == exact['aac']['true_peak_dbtp']
    assert all(c[2] is True for c in calls)
    assert C._snapshot(material) == before
    dest = tmp_path/'listen'
    ns.out = str(dest)
    r = execute(CODEC, ns, material)
    assert len(list(dest.glob('*.wav'))) == 3 and (dest/'key/key.json').is_file()
    assert sorted(str(p.relative_to(dest)).replace('\\', '/') for p in dest.rglob('*') if p.is_file()) == r['files']
    assert C._snapshot(material) == before
    assert all(g <= 0 for g in r['rows'][0]['listen_gain_db'].values())


def test_codec_existing_alignment_and_lossless_file(tmp_path):
    sr = 48000
    x = H.white_noise(-18, sr=sr, seconds=1, channels=2, seed=55)
    for lag in (-71, 0, 137):
        if lag >= 0:
            delayed = np.pad(x, ((lag, 0), (0, 0)))
        else:
            delayed = x[-lag:]
        actual = CODEC.FB.estimate_delay(x, delayed, sr)
        assert actual == lag
    # Test-only FLAC file uses existing audio_io, no production encoder path.
    path = tmp_path/'lossless.flac'
    quantized = np.round(x*2**23)/2**23
    audio_io.write(path, quantized, sr, subtype='PCM_24')
    decoded, rate = audio_io.read(path)
    result, _ = CODEC.analyze(quantized, decoded, rate, {'delay_samples': 0})
    assert result['difference_rms_dbfs'] <= -120
    assert CODEC.FB.estimate_delay(quantized, decoded, sr) == 0


def test_headroom_actual_renders_and_readonly(material, capsys):
    ns = args(HEAD, material)
    before = C._snapshot(material)
    r = execute(HEAD, ns, material)
    assert len(r['rows']) == 13 and [v['drive_db'] for v in r['rows']] == list(range(13))
    p, v = W.project(ns)
    x, sr = W.master_input(p, v)
    for row in r['rows']:
        actual = render_chain(x, sr, M.engine_chain(row['chain']), stage='master', seed=0)
        stats = next(s for s in actual.steps if s['type'] == 'adaptive_limiter')['stats']
        assert row['lufs_i'] == L.integrated(actual.audio, actual.sr)
        assert row['frac_gr_over_3db'] == stats['frac_gr_over_3db']
        assert row['max_gr_db'] == stats['gain_reduction']['max_db']
        assert actual.steps[-1]['type'] == 'limiter'
    baseline = render_chain(x, sr, M.engine_chain(v['master']['chain']), stage='master', seed=0)
    zero = render_chain(x, sr, M.engine_chain(r['rows'][0]['chain']), stage='master', seed=0)
    np.testing.assert_array_equal(baseline.audio, zero.audio)
    assert C._snapshot(material) == before
    assert main(['direction', 'query', 'limiter_headroom', '--project', str(material)]) == 0
    assert json.loads(capsys.readouterr().out) == r
    assert C._snapshot(material) == before
    print('W4b headroom:', json.dumps([{k: row[k] for k in ('drive_db', 'lufs_i', 'max_gr_db', 'frac_gr_over_3db')} for row in r['rows']]))


def test_ms1_definition_hashes():
    expected = {'knowledge/thresholds.json': '682e6f6104437d8bdc4f6d9eb6d743d7ae9bca6856396ea206b4571fdbdc3bab',
                'knowledge/rules.json': '15842e10df9a1b1b092a1c06895d741ce99f2452a6dcce72ff59412b0cc6f4eb',
                'knowledge/objective_metrics.json': '3a854f6b765be37aae9eea1a71a41cc24dfb6d3137936dce8b0b7e2a5b4e0397',
                'knowledge/mix_rules.json': 'f1789b96eb0b43e3ba625e65d3cc9299d03483cdf35c3159598bbaa8a49f81ef',
                'profiles/media_profiles.json': '85a52c337ef8ae7d7388bc6baf095c59c95fae8d2e17a33d0e0d4bf7d1452c6d'}
    from pathlib import Path
    for filename, digest in expected.items():
        assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest


def test_existing_adaptive_drive_preview():
    chain = [{'id': 'existing_adaptive', 'type': 'adaptive_limiter',
              'params': {'drive_db': 3, 'ceiling_db': -2}}, M.limiter_proc(-1, 'test')]
    r = HEAD.hypothetical_chain(chain, 7)
    assert r[0]['id'] == 'existing_adaptive'
    assert r[0]['params'] == {'drive_db': 7, 'ceiling_db': -2}
    assert chain[0]['params']['drive_db'] == 3
    assert r[-1] == chain[-1]


def test_grid_measurement_actual_shifted_hits():
    sr = 48000
    shifts = np.tile([-20, -10, 0, 10, 20], 4)
    positions = np.round((.2+np.arange(len(shifts))*.25+shifts/1000)*sr).astype(int)
    x = np.zeros((positions[-1]+sr//2, 2))
    for i, pos in enumerate(positions):
        hit = H.drum('snare', sr=sr, seconds=.12, dbfs=-12, seed=i)
        x[pos:pos+len(hit)] += hit
    o = {'primitive': 'onsets', 'params': {'grid_note': '1/8', 'bpm': 120, 'origin_s': .2}}
    r = Q.observe(x, sr, o)
    assert r['count'] == len(positions)
    expected = O.distribution(shifts)
    assert all(abs(r['grid_deviation_ms'][key]-expected[key]) <= 1 for key in ('median', 'q1', 'q3', 'max_abs'))
    print('W4b grid deviations:', json.dumps(r['grid_deviation_ms']))


def test_bus_pre_post_sends_and_chain(material):
    p = Project.open(material)
    p.set('/buses', [*p.data['buses'], {'id': 'bus_aux', 'kind': 'aux', 'output': 'bus_mix',
                                      'gain_db': -4, 'chain': [{'id': 'aux_gain', 'type': 'gain',
                                                              'params': {'gain_db': -2}, 'reason': 'test'}]}], actor='human')
    p.set('/tracks/0/sends', [{'bus': 'bus_aux', 'level_db': -7, 'pre_fader': True}], actor='human')
    p.set('/tracks/1/sends', [{'bus': 'bus_aux', 'level_db': -13, 'pre_fader': False}], actor='human')
    p.set('/tracks/0/gain_db', -5, actor='human')
    p, v = W.project(args(MET, material))
    tap, sr = W.bus_audio(p, v, 'bus_mix')
    actual, rate, _ = MR.render_mix(p, variant_id=v['id'], measure=False)
    assert sr == rate
    np.testing.assert_array_equal(tap, actual)


@pytest.mark.parametrize('flags', [('--step-ms', '9'), ('--step-ms', 'nan'), ('--max-points', '0'), ('--points', '-1')])
def test_meter_invalid_limits(material, flags):
    with pytest.raises(InputError):
        execute(MET, args(MET, material, *flags), material)


def test_readonly_failure_guard(material):
    from pathlib import Path
    def violate(ns):
        (Path(ns.project)/'directions').mkdir(exist_ok=True)
        (Path(ns.project)/'directions'/'unexpected.json').write_text('{}', encoding='utf-8')
        raise RuntimeError('callback failure')
    row = dict(ON.COMMANDS[0], run=violate)
    with pytest.raises(InputError, match='violated its write contract'):
        C.execute(row, args(ON, material), material)


def test_codec_real_backend_ms3_if_available(material):
    # No test encoder is added. The installed verification backend decides
    # availability, and an absent encoder is an expected measured result.
    ns = args(CODEC, material, '--codec', 'aac')
    before = C._snapshot(material)
    row = execute(CODEC, ns, material)['rows'][0]
    x, sr, a, b, _ = W.source(args(MONO, material))
    existing = R.codec_true_peaks(x[a:b], sr, ['aac'], 0,
                                 {'s02_codec': {'bitrates': {'aac': '256k'}}})['aac']
    if existing['status'] == 'not_run':
        assert row['status'] == 'unavailable'
    else:
        assert row['true_peak_dbtp'] == existing['true_peak_dbtp']
    assert C._snapshot(material) == before
    print('W4b real codec:', json.dumps({'preview_status': row['status'], 'verify_status': existing['status'],
                                       'preview_tp': row.get('true_peak_dbtp'), 'verify_tp': existing.get('true_peak_dbtp')}))


def test_codec_audio_excerpt_and_output_inside_project(material, tmp_path, monkeypatch):
    monkeypatch.setattr(CODEC.FB, 'available', lambda: True)
    def identity(x, sr, codec, br, return_info=False):
        return x.copy(), sr, {'encoder': 'test_lossless', 'delay_samples': 0}
    monkeypatch.setattr(CODEC.FB, 'encode_decode_roundtrip', identity)
    path = tmp_path/'supplied.wav'
    audio_io.write(path, H.sine(1000, sr=48000, seconds=2), 48000, subtype='DOUBLE')
    digest = hashlib.sha256(path.read_bytes()).digest()
    ns = args(CODEC, material, '--audio', str(path), '--codec', 'aac', '--excerpt', '.2,1.2',
              '--normalize-lufs', 'off', '-30', '--out', str(material/'codec-listen'))
    before = C._snapshot(material)
    r = execute(CODEC, ns, material)
    assert len(r['rows']) == 2 and all(row['range_s'] == [.2, 1.2] for row in r['rows'])
    assert len(list((material/'codec-listen').glob('*.wav'))) == 6
    after = C._snapshot(material)
    assert all(before[k] == after[k] for k in before)
    assert hashlib.sha256(path.read_bytes()).digest() == digest


def test_meter_tail_and_silence_use_existing_crest(material, tmp_path, monkeypatch):
    # An odd one-sample tail exercises Welch padding at very low point counts.
    x = np.zeros((SR+1, 2))
    monkeypatch.setattr(W, 'source', lambda args: (x, SR, 0, len(x), {'range_s': [0, len(x)/SR]}))
    r = MET.run(args(MET, material, '--step-ms', '1000'))
    assert r['rms_crest']['rms_dbfs'] == [None, None]
    assert r['rms_crest']['crest_db'] == [None, None]
    assert len(r['spectrum']['levels_dbfs']) == 2
