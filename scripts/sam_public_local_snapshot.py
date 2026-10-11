"""Assemble the approved full public production baseline locally, without D1 writes."""
import hashlib,json,shutil,sqlite3
from pathlib import Path
from load_sam_public import ENTITY_FIELDS,EXCLUSION_FIELDS,STATUS_SQL
from sam_public_incremental import digest,HASH_SQL,prune_candidates

def assemble(entity_path,exclusion_path,proof_path,destination):
 proof=json.loads(Path(proof_path).read_text());destination=Path(destination)
 if destination.exists():raise ValueError('Snapshot already exists; preserve it')
 shutil.copy2(entity_path,destination)
 db=sqlite3.connect(destination);db.row_factory=sqlite3.Row
 try:
  db.execute('ATTACH DATABASE ? AS source',(str(exclusion_path),))
  schema=db.execute("SELECT sql FROM source.sqlite_master WHERE type='table' AND name='exclusions'").fetchone()[0]
  db.execute(schema);db.execute('INSERT INTO exclusions SELECT * FROM source.exclusions');db.commit();db.execute('DETACH DATABASE source')
  for row in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall():db.execute('DROP INDEX '+row['name'])
  for row in proof['indexes']:
   if row['sql']:db.execute(row['sql'])
  db.executescript(STATUS_SQL)
  for status in proof['extract_status']:
   db.execute(f"INSERT OR REPLACE INTO extract_status ({','.join(status)}) VALUES ({','.join('?' for _ in status)})",list(status.values()))
  db.commit()
  actual={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in proof['counts']}
  if actual!=proof['counts']:raise ValueError('Canonical checkpoint counts differ from production proof')
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Local production snapshot failed integrity check')
  hashes={}
  for table,fields in [('entities',ENTITY_FIELDS),('exclusions',EXCLUSION_FIELDS)]:
   stream=hashlib.sha256()
   for row in db.execute('SELECT * FROM '+table+' ORDER BY '+fields[0]):stream.update((digest(dict(row),fields)+'\n').encode())
   hashes[table]=stream.hexdigest()
  report=dict(counts=actual,normalized_record_stream_sha256=hashes,extract_status=proof['extract_status'],indexes=proof['indexes'],source_proof=str(proof_path),snapshot_path=str(destination.resolve()))
  destination.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
  return report
 finally:db.close()

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('entity_path');p.add_argument('exclusion_path');p.add_argument('proof_path');p.add_argument('destination');args=p.parse_args()
 print(json.dumps(assemble(**vars(args)),indent=2))
