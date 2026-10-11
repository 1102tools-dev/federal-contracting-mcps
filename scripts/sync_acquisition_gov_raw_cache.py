"""Keep an isolated Acquisition.gov raw cache current; never parse PDFs or publish D1.

Uses the 1.0.13 loader's allowlisted, bounded, paced conditional downloader.
    python scripts/sync_acquisition_gov_raw_cache.py --raw-cache /var/lib/acquisition-gov-raw
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import asyncio
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile

import load_acquisition_gov as loader


def atomic_json(path: Path, value):
    """Replace complete JSON only, with a unique temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', suffix='.partial', delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def index_urls(result):
    parts = loader._html._parse_index(result['body'], result['final_url'])
    return sorted({d['source_url'] for p in parts for d in p['agency_deviations']})


def source_commit(root=None):
    """Read the deployed sync revision; an unmarked copy is explicitly unknown."""
    marker = (root or Path(__file__).resolve().parents[1]) / 'SOURCE_COMMIT'
    try:
        revision = marker.read_text().strip()
    except OSError:
        return None
    return revision if re.fullmatch(r'[a-f0-9]{40}', revision) else None


def cache_accounting(cache, active):
    """Count all indexed PDFs, regardless of the sample checked during this run.

    Durable absence requires a recorded origin 404/410; unverified and transient
    failures are separate, never silently represented as dead links.
    """
    cached = 0
    unavailable = []
    missing = []
    for url in sorted(active):
        entry = cache.entries.get(cache.key(url, loader.PDF))
        if entry and entry.get('sha256'):
            if (cache.path / 'bodies' / entry['sha256']).is_file():
                cached += 1
                continue
        if loader.unavailable(entry):
            unavailable.append(dict(url=url, status=int(re.search(r'HTTP (404|410)\b', entry['error']).group(1)),
                                    reason=entry['error'], checked_at=entry.get('fetched_at')))
        else:
            missing.append(dict(url=url, reason=(entry or {}).get('error', 'No recorded PDF body'),
                                checked_at=(entry or {}).get('fetched_at')))
    return dict(cached_count=cached, expected_unavailable=len(unavailable),
                unavailable_details=unavailable, missing_count=len(missing), missing_details=missing)


def archive_removed(cache, urls):
    """Archive URL metadata and its verified content before removing active references.

    Content-addressed bodies shared by surviving URLs remain active, with a copy in
    the archive. Archival is idempotent after interruption; no cache bytes are deleted.
    """
    keys = {cache.key(url, loader.PDF) for url in urls}
    survivors = {entry.get('sha256') for key, entry in cache.entries.items() if key not in keys}
    archive = loader.Recorder(cache.path / '_removed')
    results = {url: cache.load(url, loader.PDF) for url in urls}
    for url, result in results.items():
        if result is not None:
            metadata = {key: value for key, value in result.items() if key != 'body'}
            record_id = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
            atomic_json(archive.path / 'records' / (record_id + '.json'), metadata)
            archive.save(url, loader.PDF, result)
    for url in urls:
        cache.entries.pop(cache.key(url, loader.PDF), None)
    atomic_json(cache.path / 'manifest.json', cache.entries)
    for sha in {r.get('sha256') for r in results.values() if r}:
        if sha and sha not in survivors:
            # Remove references only after archive is complete; move bytes last.
            # A crash can leave harmless orphan bytes, never a broken manifest.
            os.replace(cache.path / 'bodies' / sha, archive.path / 'bodies' / sha)



@contextmanager
def mutation(cache):
    """Wait for offline readers only at a short cache commit, never during HTTP."""
    with (cache.path / '_cache.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def sync(cache, *, fetcher=None, log=print, limit=None):
    fetcher = fetcher or loader.Fetcher(raw_cache=cache, log=log)
    status = dict(finished_at=None, index_count=0, cached_count=0, added=0, changed=0, removed=0, errors=0,
                  expected_unavailable=0, error_details=[], mode='limited' if limit is not None else 'full',
                  limit=limit, checked_count=0, checked_unavailable=0, source_commit=source_commit())
    active = set()
    try:
        old_index = cache.load(loader.constants.RFO_INDEX_URL, loader.HTML)
        previous = set(index_urls(old_index)) if old_index and 'body' in old_index else set()
        state_path = cache.path / '_sync-state.json'
        if state_path.exists():
            previous = set(json.loads(state_path.read_text())['urls'])
        previous_status = cache.path / '_sync-status.json'
        if previous_status.exists():
            saved_status = json.loads(previous_status.read_text())
            previous_count = max(len(previous), int(saved_status.get('index_count', 0))
                                 if saved_status.get('mode', 'full') == 'full' else 0)
        else:
            previous_count = len(previous)
        active = previous
        status['index_count'] = len(previous)
        # Do not save a redesigned/failed index over the last usable offline index.
        index = await fetcher._fetch(loader.constants.RFO_INDEX_URL, loader.HTML)
        if 'body' not in index:
            raise RuntimeError('Index unavailable: ' + index.get('error', 'no body'))
        active = set(index_urls(index))
        status['index_count'] = len(active)
        if not active or len(active) < previous_count * 0.8:
            raise RuntimeError(f'Index shrink guard: {len(active)} PDFs versus previous {previous_count}; cache not pruned')
        resources = []
        if limit is None:
            resources += [(f'{loader.constants.RFO_INDEX_URL}/far-overhaul-part-{part}', loader.HTML, None) for part in loader.PARTS]
            resources += [(url, loader.PDF if name == 'deviation_guidance' else loader.HTML, None)
                          for name, url in loader.constants.GUIDANCE_URLS.items()]
        urls = sorted(active) if limit is None else sorted(active)[:limit]
        resources += [(url, loader.PDF, None) for url in urls]
        for number, (url, kind, fetched) in enumerate(resources, 1):
            old = cache.load(url, kind)
            if kind == loader.PDF and url in active:
                status['checked_count'] += 1
            result = fetched if fetched is not None else await fetcher._fetch(url, kind)
            if 'body' in result:
                with mutation(cache):
                    cache.save(url, kind, result)
                if kind == loader.PDF and url in active:
                    if old is None or 'body' not in old:
                        status['added'] += 1
                    elif old['sha256'] != result['sha256']:
                        status['changed'] += 1
            elif loader.unavailable(result) and (loader.unavailable(old) or
                  (kind == loader.HTML and url.endswith(('/far-overhaul-part-20', '/far-overhaul-part-21')))):
                # Already recorded 404/410s are actual absent resources, not a sync
                # failure. Retry them each night so newly posted bytes are discovered.
                with mutation(cache):
                    cache.save(url, kind, result)
                if kind == loader.PDF and url in active:
                    status['checked_unavailable'] += 1
            else:
                status['errors'] += 1
                status['error_details'].append({'url': url, 'error': result.get('error', 'no body')})
                # Preserve prior valid bytes and metadata on every failed refresh.
            if number % 25 == 0:
                log(f'{number}/{len(resources)} resources checked; {status["changed"]} changed; {status["errors"]} errors')
        if status['errors'] == 0 and limit is None:
            # Commit a new offline index only once every referenced resource was
            # checked. Limited acceptance never changes index, baseline or archive.
            removed = sorted(previous - active)
            with mutation(cache):
                archive_removed(cache, removed)
                cache.save(loader.constants.RFO_INDEX_URL, loader.HTML, index)
                atomic_json(state_path, {'urls': sorted(active)})
            status['removed'] = len(removed)
    except (loader.Abort, Exception) as exc:
        status['errors'] += 1
        status['error_details'].append({'error': str(exc)})
    finally:
        status['finished_at'] = loader.server._now()
        status.update(cache_accounting(cache, active))
        status['requests'] = fetcher.requests
        status['downloads'] = fetcher.downloads
        status['conditional_checks'] = fetcher.checks
        atomic_json(cache.path / '_sync-status.json', status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--raw-cache', required=True, type=Path)
    parser.add_argument('--limit', type=int, help='Acceptance check of at most N indexed PDFs; no pruning or index commit')
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    args.raw_cache.mkdir(parents=True, exist_ok=True)
    with (args.raw_cache / '_sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = asyncio.run(sync(loader.Recorder(args.raw_cache), limit=args.limit))
    print(json.dumps(status, indent=2, sort_keys=True))
    return 1 if status['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
