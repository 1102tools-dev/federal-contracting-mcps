import sys,sqlite3,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sam_public_cost_oracle import CostOracle
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
 def test_confirmation_requires_measured_bound(self):
  self.oracle.rehearse(["INSERT INTO hashes VALUES('entities','one','digest');"],'seed')
  with self.assertRaisesRegex(ValueError,'exceeded'):self.oracle.confirm(3)
if __name__=='__main__':unittest.main()
