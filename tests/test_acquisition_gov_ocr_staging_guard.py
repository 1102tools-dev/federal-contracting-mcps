"""Experimental OCR validates staged rows and always stops before promotion."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('ocr_load_check', Path(__file__).resolve().parents[1] / 'scripts/check_acquisition_gov_ocr_load.py')
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

URLS = ('https://example.test/GSA_RFO_Deviation_Part-8_Supplement-1.pdf',
        'https://example.test/GSA_RFO_FSS-Ordering-Procedures_538.pdf',
        'https://example.test/NASA_RFO_Deviation_Part-39.pdf')
TEXT = 'Required Use is mandatory. Head of the contracting activity. recovered with OCR'


@pytest.mark.parametrize('page_text,failure,event_hash,accepted', [
    (TEXT, None, 'sha', True),
    ('fragmented text', None, 'sha', False),
    (TEXT, 'Outlined text recovery failed', 'sha', False),
    (TEXT, None, 'different-document', False),
])
def test_validation_always_aborts_without_changing_current_or_calling_switch(tmp_path, monkeypatch,
                                                                           page_text, failure, event_hash, accepted):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
                       INSERT INTO meta VALUES ('current','9');
                       CREATE TABLE sources(snapshot INTEGER,key TEXT,doc TEXT,error TEXT,content_sha256 TEXT);
                       CREATE TABLE pages(doc TEXT,page INTEGER,seq INTEGER,failure TEXT,body TEXT);''')
    db.executemany('INSERT INTO sources VALUES (8,?,?,NULL,?)', [('pdf:' + url, 'candidate:sha', 'sha') for url in URLS])
    db.execute('INSERT INTO pages VALUES (?,2,0,?,?)', ('candidate:sha', failure, page_text))
    metrics = tmp_path / 'ocr-pages.jsonl'
    metrics.write_text(json.dumps(dict(source_url=URLS[0], sha256=event_hash, page=2,
                                      outcome='recovered', required_use=True)) + '\n')
    monkeypatch.setenv('ACQUISITION_OCR_METRICS', str(metrics))
    switch_calls = []

    class Abort(SystemExit):
        pass

    class Loader:
        def switch(self, *args):
            switch_calls.append(args)
            db.execute("UPDATE meta SET value='8' WHERE key='current'")
            raise AssertionError('The production switch must never be called')

    import os
    namespace = dict(Loader=Loader, Abort=Abort, json=json, os=os, Path=Path, time=time,
                     PARSER_VERSION='isolated-candidate', doc_id=lambda *_: 'candidate:sha')
    exec(check.PRE_SWITCH, namespace)
    loader = Loader()
    loader.revalidate_urls = URLS
    loader.counts = {'forced_rechecks': 3}
    loader.now = lambda: '2026-10-11T06:20:00+00:00'
    loader.db = SimpleNamespace(query=lambda sql, params: [dict(row) for row in db.execute(sql, params)])
    loader.fetcher = SimpleNamespace(requests=3, downloads=3, checks=0, bytes=100)
    with pytest.raises(Abort, match='current snapshot unchanged'):
        loader.switch(9, 8, time.monotonic(), 1401)
    guard = json.loads(metrics.with_name('pre-switch.json').read_text())
    assert guard['acceptance_passed'] is accepted
    assert guard['promoted'] is False
    assert guard['staging_snapshot'] == 8 and guard['prior_current'] == 9
    assert guard['loader_stats']['forced_rechecks'] == 3
    assert not switch_calls
    assert db.execute("SELECT value FROM meta WHERE key='current'").fetchone()[0] == '9'


def test_experimental_setup_never_registers_or_reuses_production_staging(tmp_path):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript("""CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
                       INSERT INTO meta VALUES ('current','9'), ('staging','10');
                       CREATE TABLE snapshots(id INTEGER PRIMARY KEY,started_at TEXT);
                       INSERT INTO snapshots VALUES (9,'trusted'),(10,'nightly');""")
    schema = tmp_path / 'schema.sql'
    schema.write_text('SELECT 1;')

    class Loader:
        def switch(self, *args):
            raise AssertionError('no production promotion')

    def execute(statements):
        for statement in statements:
            db.execute(statement)

    def inserts(table, columns, rows):
        return [f"INSERT INTO {table}({','.join(columns)}) VALUES ({row[0]},'{row[1]}');" for row in rows]

    namespace = dict(Loader=Loader, WORKER_DIR=tmp_path, inserts=inserts)
    exec(check.PRE_SWITCH, namespace)
    loader = Loader()
    loader.meta = lambda: {row['key']: row['value'] for row in db.execute('SELECT * FROM meta')}
    loader.db = SimpleNamespace(execute=execute, query=lambda sql: [dict(row) for row in db.execute(sql)])
    loader.now = lambda: 'validation'
    assert loader.setup() == (9, 11)
    assert loader.meta() == {'current': '9', 'staging': '10'}
    assert db.execute('SELECT started_at FROM snapshots WHERE id=10').fetchone()[0] == 'nightly'
