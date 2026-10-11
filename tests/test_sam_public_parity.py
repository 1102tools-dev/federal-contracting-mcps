"""Regression checks for honest, fail-closed public replay comparison."""
import importlib.util
from pathlib import Path
import unittest
import asyncio
import json
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sam_public_parity', ROOT/'scripts/verify_sam_public_parity.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicParityTests(unittest.TestCase):
    def test_missing_null_is_a_difference(self):
        matched, errors = module.compare({'entityData':[{'cageCode':None}]}, {'entityData':[{}]})
        self.assertEqual(matched, 0)
        self.assertFalse(errors[0]['actual_present'])

    def test_added_field_is_a_difference(self):
        _, errors = module.compare({'a':1}, {'a':1,'b':None})
        self.assertEqual(errors[0]['field'], 'b')
        self.assertFalse(errors[0]['expected_present'])

    def test_list_change_cannot_hide_in_aggregate(self):
        _, errors = module.compare({'naics':['541512','541519']}, {'naics':['541512','541511']})
        self.assertEqual(errors[0]['field'], 'naics[1]')

    def test_normalization_handles_only_presentation_and_unordered_codes(self):
        public={'date':'2026-10-10','city':'CHICAGO','naicsList':[{'naicsCode':'541519'},{'naicsCode':'541512'}]}
        live={'date':'10-10-2026','city':'Chicago','naicsList':[{'naicsCode':'541512'},{'naicsCode':'541519'}]}
        self.assertNotEqual(module.compare(public,live)[1],[])
        self.assertEqual(module.compare(module.normalize_public(public),module.normalize_public(live))[1],[])
        live['date']='10-11-2026'
        self.assertEqual(module.compare(module.normalize_public(public),module.normalize_public(live))[1][0]['field'],'date')

    def test_live_failure_never_saves_exception_uri_or_credential(self):
        from sam_gov_mcp import server
        entity=ROOT/'tests/fixtures/sam_public/entities.dat'
        exclusion=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv'
        replay=module.run(entity,exclusion)
        sentinel='SIMULATED_CREDENTIAL_DO_NOT_PERSIST'
        async def failing(*args,**kwargs):
            raise RuntimeError('https://invalid.example/?api_key='+sentinel)
        with patch.object(server,'lookup_entity_by_uei',failing), patch.object(server,'check_exclusion_by_uei',failing), patch.object(server,'search_exclusions',failing):
            result=asyncio.run(module.live_comparison(replay,entity,exclusion,sentinel))
        self.assertEqual(len(result['errors']),sum(result['attempted_records'].values()))
        self.assertFalse(result['passed'])
        self.assertFalse(result['live_api_parity_verified'])
        self.assertNotIn(sentinel,json.dumps(result))
        self.assertNotIn('invalid.example',json.dumps(result))

    def test_hosted_handlers_execute_complete_supplemental_real_pool(self):
        rows,hosted=module.hosted_pool(ROOT/'tests/fixtures/sam_public/entities.dat',ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv')
        self.assertGreaterEqual(len(rows['entities']),100)
        self.assertGreaterEqual(len(rows['exclusions']),60)
        self.assertEqual(len(hosted['entities']),len(rows['entities']))
        self.assertEqual(len(hosted['exclusions']),len(rows['exclusions']))
        for source,response in zip(rows['exclusions'],hosted['exclusions'],strict=True):
            self.assertEqual(response['record']['publicExtract']['samNumber'],source['exclusion_id'])
            self.assertTrue(response['file_name'])

    def test_nested_public_baseline_preserves_codes_and_excludes_other_fields(self):
        expected={'businessTypeList':[{'businessTypeCode':'A5'},{'businessTypeCode':'LJ'}]}
        actual={'businessTypeList':[{'businessTypeCode':'A5','privateExtra':'excluded'},{'businessTypeCode':'F'},{'businessTypeCode':'LJ'}],'privateSection':'excluded'}
        baseline=module.public_baseline(expected,actual)
        self.assertEqual([item['businessTypeCode'] for item in baseline['businessTypeList']],['A5','F','LJ'])
        self.assertNotIn('private',json.dumps(baseline))

    def test_live_comparison_refuses_other_cage_for_same_uei(self):
        from sam_gov_mcp import server
        from sam_entity_extract import iter_rows
        entity=ROOT/'tests/fixtures/sam_public/entities.dat'
        exclusion=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv'
        replay=module.run(entity,exclusion)
        sources={row['uei']:row for row in iter_rows(entity)}
        async def wrong_cage(uei,**kwargs):
            row=sources[uei]
            record=json.loads(json.dumps(row['record_json']))
            record['entityRegistration']['cageCode']='ZZZZZ'
            return {'totalRecords':1,'entityData':[record]}
        async def empty(*args,**kwargs): return {'totalRecords':0,'excludedEntity':[]}
        with patch.object(server,'lookup_entity_by_uei',wrong_cage), patch.object(server,'check_exclusion_by_uei',empty), patch.object(server,'search_exclusions',empty):
            result=asyncio.run(module.live_comparison(replay,entity,exclusion,'SIMULATED_EXISTING_KEY'))
        self.assertFalse(result['passed'])
        self.assertTrue(any(error.get('identity_strategy')=='UEI+CAGE' for error in result['errors']))

    def test_ambiguous_duplicate_registration_never_counts_as_parity(self):
        from sam_gov_mcp import server
        entity=ROOT/'tests/fixtures/sam_public/entities.dat'
        exclusion=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv'
        replay=module.run(entity,exclusion)
        rows,hosted=module.hosted_pool(entity,exclusion)
        sources={row['uei']:item['record'] for row,item in zip(rows['entities'],hosted['entities'],strict=True)}
        async def duplicate(uei,**kwargs):
            return {'totalRecords':2,'entityData':[sources[uei],sources[uei]]}
        async def empty(*args,**kwargs):return {'totalRecords':0,'excludedEntity':[]}
        with patch.object(server,'lookup_entity_by_uei',duplicate),patch.object(server,'check_exclusion_by_uei',empty),patch.object(server,'search_exclusions',empty):
            result=asyncio.run(module.live_comparison(replay,entity,exclusion,'SIMULATED_EXISTING_KEY'))
        self.assertEqual(result['selected_records']['entities'],0)
        self.assertTrue(any(error.get('eligible_records')==2 for error in result['errors']))

    def test_existing_key_file_requires_unambiguous_sam_assignment(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'keys.txt'
            path.write_text('Other: SOME_OTHER_SERVICE_KEY_123456789\n')
            with self.assertRaises(ValueError): module.existing_key(path)
            path.write_text('SAM.gov: SIMULATED_EXISTING_KEY_123456789\n')
            self.assertEqual(module.existing_key(path),'SIMULATED_EXISTING_KEY_123456789')

    def test_real_extract_cross_runtime_replay(self):
        report = module.run(ROOT/'tests/fixtures/sam_public/entities.dat',
                            ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv')
        self.assertTrue(report['passed'])
        self.assertEqual(report['mismatched_fields'],0)
        self.assertEqual(sum(row['kind']=='entities' for row in report['records']),22)
        self.assertEqual(sum(row['kind']=='exclusions' for row in report['records']),12)
        self.assertEqual({row['local_request']['tool'] for row in report['records']},
                         {'lookup_entity_by_uei','lookup_entity_by_cage','search_entities','check_exclusion_by_uei','search_exclusions'})
        self.assertFalse(report['live_api_parity_verified'])
        self.assertFalse(report['credential_used'])
        self.assertEqual(report['network_requests'],0)
        self.assertGreater(report['matched_fields'],1000)

if __name__=='__main__':
    unittest.main()
