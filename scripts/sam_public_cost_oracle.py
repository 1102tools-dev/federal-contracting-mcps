"""Rehearse exact public-loader SQL on a full local SQLite production copy.

SQLite total_changes excludes ordinary-index mutations and DROP entry removals.
Reports keep those costs separate, then conservatively include both in the cap.
No network access; no credential handling.
"""
import json
import hashlib
from pathlib import Path
import re
import sqlite3

STEP_LIMIT=None
ROUND_LIMIT=5_000_000

def amplification_exceeded(actual,local):
    return actual-local>100000 and actual*5>local*6


class CostOracle:
    def __init__(self,snapshot_path,report_directory,round_limit=ROUND_LIMIT):
        self.db=sqlite3.connect(snapshot_path)
        self.directory=Path(report_directory)
        if (self.directory/'local-cost-report.json').exists():
            raise ValueError('Oracle round already exists; refusing to reset reservations')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.pending=False;self.diverged=False
        self.round_limit=round_limit;self.total=0;self.actual_total=0;self.steps=[]
        objects=self.db.execute("SELECT type,sql FROM sqlite_master WHERE type='trigger' OR sql LIKE 'CREATE VIRTUAL TABLE%'").fetchall()
        if objects:raise ValueError('Oracle does not support triggers or virtual tables')
    @classmethod
    def resume_catalog_reconciliation(cls,snapshot_path,report_directory,proof_path,analytics_path):
        """Resume this acknowledged catalog-only exception without resetting cost.

        This deliberately accepts only the observed four-table initialization,
        not an arbitrary DML amplification or an unknown transport outcome.
        """
        from sam_public_incremental import RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL
        import datetime as dt
        directory=Path(report_directory);saved=json.loads((directory/'local-cost-report.json').read_text())
        proof=json.loads(Path(proof_path).read_text());events=json.loads(Path(analytics_path).read_text())
        if len(saved['steps'])!=1:raise ValueError('Catalog recovery requires the original single stopped operation')
        step=saved['steps'][0]
        expected=hashlib.sha256(('\n'.join([RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL])+'\n').encode()).hexdigest()
        if step.get('sql_sha256')!=expected or step['label']!='sidecar-and-journal-schema' or step['conservative_units']!=8 or step.get('actual_rows_written')!=12:
            raise ValueError('Stopped catalog operation differs from measured recovery case')
        start=dt.datetime.fromisoformat(step['cloudflare_started_at']);end=dt.datetime.fromisoformat(step['cloudflare_ended_at'])
        if not events or any(not start<=dt.datetime.fromisoformat(e['dimensions']['datetime'].replace('Z','+00:00'))<end for e in events) or sum(e['sum']['rowsWritten'] for e in events)!=12:
            raise ValueError('Catalog GraphQL event does not reconcile the original window')
        obj=cls.__new__(cls);obj.db=sqlite3.connect(snapshot_path);obj.db.row_factory=sqlite3.Row
        obj.directory=directory;obj.round_limit=ROUND_LIMIT;obj.steps=saved['steps'];obj.pending=False;obj.diverged=False
        try:
            required={'entities','exclusions','entity_naics','entity_business_types','public_record_hashes','public_refresh_runs','public_write_budget','public_daily_budget'}
            if not required<=set(proof['counts']):raise ValueError('Recovery proof lacks complete public counts')
            for table,count in proof['counts'].items():
                if obj.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]!=count:raise ValueError('Recovery counts differ from local acknowledged copy')
            for table in ['public_record_hashes','public_refresh_runs','public_write_budget','public_daily_budget']:
                if proof['counts'][table]!=0:raise ValueError('Recovery cannot accept already seeded tracking tables')
            local_tables=[dict(r) for r in obj.db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name LIKE 'public_%' ORDER BY name")]
            if local_tables!=proof['tables']:raise ValueError('Recovery auxiliary schemas differ')
            if [dict(r) for r in obj.db.execute('SELECT * FROM extract_status ORDER BY kind')]!=proof['extract_status']:raise ValueError('Recovery source metadata differs')
            local_indexes=[dict(r) for r in obj.db.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('entities','exclusions','entity_naics','entity_business_types') ORDER BY name")]
            if local_indexes!=proof['indexes'] or proof['leftovers']:raise ValueError('Recovery public indexes or leftovers differ')
            step['measured_provider_catalog_overhead']=4;step['remote_outcome']='confirmed catalog-only exception by read-only reconciliation'
            step['round_units']=12;obj.total=12;obj.actual_total=12
            obj._save()
            (directory/'catalog-reconciliation.json').write_text(json.dumps({'original_local_units':8,'measured_provider_catalog_overhead':4,'consumed_round_units':12,'original_sql_sha256':expected,'proof_path':str(proof_path),'analytics_path':str(analytics_path),'public_record_dml_submitted':False,'remote_record_digest_comparison_claimed':False},indent=2)+'\n')
            return obj
        except BaseException:obj.db.close();raise
    def close(self):self.db.close()
    def indexes(self,table):
        result=[]
        for index in self.db.execute(f'PRAGMA index_list({table})'):
            name=index[1]
            if index[4]:raise ValueError('Oracle does not support partial indexes')
            columns=[r[2] for r in self.db.execute(f'PRAGMA index_info({name})')]
            if None in columns:raise ValueError('Oracle does not support expression indexes')
            result.append(set(columns))
        return result
    def rehearse(self,statements,label,step_limit=STEP_LIMIT):
        if self.pending or self.diverged:
            raise ValueError('Oracle has an unconfirmed or divergent remote operation; reconcile before reuse')
        native=index_units=ddl_units=replace_units=0
        sql='\n'.join(statements)+'\n'
        self.db.execute('BEGIN')
        try:
            for statement in statements:
                text=statement.strip()
                if not re.match(r'^(INSERT(?: OR REPLACE)? INTO|UPDATE|DELETE FROM|DROP INDEX|CREATE INDEX|CREATE TABLE|ALTER TABLE|DROP TABLE|SELECT CASE)\b',text,re.I):
                    raise ValueError('Unsupported SQL in cost oracle')
                dml=re.match(r'(INSERT(?: OR REPLACE)? INTO|UPDATE|DELETE FROM) ([A-Za-z0-9_]+)',text,re.I)
                before=self.db.total_changes
                replacement=False
                if dml:
                    operation,table=dml.groups();indexes=self.indexes(table)
                    changed=set()
                    if operation.upper()=='UPDATE':
                        setters=text.split(' SET ',1)[1].rsplit(' WHERE ',1)[0]
                        changed=set(re.findall(r'(?:^|,)\s*([A-Za-z0-9_]+)\s*=',setters))
                    if 'OR REPLACE' in operation.upper():replacement=True
                drop=re.match(r'DROP INDEX ([A-Za-z0-9_]+)',text,re.I)
                if drop:
                    table=self.db.execute('SELECT tbl_name FROM sqlite_master WHERE type=\'index\' AND name=?',(drop[1],)).fetchone()
                    if table:ddl_units+=self.db.execute(f'SELECT COUNT(*) FROM {table[0]}').fetchone()[0]+1
                create_index=re.match(r'CREATE INDEX(?: IF NOT EXISTS)? ([A-Za-z0-9_]+) ON ([A-Za-z0-9_]+)',text,re.I)
                if create_index:
                    exists=self.db.execute('SELECT1 FROM sqlite_master WHERE name=?'.replace('SELECT1','SELECT 1'),(create_index[1],)).fetchone()
                    if not exists:ddl_units+=self.db.execute(f'SELECT COUNT(*) FROM {create_index[2]}').fetchone()[0]+1
                if re.match(r'CREATE TABLE|ALTER TABLE',text,re.I):ddl_units+=2
                if re.match(r'DROP TABLE',text,re.I):
                    table=re.search(r'DROP TABLE(?: IF EXISTS)? ([A-Za-z0-9_]+)',text,re.I)[1]
                    if self.db.execute("SELECT1 FROM sqlite_master WHERE type='table' AND name=?".replace('SELECT1','SELECT 1'),(table,)).fetchone():
                        ddl_units+=self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]*(1+len(self.indexes(table)))+1
                self.db.execute(statement)
                affected=self.db.total_changes-before;native+=affected
                if dml:
                    if operation.upper()=='UPDATE':index_units+=affected*2*sum(bool(changed&columns) for columns in indexes)
                    elif 'ON CONFLICT' in text.upper():
                        # Conservative: charge insertion index cost even for a
                        # hash-only conflict update with unchanged primary key.
                        index_units+=affected*len(indexes)
                    else:index_units+=affected*len(indexes)
                    if replacement:
                        # SQLite does not report deleted REPLACE rows. Reserve
                        # an additional deleted data row and all index entries.
                        replace_units+=affected*(1+len(indexes))
            total=native+index_units+ddl_units+replace_units
            if (step_limit is not None and total>step_limit) or self.total+total>=self.round_limit:
                raise ValueError(f'Local SQL cost exceeds cap: step {total}/{step_limit}, round {self.total+total}/{self.round_limit}')
            self.db.commit()
        except BaseException:
            self.db.rollback();raise
        self.total+=total
        report=dict(label=label,sql_sha256=hashlib.sha256(sql.encode()).hexdigest(),statement_count=len(statements),native_total_changes=native,index_entry_operations=index_units,ddl_entry_reservation=ddl_units,replace_delete_reservation=replace_units,conservative_units=total,round_units=self.total)
        self.steps.append(report)
        self.pending=True
        report['remote_outcome']='pending'
        with (self.directory/'exact-statements.sql').open('a') as output:output.write(sql)
        (self.directory/'local-cost-report.json').write_text(json.dumps({'steps':self.steps,'round_units':self.total,'actual_round_units':self.actual_total},indent=2)+'\n')
        return report

    def note_remote_batch(self,rows_written):
        if not self.pending or self.diverged or not isinstance(rows_written,int) or rows_written<0:raise ValueError('Cannot record this remote batch')
        step=self.steps[-1];step['actual_rows_written']=step.get('actual_rows_written',0)+rows_written
        step['actual_budget_rows_written']=step['actual_rows_written'];self.actual_total+=rows_written
        self._save()
        if amplification_exceeded(step['actual_rows_written'],step['conservative_units']) or self.actual_total>self.round_limit:
            self.invalidate();raise ValueError('Measured write amplification or round limit exceeded')

    def confirm(self,actual_rows_written):
        if not self.pending or self.diverged:raise ValueError('No confirmable oracle operation')
        if not isinstance(actual_rows_written,int) or actual_rows_written<0:
            self.invalidate();raise ValueError('Remote write metrics unavailable')
        step=self.steps[-1];previous=step.get('actual_budget_rows_written',0)
        step['actual_rows_written']=actual_rows_written
        step['actual_budget_rows_written']=actual_rows_written
        self.actual_total+=actual_rows_written-previous
        if amplification_exceeded(actual_rows_written,self.steps[-1]['conservative_units']) or self.actual_total>self.round_limit:
            self.invalidate();raise ValueError('Measured write amplification or round limit exceeded')
        self.steps[-1]['remote_outcome']='confirmed';self.pending=False
        self._save()

    def confirm_analytics(self,graphql_rows_written):
        if self.pending or self.diverged or not isinstance(graphql_rows_written,int):raise ValueError('Analytics cannot confirm this oracle operation')
        step=self.steps[-1];previous=step.get('actual_budget_rows_written',step['actual_rows_written'])
        self.actual_total+=graphql_rows_written-previous
        step['graphql_rows_written']=graphql_rows_written;step['actual_budget_rows_written']=graphql_rows_written
        if amplification_exceeded(graphql_rows_written,step['conservative_units']) or self.actual_total>self.round_limit:
            self.invalidate();raise ValueError('Measured write amplification or round limit exceeded')
        self._save()

    def invalidate(self):
        self.diverged=True
        if self.steps:self.steps[-1]['remote_outcome']='unknown; reconciliation required'
        self._save()

    def _save(self):
        (self.directory/'local-cost-report.json').write_text(json.dumps({'steps':self.steps,'round_units':self.total,'diverged':self.diverged,'actual_round_units':self.actual_total},indent=2)+'\n')


def export_snapshot(db,destination):
    """Wrangler's read-only D1 export supplies the actual current generation.

    This also handles a partially applied generation: never infer its contents
    from an old source ZIP. Export SQL is consumed locally and never reuploaded.
    """
    import subprocess
    from load_sam_public import WORKER_DIR
    destination=Path(destination)
    dump=destination.with_suffix('.sql')
    result=subprocess.run(['npx','--no-install','wrangler','d1','export',db.database,'--remote','--output',str(dump)],cwd=WORKER_DIR,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode or not dump.exists():raise RuntimeError('Read-only production export failed; no writes attempted')
    local=sqlite3.connect(destination)
    local.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;')
    try:
        buffer=''
        with dump.open() as source:
            for line in source:
                buffer+=line
                if sqlite3.complete_statement(buffer):local.execute(buffer);buffer=''
        if buffer.strip():raise ValueError('Truncated read-only D1 export')
        local.commit()
        if local.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Exported local production snapshot failed integrity check')
    finally:local.close()
    dump.unlink()
    return destination
