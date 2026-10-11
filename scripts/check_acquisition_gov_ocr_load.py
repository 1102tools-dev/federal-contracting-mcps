"""CI-only experimental OCR check using the existing nightly loader and D1 shape.

Temporarily installs an immutable parser candidate into the runner checkout, uses
an isolated parsed-document namespace, validates a staged ordinary incremental load without promotion, and
restores every source file. Never use this wrapper on the Dell or for a release.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = '4075fe6ab4f4bdb085068903a8f198d66288c127'
PACKAGE = ROOT / 'servers/acquisition-gov-mcp/src/acquisition_gov_mcp'

INSTRUMENT = r'''

# CI-only instrumentation; never part of the released parser.
_original_ocr_check = _ocr_outlined_page

def _ocr_outlined_page(body, page_number, *, timeout):
    import hashlib, json, os, sys, time
    started = time.monotonic()
    event = {'page': page_number, 'sha256': hashlib.sha256(body).hexdigest(),
             'timeout': timeout, 'outcome': 'error'}
    if '--parse-worker' in sys.argv:
        arguments = json.loads(sys.argv[sys.argv.index('--parse-worker') + 2])
        event['source_url'] = arguments.get('source_url')
    try:
        result = _original_ocr_check(body, page_number, timeout=timeout)
        event.update(outcome='recovered', characters=len(result),
                     required_use='required use' in result.casefold())
        return result
    except Exception as exc:
        event['error_type'] = type(exc).__name__
        raise
    finally:
        event['seconds'] = round(time.monotonic() - started, 6)
        with open(os.environ['ACQUISITION_OCR_METRICS'], 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(event, sort_keys=True) + '\n')
'''


PRE_SWITCH = r'''

# CI-only staging guard. Never register a resumable production staging snapshot
# and never call the production promotion method, including on successful OCR.
def _ocr_check_setup(self):
    self.db.execute([(WORKER_DIR / "schema.sql").read_text()])
    meta = self.meta()
    current = int(meta["current"]) if "current" in meta else None
    staging = max([current or 0] + [row["id"] for row in self.db.query("SELECT id FROM snapshots")]) + 1
    self.db.execute(inserts("snapshots", ["id", "started_at"], [[staging, self.now()]]))
    self.generation = None
    return current, staging

Loader.setup = _ocr_check_setup

def _ocr_check_switch(self, current, staging, started, pdfs):
    events = [json.loads(line) for line in Path(os.environ['ACQUISITION_OCR_METRICS']).read_text().splitlines() if line]
    failures = []
    forced = tuple(self.revalidate_urls)
    if len(forced) != 3 or self.counts.get('forced_rechecks') != 3:
        failures.append('All three affected PDFs must be rechecked')
    for url in forced:
        rows = self.db.query('SELECT doc,error,content_sha256 FROM sources WHERE snapshot=? AND key=?', [staging, 'pdf:' + url])
        if len(rows) != 1 or rows[0]['error'] or not rows[0]['doc']:
            failures.append('Forced source was not parsed: ' + url)
            continue
        row = rows[0]
        if row['doc'] != doc_id('pdf', row['content_sha256']):
            failures.append('Forced source reused another parser namespace: ' + url)
        if url.endswith('/GSA_RFO_Deviation_Part-8_Supplement-1.pdf'):
            pages = self.db.query('SELECT failure,body FROM pages WHERE doc=? AND page=2 ORDER BY seq', [row['doc']])
            text = '\n'.join(page['body'] or '' for page in pages)
            recovered = any(event.get('source_url') == url and event.get('sha256') == row['content_sha256'] and
                            event['page'] == 2 and event['outcome'] == 'recovered' and event.get('required_use') for event in events)
            normalized = ' '.join(text.casefold().split())
            if not recovered or not pages or any(page['failure'] for page in pages) or 'required use' not in normalized or 'mandatory' not in normalized or not ('head of the contracting activity' in normalized or 'hca' in normalized) or 'recovered with OCR' not in text:
                failures.append('GSA supplement page 2 must recover and store Required Use wording')
    if not any(url.endswith('/GSA_RFO_Deviation_Part-8_Supplement-1.pdf') for url in forced):
        failures.append('GSA supplement must be one of the forced sources')
    stats = {'snapshot': staging, 'pdfs': pdfs, 'seconds': round(time.monotonic() - started, 1),
             'requests': self.fetcher.requests, 'downloads': self.fetcher.downloads,
             'conditional_checks': self.fetcher.checks, 'bytes': self.fetcher.bytes,
             'parser_version': PARSER_VERSION, **self.counts}
    guard = {'staging_snapshot': staging, 'prior_current': current, 'acceptance_passed': not failures,
             'failures': failures, 'promoted': False, 'validated_at': self.now(), 'loader_stats': stats}
    Path(os.environ['ACQUISITION_OCR_METRICS']).with_name('pre-switch.json').write_text(json.dumps(guard, indent=2) + '\n')
    if failures:
        raise Abort('Experimental OCR did not pass; current snapshot unchanged: ' + '; '.join(failures))
    raise Abort('Experimental staging validation passed; promotion is disabled; current snapshot unchanged.')

Loader.switch = _ocr_check_switch
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-commit', default=CANDIDATE)
    parser.add_argument('--revalidate-url', action='append', required=True)
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        parser.error('This staging validation runs on a GitHub Actions main-branch runner only.')
    if args.candidate_commit != CANDIDATE:
        parser.error('Only the reviewed immutable experimental candidate is allowed.')
    if not (os.environ.get('CLOUDFLARE_D1_TOKEN') or os.environ.get('CLOUDFLARE_API_TOKEN')):
        parser.error('Existing D1 credential is required in the runner environment.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metrics = output / 'ocr-pages.jsonl'
    metrics.write_text('')
    guard_path = metrics.with_name('pre-switch.json')
    guard_path.unlink(missing_ok=True)
    pdf_path, constants_path = PACKAGE / '_pdf.py', PACKAGE / 'constants.py'
    loader_path = ROOT / 'scripts/load_acquisition_gov.py'
    paths = (pdf_path, constants_path, loader_path)
    originals = {path: path.read_bytes() for path in paths}
    candidate = subprocess.check_output(['git', 'show', f'{CANDIDATE}:{pdf_path.relative_to(ROOT)}'], cwd=ROOT)
    candidate_hash = hashlib.sha256(candidate).hexdigest()
    loader_source = originals[loader_path].decode()
    namespace = f'ocr-validation:{CANDIDATE}:{os.environ.get("GITHUB_RUN_ID", "unknown")}:{os.environ.get("GITHUB_RUN_ATTEMPT", "1")}'
    loader_source, replacements = re.subn(r'^(PARSER_VERSION\s*=.*)$',
                                         lambda match: match[1] + f' + {namespace!r}', loader_source, count=1, flags=re.M)
    if replacements != 1:
        raise RuntimeError('Cannot isolate the experimental parsed-document namespace.')
    entry = '\nif __name__ == \"__main__\":'
    if loader_source.count(entry) != 1:
        raise RuntimeError('Cannot install the pre-promotion experimental acceptance guard.')
    loader_source = loader_source.replace(entry, PRE_SWITCH + entry, 1)
    env = dict(os.environ, ACQUISITION_OCR_METRICS=str(metrics))
    command = [sys.executable, str(loader_path), '--remote', '--revalidate', '100']
    for url in args.revalidate_url:
        command += ['--revalidate-url', url]
    started = time.monotonic()
    versions = {}
    for distribution in ('rapidocr', 'onnxruntime', 'pypdfium2'):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = None
    receipt = dict(dependency_versions=versions, candidate_commit=CANDIDATE, candidate_pdf_sha256=candidate_hash,
                   parsed_namespace=namespace, forced_urls=args.revalidate_url,
                   mode='staging-only normal incremental loader: 100 rechecks plus forced affected PDFs',
                   full_reload=False, promoted=False, source_files_restored=False)
    exit_code = 1
    try:
        pdf_path.write_bytes(candidate + INSTRUMENT.encode())
        constants_path.write_bytes(originals[constants_path] + b'\nMAX_PDF_OCR_MEMORY_BYTES = 2 * 1024 * 1024 * 1024\n')
        loader_path.write_text(loader_source)
        with (output / 'loader-status.json').open('w') as status:
            exit_code = subprocess.run(command, cwd=ROOT, env=env, stdout=status).returncode
        receipt['loader_exit_code'] = exit_code
        if not guard_path.exists():
            raise RuntimeError('Loader did not reach the staged validation guard.')
        guard = json.loads(guard_path.read_text())
        receipt['staged_validation'] = guard
        receipt['loader_stats'] = guard['loader_stats']
        if not guard['acceptance_passed'] or guard['promoted'] or exit_code != 1:
            raise RuntimeError('Staged validation failed or loader did not stop before promotion.')
        exit_code = 0
        if guard['acceptance_passed']:
            # Read staging only. Production current must remain the prior snapshot.
            sys.path.insert(0, str(ROOT / 'scripts'))
            import load_acquisition_gov as loader
            token = env.get('CLOUDFLARE_D1_TOKEN') or env.get('CLOUDFLARE_API_TOKEN')
            db = loader.RemoteD1(loader.database_id(None), token)
            current = db.query("SELECT value FROM meta WHERE key='current'")[0]['value']
            receipt['current_snapshot'] = current
            receipt['current_unchanged'] = str(current) == str(guard['prior_current'])
            if not receipt['current_unchanged']:
                raise RuntimeError('Production current changed during the staging-only experiment.')
            staging = guard['staging_snapshot']
            receipt['staging_snapshot'] = staging
            documents = []
            for url in args.revalidate_url:
                rows = db.query('SELECT s.doc,s.error,s.content_sha256,s.retrieved_at,d.info FROM sources s LEFT JOIN docs d ON d.id=s.doc WHERE s.snapshot=? AND s.key=?', [staging, 'pdf:' + url])
                if len(rows) != 1:
                    raise RuntimeError('Forced source absent from staged snapshot: ' + url)
                row = rows[0]
                if row['error'] or not row['doc']:
                    raise RuntimeError('Forced source was not parsed into the staged snapshot: ' + url)
                if row['doc'] != loader.doc_id('pdf', row['content_sha256']):
                    raise RuntimeError('Forced source reused a different parser namespace: ' + url)
                pages = db.query('SELECT page,failure,body FROM pages WHERE doc=? ORDER BY page,seq', [row['doc']]) if row['doc'] else []
                text = '\n'.join(page['body'] or '' for page in pages)
                page2 = [page for page in pages if page['page'] == 2]
                page2_text = ' '.join(' '.join(page['body'] or '' for page in page2).casefold().split())
                documents.append(dict(url=url, **row, page_rows=len(pages),
                                      failed_pages=sorted({page['page'] for page in pages if page['failure']}),
                                      ocr_notice='recovered with OCR' in text,
                                      required_use='required use' in text.casefold(),
                                      page2_failed=not page2 or any(page['failure'] for page in page2),
                                      page2_required_use='required use' in page2_text,
                                      page2_mandatory='mandatory' in page2_text,
                                      page2_hca='head of the contracting activity' in page2_text or 'hca' in page2_text,
                                      page2_ocr_notice='recovered with ocr' in page2_text))
            receipt['stored_forced_documents'] = documents
    except Exception as exc:
        receipt['validation_error'] = f'{type(exc).__name__}: {exc}'
        exit_code = 1
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
        receipt['source_files_restored'] = all(path.read_bytes() == original for path, original in originals.items())
        events = [json.loads(line) for line in metrics.read_text().splitlines() if line]
        receipt['ocr_events'] = events
        if exit_code == 0:
            supplement = next((doc for doc in receipt.get('stored_forced_documents', [])
                               if doc['url'].endswith('/GSA_RFO_Deviation_Part-8_Supplement-1.pdf')), None)
            recovered = any(event.get('source_url') == (supplement or {}).get('url') and
                            event['page'] == 2 and event['outcome'] == 'recovered' and event.get('required_use')
                            for event in events)
            gate = bool(receipt.get('current_unchanged') and not receipt['promoted'] and supplement and recovered and not supplement['page2_failed']
                        and supplement['page2_required_use'] and supplement['page2_mandatory']
                        and supplement['page2_hca'] and supplement['page2_ocr_notice']
                        and receipt.get('loader_stats', {}).get('forced_rechecks') == len(set(args.revalidate_url))
                        and all(not doc['error'] for doc in receipt.get('stored_forced_documents', [])))
            receipt['acceptance_passed'] = gate
            if not gate:
                receipt['validation_error'] = 'Experimental OCR acceptance failed: GSA page 2 and stored Required Use wording must both be recovered, and all forced sources must be checked without source errors.'
                exit_code = 1
        receipt['ocr_seconds'] = round(sum(event['seconds'] for event in events), 3)
        receipt['ocr_recovered_pages'] = sum(event['outcome'] == 'recovered' for event in events)
        receipt['ocr_attempt_failed_pages'] = sum(event['outcome'] != 'recovered' for event in events)
        receipt['forced_document_unrecovered_pages'] = [
            {'url': doc['url'], 'pages': doc['failed_pages']}
            for doc in receipt.get('stored_forced_documents', []) if doc['failed_pages']
        ]
        receipt['total_seconds'] = round(time.monotonic() - started, 3)
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
