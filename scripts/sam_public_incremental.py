"""Bounded, resumable public-file deltas. No full D1 copies or hash backfills.

An applying run hides the affected dataset until all record transactions finish.
Failure leaves committed record transactions in place, with the same source SHA
required to resume. This trades whole-file rollback for bounded write cost.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

RUN_SQL = '''CREATE TABLE IF NOT EXISTS public_refresh_runs (
kind TEXT PRIMARY KEY CHECK(kind IN ('entities','exclusions')),
state TEXT NOT NULL CHECK(state IN ('applying','complete')),
target_sha TEXT NOT NULL, parser_sha TEXT NOT NULL,
target_metadata_json TEXT NOT NULL, base_row_count INTEGER NOT NULL,
planned_write_units INTEGER NOT NULL, committed_write_units INTEGER NOT NULL DEFAULT 0,
budget_month TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
owner_token TEXT NOT NULL, owner_expires_at TEXT NOT NULL);'''
BUDGET_SQL = '''CREATE TABLE IF NOT EXISTS public_write_budget (
period TEXT PRIMARY KEY, entity_units INTEGER NOT NULL DEFAULT 0,
exclusion_units INTEGER NOT NULL DEFAULT 0,
CHECK(entity_units>=0 AND entity_units<=4000000),
CHECK(exclusion_units>=0 AND exclusion_units<=5890000),
CHECK(entity_units+exclusion_units<=9900000));'''
DAILY_SQL = '''CREATE TABLE IF NOT EXISTS public_daily_budget (
day TEXT PRIMARY KEY, units INTEGER NOT NULL CHECK(units>=0 AND units<=190000));'''
HASH_SQL = '''CREATE TABLE IF NOT EXISTS public_record_hashes (
kind TEXT NOT NULL CHECK(kind IN ('entities','exclusions')),
record_key TEXT NOT NULL, content_hash TEXT NOT NULL,
PRIMARY KEY(kind,record_key));'''
MANIFEST_ROWS = 1000
RESPONSE_BUDGET = 80_000
BATCH_BYTES = 65_000
MIGRATION_ALLOWANCE = 1000


def digest(row, fields):
    return hashlib.sha256(json.dumps([row.get(k) for k in fields],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def billing_period():
    now=dt.datetime.now(dt.timezone.utc)
    account=os.environ.get('CLOUDFLARE_ACCOUNT_ID') or '846d3e41e48446abcd3570c0959f9fb5'
    request=urllib.request.Request(f'https://api.cloudflare.com/client/v4/accounts/{account}/subscriptions',headers={'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN']})
    with urllib.request.urlopen(request,timeout=120) as response: result=json.load(response)
    if not result.get('success'): raise RuntimeError('Workers billing period unavailable; refusing mutations')
    matches=[s for s in result['result'] if s.get('rate_plan',{}).get('id')=='workers_paid' and s.get('state')=='Paid']
    if len(matches)!=1: raise RuntimeError('Workers Paid subscription ambiguous; refusing mutations')
    start=dt.datetime.fromisoformat(matches[0]['current_period_start'].replace('Z','+00:00'))
    end=dt.datetime.fromisoformat(matches[0]['current_period_end'].replace('Z','+00:00'))
    if not start<=now<end or (now-start).total_seconds()>31*86400:
        raise RuntimeError('Workers billing period outside analytics retention; refusing mutations')
    return {'start':start.isoformat(),'end':end.isoformat()}


def account_month_written(period=None):
    now=dt.datetime.now(dt.timezone.utc)
    period=period or billing_period()
    start=dt.datetime.fromisoformat(period['start'])
    account=os.environ.get('CLOUDFLARE_ACCOUNT_ID') or '846d3e41e48446abcd3570c0959f9fb5'
    query='''query($account:String!,$start:Date!,$end:Date!){viewer{accounts(filter:{accountTag:$account}){d1AnalyticsAdaptiveGroups(limit:10000,filter:{date_geq:$start,date_leq:$end}){sum{rowsWritten} dimensions{databaseId date}}}}}'''
    request=urllib.request.Request('https://api.cloudflare.com/client/v4/graphql',data=json.dumps({'query':query,'variables':{'account':account,'start':start.date().isoformat(),'end':now.date().isoformat()}}).encode(),headers={'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=120) as response: result=json.load(response)
    if result.get('errors') or not result.get('data',{}).get('viewer',{}).get('accounts'):
        raise RuntimeError('Account D1 write analytics unavailable; refusing mutations')
    groups=result['data']['viewer']['accounts'][0].get('d1AnalyticsAdaptiveGroups')
    if not groups:
        raise RuntimeError('Account D1 write analytics missing; refusing mutations')
    if len(groups)>=10000:
        raise RuntimeError('Account analytics truncated; refusing mutations')
    return sum(int(row['sum']['rowsWritten']) for row in groups)


def table_exists(db,name):
    from load_sam_public import quote
    return bool(db.query(f"SELECT name FROM sqlite_master WHERE type='table' AND name={quote(name)}"))


def manifests(db,kind):
    """Small indexed pages; never read the public JSON in the manifest."""
    from load_sam_public import quote
    key='entity_id' if kind=='entities' else 'exclusion_id'
    tracking=table_exists(db,'public_record_hashes')
    hash_column='h.content_hash' if tracking else 'NULL'
    join=f" LEFT JOIN public_record_hashes h ON h.kind={quote(kind)} AND h.record_key=e.{key}" if tracking else ''
    maxima=db.query(f"SELECT MAX(length(e.{key})) AS key_length,MAX(length({hash_column})) AS hash_length"+(',MAX(length(uei)) AS uei_length,MAX(length(cage_code)) AS cage_length' if kind=='entities' else '')+f' FROM {kind} e{join}')[0]
    if (maxima['key_length'] or 0)>64 or (maxima['hash_length'] or 0)>64 or (maxima.get('uei_length') or 0)>14 or (maxima.get('cage_length') or 0)>6:
        raise ValueError('Manifest keys exceed bounded public identifier lengths')
    last=''
    while True:
        extra=',uei,cage_code' if kind=='entities' else ''
        rows=db.query(f'SELECT e.{key},{hash_column} AS content_hash{extra} FROM {kind} e{join} WHERE e.{key}>{quote(last)} ORDER BY e.{key} LIMIT {MANIFEST_ROWS}')
        if not rows: break
        if len(json.dumps(rows,ensure_ascii=False).encode())>1_000_000:
            raise ValueError('Manifest response exceeds1MB bound')
        yield from rows
        last=rows[-1][key]


def projected_rows(db,kind,ids,fields):
    """Bound full-record responses by projected UTF-8 size before fetching."""
    from load_sam_public import quote
    key=fields[0]
    for offset in range(0,len(ids),MANIFEST_ROWS):
        page=ids[offset:offset+MANIFEST_ROWS]
        sizes=db.query(f"SELECT {key}, 2048+2*({' + '.join('length(CAST(COALESCE('+f+",'') AS BLOB))" for f in fields)}) AS bytes FROM {kind} WHERE {key} IN ({','.join(map(quote,page))})")
        batch=[];size=0
        for record in sizes:
            cost=record['bytes']
            if cost>RESPONSE_BUDGET:
                raise ValueError('Legacy normalized record exceeds bounded response budget')
            if batch and size+cost>RESPONSE_BUDGET:
                yield from db.query(f"SELECT {','.join(fields)} FROM {kind} WHERE {key} IN ({','.join(map(quote,batch))})")
                batch=[];size=0
            batch.append(record[key]);size+=cost
        if batch:
            yield from db.query(f"SELECT {','.join(fields)} FROM {kind} WHERE {key} IN ({','.join(map(quote,batch))})")


def memberships(row):
    naics=set(json.loads(row.get('naics_codes_json') or '[]'))
    types={(code,kind) for field,kind in [('business_type_codes_json','business'),('sba_business_type_codes_json','sba')] for code in json.loads(row.get(field) or '[]')}
    return naics,types


def prune_candidates(db,tables):
    expected={'entities':{'2':{'legal_business_name'},'5':{'registration_status'},'6':{'expiration_date'}},'exclusions':{'5':{'activation_date'}}}
    result=[]
    for table in tables:
        for index in db.query(f'PRAGMA index_list({table})'):
            match=re.fullmatch(r'(entities|exclusions)_(2|5|6)(?:_stage_[0-9a-f]{12})?',index['name'])
            if not match or match[1]!=table or match[2] not in expected.get(table,{}):continue
            columns={r['name'] for r in db.query(f"PRAGMA index_info({index['name']})")}
            if columns!=expected[table][match[2]] or index.get('partial'):
                raise ValueError('Prunable index definition unexpected; refusing mutations')
            result.append(index['name'])
    return result


def index_columns(db,tables,ignore=()):
    """Inspect all actual indexes, including SQLite PK autoindexes."""
    result={}
    objects=db.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE type IN ('trigger','table')")
    if any(row['type']=='trigger' or (row['tbl_name'] in tables and 'CREATE VIRTUAL TABLE' in (row['sql'] or '').upper()) for row in objects):
        raise ValueError('Unmodeled trigger/virtual-table writes; refusing incremental mutations')
    for table in tables:
        result[table]=[]
        for index in db.query(f'PRAGMA index_list({table})'):
            if index['name'] in ignore:continue
            name=index['name']
            if not re.fullmatch(r'[A-Za-z0-9_]+',name): raise ValueError('Unexpected index name')
            columns=db.query(f'PRAGMA index_info({name})')
            from sam_public_cost_oracle import DBA_INDEX_NAME,known_dba_partial_index
            if any(r['name'] is None for r in columns):
                raise ValueError('Unmodeled partial/expression index writes; refusing incremental mutations')
            if index.get('partial') or name==DBA_INDEX_NAME:
                sql=db.query(f"SELECT sql FROM sqlite_master WHERE type='index' AND name='{name}'")[0]['sql']
                if not index.get('partial') or not known_dba_partial_index(name,table,[r['name'] for r in columns],sql):
                    raise ValueError('Unmodeled partial/expression index writes; refusing incremental mutations')
            result[table].append({r['name'] for r in columns})
    return result


def record_delta(kind,old,new,fields,indexes,new_hash):
    from load_sam_public import quote
    key=fields[0];stable_id=(old or new)[key]
    statements=[];units=0
    if old is None:
        payload=dict(new)
        statements.append(f"INSERT INTO {kind} ({','.join(payload)}) VALUES ({','.join(quote(v) for v in payload.values())});")
        units+=1+len(indexes[kind])
    elif new is not None:
        changed={f:new[f] for f in fields[1:] if old[f]!=new[f]}
        if changed:
            statements.append(f"UPDATE {kind} SET {','.join(f+'='+quote(v) for f,v in changed.items())} WHERE {key}={quote(stable_id)};")
            units+=1+2*sum(bool(set(changed)&cols) for cols in indexes[kind])
    if kind=='entities':
        before=memberships(old) if old else (set(),set())
        after=memberships(new) if new else (set(),set())
        for table,b,a in [('entity_naics',before[0],after[0]),('entity_business_types',before[1],after[1])]:
            for value in sorted(b-a):
                code,k=(value,None) if table=='entity_naics' else value
                statements.append(f'DELETE FROM {table} WHERE entity_id={quote(stable_id)} AND code={quote(code)}'+(f' AND kind={quote(k)}' if k else '')+';')
                units+=1+2*len(indexes[table])
            for value in sorted(a-b):
                values=[stable_id,value] if table=='entity_naics' else [stable_id,*value]
                statements.append(f"INSERT INTO {table} VALUES ({','.join(map(quote,values))});")
                units+=1+len(indexes[table])
    if new is None:
        statements.append(f'DELETE FROM {kind} WHERE {key}={quote(stable_id)};')
        units+=1+2*len(indexes[kind])
        statements.append(f'DELETE FROM public_record_hashes WHERE kind={quote(kind)} AND record_key={quote(stable_id)};')
        units+=2
    else:
        statements.append(f"INSERT INTO public_record_hashes VALUES ({quote(kind)},{quote(stable_id)},{quote(new_hash)}) ON CONFLICT(kind,record_key) DO UPDATE SET content_hash=excluded.content_hash;")
        units+=2
    return statements,units


def plan(db,kind,prepared_path,plan_path,allow_prune=True):
    """Disk-backed manifest/delta plan. No remote writes or digest bootstrap."""
    from load_sam_public import ENTITY_FIELDS,EXCLUSION_FIELDS
    fields=ENTITY_FIELDS if kind=='entities' else EXCLUSION_FIELDS
    key=fields[0];tables=[kind]+(['entity_naics','entity_business_types'] if kind=='entities' else [])
    prune=prune_candidates(db,tables) if allow_prune else []
    indexes=index_columns(db,tables,prune)
    local=sqlite3.connect(prepared_path);local.row_factory=sqlite3.Row
    work=sqlite3.connect(plan_path);work.row_factory=sqlite3.Row
    work.executescript('CREATE TABLE manifest(id TEXT PRIMARY KEY,identity TEXT UNIQUE,hash TEXT); CREATE TABLE pending(old_id TEXT PRIMARY KEY,new_id TEXT,hash TEXT); CREATE TABLE delta(seq INTEGER PRIMARY KEY,sql_json TEXT,units INTEGER,action TEXT);')
    try:
        for row in manifests(db,kind):
            identity=json.dumps([row.get('uei'),row.get('cage_code')],separators=(',',':')) if kind=='entities' else row[key]
            work.execute('INSERT INTO manifest VALUES (?,?,?)',(row[key],identity,row['content_hash'] or (row[key] if kind=='entities' else None)))
        if kind=='exclusions':
            missing=[r['id'] for r in work.execute('SELECT id FROM manifest WHERE hash IS NULL')]
            for row in projected_rows(db,kind,missing,fields): work.execute('UPDATE manifest SET hash=? WHERE id=?',(digest(row,fields),row[key]))
        counts={'inserted':0,'changed':0,'removed':0,'unchanged':0}
        for source in local.execute(f'SELECT * FROM {kind}'):
            new=dict(source)
            identity=json.dumps([new['uei'],new['cage_code']],separators=(',',':')) if kind=='entities' else new[key]
            current=work.execute('SELECT * FROM manifest WHERE identity=?',(identity,)).fetchone()
            new_hash=new[key] if kind=='entities' else digest(new,fields)
            if current:
                work.execute('DELETE FROM manifest WHERE id=?',(current['id'],))
                if current['hash']==new_hash:
                    counts['unchanged']+=1;continue
                work.execute('INSERT INTO pending VALUES (?,?,?)',(current['id'],new[key],new_hash));counts['changed']+=1
            else:
                statements,units=record_delta(kind,None,new,fields,indexes,new_hash)
                work.execute('INSERT INTO delta(sql_json,units,action) VALUES (?,?,?)',(json.dumps(statements),units,'inserted'));counts['inserted']+=1
        for ids in iter_pages(work.execute('SELECT old_id FROM pending ORDER BY old_id'),MANIFEST_ROWS):
            for old in projected_rows(db,kind,[r['old_id'] for r in ids],fields):
                pending=work.execute('SELECT * FROM pending WHERE old_id=?',(old[key],)).fetchone()
                new=dict(local.execute(f'SELECT * FROM {kind} WHERE {key}=?',(pending['new_id'],)).fetchone())
                statements,units=record_delta(kind,old,new,fields,indexes,pending['hash'])
                work.execute('INSERT INTO delta(sql_json,units,action) VALUES (?,?,?)',(json.dumps(statements),units,'changed'))
        for ids in iter_pages(work.execute('SELECT id FROM manifest ORDER BY id'),MANIFEST_ROWS):
            for old in projected_rows(db,kind,[r['id'] for r in ids],fields):
                statements,units=record_delta(kind,old,None,fields,indexes,None)
                work.execute('INSERT INTO delta(sql_json,units,action) VALUES (?,?,?)',(json.dumps(statements),units,'removed'));counts['removed']+=1
        work.commit()
        return counts,indexes,prune
    finally:local.close();work.close()


def iter_pages(iterator,size):
    batch=[]
    for row in iterator:
        batch.append(row)
        if len(batch)==size:yield batch;batch=[]
    if batch:yield batch


def batches(connection):
    statements=[];units=0;size=0
    for row in connection.execute('SELECT * FROM delta ORDER BY seq'):
        items=json.loads(row['sql_json']);cost=sum(len(s.encode())+1 for s in items)
        if cost>BATCH_BYTES: raise ValueError('Registration transaction exceeds bounded SQL budget')
        if statements and size+cost>BATCH_BYTES:
            yield statements,units+10
            statements=[];units=0;size=0
        statements.extend(items);units+=row['units'];size+=cost
    if statements:yield statements,units+10


def incremental_load(db,kind,path,metadata,allow_small=False,diagnostic_max_writes=None,*,oracle=None,authorized_round=False):
    from load_sam_public import prepare,refuse_leftovers,file_sha256,validate_count,quote,ROOT,STATUS_SQL,table_sql
    start=time.monotonic()
    if getattr(db,'target',None)=='remote' and oracle is None:
        raise ValueError('Remote writes require a full local production-copy cost oracle')
    refuse_leftovers(db)
    if getattr(db,'target',None)=='remote' and kind=='exclusions' and not zipfile.is_zipfile(path):
        raise ValueError('Remote exclusions require intact source ZIP')
    sha=file_sha256(path)
    parser_sha=file_sha256(ROOT/'scripts'/('sam_entity_extract.py' if kind=='entities' else 'sam_exclusion_extract.py'))
    active=db.query(f"SELECT * FROM public_refresh_runs WHERE kind={quote(kind)}") if table_exists(db,'public_refresh_runs') else []
    if active and active[0]['state']=='applying' and (active[0]['target_sha'],active[0]['parser_sha'])!=(sha,parser_sha):
        raise ValueError('Incomplete refresh requires the identical source ZIP and parser to resume')
    if active and active[0]['state']=='applying' and json.loads(active[0]['target_metadata_json'])!=metadata:
        raise ValueError('Incomplete refresh requires identical source provenance metadata')
    if active and active[0]['state']=='applying' and active[0].get('owner_expires_at','')>dt.datetime.now(dt.timezone.utc).isoformat():
        raise ValueError('Another refresh owns an unexpired lease; do not resume concurrently')
    with tempfile.TemporaryDirectory(prefix='sam-delta-') as directory:
        prepared=Path(directory)/'prepared.sqlite';plan_path=Path(directory)/'plan.sqlite';audit={}
        count,_=prepare(kind,path,prepared,audit)
        exists=table_exists(db,kind)
        if not exists: raise ValueError('Incremental loader requires initialized public schema; no full-copy bootstrap')
        current=db.query(f'SELECT COUNT(*) AS n FROM {kind}')[0]['n']
        current_status=db.query(f"SELECT sha256,file_name,file_date,loaded_at,row_count FROM extract_status WHERE kind={quote(kind)}")
        if oracle:
            oracle.db.row_factory=sqlite3.Row
            local_status=[dict(r) for r in oracle.db.execute(f"SELECT sha256,file_name,file_date,loaded_at,row_count FROM extract_status WHERE kind={quote(kind)}") ]
            if local_status!=current_status:raise ValueError('Local production snapshot source generation differs from D1; no writes attempted')
            tables=[kind]+(['entity_naics','entity_business_types'] if kind=='entities' else [])
            for table in tables:
                local_count=oracle.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                if db.query('SELECT COUNT(*) n FROM '+table)[0]['n']!=local_count:raise ValueError('Local production snapshot counts differ from D1; no writes attempted')
            local_run=[dict(r) for r in oracle.db.execute(f"SELECT * FROM public_refresh_runs WHERE kind={quote(kind)}") ] if oracle.db.execute("SELECT name FROM sqlite_master WHERE name='public_refresh_runs'").fetchone() else []
            if local_run!=active:raise ValueError('Local production snapshot refresh revision differs from D1; no writes attempted')
        metadata_changed=not current_status or any(current_status[0][field]!=value for field,value in [('sha256',sha),('file_name',metadata['file_name']),('file_date',metadata['file_date'])])
        validate_count(kind,count,active[0]['base_row_count'] if active and active[0]['state']=='applying' else current,allow_small)
        counts,indexes,prune=plan(db,kind,prepared,plan_path,allow_prune=diagnostic_max_writes is None)
        work=sqlite3.connect(plan_path);work.row_factory=sqlite3.Row
        try:
            transaction_units=sum(units for _,units in batches(work))
            prune_units=current*len(prune)
            planned=transaction_units+prune_units+MIGRATION_ALLOWANCE+10 if transaction_units or metadata_changed or (active and active[0]['state']=='applying') else 0
            now=dt.datetime.now(dt.timezone.utc);day=now.date().isoformat()
            period=billing_period() if getattr(db,'target',None)=='remote' else {'start':now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat(),'end':'local fixture'}
            month=period['start']
            account=account_month_written(period) if getattr(db,'target',None)=='remote' else 0
            result=dict(kind=kind,source_sha=sha,row_count=count,delta=counts,estimated_write_units=planned,prune_entry_write_reservation=prune_units,account_month_written=account,account_analytics_window=period,indexes={t:len(v) for t,v in indexes.items()},prunable_indexes=prune)
            if diagnostic_max_writes is not None and not 0<diagnostic_max_writes<=10000: raise ValueError('Diagnostic cap must be between1 and10000')
            if not planned and not (active and active[0]['state']=='applying'):
                return dict(result,skipped='normalized content unchanged',actual_record_writes=0)
            if oracle and oracle.total+planned>=oracle.round_limit:raise ValueError('Entire refresh reservation exceeds remaining authorized round; no mutations attempted')
            if diagnostic_max_writes is not None:
                if planned>diagnostic_max_writes: raise ValueError(f'Entire delta estimate {planned} exceeds diagnostic cap; no writes started')
            ledger=db.query(f'SELECT * FROM public_write_budget WHERE period={quote(month)}') if table_exists(db,'public_write_budget') else []
            entity_used=ledger[0]['entity_units'] if ledger else 0;excl_used=ledger[0]['exclusion_units'] if ledger else 0
            daily=db.query(f'SELECT units FROM public_daily_budget WHERE day={quote(day)}') if table_exists(db,'public_daily_budget') else []
            if entity_used+excl_used+planned>9900000 or (kind=='entities' and entity_used+planned>4000000) or (kind=='exclusions' and ((daily[0]['units'] if daily else 0)+planned>190000 or excl_used+planned>5890000)):
                raise ValueError('Public refresh write allocation exceeded; no writes started')
            if db.query(f"SELECT sha256,file_name,file_date,loaded_at,row_count FROM extract_status WHERE kind={quote(kind)}")!=current_status:
                raise ValueError('Source generation changed while planning; no mutations attempted')
            observed_run=db.query(f"SELECT * FROM public_refresh_runs WHERE kind={quote(kind)}") if table_exists(db,'public_refresh_runs') else []
            if observed_run!=active:raise ValueError('Refresh revision changed while planning; no mutations attempted')
            actual_writes=0
            remote=getattr(db,'target',None)=='remote'
            def measured_atomic(statements,reserved):
                nonlocal actual_writes
                proof=oracle.rehearse(statements,f'{kind}-transaction-{len(oracle.steps)+1}') if oracle else None
                try:response=db.atomic(statements)
                except BaseException:
                    if oracle:oracle.invalidate()
                    raise
                if remote:
                    if not response or any(not isinstance(r.get('meta',{}).get('rows_written'),int) for r in response):
                        if oracle:oracle.invalidate()
                        raise RuntimeError('D1 write metrics unavailable after transaction; stop before any further mutations')
                    measured=sum(r['meta']['rows_written'] for r in response)
                    actual_writes+=measured
                    if oracle:oracle.confirm(measured)
                    from sam_public_cost_oracle import amplification_exceeded
                    if amplification_exceeded(measured,proof['conservative_units'] if proof else reserved) or (oracle is None and actual_writes>5000000):
                        raise RuntimeError(f'D1 write amplification exceeded reservation ({measured}>{reserved}, total {actual_writes}/{planned}); stop before any further mutations')
                return response
            measured_atomic([RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL],MIGRATION_ALLOWANCE)
            run_columns={r['name'] for r in db.query('PRAGMA table_info(public_refresh_runs)')}
            if not {'owner_token','owner_expires_at'}<=run_columns:raise ValueError('Refresh journal schema missing ownership columns; refusing public writes')
            started=active[0]['started_at'] if active and active[0]['state']=='applying' else now.isoformat()
            base=active[0]['base_row_count'] if active and active[0]['state']=='applying' else current
            committed=active[0]['committed_write_units'] if active and active[0]['state']=='applying' else 0
            owner=uuid.uuid4().hex
            expires=(now+dt.timedelta(minutes=5)).isoformat()
            column='entity_units' if kind=='entities' else 'exclusion_units'
            def budget_sql(units):
                sql=[f"INSERT INTO public_write_budget(period,{column}) VALUES ({quote(month)},{units}) ON CONFLICT(period) DO UPDATE SET {column}={column}+{units};"]
                if kind=='exclusions': sql.append(f"INSERT INTO public_daily_budget VALUES ({quote(day)},{units}) ON CONFLICT(day) DO UPDATE SET units=units+{units};")
                return sql
            def ownership_assert():
                return f"SELECT CASE WHEN EXISTS (SELECT 1 FROM public_refresh_runs WHERE kind={quote(kind)} AND state='applying' AND target_sha={quote(sha)} AND parser_sha={quote(parser_sha)} AND owner_token={quote(owner)} AND owner_expires_at>{quote(dt.datetime.now(dt.timezone.utc).isoformat())}) THEN 1 ELSE json('refresh ownership assertion failed') END;"
            baseline_source=' AND '.join(f'{field}={quote(value)}' for field,value in current_status[0].items()) if current_status else '0'
            baseline_run=' AND '.join(f'{field}={quote(value)}' for field,value in active[0].items()) if active else ''
            revision=(f"EXISTS (SELECT 1 FROM public_refresh_runs WHERE kind={quote(kind)} AND {baseline_run})" if active else f"NOT EXISTS (SELECT 1 FROM public_refresh_runs WHERE kind={quote(kind)})")
            baseline_assert=f"SELECT CASE WHEN EXISTS (SELECT 1 FROM extract_status WHERE kind={quote(kind)} AND {baseline_source}) AND {revision} THEN 1 ELSE json('refresh baseline revision changed') END;"
            measured_atomic([baseline_assert]+budget_sql(MIGRATION_ALLOWANCE+10)+[f"DELETE FROM public_refresh_runs WHERE kind={quote(kind)} AND state='complete';",f"INSERT INTO public_refresh_runs VALUES ({quote(kind)},'applying',{quote(sha)},{quote(parser_sha)},{quote(json.dumps(metadata,sort_keys=True))},{base},{planned},{committed},{quote(month)},{quote(started)},{quote(now.isoformat())},{quote(owner)},{quote(expires)}) ON CONFLICT(kind) DO UPDATE SET planned_write_units={planned},updated_at={quote(now.isoformat())},owner_token={quote(owner)},owner_expires_at={quote(expires)} WHERE state='applying' AND target_sha={quote(sha)} AND parser_sha={quote(parser_sha)} AND owner_expires_at<={quote(now.isoformat())};",ownership_assert()],10)
            lease=db.query(f"SELECT state,target_sha,parser_sha FROM public_refresh_runs WHERE kind={quote(kind)}")
            if not lease or (lease[0]['state'],lease[0]['target_sha'],lease[0]['parser_sha'])!=('applying',sha,parser_sha):
                raise ValueError('Refresh ownership changed; no record mutations attempted')
            if prune:measured_atomic([ownership_assert()]+[f'DROP INDEX {name};' for name in prune],prune_units+MIGRATION_ALLOWANCE)
            for number,(statements,units) in enumerate(batches(work),1):
                heartbeat=dt.datetime.now(dt.timezone.utc)
                try:
                    measured_atomic([ownership_assert()]+statements+budget_sql(units)+[f"UPDATE public_refresh_runs SET committed_write_units=committed_write_units+{units},updated_at={quote(heartbeat.isoformat())},owner_expires_at={quote((heartbeat+dt.timedelta(minutes=5)).isoformat())} WHERE kind={quote(kind)};"],units)
                except Exception as failure:
                    failure.add_note(f'{kind}: incremental transaction {number} failed; maintenance gate retained, lease must expire before resume')
                    raise
                committed+=units
            final_count=db.query(f'SELECT COUNT(*) n FROM {kind}')[0]['n']
            if final_count!=count: raise ValueError('Applied record count differs from validated source; maintenance gate retained')
            if kind=='entities':
                local=sqlite3.connect(prepared)
                try:
                    for table in ['entity_naics','entity_business_types']:
                        expected=local.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                        if db.query(f'SELECT COUNT(*) n FROM {table}')[0]['n']!=expected:
                            raise ValueError('Applied child count differs from validated source; maintenance gate retained')
                finally:local.close()
            status=dict(kind=kind,**metadata,loaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),row_count=count,sha256=sha,database_bytes=db.size(),load_seconds=round(time.monotonic()-start,3),source_rows=int(audit.get('source_rows',count)),rejected_rows=int(audit.get('rejected_rows',0)),opted_out_rows=int(audit.get('opted_out_rows',0)),duplicate_rows=int(audit.get('duplicate_rows',0)))
            final_sql=[ownership_assert(),f"INSERT OR REPLACE INTO extract_status ({','.join(status)}) VALUES ({','.join(quote(v) for v in status.values())});",f"UPDATE public_refresh_runs SET state='complete',updated_at={quote(status['loaded_at'])},owner_expires_at={quote(status['loaded_at'])} WHERE kind={quote(kind)};"]
            try:measured_atomic(final_sql,10)
            except Exception as failure:
                observed=db.query(f"SELECT state,owner_token FROM public_refresh_runs WHERE kind={quote(kind)}")
                source=db.query(f"SELECT sha256,loaded_at FROM extract_status WHERE kind={quote(kind)}")
                if not (observed and observed[0]['state']=='complete' and observed[0]['owner_token']==owner and source and source[0]['sha256']==sha and source[0]['loaded_at']==status['loaded_at']):
                    failure.add_note('Finalization outcome uncertain; inspect journal/source metadata before resume')
                    raise
                result['finalization_warning']='Committed completion confirmed after lost acknowledgement'
            return dict(result,completed=True,committed_write_units=committed+MIGRATION_ALLOWANCE+10,actual_rows_written=actual_writes if remote else None,source=status)
        finally:work.close()


def initialize_tracking(db,oracle,*,execute=False):
    """Rehearse the one authorized sidecar seed/prune round on the full copy.

    Each logical operation is capped independently. Exact SQL is retained by the
    oracle before the matching D1 operation. A failed/unknown outcome stops this
    round; its reservations cannot be reused or reset.
    """
    from load_sam_public import EXCLUSION_FIELDS,quote
    if oracle is None:raise ValueError('Initialization requires a full local production-copy cost oracle')
    operations=[('sidecar-and-journal-schema',[RUN_SQL,BUDGET_SQL,DAILY_SQL,HASH_SQL])]
    source=oracle.db
    source.row_factory=sqlite3.Row
    if execute:
        from load_sam_public import refuse_leftovers
        refuse_leftovers(db)
        for table in ['entities','exclusions','entity_naics','entity_business_types']:
            if source.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]!=db.query('SELECT COUNT(*) n FROM '+table)[0]['n']:
                raise ValueError('Initialization baseline counts differ from D1; no writes attempted')
        local_status=[dict(r) for r in source.execute('SELECT * FROM extract_status ORDER BY kind')]
        if local_status!=db.query('SELECT * FROM extract_status ORDER BY kind'):
            raise ValueError('Initialization baseline metadata differs from D1; no writes attempted')
        local_indexes=[dict(r) for r in source.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('entities','exclusions','entity_naics','entity_business_types') ORDER BY name")]
        if local_indexes!=db.query("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('entities','exclusions','entity_naics','entity_business_types') ORDER BY name"):
            raise ValueError('Initialization baseline indexes differ from D1; no writes attempted')
        if table_exists(db,'public_record_hashes') and db.query('SELECT COUNT(*) n FROM public_record_hashes')[0]['n'] and not any(r['label']=='entities-hash-seed' and r['remote_outcome']=='confirmed' for r in oracle.steps):
            raise ValueError('Hash tracking already contains rows; initialization cannot be repeated')
    for kind,key in [('entities','entity_id'),('exclusions','exclusion_id')]:
        source.row_factory=sqlite3.Row
        statements=[];values=[];size=0
        # Build against the exact baseline. INSERT, not REPLACE, deliberately
        # refuses accidental reseeding or concurrent production initialization.
        for row in source.execute(f'SELECT * FROM {kind} ORDER BY {key}'):
            content=row[key] if kind=='entities' else digest(dict(row),EXCLUSION_FIELDS)
            value='('+','.join(map(quote,[kind,row[key],content]))+')'
            if values and size+len(value.encode())>55000:
                statements.append('INSERT INTO public_record_hashes VALUES '+','.join(values)+';');values=[];size=0
            values.append(value);size+=len(value.encode())+1
        if values:statements.append('INSERT INTO public_record_hashes VALUES '+','.join(values)+';')
        operations.append((kind+'-hash-seed',statements))
    # These exact actual names are derived from the local production schema,
    # with strict name+column matching; never prune guessed or unchecked names.
    class LocalSchema:
        def query(self,sql):return [dict(r) for r in source.execute(sql)]
    prune=prune_candidates(LocalSchema(),['entities','exclusions'])
    operations.append(('prune-unused-indexes',['DROP INDEX '+name+';' for name in prune]))
    reports=[]
    for label,statements in operations:
        completed=[r for r in oracle.steps if r['label']==label and r['remote_outcome'].startswith('confirmed')]
        if completed:
            regenerated=hashlib.sha256(('\n'.join(statements)+'\n').encode()).hexdigest()
            if completed[0].get('graphql_pending') or regenerated!=completed[0]['sql_sha256']:raise ValueError('Completed operation proof is pending or regenerated SQL differs; no writes attempted')
            continue
        if not statements:continue
        report=oracle.rehearse(statements,label)
        if execute:
            time.sleep(2)
            report['cloudflare_started_at']=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
            actual=0;batch=[];size=0
            try:
                for statement in statements:
                    cost=len(statement.encode())
                    if batch and size+cost>700000:
                        response=db.atomic(batch)
                        if not response or any(not isinstance(r.get('meta',{}).get('rows_written'),int) for r in response):raise RuntimeError('D1 metrics missing; stop initialization')
                        paid=sum(r['meta']['rows_written'] for r in response);actual+=paid
                        oracle.note_remote_batch(paid)
                        from sam_public_cost_oracle import amplification_exceeded
                        if amplification_exceeded(actual,report['conservative_units']) or oracle.actual_total>5000000:raise RuntimeError('D1 measured operation exceeded amplification or round limit; stop round')
                        batch=[];size=0
                    batch.append(statement);size+=cost
                if batch:
                    response=db.atomic(batch)
                    if not response or any(not isinstance(r.get('meta',{}).get('rows_written'),int) for r in response):raise RuntimeError('D1 metrics missing; stop initialization')
                    paid=sum(r['meta']['rows_written'] for r in response);actual+=paid
                    oracle.note_remote_batch(paid)
                db.query('SELECT kind,file_date FROM extract_status')
                report['cloudflare_ended_at']=(dt.datetime.now(dt.timezone.utc).replace(microsecond=0)+dt.timedelta(seconds=1)).isoformat()
                oracle.confirm(actual)
                oracle.mark_graphql_pending()
                graphql=reconcile_operation(db,report['cloudflare_started_at'],report['cloudflare_ended_at'],actual)
                oracle.confirm_analytics(graphql)
            except BaseException:
                if oracle.pending:oracle.invalidate()
                raise
        else:
            # This is an offline proof only, explicitly never actual CF metrics.
            oracle.steps[-1]['remote_outcome']='offline rehearsal only';oracle.pending=False;oracle._save()
        reports.append(report)
    return reports


def operation_analytics(db,start,end):
    account=os.environ.get('CLOUDFLARE_ACCOUNT_ID') or '846d3e41e48446abcd3570c0959f9fb5'
    query='query{viewer{accounts(filter:{accountTag:'+json.dumps(account)+'}){d1AnalyticsAdaptiveGroups(limit:10000,filter:{datetime_geq:'+json.dumps(start)+',datetime_lt:'+json.dumps(end)+',databaseId:'+json.dumps(db.identifier())+'}){sum{rowsWritten rowsRead} dimensions{datetime}}}}}'
    request=urllib.request.Request('https://api.cloudflare.com/client/v4/graphql',data=json.dumps({'query':query}).encode(),headers={'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=45) as response:result=json.load(response)
    if result.get('errors'):raise RuntimeError('Per-operation D1 analytics unavailable; stop before next write')
    accounts=result.get('data',{}).get('viewer',{}).get('accounts')
    if not accounts:raise RuntimeError('Per-operation analytics missing; stop before next write')
    groups=accounts[0].get('d1AnalyticsAdaptiveGroups')
    if groups is None or len(groups)>=10000:raise RuntimeError('Per-operation analytics missing or truncated')
    return groups

def reconcile_operation(db,start,end,actual):
    # A broader query avoids stale cached-empty narrow windows. Returned events
    # are filtered back to the exact nonoverlapping operation interval.
    beginning=dt.datetime.fromisoformat(start);ending=dt.datetime.fromisoformat(end)
    for attempt in range(180):
        rows=operation_analytics(db,(beginning-dt.timedelta(seconds=20)).isoformat(),(max(ending,dt.datetime.now(dt.timezone.utc))+dt.timedelta(seconds=20+attempt)).isoformat())
        groups=[r for r in rows if beginning<=dt.datetime.fromisoformat(r['dimensions']['datetime'].replace('Z','+00:00'))<ending]
        measured=sum(int(r['sum']['rowsWritten']) for r in groups)
        if groups and measured>=actual:return measured
        time.sleep(5)
    raise RuntimeError('GraphQL operation writes did not reconcile; stop before next write')
