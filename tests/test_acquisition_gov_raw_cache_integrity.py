"""Small offline regressions for raw-cache repairs and durable error classification."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('acquisition_raw_integrity_loader', ROOT / 'scripts/load_acquisition_gov.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
URL = 'https://www.acquisition.gov/sites/default/files/test.pdf'


def response(body=b'%PDF-small cached bytes'):
    return {'url': URL, 'final_url': URL, 'content_type': 'application/pdf',
            'body': body, 'sha256': hashlib.sha256(body).hexdigest(), 'fetched_at': '2026-10-10T00:00:00Z'}


@pytest.mark.parametrize('damaged', [b'corrupt', b'x' * len(response()['body'])])
def test_verified_incoming_response_repairs_existing_corrupt_body(tmp_path, damaged):
    cache = loader.Recorder(tmp_path)
    original = response()
    cache.save(URL, loader.PDF, original)
    (tmp_path / 'bodies' / original['sha256']).write_bytes(damaged)
    cache.save(URL, loader.PDF, original)
    assert loader.Recorder(tmp_path).load(URL, loader.PDF)['body'] == original['body']
    assert not list((tmp_path / 'bodies').glob('*.partial'))


@pytest.mark.parametrize('message', ["Unexpected Content-Type 'text/html' from Acquisition.gov.",
                                     'Acquisition.gov exceeded the redirect limit or omitted Location.'])
def test_failed_guard_refresh_preserves_verified_raw_cache(tmp_path, message):
    cache = loader.Recorder(tmp_path)
    original = response()
    cache.save(URL, loader.PDF, original)

    class Failed(loader.Fetcher):
        async def _download(self, *args, **kwargs):
            raise RuntimeError(message)

    result = asyncio.run(Failed(raw_cache=cache).fetch(URL, loader.PDF))
    assert result['error'] == message
    assert loader.Recorder(tmp_path).load(URL, loader.PDF)['body'] == original['body']


@pytest.mark.parametrize('status', [404, 410])
def test_explicit_unavailable_response_remains_truthful_offline(tmp_path, status):
    cache = loader.Recorder(tmp_path)
    cache.save(URL, loader.PDF, response())

    class Missing(loader.Fetcher):
        async def _download(self, *args, **kwargs):
            raise RuntimeError(f'Acquisition.gov returned HTTP {status}: unavailable')

    result = asyncio.run(Missing(raw_cache=cache).fetch(URL, loader.PDF))
    offline = loader.Fetcher(raw_cache=loader.Recorder(tmp_path), reparse=True)
    assert asyncio.run(offline.fetch(URL, loader.PDF)) == result
    assert offline.requests == offline.downloads == 0
    assert 'body' not in result


def test_recorded_guard_failure_is_not_an_offline_absence(tmp_path):
    cache = loader.Recorder(tmp_path)
    cache.save(URL, loader.PDF, {'url': URL, 'error': 'Unexpected Content-Type from Acquisition.gov.',
                                'transient': False, 'fetched_at': '2026-10-10T00:00:00Z'})
    offline = loader.Fetcher(raw_cache=cache, reparse=True)
    with pytest.raises(loader.Abort):
        asyncio.run(offline.fetch(URL, loader.PDF))
    assert offline.requests == offline.downloads == 0
