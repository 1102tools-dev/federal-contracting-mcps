import sys,sqlite3,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sam_public_cost_oracle import CostOracle,amplification_exceeded
from sam_public_incremental import initialize_tracking
from unittest.mock import patch
class CostTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.path=self.base/'db.sqlite'
  db=sqlite3.connect(self.path);db.executescript('CREATE TABLE hashes(kind TEXT,record_key TEXT,hash TEXT,PRIMARY KEY(kind,record_key));CREATE TABLE records(id INTEGER PRIMARY KEY,name TEXT);CREATE INDEX names ON records(name);INSERT INTO records VALUES(1,"old");');db.close()
  self.oracle=CostOracle(self.path,self.base/'report')
 def tearDown(self):self.oracle.close();self.tmp.cleanup()
 def test_seed_counts_pk(self):
  r=self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed');self.assertEqual((r['native_total_changes'],r['index_entry_operations'],r['conservative_units']),(1,1,2))
 def test_update_index_delete_and_insert(self):
  r=self.oracle.rehearse(["UPDATE records SET name='new' WHERE id=1;"],'update');self.assertEqual(r['conservative_units'],3)
 def test_ddl_does_not_reuse_changes(self):
  r=self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');",'DROP INDEX names;'],'drop');self.assertEqual(r['native_total_changes'],1);self.assertEqual(r['ddl_entry_reservation'],2)
 def test_round_strict_boundary(self):
  self.oracle.round_limit=2
  with self.assertRaisesRegex(ValueError,'exceeds cap'):self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed')
 def test_step_equal_allowed(self):
  r=self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed',2);self.assertEqual(r['conservative_units'],2)
 def test_restart_does_not_reset(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed')
  with self.assertRaisesRegex(ValueError,'already exists'):CostOracle(self.path,self.base/'report')
 def test_unknown_sql_refused(self):
  with self.assertRaisesRegex(ValueError,'Unsupported'):self.oracle.rehearse(["REPLACE INTO hashes VALUES('entities','one','digest');"],'replace')
 def test_unknown_remote_blocks_next(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed');self.oracle.invalidate()
  with self.assertRaisesRegex(ValueError,'divergent'):self.oracle.rehearse(['DROP INDEX names;'],'drop')
 def test_initialization_seeds_only_sidecar_without_public_rewrites(self):
  self.oracle.db.executescript("CREATE TABLE entities(entity_id TEXT PRIMARY KEY,uei TEXT,cage_code TEXT);INSERT INTO entities VALUES('hash','UEI','CAGE');CREATE TABLE exclusions(exclusion_id TEXT PRIMARY KEY,name TEXT);INSERT INTO exclusions VALUES('SAM1','Example');")
  reports=initialize_tracking(None,self.oracle)
  self.assertEqual([r['conservative_units'] for r in reports],[8,2,2])
  self.assertEqual(self.oracle.db.execute('SELECT COUNT(*) FROM public_record_hashes').fetchone()[0],2)
  sql=(self.base/'report'/'exact-statements.sql').read_text()
  self.assertNotIn('ALTER TABLE',sql);self.assertNotIn('UPDATE entities',sql);self.assertNotIn('UPDATE exclusions',sql)
 def test_catalog_recovery_preserves_twelve_consumed_units(self):
  from sam_public_incremental import RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL
  self.oracle.db.executescript('CREATE TABLE entities(entity_id TEXT PRIMARY KEY);CREATE TABLE exclusions(exclusion_id TEXT PRIMARY KEY);CREATE TABLE entity_naics(entity_id TEXT,code TEXT);CREATE TABLE entity_business_types(entity_id TEXT,code TEXT,kind TEXT);CREATE TABLE extract_status(kind TEXT);')
  report=self.oracle.rehearse([RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL],'sidecar-and-journal-schema')
  report['cloudflare_started_at']='2026-10-11T10:30:38+00:00';report['cloudflare_ended_at']='2026-10-11T10:30:40+00:00'
  self.oracle.confirm(12);self.oracle.invalidate()
  self.oracle.db.row_factory=sqlite3.Row
  tables=['entities','exclusions','entity_naics','entity_business_types','public_record_hashes','public_refresh_runs','public_write_budget','public_daily_budget']
  proof={'counts':{t:0 for t in tables},'tables':[dict(r) for r in self.oracle.db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name LIKE 'public_%' ORDER BY name")],'extract_status':[],'leftovers':[],'indexes':[dict(r) for r in self.oracle.db.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('entities','exclusions','entity_naics','entity_business_types') ORDER BY name")]}
  pp=self.base/'proof.json';ap=self.base/'analytics.json';pp.write_text(json.dumps(proof));ap.write_text(json.dumps([{'dimensions':{'datetime':'2026-10-11T10:30:39Z'},'sum':{'rowsWritten':12}}]))
  recovered=CostOracle.resume_catalog_reconciliation(self.path,self.base/'report',pp,ap)
  try:
   self.assertEqual(recovered.total,12);self.assertFalse(recovered.diverged)
   self.assertEqual(recovered.steps[0]['conservative_units'],8)
   self.assertEqual(recovered.steps[0]['measured_provider_catalog_overhead'],4)
  finally:recovered.close()
 def test_amplification_strict_boundaries(self):
  self.assertFalse(amplification_exceeded(1200000,1000000))
  self.assertFalse(amplification_exceeded(200000,100000))
  self.assertFalse(amplification_exceeded(1200001,1100000))
  self.assertTrue(amplification_exceeded(1200001,1000000))
 def test_actual_round_five_million_exact_allowed_then_one_refused(self):
  self.oracle.actual_total=4999998
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed');self.oracle.confirm(2)
  self.assertEqual(self.oracle.actual_total,5000000)
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','two','digest');"],'seed2')
  with self.assertRaises(ValueError):self.oracle.confirm(1)
 def test_partial_batches_persist_without_confirm_double_count(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed')
  self.oracle.note_remote_batch(1);self.oracle.note_remote_batch(1)
  self.assertEqual(json.loads((self.base/'report'/'local-cost-report.json').read_text())['actual_round_units'],2)
  self.oracle.confirm(2);self.assertEqual(self.oracle.actual_total,2)
  self.oracle.confirm_analytics(3);self.assertEqual(self.oracle.actual_total,3)
  self.assertEqual(self.oracle.steps[-1]['actual_rows_written'],2)
  self.assertEqual(self.oracle.steps[-1]['graphql_rows_written'],3)
 def test_pending_analytics_blocks_next_rehearsal_until_confirmed(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed');self.oracle.confirm(2);self.oracle.mark_graphql_pending()
  with self.assertRaisesRegex(ValueError,'unconfirmed'):self.oracle.rehearse(['DROP INDEX names;'],'drop')
  self.oracle.confirm_analytics(2)
  self.assertFalse(self.oracle.steps[-1]['graphql_pending']);self.oracle.rehearse(['DROP INDEX names;'],'drop')
 def test_regenerated_completed_sql_mismatch_refused(self):
  self.oracle.db.executescript("CREATE TABLE entities(entity_id TEXT PRIMARY KEY);CREATE TABLE exclusions(exclusion_id TEXT PRIMARY KEY);")
  self.oracle.steps=[{'label':'sidecar-and-journal-schema','remote_outcome':'confirmed','sql_sha256':'wrong'}]
  with self.assertRaisesRegex(ValueError,'regenerated SQL differs'):initialize_tracking(None,self.oracle)
 def test_confirmation_requires_measured_bound(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed')
  with self.assertRaisesRegex(ValueError,'exceeded'):self.oracle.confirm(100003)
if __name__=='__main__':unittest.main()
