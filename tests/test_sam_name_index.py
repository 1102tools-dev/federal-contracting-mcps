import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_sam_name_index as name_index

ROOT = Path(__file__).resolve().parents[1]


class FakeD1:
    """D1-shaped sqlite: query() reads, api() runs one atomic batch."""
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.row_factory = sqlite3.Row

    def query(self, sql):
        return [dict(r) for r in self.db.execute(sql)]

    def api(self, payload):
        before = self.db.total_changes
        self.db.execute('BEGIN')
        try:
            for statement in payload['sql'].split(';\n'):
                if statement.strip():
                    self.db.execute(statement)
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        return [{'meta': {'rows_written': self.db.total_changes - before}}]


def source_db():
    d1 = FakeD1()
    d1.db.executescript("""
      CREATE TABLE entities (entity_id TEXT PRIMARY KEY, legal_business_name TEXT, dba_name TEXT);
      CREATE TABLE exclusions (exclusion_id TEXT PRIMARY KEY, name TEXT, first_name TEXT, middle_name TEXT, last_name TEXT);
      CREATE TABLE extract_status (kind TEXT PRIMARY KEY, sha256 TEXT, loaded_at TEXT);
      CREATE TABLE public_refresh_runs (kind TEXT PRIMARY KEY, state TEXT);
      INSERT INTO entities VALUES ('e1','Booz Allen Hamilton Inc.',NULL),('e2','Acme Widgets LLC','Acme Federal'),('e3','Leidos, Inc.','');
      INSERT INTO exclusions VALUES ('x1',NULL,'John','Q','Smith'),('x2','Bad Actor Corp',NULL,NULL,NULL);
      INSERT INTO extract_status VALUES ('entities','sha-e1','2026-10-12T00:00:00Z'),('exclusions','sha-x1','2026-10-12T00:00:00Z');
    """)
    return d1


def index_db():
    d1 = FakeD1()
    schema = (ROOT / 'deploy/sam-gov/name-index-schema.sql').read_text()
    d1.db.executescript('\n'.join(l for l in schema.splitlines() if not l.startswith('--')))
    return d1


def match(index, kind, query):
    grams = {query[i:i + 3] for i in range(len(query) - 2)}
    where = ' AND '.join(f'"{g}"' for g in grams)
    return sorted(r['rowid'] for r in index.query(f"SELECT rowid FROM {kind}_name_index WHERE {kind}_name_index MATCH '{where}'"))


class NameIndex(unittest.TestCase):
    def test_compact_matches_worker_normalization(self):
        for raw, expected in json.loads((ROOT / 'tests/fixtures/sam_public/name_compact.json').read_text()):
            self.assertEqual(name_index.compact(raw), expected, raw)

    def test_first_build_then_current_then_changes_only(self):
        source, index = source_db(), index_db()
        first = name_index.sync(source, index, 'entities', 10_000, 0, 0, account=0)
        self.assertTrue(first['current'])
        self.assertEqual((first['added'], first['changed'], first['removed']), (3, 0, 0))
        self.assertEqual(match(index, 'entities', 'allenham'), [1])
        self.assertEqual(match(index, 'entities', 'mefeder'), [2])  # matches the dba column
        self.assertEqual(name_index.sync(source, index, 'entities', 10_000, 0, 0, account=0)['skipped'], 'index current')
        source.db.executescript("UPDATE entities SET legal_business_name='Leidos Holdings' WHERE entity_id='e3'; DELETE FROM entities WHERE entity_id='e1'; UPDATE extract_status SET sha256='sha-e2' WHERE kind='entities';")
        second = name_index.sync(source, index, 'entities', 10_000, 0, 0, account=0)
        self.assertEqual((second['added'], second['changed'], second['removed']), (0, 1, 1))
        self.assertEqual(match(index, 'entities', 'allenham'), [])
        self.assertEqual(match(index, 'entities', 'dosholdin'), [3])
        self.assertEqual(index.query("SELECT source_sha FROM name_index_status WHERE kind='entities'")[0]['source_sha'], 'sha-e2')

    def test_exclusion_person_names_are_indexed(self):
        source, index = source_db(), index_db()
        self.assertTrue(name_index.sync(source, index, 'exclusions', 10_000, 0, 0, account=0)['current'])
        self.assertEqual(match(index, 'exclusions', 'johnqsmith'), [1])
        self.assertEqual(match(index, 'exclusions', 'johnsmith'), [1])
        self.assertEqual(match(index, 'exclusions', 'badactor'), [2])

    def test_large_sync_waits_for_billing_ceiling_unless_explicitly_paid(self):
        source, index = source_db(), index_db()
        original = name_index.SMALL_SYNC_ROWS
        name_index.SMALL_SYNC_ROWS = 1
        try:
            waiting = name_index.sync(source, index, 'entities', 10_000, 0, 0, account=name_index.MONTHLY_CEILING)
            self.assertIn('waiting', waiting['skipped'])
            self.assertEqual(index.query('SELECT count(*) AS n FROM name_index_keys')[0]['n'], 0)
            self.assertTrue(name_index.sync(source, index, 'entities', 10_000, 100, 0, account=name_index.MONTHLY_CEILING)['current'])
        finally:
            name_index.SMALL_SYNC_ROWS = original

    def test_hard_cap_writes_nothing_and_refreshing_source_is_skipped(self):
        source, index = source_db(), index_db()
        with self.assertRaisesRegex(RuntimeError, 'hard cap'):
            name_index.sync(source, index, 'entities', 5, 0, 0, account=0)
        self.assertEqual(index.query('SELECT count(*) AS n FROM name_index_keys')[0]['n'], 0)
        source.db.execute("INSERT INTO public_refresh_runs VALUES ('entities','applying')")
        self.assertIn('refreshing', name_index.sync(source, index, 'entities', 10_000, 0, 0, account=0)['skipped'])


if __name__ == '__main__':
    unittest.main()
