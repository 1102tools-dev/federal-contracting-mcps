"""Safety checks for separate public SAM D1 staging and atomic promotion."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import load_sam_public as loader


class SQLiteD1:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.fail_import = False
    def execute_file(self, statements):
        if self.fail_import and any(s.startswith('INSERT INTO exclusions_stage') for s in statements):
            raise RuntimeError('simulated interrupted D1 upload')
        self.db.executescript('\n'.join(statements))
    def query(self, statement):
        return [dict(row) for row in self.db.execute(statement)]
    def size(self):
        return self.query('PRAGMA page_count')[0]['page_count'] * self.query('PRAGMA page_size')[0]['page_size']
    def atomic(self, statements):
        with self.db:
            self.db.execute('BEGIN')
            for statement in statements:
                self.db.execute(statement)


class Safety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'fixture.csv'
        self.path.write_text('test public source\n')
        self.db = SQLiteD1()
        self.db.execute_file(loader.table_sql('exclusions') + [loader.STATUS_SQL])
        self.db.db.execute("INSERT INTO exclusions (exclusion_id,name) VALUES ('old','Previous record')")
        self.db.db.commit()
        self.metadata = dict(file_name='public.csv', file_date='2026-10-10', source_url='https://sam.gov/public')
    def tearDown(self):
        self.db.db.close()
        self.tmp.cleanup()
    def prepare(self, kind, path, local_path, audit=None):
        db = sqlite3.connect(local_path)
        db.executescript('\n'.join(loader.table_sql(kind)))
        db.execute("INSERT INTO exclusions (exclusion_id,name) VALUES ('new','New record')")
        db.commit(); db.close()
        return 1, Path(local_path).stat().st_size
    def test_empty_and_much_smaller_refused(self):
        for count, existing in [(0,0),(59,100),(10,0)]:
            with self.assertRaises(ValueError):
                loader.validate_count('entities', count, existing)
        with self.assertRaises(ValueError):
            loader.validate_count('exclusions',59,100,allow_small=True)
        loader.validate_count('exclusions',60,100,allow_small=True)
    def test_load_builds_each_staged_index_in_a_separate_import(self):
        original = self.db.execute_file
        built = []
        def bounded_import(statements):
            indexes = [s for s in statements if s.startswith('CREATE INDEX') and '_stage_' in s]
            if indexes:
                self.assertEqual(len(statements),1,'D1 index imports must be bounded individually')
                built.extend(indexes)
            if any(s.startswith('INSERT INTO exclusions_stage') for s in statements):
                self.assertEqual(len(built),6,'All staging indexes must precede row uploads')
                table = self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'exclusions_stage_%'")[0]['name']
                self.assertEqual(self.db.query(f'SELECT COUNT(*) n FROM {table}')[0]['n'],0)
            original(statements)
        with patch.object(loader,'prepare',side_effect=self.prepare), patch.object(self.db,'execute_file',side_effect=bounded_import):
            result = loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(len(built),6)
        self.assertEqual(result['row_count'],1)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'new'}])
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%stage%'"),[])
        self.assertEqual(len(self.db.query("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='exclusions' AND sql IS NOT NULL")),6)
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%previous%'"),[])
    def test_leftover_tables_refuse_all_writes_for_either_kind(self):
        for table in ['entities','entity_naics','entity_business_types','exclusions']:
            for suffix in ['_stage_123456abcdef','_previous','_previous_123456abcdef']:
                name=table+suffix
                self.db.db.execute(f'CREATE TABLE {name} (id TEXT)')
                for kind in ['entities','exclusions']:
                    with self.subTest(name=name,kind=kind), patch.object(self.db,'execute_file') as writes:
                        with self.assertRaisesRegex(ValueError,name):
                            loader.load(self.db,kind,self.path,self.metadata,True)
                        writes.assert_not_called()
                        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
                self.db.db.execute(f'DROP TABLE {name}')
    def test_main_leftover_guard_precedes_status_write(self):
        self.db.db.execute('CREATE TABLE entities_previous (id TEXT)')
        with patch.object(loader,'D1',return_value=self.db), patch.object(self.db,'execute_file') as writes:
            with self.assertRaisesRegex(ValueError,'entities_previous'):
                loader.main(['--local','--kind','exclusions'])
            writes.assert_not_called()
    def test_cleanup_failure_preserves_original_error_and_blocks_next_load(self):
        original=self.db.execute_file
        def interrupted(statements):
            if any(s.startswith('INSERT INTO exclusions_stage') for s in statements):
                raise RuntimeError('original indexed upload failed')
            if any(s.startswith('DROP TABLE IF EXISTS exclusions_stage') for s in statements):
                raise RuntimeError('secondary cleanup error')
            original(statements)
        with patch.object(loader,'prepare',side_effect=self.prepare), patch.object(self.db,'execute_file',side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError,'original indexed upload failed') as caught:
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertTrue(any('Stage cleanup also failed' in note for note in caught.exception.__notes__))
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
        with patch.object(self.db,'execute_file') as writes:
            with self.assertRaisesRegex(ValueError,'leftover tables'):
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
            writes.assert_not_called()
    def test_indexed_chunks_have_smaller_bound(self):
        self.assertLessEqual(loader.CHUNK_BYTES,8_000_000)
        statements=['X'*80_000]*120
        batches=list(loader.chunks(iter(statements)))
        self.assertGreater(len(batches),1)
        self.assertTrue(all(sum(len(s.encode())+1 for s in batch)<=loader.CHUNK_BYTES for batch in batches))
    def test_entity_indexes_and_child_indexes_precede_first_upload(self):
        original=self.db.execute_file
        started=False
        def check_upload(statements):
            nonlocal started
            if any(s.startswith('INSERT INTO entities_stage') for s in statements):
                started=True
                tables=self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%stage%'")
                for table in tables:
                    self.assertEqual(self.db.query(f"SELECT COUNT(*) n FROM {table['name']}")[0]['n'],0)
                indexes=self.db.query("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND tbl_name LIKE '%stage%'")
                self.assertEqual(len(indexes),10)
            original(statements)
        row=dict(uei='DJFGWZADMU16',cage_code='5QRC1',legal_business_name='CITY',naics_codes=['541611'],business_type_codes=['A2'],sba_business_type_codes=[])
        with patch('sam_entity_extract.iter_rows',return_value=iter([row])),patch.object(self.db,'execute_file',side_effect=check_upload):
            loader.load(self.db,'entities',self.path,self.metadata,True)
        self.assertTrue(started)
        self.assertEqual(self.db.query('SELECT COUNT(*) n FROM entity_naics')[0]['n'],1)
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%previous%'"),[])
    def test_backend_failure_keeps_diagnostic_cause_out_of_readable_error(self):
        response=subprocess.CompletedProcess(['wrangler'],1,'private stdout','private stderr')
        with patch.object(loader.subprocess,'run',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'D1 execute failed') as caught:
                loader.D1('remote','sam-gov-entities').run('--command','SELECT 1')
        self.assertEqual(caught.exception.__cause__.stderr,'private stderr')
        self.assertNotIn('private',str(caught.exception))
    def test_readable_error_redacts_credentials_and_collapses_lines_with_notes(self):
        failure=RuntimeError('backend\n failed token-secret')
        failure.add_note('entities: failed while uploading indexed chunk 3')
        failure.add_note('Stage cleanup also failed')
        with patch.dict(os.environ,{'CLOUDFLARE_API_TOKEN':'token-secret'}):
            text=loader.readable_error(failure)
        self.assertNotIn('token-secret',text)
        self.assertNotIn('\n',text)
        self.assertIn('[redacted]',text)
        self.assertIn('chunk 3',text)
        self.assertIn('Stage cleanup also failed',text)
    def test_known_backend_error_code_is_retained_without_request_payload(self):
        response=subprocess.CompletedProcess(['wrangler'],1,'','[ERROR] Database operation rejected [code: 7500]\nrequest sql=INSERT private')
        with patch.object(loader.subprocess,'run',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'Database operation rejected.*7500') as caught:
                loader.D1('remote','sam-gov-entities').run('--command','SELECT 1')
        self.assertNotIn('private',str(caught.exception))
    def test_postpromotion_diagnostic_failure_reports_committed_reload(self):
        for fail_at in ['size','status_update']:
            with self.subTest(fail_at=fail_at):
                original_size=self.db.size
                original_atomic=self.db.atomic
                calls=0
                def measured_size():
                    nonlocal calls
                    calls+=1
                    if fail_at=='size' and calls==3:
                        raise RuntimeError('metric read failed')
                    return original_size()
                def atomic(statements):
                    if fail_at=='status_update' and statements[0].startswith('UPDATE extract_status'):
                        raise RuntimeError('metric status write failed')
                    original_atomic(statements)
                with patch.object(loader,'prepare',side_effect=self.prepare),patch.object(self.db,'size',side_effect=measured_size),patch.object(self.db,'atomic',side_effect=atomic):
                    result=loader.load(self.db,'exclusions',self.path,self.metadata,True)
                self.assertTrue(result['promoted'])
                self.assertIn('metric',result['diagnostics_warning'])
                self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'new'}])
                self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%stage%' OR name LIKE '%previous%')"),[])
    def test_lost_promotion_acknowledgement_reads_back_committed_generation(self):
        original=self.db.atomic
        def lost_acknowledgement(statements):
            original(statements)
            if statements[0].startswith('ALTER TABLE'):
                raise RuntimeError('transport acknowledgement lost')
        with patch.object(loader,'prepare',side_effect=self.prepare),patch.object(self.db,'atomic',side_effect=lost_acknowledgement):
            result=loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertTrue(result['promoted'])
        self.assertIn('confirmed',result['promotion_warning'])
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'new'}])
    def test_middle_staged_index_failure_preserves_previous_data_and_status(self):
        self.db.db.execute("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES ('exclusions','previous.zip','2026-10-09','public','then',1,'hash',1,1)")
        self.db.db.commit()
        previous_status = self.db.query('SELECT * FROM extract_status')
        original = self.db.execute_file
        built = []
        def fail_middle_index(statements):
            if any(s.startswith('CREATE INDEX') and '_stage_' in s for s in statements):
                built.extend(statements)
                if len(built)==3:
                    raise RuntimeError('simulated D1 index import polling failure')
            original(statements)
        with patch.object(loader,'prepare',side_effect=self.prepare), patch.object(self.db,'execute_file',side_effect=fail_middle_index):
            with self.assertRaisesRegex(RuntimeError,'index import polling failure'):
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(len(built),3)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
        self.assertEqual(self.db.query('SELECT * FROM extract_status'),previous_status)
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE name LIKE '%stage%'"),[])
    def test_actual_small_load_retains_previous_rows_and_status(self):
        self.db.db.executemany('INSERT INTO exclusions (exclusion_id) VALUES (?)',[(f'old{i}',) for i in range(99)])
        self.db.db.execute("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES ('exclusions','previous.zip','2026-10-09','public','then',100,'hash',1,1)")
        self.db.db.commit()
        with patch.object(loader,'prepare',side_effect=self.prepare):
            with self.assertRaises(ValueError):
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(self.db.query('SELECT COUNT(*) AS n FROM exclusions')[0]['n'],100)
        self.assertEqual(self.db.query('SELECT file_name FROM extract_status')[0]['file_name'],'previous.zip')
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE name LIKE '%stage%'"),[])

    def test_entity_duplicates_and_multiple_cage_assertion_scope(self):
        rows = [dict(uei='DJFGWZADMU16',cage_code='5QRC1',legal_business_name='CITY',naics_codes=['541611'],business_type_codes=['A2'],sba_business_type_codes=[]),
                dict(uei='DJFGWZADMU16',cage_code='8Y3E7',legal_business_name='CITY',naics_codes=['541512'],business_type_codes=['QF'],sba_business_type_codes=[])]
        rows.append(dict(rows[0]))
        audit = {}
        prepared = Path(self.tmp.name) / 'entities.sqlite'
        with patch('sam_entity_extract.iter_rows',return_value=iter(rows)):
            count,_ = loader.prepare('entities',self.path,prepared,audit)
        self.assertEqual(count,2)
        self.assertEqual(audit['duplicate_rows'],1)
        db=sqlite3.connect(prepared)
        try:
            results=db.execute('SELECT e.cage_code,n.code FROM entities e JOIN entity_naics n ON n.entity_id=e.entity_id ORDER BY e.cage_code').fetchall()
            self.assertEqual(results,[('5QRC1','541611'),('8Y3E7','541512')])
        finally:
            db.close()

    def test_completed_checkpoint_reuse_and_changed_source_rejection(self):
        cached=Path(self.tmp.name)/'checkpoint.sqlite'
        count,size=self.prepare('exclusions',self.path,cached)
        checkpoint=dict(path=str(cached),count=count,audit={},sha256=loader.file_sha256(self.path),prepare_seconds=0,parser_sha256=loader.file_sha256(loader.ROOT/'scripts'/'sam_exclusion_extract.py'))
        with patch.object(loader,'prepare',side_effect=AssertionError('should reuse validated checkpoint')):
            loader.load(self.db,'exclusions',self.path,self.metadata,True,prepared=checkpoint)
        self.path.write_text('source bytes changed')
        with self.assertRaisesRegex(ValueError,'SHA mismatch'):
            loader.load(self.db,'exclusions',self.path,self.metadata,True,prepared=checkpoint)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'new'}])

    def test_truncated_parser_preserves_current(self):
        with patch.object(loader,'prepare',side_effect=ValueError('missing EOF')):
            with self.assertRaises(ValueError):
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
    def test_failed_upload_preserves_current(self):
        self.db.fail_import = True
        with patch.object(loader,'prepare',side_effect=self.prepare):
            with self.assertRaises(RuntimeError):
                loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
        self.assertEqual(self.db.query("SELECT name FROM sqlite_master WHERE name LIKE '%stage%'"),[])
    def test_peak_size_observed_before_promotion_with_both_copies(self):
        observations=[]
        def size():
            stable=self.db.query('SELECT exclusion_id FROM exclusions')[0]['exclusion_id']
            stages=self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'exclusions_stage_%'")
            observations.append((stable,bool(stages)))
            return 3_000_000_000 if stages else 1_000_000_000
        with patch.object(loader,'prepare',side_effect=self.prepare), patch.object(self.db,'size',side_effect=size):
            result=loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(observations,[('old',False),('old',True),('new',False)])
        self.assertEqual(result['existing_database_bytes'],1_000_000_000)
        self.assertEqual(result['peak_database_bytes'],3_000_000_000)
        self.assertEqual(result['database_bytes'],1_000_000_000)
        self.assertEqual(result['peak_headroom_bytes'],loader.MAX_DATABASE_BYTES-3_000_000_000)
        self.assertEqual(result['peak_headroom_percent'],70.0)
        self.assertEqual(result['database_limit_bytes'],10_000_000_000)
        self.assertGreater(result['prepared_database_bytes'],0)
        columns={row['name'] for row in self.db.query('PRAGMA table_info(extract_status)')}
        self.assertNotIn('peak_database_bytes',columns)

    def test_success_promotes_data_and_status(self):
        with patch.object(loader,'prepare',side_effect=self.prepare):
            status = loader.load(self.db,'exclusions',self.path,self.metadata,True)
        self.assertEqual(status['row_count'],1)
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'new'}])
        self.assertEqual(self.db.query('SELECT file_name FROM extract_status'),[{'file_name':'public.csv'}])
    def test_failed_atomic_promotion_rolls_back(self):
        self.db.execute_file(loader.table_sql('exclusions','_test'))
        self.db.db.execute("INSERT INTO exclusions_test (exclusion_id) VALUES ('new')")
        self.db.db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            self.db.atomic(["ALTER TABLE exclusions RENAME TO exclusions_previous;", "ALTER TABLE exclusions_test RENAME TO exclusions;", 'INSERT INTO nonexistent VALUES (1);'])
        self.assertEqual(self.db.query('SELECT exclusion_id FROM exclusions'),[{'exclusion_id':'old'}])
    def test_remote_exclusion_plain_csv_cannot_claim_complete_source(self):
        self.db.target='remote'
        with self.assertRaisesRegex(ValueError,'intact source ZIP'):
            loader.load(self.db,'exclusions',self.path,self.metadata,True)

    def test_corrupt_zip_rejected(self):
        path = Path(self.tmp.name) / 'bad.zip'
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('public.dat','original public text')
        content = path.read_bytes().replace(b'original public text',b'corrupt! public text')
        path.write_bytes(content)
        with self.assertRaises((ValueError,zipfile.BadZipFile)):
            loader.validate_zip(path)
    def test_opportunities_database_never_targeted(self):
        with self.assertRaises(ValueError):
            loader.D1('remote','sam-gov-opportunities')
        with self.assertRaises(ValueError):
            loader.D1('remote','8875076f-cbb2-4ce8-9ea1-b152323fbbb0')
    def test_entity_file_date_uses_snapshot_not_previous_day_modified(self):
        payload={'_embedded':{'customS3ObjectSummaryList':[{'displayKey':'SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP','dateModified':'Oct 04,2026'}]}}
        with patch.object(loader,'fetch_json',return_value=payload):
            self.assertEqual(loader.newest('entities')['file_date'],'2026-10-05')

    def test_sensitive_listing_entry_refused_even_with_public_style_name(self):
        payload={'_embedded':{'customS3ObjectSummaryList':[{'displayKey':'SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP','dateModified':'Oct 04,2026','privacy':'FOUO'}]}}
        with patch.object(loader,'fetch_json',return_value=payload):
            with self.assertRaises(ValueError):
                loader.newest('entities')

    def test_list_real_service_envelope(self):
        payload = {'_embedded':{'customS3ObjectSummaryList':[
            {'displayKey':'SAM_Exclusions_Public_Extract_V2_26283.ZIP','dateModified':'Oct 10,2026'},
            {'displayKey':'SAM_Exclusions_Public_Extract_V2_26282.ZIP','dateModified':'Oct 09,2026'},
        ]}}
        with patch.object(loader,'fetch_json',return_value=payload):
            result = loader.newest('exclusions')
        self.assertEqual(result['file_date'],'2026-10-10')
        self.assertIn('privacy=Public',result['source_url'])


if __name__ == '__main__':
    unittest.main()
