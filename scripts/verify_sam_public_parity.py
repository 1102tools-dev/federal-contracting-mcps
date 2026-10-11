"""Keyless cross-runtime public-extract replay verification.

This runs the actual local Python tools with a patched _get transport and the
actual hosted TypeScript handlers against SQLite using the production schema.
It is NOT live-API parity: the local transport receives public-file projections,
so independent agreement with SAM's live API cannot be established by this run.
Default replay reads no credential and makes no network request. Optional --live
requires explicit authorization and an existing local key; it uses only public
entity/exclusion API sections and retains shared public fields, never the key.
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import datetime as dt
import subprocess
import sys
import tempfile
from unittest.mock import patch
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'servers/sam-gov-mcp/src'))


def leaves(value, path=''):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f'{path}.{key}' if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, f'{path}[{index}]')
        if not value:
            yield path, value
    else:
        yield path, value


def compare(expected, actual):
    """Fail for removed, added, or changed fields, including explicit nulls."""
    left, right = dict(leaves(expected)), dict(leaves(actual))
    paths = sorted(set(left) | set(right))
    errors = [{'field': key, 'expected': left.get(key), 'actual': right.get(key),
               'expected_present': key in left, 'actual_present': key in right}
              for key in paths if key not in left or key not in right or left[key] != right[key]]
    return len(paths) - len(errors), errors


NODE = r'''
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import './src/tools.ts';
import {searchEntities} from './src/entity-tools.ts';
import {searchExclusions} from './src/exclusion-tools.ts';
const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const sqlite = new DatabaseSync(input.database);
const db = {prepare: sql => ({bind: (...values) => ({all: async () => ({results: sqlite.prepare(sql).all(...values)})})})};
const outputs=[];
for(const call of input.calls) outputs.push(await (call.kind==='entities'?searchEntities:searchExclusions)(db,call.args));
console.log(JSON.stringify(outputs));
sqlite.close();
'''


async def local_calls(calls):
    from sam_gov_mcp import server
    outputs, params_seen = [], []
    for call in calls:
        async def replay(path, params):
            tool = ('lookup_entity_by_uei' if 'uei' in call['args'] else 'lookup_entity_by_cage' if 'cage_code' in call['args'] else 'search_entities') if call['kind']=='entities' else ('check_exclusion_by_uei' if 'uei' in call['args'] else 'search_exclusions')
            params_seen.append({'kind':call['kind'], 'tool':tool, 'path':path, 'params':dict(params)})
            return copy.deepcopy(call['expected'])
        with patch.object(server, '_get', replay):
            if call['kind'] == 'entities':
                if 'uei' in call['args']:
                    result = await server.lookup_entity_by_uei(call['args']['uei'], include_sections=['All'])
                elif 'cage_code' in call['args']:
                    result = await server.lookup_entity_by_cage(call['args']['cage_code'], include_sections=['All'])
                else:
                    result = await server.search_entities(**call['local_args'])
            elif 'uei' in call['args']:
                result = await server.check_exclusion_by_uei(call['args']['uei'])
            else:
                result = await server.search_exclusions(**call['args'])
        outputs.append(result)
    return outputs, params_seen


def run(entity_file, exclusion_file, entity_count=20, exclusion_count=10):
    from load_sam_public import prepare
    from sam_entity_extract import iter_rows as entities
    from sam_exclusion_extract import iter_rows as exclusions
    rows = {'entities':list(entities(entity_file)), 'exclusions':list(exclusions(exclusion_file))}
    if len(rows['entities']) < entity_count or len(rows['exclusions']) < exclusion_count:
        raise ValueError('Insufficient real fixture records for requested replay coverage')
    calls = []
    entity_date = dt.datetime.strptime(entity_file.read_text(encoding='utf-8').splitlines()[0].split()[4], '%Y%m%d').date().isoformat()
    source_metadata = {'entities':(f"SAM_PUBLIC_UTF-8_MONTHLY_V2_{entity_date.replace('-', '')}.ZIP",entity_date), 'exclusions':('SAM_Exclusions_Public_Extract_V2_26283.ZIP','2026-10-10')}
    for kind, minimum in [('entities',entity_count),('exclusions',exclusion_count)]:
        seen=set()
        for row in rows[kind]:
            identifier = row['uei'] if kind=='entities' else row['exclusion_id']
            if identifier in seen: continue
            seen.add(identifier)
            args = {'uei':row['uei']} if row['uei'] else {'entity_name':row['name']}
            matching = [item for item in rows[kind] if item['uei']==row['uei']] if row['uei'] else [item for item in rows[kind] if row['name'].lower() in item['name'].lower()]
            matching.sort(key=lambda item: ((item.get('legal_business_name') or item.get('name') or '').casefold(),item['uei'] or '',item.get('exclusion_id',item.get('entity_id',''))))
            key = 'entityData' if kind=='entities' else 'excludedEntity'
            expected = {'totalRecords':len(matching),key:[item['record_json'] for item in matching]}
            if kind=='entities': args['include_sections']=['All']
            calls.append({'kind':kind,'identifier':identifier,'args':args,'expected':expected})
            if len(seen)>=minimum: break
    # Exercise CAGE and named-search entry points as well as UEI routes.
    for kind in ('entities','exclusions'):
        for field in ('cage_code','legal_business_name' if kind=='entities' else 'entity_name'):
            column = field if kind=='entities' else ('name' if field=='entity_name' else field)
            row = next(item for item in rows[kind] if item.get(column) and
                       len([x for x in rows[kind] if x.get(column)==item[column]])==1 and
                       (kind!='entities' or item['registration_status']=='Active') and
                       not any(char in item[column] for char in '&()|{}^\\'))
            args={field:row[column]}
            if kind=='entities': args['include_sections']=['All']
            key='entityData' if kind=='entities' else 'excludedEntity'
            calls.append({'kind':kind,'identifier':row.get('uei') or row['exclusion_id'],
                          'args':args,'local_args':args,
                          'expected':{'totalRecords':1,key:[row['record_json']]}})
    with tempfile.TemporaryDirectory(prefix='sam-public-parity-') as temp:
        database = Path(temp)/'parity.sqlite'
        prepare('entities',entity_file,database)
        prepare('exclusions',exclusion_file,database)
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript((ROOT/'deploy/sam-gov/entity-schema.sql').read_text())
            for kind,path in [('entities',entity_file),('exclusions',exclusion_file)]:
                db.execute('INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)',
                           (kind,*source_metadata[kind],'public-file-fixture','2026-10-11T00:00:00Z',len(rows[kind]),hashlib.sha256(path.read_bytes()).hexdigest(),database.stat().st_size,0))
        payload=Path(temp)/'input.json'
        payload.write_text(json.dumps({'database':str(database),'calls':calls}))
        # Script resides beside src because native Node TypeScript resolves relative imports.
        with tempfile.NamedTemporaryFile(mode='w',suffix='.ts',prefix='.parity-',dir=ROOT/'deploy/sam-gov',delete=False) as script:
            script.write(NODE); script_path=Path(script.name)
        try:
            process=subprocess.run(['node',str(script_path),str(payload)],capture_output=True,text=True)
            if process.returncode:
                raise RuntimeError(process.stderr)
            hosted=json.loads(process.stdout)
        finally:
            script_path.unlink(missing_ok=True)
        local,params=asyncio.run(local_calls(calls))
    report={'mode':'public_extract_transport_replay','live_api_parity_verified':False,
            'credential_used':False,'network_requests':0,
            'limitations':[
                'The local _get transport is patched with public-file API-style projections; this does not compare against an independently obtained live API response.',
                'Live API may include opt-out entities, newer dates/status, extra sections/POCs, distinct nested field naming, and duplicate registrations unavailable in the public monthly file.',
                'Replay confirms actual local tool invocation, public normalization preservation, hosted query execution and every projected field; live-versus-public differences remain unmeasured.'
            ],'fixtures':{},'records':[],'matched_fields':0,'mismatched_fields':0}
    for kind,path in [('entities',entity_file),('exclusions',exclusion_file)]:
        report['fixtures'][kind]={'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows':len(rows[kind]),'source_file':source_metadata[kind][0],'source_date':source_metadata[kind][1]}
    for call,left,right,param in zip(calls,local,hosted,params,strict=True):
        key='entityData' if call['kind']=='entities' else 'excludedEntity'
        matched,errors=compare({k:left[k] for k in ('totalRecords',key)},{k:right[k] for k in ('totalRecords',key)})
        report['matched_fields']+=matched; report['mismatched_fields']+=len(errors)
        report['records'].append({'kind':call['kind'],'identifier':call['identifier'],
                                  'matched_fields':matched,'mismatches':errors,'local_request':param,
                                  'source_file':right.get('file_name',right.get('source_file')),
                                  'file_date':right.get('file_date')})
        if not report['records'][-1]['source_file'] or not right.get('file_date'):
            raise AssertionError('Hosted response must identify source file and date')
    report['passed']=report['mismatched_fields']==0
    return report


def hosted_pool(entity_file,exclusion_file):
    """Load every real fixture through the actual loader, then invoke TS handlers."""
    from load_sam_public import prepare
    from sam_entity_extract import iter_rows as entities
    from sam_exclusion_extract import iter_rows as exclusions
    with tempfile.TemporaryDirectory(prefix='sam-hosted-pool-') as temporary:
        folder=Path(temporary)
        lines=entity_file.read_text().splitlines()
        entity_lines=lines[1:-1]
        extra=ROOT/'tests/fixtures/sam_public/entities-extra.dat'
        if extra.is_file(): entity_lines.extend(extra.read_text().splitlines()[1:-1])
        entity_lines=list(dict.fromkeys(entity_lines))
        header=lines[0].split();header[5]=f'{len(entity_lines):07}'
        combined_header=' '.join(header)
        combined_entities=folder/'entities.dat'
        combined_entities.write_text(combined_header+'\n'+'\n'.join(entity_lines)+'\nEOF'+combined_header[3:]+'\n')
        with exclusion_file.open(newline='') as stream:
            content=list(csv.reader(stream))
        exclusion_lines=content[1:];known={row[27] for row in exclusion_lines}
        pool=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_firms.csv'
        if pool.is_file():
            with pool.open(newline='') as stream:
                for row in list(csv.reader(stream))[1:]:
                    if row[27] not in known: exclusion_lines.append(row);known.add(row[27])
        combined_exclusions=folder/'exclusions.csv'
        with combined_exclusions.open('w',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(content[0]);writer.writerows(exclusion_lines)
        rows={'entities':list(entities(combined_entities)),'exclusions':list(exclusions(combined_exclusions))}
        database=folder/'public.sqlite'
        prepare('entities',combined_entities,database);prepare('exclusions',combined_exclusions,database)
        calls=[]
        for kind in ('entities','exclusions'):
            for row in rows[kind]:
                args={'uei':row['uei']} if row['uei'] else {'entity_name':row['name']}
                if row.get('cage_code'):args['cage_code']=row['cage_code']
                if kind=='entities':args['include_sections']=['All']
                else:
                    args.update({name:row[column] for name,column in [('entity_name','name'),('classification','classification'),('exclusion_program','exclusion_program'),('excluding_agency_code','excluding_agency_code')] if row.get(column)})
                calls.append({'kind':kind,'args':args})
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript((ROOT/'deploy/sam-gov/entity-schema.sql').read_text())
            for kind in ('entities','exclusions'):
                name='SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP' if kind=='entities' else 'SAM_Exclusions_Public_Extract_V2_26283.ZIP'
                date='2026-10-05' if kind=='entities' else '2026-10-10'
                db.execute('INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)',(kind,name,date,'public-file-fixtures','2026-10-11T00:00:00Z',len(rows[kind]),'fixture',database.stat().st_size,0))
        payload=folder/'input.json';payload.write_text(json.dumps({'database':str(database),'calls':calls}))
        with tempfile.NamedTemporaryFile(mode='w',suffix='.ts',prefix='.parity-',dir=ROOT/'deploy/sam-gov',delete=False) as script:
            script.write(NODE);script_path=Path(script.name)
        try:
            process=subprocess.run(['node',str(script_path),str(payload)],capture_output=True,text=True)
            if process.returncode:raise RuntimeError(process.stderr)
            responses=json.loads(process.stdout)
        finally:script_path.unlink(missing_ok=True)
    index=0;hosted={}
    for kind in ('entities','exclusions'):
        hosted[kind]=[]
        key='entityData' if kind=='entities' else 'excludedEntity'
        for row in rows[kind]:
            response=responses[index];call=calls[index];index+=1
            candidates=response[key]
            if kind=='exclusions':
                candidate=next((item for item in candidates if item.get('publicExtract',{}).get('samNumber')==row['exclusion_id']),None)
            else:
                candidate=next((item for item in candidates if item.get('entityRegistration',{}).get('ueiSAM')==row['uei'] and item.get('entityRegistration',{}).get('cageCode')==row.get('cage_code') and item.get('entityRegistration',{}).get('registrationDate')==row.get('registration_date')),None)
            if candidate is None:raise AssertionError('Actual hosted query did not return the source identity')
            hosted[kind].append({'record':candidate,'totalRecords':response['totalRecords'],'query':call['args'],'file_name':response.get('file_name'),'file_date':response.get('file_date')})
    return rows,hosted


def public_baseline(expected,actual):
    """Retain nested public shared paths and complete code arrays, no other sections."""
    if isinstance(expected,dict) and isinstance(actual,dict):
        return {key:public_baseline(value,actual[key]) for key,value in expected.items() if key in actual}
    if isinstance(expected,list) and isinstance(actual,list):
        templates=[item for item in expected if isinstance(item,dict)]
        if templates:
            template={key:value for item in templates for key,value in item.items()}
            return [public_baseline(template,item) for item in actual]
        return actual if not actual else []
    return actual


def normalize_public(value):
    """Normalize unordered code arrays and API date/text presentation only."""
    if isinstance(value,dict):
        return {key:normalize_public(item) for key,item in value.items()}
    if isinstance(value,list):
        result=[normalize_public(item) for item in value]
        if result and all(isinstance(item,dict) for item in result):
            key=next((key for key in ('naicsCode','businessTypeCode','sbaBusinessTypeCode') if all(key in item for item in result)),None)
            if key: return {str(item[key]):item for item in sorted(result,key=lambda item:str(item[key]))}
        return result
    if isinstance(value,str):
        if re.fullmatch(r'\d{2}-\d{2}-\d{4}',value):
            try:return dt.datetime.strptime(value,'%m-%d-%Y').date().isoformat()
            except ValueError:pass
        return value.casefold()
    return value


def code_sets(value,path=''):
    result={}
    if isinstance(value,dict):
        for key,item in value.items(): result.update(code_sets(item,f'{path}.{key}' if path else key))
    elif isinstance(value,list):
        name=path.rsplit('.',1)[-1]
        key={'naicsList':'naicsCode','businessTypeList':'businessTypeCode','sbaBusinessTypeList':'sbaBusinessTypeCode'}.get(name)
        if key:
            result[path]=sorted({str(item[key]).upper() for item in value if isinstance(item,dict) and item.get(key) not in (None,'')})
    return result


def code_differences(public,live):
    source_sets,live_sets=code_sets(public),code_sets(live)
    return [{'field':field,'public':source_sets.get(field,[]),'live':live_sets.get(field,[]),
             'classification':'API enrichment' if set(source_sets.get(field,[]))<=set(live_sets.get(field,[])) else 'source/live code-set difference'}
            for field in sorted(set(source_sets)|set(live_sets)) if source_sets.get(field,[])!=live_sets.get(field,[])]


def existing_key(path):
    """Use only an existing SAM-labelled assignment, without printing its value."""
    for line in path.read_text().splitlines():
        if re.search(r'\bSAM(?:\.gov)?\b|SAM_API_KEY', line, re.I):
            parts=re.split(r'[:=]',line,maxsplit=1)
            if len(parts)==2:
                tokens=re.findall(r'[A-Za-z0-9_-]{20,}',parts[1])
                if len(tokens)==1:
                    return tokens[0]
    raise ValueError('No unambiguous existing SAM key assignment found in supplied local file')


async def live_comparison(replay,entity_file,exclusion_file,key,output_path=None):
    from sam_gov_mcp import server
    from sam_entity_extract import iter_rows as entities
    from sam_exclusion_extract import iter_rows as exclusions
    rows,hosted=hosted_pool(entity_file,exclusion_file)
    pool=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_firms.csv'
    report={'mode':'live_api_public_shared_field_comparison','live_api_parity_verified':False,
            'credential_source':'existing_local_SAM_key_ephemeral_process_only',
            'strict_sample_target':{'entities':20,'exclusions':10},'records':[],'selected_records':{'entities':0,'exclusions':0},'attempted_records':{'entities':0,'exclusions':0},
            'matched_fields':0,'mismatched_fields':0,'raw_matched_fields':0,'raw_mismatched_fields':0,'public_only_fields':0,'errors':[],
            'limitations':['Live responses are restricted to entityRegistration/coreData/assertions and exclusions. Only shared public projected fields are saved; no POCs or private extra sections are requested or saved.',
                           'Monthly entities and daily exclusions may differ from current live API. Exact differences are recorded; source-only fields are counted separately from shared field mismatches.']}
    report['candidate_pool']={'entities':len(rows['entities']),'exclusions':len(rows['exclusions'])}
    if pool.is_file(): report['extra_exclusion_fixture']={'path':str(pool.relative_to(ROOT)),'sha256':hashlib.sha256(pool.read_bytes()).hexdigest()}
    selected_identities=set()
    for kind,minimum in [('entities',20),('exclusions',10)]:
        provenance=next(item for item in replay['records'] if item['kind']==kind)
        for row,hosted_item in zip(rows[kind],hosted[kind],strict=True):
            if report['selected_records'][kind]>=minimum: break
            report['attempted_records'][kind]+=1
            item={'source_file':provenance['source_file'],'file_date':provenance['file_date']}
            identifier=row['uei']
            try:
                with patch.dict(os.environ,{'SAM_API_KEY':key}):
                    response=await (server.lookup_entity_by_uei(identifier,include_sections=['entityRegistration','coreData','assertions']) if kind=='entities' else server.check_exclusion_by_uei(identifier) if identifier else server.search_exclusions(entity_name=row['name']))
                collection='entityData' if kind=='entities' else 'excludedEntity'
                candidates=response.get(collection,[])
                if isinstance(candidates,dict): candidates=[candidates]
                if not candidates:
                    report['errors'].append({'kind':kind,'identifier':identifier,'error':'No live record returned','totalRecords':response.get('totalRecords')})
                    continue
                source_count=sum(x.get('uei')==row.get('uei') for x in rows[kind]) if row.get('uei') else sum(x.get('name')==row.get('name') for x in rows[kind])
                identity_strategy='UEI+CAGE' if kind=='entities' and row.get('cage_code') else 'UEI (source CAGE unavailable)' if kind=='entities' else 'UEI/name+activation date (API has no SAM source ID)'
                eligible=[]
                for candidate in candidates:
                    registration=candidate.get('entityRegistration',{}) if kind=='entities' else candidate.get('exclusionIdentification',{})
                    if identifier and str(registration.get('ueiSAM','')).upper()!=identifier.upper(): continue
                    if kind=='entities':
                        if row.get('cage_code') and str(registration.get('cageCode','')).upper()!=row['cage_code'].upper(): continue
                    else:
                        api_id=registration.get('samNumber') or registration.get('exclusionId')
                        if api_id:
                            if str(api_id)!=row['exclusion_id']: continue
                            identity_strategy='exact source SAM ID'
                        else:
                            api_name=registration.get('entityName') or ' '.join(str(registration.get(key) or '') for key in ('firstName','middleName','lastName','suffix')).strip()
                            if ' '.join(api_name.split()).casefold()!=' '.join(row['name'].split()).casefold(): continue
                            if row.get('cage_code') and str(registration.get('cageCode','')).upper()!=row['cage_code'].upper(): continue
                            details=candidate.get('exclusionDetails',{})
                            if any(normalize_public(details.get(api_key))!=normalize_public(row.get(source_key)) for api_key,source_key in [('excludingAgencyCode','excluding_agency_code'),('exclusionProgram','exclusion_program'),('exclusionType','exclusion_type')]): continue
                            actions=candidate.get('exclusionActions',{}).get('listOfActions',[])
                            matching_actions=[action for action in actions if normalize_public(action.get('activateDate'))==row.get('activation_date') and normalize_public(action.get('terminationDate'))==row.get('termination_date') and normalize_public(action.get('recordStatus'))==normalize_public(row.get('record_status'))]
                            if len(matching_actions)!=1: continue
                            candidate=copy.deepcopy(candidate)
                            candidate['exclusionActions']['listOfActions']=matching_actions[:1]
                    eligible.append(candidate)
                if not eligible:
                    report['errors'].append({'kind':kind,'identifier':identifier or row.get('exclusion_id'),'error':'No exact source identity/action matched live records','identity_strategy':identity_strategy,'live_totalRecords':response.get('totalRecords')})
                    continue
                if len(eligible)!=1:
                    report['errors'].append({'kind':kind,'identifier':identifier or row.get('exclusion_id'),'error':'Ambiguous multiple live records satisfy source identity/action','eligible_records':len(eligible)})
                    continue
                candidates=eligible
                # Exact UEI returns may have multiple registrations. Preserve counts and
                # compare each candidate; choose the record with the most exact matches.
                raw_expected=dict(leaves(hosted_item['record']))
                expected=dict(leaves(normalize_public(hosted_item['record'])))
                comparisons=[]
                for candidate in candidates:
                    actual=dict(leaves(normalize_public(candidate)))
                    common=sorted(set(expected)&set(actual))
                    matched=sum(expected[field]==actual[field] for field in common)
                    mismatch=[{'field':field,'public':expected[field],'live':actual[field]} for field in common if expected[field]!=actual[field]]
                    comparisons.append((matched,len(common),mismatch,common,actual,candidate))
                matched,shared,mismatch,common,actual,candidate=max(comparisons,key=lambda result:(result[0],result[1]))
                minimum_shared=20 if kind=='entities' else 15
                if shared<minimum_shared:
                    report['errors'].append({'kind':kind,'identifier':identifier or row.get('exclusion_id'),'error':'Too few shared public fields to establish substantive parity','shared_fields':shared,'minimum':minimum_shared})
                    continue
                raw_actual=dict(leaves(candidate))
                raw_common=sorted(set(raw_expected)&set(raw_actual))
                raw_mismatch=[{'field':field,'public':raw_expected[field],'live':raw_actual[field]} for field in raw_common if raw_expected[field]!=raw_actual[field]]
                raw_matched=len(raw_common)-len(raw_mismatch)
                code_changes=code_differences(hosted_item['record'],candidate)
                missing=sorted(set(expected)-set(actual))
                record={'kind':kind,'identifier':(identifier or row.get('exclusion_id')),'live_totalRecords':response.get('totalRecords'),'public_fixture_records_for_identifier':source_count,'identity_strategy':identity_strategy,
                        'source_file':item['source_file'],'file_date':item['file_date'],
                        'matched_fields':matched,'mismatches':mismatch,'raw_matched_fields':raw_matched,'raw_mismatches':raw_mismatch,'code_set_differences':code_changes,'public_only_fields':missing,
                        'shared_public_baseline':{field:raw_actual[field] for field in raw_common},
                        'live_public_baseline':public_baseline(hosted_item['record'],candidate),
                        'hosted_public_baseline':hosted_item['record'],'hosted_query':hosted_item['query'],'hosted_totalRecords':hosted_item['totalRecords']}
                identity=(kind,identifier) if kind=='entities' else (kind,identifier or row['name'],row.get('cage_code'),row.get('excluding_agency_code'),row.get('exclusion_program'),row.get('exclusion_type'),row.get('activation_date'),row.get('termination_date'),row.get('record_status'))
                record['duplicate_selected_identity']=identity in selected_identities
                record['selected_for_strict_parity']=not mismatch and not record['duplicate_selected_identity'] and all(change['classification']=='API enrichment' for change in code_changes)
                if record['selected_for_strict_parity']:
                    report['selected_records'][kind]+=1
                    selected_identities.add(identity)
                report['records'].append(record)
                report['matched_fields']+=matched;report['mismatched_fields']+=len(mismatch);report['public_only_fields']+=len(missing)
                report['raw_matched_fields']+=raw_matched;report['raw_mismatched_fields']+=len(raw_mismatch)
            except Exception as exc:
                # Do not retain exception text or URLs: errors may contain key-bearing
                # transport details. Error type is sufficient to classify availability.
                report['errors'].append({'kind':kind,'identifier':identifier,'error_type':type(exc).__name__})
            if output_path:
                output_path.parent.mkdir(parents=True,exist_ok=True)
                output_path.write_text(json.dumps(report,indent=2)+'\n')
    report['live_completed_records']={kind:sum(r['kind']==kind for r in report['records']) for kind in ['entities','exclusions']}
    report['code_set_difference_records']=sum(bool(row['code_set_differences']) for row in report['records'])
    report['selected_matched_fields']=sum(row['matched_fields'] for row in report['records'] if row['selected_for_strict_parity'])
    report['selected_mismatched_fields']=sum(len(row['mismatches']) for row in report['records'] if row['selected_for_strict_parity'])
    report['passed']=report['selected_records']=={'entities':20,'exclusions':10}
    report['live_api_comparison_completed']=report['selected_records']=={'entities':20,'exclusions':10}
    report['live_api_parity_verified']=report['passed']
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entities-fixture',type=Path,default=ROOT/'tests/fixtures/sam_public/entities.dat')
    parser.add_argument('--exclusions-fixture',type=Path,default=ROOT/'tests/fixtures/sam_public/exclusions_v2_26283_slice.csv')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true',help='Authorized live API comparison using an EXISTING local key only')
    parser.add_argument('--existing-key-file',type=Path)
    args=parser.parse_args()
    report=run(args.entities_fixture,args.exclusions_fixture)
    if args.live:
        if not args.existing_key_file:
            parser.error('--live requires --existing-key-file; never request/create a new key')
        key=existing_key(args.existing_key_file)
        report=asyncio.run(live_comparison(report,args.entities_fixture,args.exclusions_fixture,key,args.output))
        key=None
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('mode','live_api_parity_verified','matched_fields','mismatched_fields','passed')}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
