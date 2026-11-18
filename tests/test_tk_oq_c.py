"""OQ-3: actual HTTP/CLI equivalence and read-only observation boundaries."""
import json
from urllib.parse import urlencode

import numpy as np
import pytest

from mankomix.cli.main import main
from mankomix.core import config
from mankomix.core.server import MankoServer
from mankomix.director import commands
from mankomix.dsp.engine import validate_chain
from tests.test_serve import Client
from tests.test_upgrade2_duck import SR, _make


@pytest.fixture
def observation_server(tmp_path, monkeypatch):
    monkeypatch.setenv('MANKOMIX_HOME', str(tmp_path / 'home'))
    config.clear_cache()
    t = np.arange(round(1.2 * SR)) / SR
    x = .1 * np.sin(2 * np.pi * np.where(t < .6, 220, 330) * t)
    root = _make(tmp_path / 'song', {'voice': np.column_stack([x, .8 * x])})
    before = commands._snapshot(root)
    try:
        with MankoServer(tmp_path, project='song', port=0) as srv:
            yield root, Client(srv.url, tmp_path)
        assert commands._snapshot(root) == before
    finally:
        config.clear_cache()


def cli_json(root, capsys, *flags):
    assert main(['direction', *flags, '--project', str(root)]) == 0
    return json.loads(capsys.readouterr().out)


def test_pitch_notes_cli_api_exact(observation_server, capsys):
    root, client = observation_server
    section = '{"t0_s":0.1,"t1_s":1.1}'
    cli = cli_json(root, capsys, 'pitch', 'notes', '--target', 'trk_vocals',
                   '--section', section, '--lo-hz', '90', '--hi-hz', '800', '--a4', '442')
    query = urlencode(dict(target='trk_vocals', section=section, lo_hz=90, hi_hz=800, a4=442))
    result = client.get('/api/direction/pitch/notes?' + query)
    assert result == cli
    assert result['count'] >= 2 and all(n['pitch_midi'] > 0 for n in result['notes'])
    assert client.get('/api/direction/pitch/notes?' + query) == result


def test_meters_cli_api_exact(observation_server, capsys):
    root, client = observation_server
    cli = cli_json(root, capsys, 'query', 'meters', '--target', 'trk_vocals', '--section', '0.1,1.1',
                   '--step-ms', '50', '--max-points', '7', '--points', '12', '--octave', '6')
    query = urlencode(dict(target='trk_vocals', section='0.1,1.1', step_ms=50, max_points=7, points=12, octave=6))
    result = client.get('/api/direction/query/meters?' + query)
    assert result == cli
    assert result['decimation_factor'] > 1
    assert {'peak', 'loudness', 'spectrum', 'spectrogram', 'vectorscope', 'correlation'} <= result.keys()
    assert len(result['times_s']) <= 7


def test_spectral_preview_cli_api_exact(observation_server, capsys):
    root, client = observation_server
    params = dict(t0_s=[.1, .7], t1_s=[.3, .9], lo_hz=[100, 300], hi_hz=[200, 500], mode='attenuate')
    # validate_chain is the CLI render path; it calls the same parameter validator.
    canonical = validate_chain([dict(id='oq_preview', type='spectral_repair', params=params)], 'track')[0]['params']
    cli = cli_json(root, capsys, 'query', 'meters', '--target', 'trk_vocals', '--what', 'spectrogram',
                   '--section', '0.1,1.1', '--step-ms', '50', '--max-points', '9')
    result = client.post('/api/direction/spectral-repair/preview',
                         dict(target='trk_vocals', section='0.1,1.1', step_ms=50, max_points=9, params=params))
    assert result['params'] == canonical
    assert result['observation'] == cli
    assert result['read_only'] is True
    assert result['params']['context_ms'] == 200
    assert result['params']['t0_s'] == [.1, .7]


@pytest.mark.parametrize('params', [
    dict(t0_s=[0], t1_s=[], lo_hz=[100], hi_hz=[200]),
    dict(t0_s=[0], t1_s=[2.1], lo_hz=[100], hi_hz=[200]),
    dict(t0_s=[.2], t1_s=[.1], lo_hz=[100], hi_hz=[200]),
    dict(t0_s=[0], t1_s=[.1], lo_hz=[200], hi_hz=[100]),
    dict(t0_s=[0] * 65, t1_s=[.1] * 65, lo_hz=[100] * 65, hi_hz=[200] * 65),
    dict(mode='unknown'), dict(window=512), dict(feather_oct=.6),
])
def test_spectral_invalid_matches_cli_validation(observation_server, params):
    _, client = observation_server
    from mankomix.dsp.errors import ParamError
    with pytest.raises(ParamError):
        validate_chain([dict(type='spectral_repair', params=params)], 'track')
    error = client.post('/api/direction/spectral-repair/preview', dict(target='trk_vocals', params=params), expect=400)
    assert error['error'] == 'input_error'


@pytest.mark.parametrize('route', [
    '/api/direction/pitch/notes',
    '/api/direction/pitch/notes?target=missing',
    '/api/direction/query/meters?target=missing',
    '/api/direction/query/meters?target=trk_vocals&step_ms=nan',
    '/api/direction/query/meters?target=trk_vocals&what=invalid',
    '/api/direction/query/meters?target=trk_vocals&project=outside',
    '/api/direction/query/meters?target=trk_vocals&audio=outside.wav',
])
def test_observation_invalid_and_path_overrides(observation_server, route):
    _, client = observation_server
    assert client.get(route, expect=400)['error'] == 'input_error'


def test_spectral_empty_and_rejects_project_override(observation_server):
    _, client = observation_server
    result = client.post('/api/direction/spectral-repair/preview', dict(target='trk_vocals', params={}))
    assert all(result['params'][k] == [] for k in ('t0_s', 't1_s', 'lo_hz', 'hi_hz'))
    client.post('/api/direction/spectral-repair/preview', dict(target='trk_vocals', params={}, project='outside'), expect=400)
