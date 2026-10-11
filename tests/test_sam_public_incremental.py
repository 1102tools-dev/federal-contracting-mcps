import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import load_sam_public as loader
import sam_public_incremental as incremental
from test_sam_public_loader import SQLiteD1


class Incremental(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'public.csv';self.path.write_text('public')
        self.db=SQLiteD1()
        self.db.execute_file(loader.table_sql('entities')+loader.table_sql('exclusions')+[loader.STATUS_SQL])
        self.metadata=dict(file_name='public.csv',file_date='2026-10-11',source_url='https://sam.gov/public')
    def tearDown(self):self.db.db.close();self.tmp.cleanup()
    def entity(self,uei='ABCDEF123456',cage='12345',date='2026-10-11',naics=None):
        return dict(uei=uei,cage_code=cage,legal_business_name='Example',registration_date=date,naics_codes=naics or ['541611'],business_type_codes=['A2'],sba_business_type_codes=[],record_json={'date':date})
    def seed(self,kind,rows):
        prepared=Path(self.tmp.name)/'seed.sqlite'
        with patch(('sam_entity_extract' if kind=='entities' else 'sam_exclusion_extract')+'.iter_rows',return_value=iter(rows)):
            loader.prepare(kind,self.path,prepared)
        local=sqlite3.connect(prepared)
        tables=[kind]+(['entity_naics','entity_business_types'] if kind=='entities' else [])
        for table in tables:
            data=local.execute(f'SELECT * FROM {table}').fetchall()
            for row in data:self.db.db.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in row)})',row)
        local.close()
        self.db.db.execute('INSERT INTO extract_status(kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)',(kind,self.metadata['file_name'],self.metadata['file_date'],self.metadata['source_url'],'old',len(rows),loader.file_sha256(self.path),1,1))
        self.db.db.commit()
    def run_load(self,kind,rows,**options):
        with patch(('sam_entity_extract' if kind=='entities' else 'sam_exclusion_extract')+'.iter_rows',return_value=iter(rows)):
            return incremental.incremental_load(self.db,kind,self.path,self.metadata,True,**options)
    def test_unchanged_entity_performs_zero_database_writes(self):
        rows=[self.entity()];self.seed('entities',rows)
        with patch.object(self.db,'execute_file') as ddl,patch.object(self.db,'atomic') as mutations:
            result=self.run_load('entities',rows)
        ddl.assert_not_called();mutations.assert_not_called()
        self.assertEqual(result['actual_record_writes'],0)
    def test_unchanged_legacy_exclusion_hash_does_not_backfill(self):
        rows=[{'exclusion_id':'SAM0001','name':'Example','record_json':{'entityName':'Example'}}];self.seed('exclusions',rows)
        with patch.object(self.db,'execute_file') as ddl,patch.object(self.db,'atomic') as mutations:
            result=self.run_load('exclusions',rows)
        ddl.assert_not_called();mutations.assert_not_called()
        self.assertEqual(result['delta']['unchanged'],1)
    def test_date_only_change_preserves_entity_id_and_children(self):
        self.seed('entities',[self.entity()])
        old=self.db.query('SELECT entity_id FROM entities')[0]['entity_id']
        children=self.db.query('SELECT * FROM entity_naics')
        statements=[];original=self.db.atomic
        def atomic(sql):statements.extend(sql);original(sql)
        with patch.object(self.db,'atomic',side_effect=atomic):result=self.run_load('entities',[self.entity(date='2026-10-12')])
        self.assertEqual(self.db.query('SELECT entity_id FROM entities')[0]['entity_id'],old)
        self.assertEqual(self.db.query('SELECT * FROM entity_naics'),children)
        self.assertFalse(any(s.startswith(('DELETE FROM entity_','INSERT INTO entity_')) for s in statements))
        self.assertEqual(result['delta']['changed'],1)
        self.assertEqual(self.db.query('SELECT state FROM public_refresh_runs')[0]['state'],'complete')
    def test_add_change_remove_and_membership_diffs(self):
        self.seed('entities',[self.entity(),self.entity(uei='REMOVE000001',cage='99999')])
        result=self.run_load('entities',[self.entity(naics=['541512']),self.entity(uei='NEWNEW000001',cage='54321')])
        self.assertEqual(result['delta'],dict(inserted=1,changed=1,removed=1,unchanged=0))
        self.assertEqual(self.db.query('SELECT COUNT(*) n FROM entities')[0]['n'],2)
        self.assertEqual(self.db.query('SELECT COUNT(*) n FROM entity_naics')[0]['n'],2)
    def test_historical_account_writes_do_not_block_new_delta(self):
        self.seed('entities',[self.entity()]);self.db.target='remote'
        oracle=SimpleNamespace(db=self.db.db,total=0,round_limit=5000000,
            steps=[],rehearse=lambda *args: {},invalidate=lambda: None)
        with patch.object(incremental,'billing_period',return_value={'start':'2026-10-07T00:00:00+00:00','end':'2026-11-07T00:00:00+00:00'}),patch.object(incremental,'account_month_written',return_value=111_000_000),patch.object(self.db,'atomic',side_effect=RuntimeError('mutation reached')) as mutations:
            with self.assertRaisesRegex(RuntimeError,'mutation reached'):
                self.run_load('entities',[self.entity(date='2026-10-12')],oracle=oracle)
        mutations.assert_called_once()
    def test_entity_monthly_cap_still_blocks_before_mutations(self):
        self.seed('entities',[self.entity()])
        self.db.execute_file([incremental.BUDGET_SQL])
        period=incremental.dt.datetime.now(incremental.dt.timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
        self.db.db.execute('INSERT INTO public_write_budget VALUES (?,4000000,0)',(period,));self.db.db.commit()
        with patch.object(self.db,'atomic') as mutations:
            with self.assertRaisesRegex(ValueError,'Public refresh write allocation'):
                self.run_load('entities',[self.entity(date='2026-10-12')])
        mutations.assert_not_called()
    def test_exclusions_daily_cap_still_blocks_before_mutations(self):
        rows=[{'exclusion_id':'SAM0001','name':'Example','record_json':{'entityName':'Example'}}]
        self.seed('exclusions',rows)
        self.db.execute_file([incremental.DAILY_SQL])
        day=incremental.dt.datetime.now(incremental.dt.timezone.utc).date().isoformat()
        self.db.db.execute('INSERT INTO public_daily_budget VALUES (?,190000)',(day,));self.db.db.commit()
        with patch.object(self.db,'atomic') as mutations:
            with self.assertRaisesRegex(ValueError,'Public refresh write allocation'):
                self.run_load('exclusions',[dict(rows[0],name='Changed')])
        mutations.assert_not_called()
    def test_entire_delta_must_fit_diagnostic_limit(self):
        self.seed('entities',[self.entity()])
        with patch.object(self.db,'execute_file') as ddl,patch.object(self.db,'atomic') as mutations:
            with self.assertRaisesRegex(ValueError,'Entire delta estimate'):
                self.run_load('entities',[self.entity(date='2026-10-12')],diagnostic_max_writes=100)
        ddl.assert_not_called();mutations.assert_not_called()
    def test_partial_failure_is_gated_and_same_source_resumes(self):
        self.seed('entities',[self.entity()])
        rows=[self.entity(date='2026-10-12'),self.entity(uei='NEWNEW000001',cage='54321')]
        original=self.db.atomic
        def fail_records(sql):
            if any(s.startswith(('INSERT INTO entities (','UPDATE entities SET')) for s in sql):raise RuntimeError('bounded transaction failed')
            original(sql)
        with patch.object(self.db,'atomic',side_effect=fail_records):
            with self.assertRaisesRegex(RuntimeError,'bounded transaction failed'):self.run_load('entities',rows)
        self.assertEqual(self.db.query('SELECT state FROM public_refresh_runs')[0]['state'],'applying')
        with self.assertRaisesRegex(ValueError,'unexpired lease'):self.run_load('entities',rows)
        self.db.db.execute("UPDATE public_refresh_runs SET owner_expires_at='' ");self.db.db.commit()
        self.path.write_text('different')
        with self.assertRaisesRegex(ValueError,'identical source ZIP'):self.run_load('entities',rows)
        self.path.write_text('public')
        result=self.run_load('entities',rows)
        self.assertTrue(result['completed'])
        self.assertEqual(self.db.query('SELECT state FROM public_refresh_runs')[0]['state'],'complete')
    def test_remote_requires_exact_local_oracle_before_mutations(self):
        self.seed('entities',[self.entity()]);self.db.target='remote'
        with patch.object(self.db,'atomic') as mutations:
            with self.assertRaisesRegex(ValueError,'cost oracle'):self.run_load('entities',[self.entity(date='2026-10-12')])
        mutations.assert_not_called()
    def test_pk_and_changed_index_weights_counted(self):
        fields=loader.ENTITY_FIELDS
        old={f:None for f in fields};old.update(entity_id='stable',uei='ABC',naics_codes_json='[]',business_type_codes_json='[]',sba_business_type_codes_json='[]')
        new=dict(old,uei='DEF')
        sql,units=incremental.record_delta('entities',old,new,fields,{'entities':[{'entity_id'},{'uei'}],'entity_naics':[],'entity_business_types':[]},'hash')
        self.assertEqual(units,5)
        self.assertEqual(len(sql),2)
        self.assertNotIn('entity_id=',sql[0].split(' WHERE ')[0])

    def test_known_dba_partial_index_membership_costs_are_conservative(self):
        self.db.db.execute("CREATE INDEX entities_dba_name ON entities(dba_name,registration_status,entity_id) WHERE dba_name IS NOT NULL AND dba_name<>''")
        indexes=incremental.index_columns(self.db,['entities','entity_naics','entity_business_types'])
        self.assertIn({'dba_name','registration_status','entity_id'},indexes['entities'])
        fields=loader.ENTITY_FIELDS
        old={f:None for f in fields};old.update(entity_id='stable',naics_codes_json='[]',business_type_codes_json='[]',sba_business_type_codes_json='[]')
        for changes,expected in [({'dba_name':'DBA'},5),({'registration_status':'A'},9),({'registration_date':'2026-10-11'},3)]:
            with self.subTest(changes=changes):
                _,units=incremental.record_delta('entities',old,dict(old,**changes),fields,indexes,'hash')
                self.assertEqual(units,expected)
        _,units=incremental.record_delta('entities',dict(old,dba_name='DBA'),old,fields,indexes,'hash')
        self.assertEqual(units,5)

    def test_other_partial_or_expression_indexes_are_refused(self):
        for sql in ["CREATE INDEX other_partial ON entities(dba_name) WHERE dba_name IS NOT NULL", "CREATE INDEX entities_dba_name ON entities(dba_name,registration_status,entity_id) WHERE dba_name IS NOT NULL", "CREATE INDEX expression_name ON entities(lower(dba_name))"]:
            with self.subTest(sql=sql):
                self.db.db.execute(sql)
                with self.assertRaisesRegex(ValueError,'partial/expression'):
                    incremental.index_columns(self.db,['entities'])
                name=sql.split()[2];self.db.db.execute('DROP INDEX '+name)


    def test_exclusions_daily_budget_accumulates_across_runs(self):
        rows=[{'exclusion_id':'SAM0001','name':'Example','record_json':{'entityName':'Example'}}]
        self.seed('exclusions',rows)
        self.run_load('exclusions',[dict(rows[0],name='First')])
        first=self.db.query('SELECT units FROM public_daily_budget')[0]['units']
        self.run_load('exclusions',[dict(rows[0],name='Second')])
        second=self.db.query('SELECT units FROM public_daily_budget')[0]['units']
        self.assertGreater(first,0)
        self.assertGreater(second,first)


if __name__=='__main__':unittest.main()
