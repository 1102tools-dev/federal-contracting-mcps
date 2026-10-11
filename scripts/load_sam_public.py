"""Load keyless SAM public entities/exclusions into their own D1 database.

Complete source validation happens in SQLite before D1 writes. Remote tables are
staged, checked, and promoted with one atomic D1 batch; old tables survive any
failed staging/import/promotion. Never targets the opportunities database.

Run only one loader per database (the Actions workflow enforces this). After a
hard runner termination, orphan stage tables can remain. With no loader active,
inspect sqlite_master and remove only verified leftover staging tables.
Never delete stable tables or *_previous without inspecting their generation.
Every reload refuses leftover controlled stage/previous tables before any write.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / 'deploy/sam-gov'
MIN_KEEP_RATIO = 0.6
MIN_ROWS = {'entities': 100000, 'exclusions': 10000}
MAX_DATABASE_BYTES = 10_000_000_000
CHUNK_BYTES = 8_000_000
MAX_STATEMENT_BYTES = 90_000
BASE = 'https://sam.gov/api/prod/fileextractservices/v1/api/'
DOMAINS = {'entities': 'Entity Registration/Public V2', 'exclusions': 'Exclusions/Public V2'}
PATTERNS = {'entities': r'SAM_PUBLIC_UTF-8_MONTHLY_V2_\d{8}\.ZIP',
            'exclusions': r'SAM_Exclusions_Public_Extract_V2_\d{5}\.ZIP'}
ENTITY_FIELDS = 'entity_id uei cage_code legal_business_name dba_name registration_status purpose_of_registration registration_date activation_date expiration_date last_update_date uei_status exclusion_status_flag public_display_flag address_line_1 address_line_2 city state zip_code country primary_naics entity_structure entity_url naics_codes_json business_type_codes_json sba_business_type_codes_json record_json'.split()
EXCLUSION_FIELDS = 'exclusion_id uei cage_code name first_name middle_name last_name suffix classification exclusion_type exclusion_program excluding_agency_code excluding_agency_name record_status activation_date termination_date creation_date last_update_date address_line_1 address_line_2 city state zip_code country description record_json'.split()


def table_sql(kind, suffix=''):
    if kind == 'entities':
        columns = ', '.join(f'{f} TEXT' + (' PRIMARY KEY NOT NULL' if f == 'entity_id' else '') for f in ENTITY_FIELDS)
        sql = [f'CREATE TABLE entities{suffix} ({columns});',
               f'CREATE TABLE entity_naics{suffix} (entity_id TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY(entity_id,code));',
               f"CREATE TABLE entity_business_types{suffix} (entity_id TEXT NOT NULL, code TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('business','sba')), PRIMARY KEY(entity_id,code,kind));"]
        indexes = [('entities', c) for c in ['uei','cage_code','legal_business_name','state','primary_naics','registration_status','expiration_date']]
        indexes += [('entity_naics','code'), ('entity_business_types','code,kind')]
    else:
        columns = ', '.join(f'{f} TEXT' + (' PRIMARY KEY NOT NULL' if f == 'exclusion_id' else '') for f in EXCLUSION_FIELDS)
        sql = [f'CREATE TABLE exclusions{suffix} ({columns});']
        indexes = [('exclusions', c) for c in ['uei','cage_code','name','state','record_status','activation_date']]
    for i, (table, column) in enumerate(indexes):
        collation = ' COLLATE NOCASE' if column in ('legal_business_name','name') else ''
        sql.append(f'CREATE INDEX {kind}_{i}{suffix} ON {table}{suffix} ({column}{collation});')
    if kind == 'entities':
        sql.append(f'CREATE INDEX entities_status_name{suffix} ON entities{suffix} (registration_status, legal_business_name COLLATE NOCASE, uei, entity_id);')
    return sql


STATUS_SQL = '''CREATE TABLE IF NOT EXISTS extract_status (
kind TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_date TEXT NOT NULL,
source_url TEXT NOT NULL, loaded_at TEXT NOT NULL, row_count INTEGER NOT NULL,
sha256 TEXT NOT NULL, database_bytes INTEGER NOT NULL, load_seconds REAL NOT NULL,
source_rows INTEGER NOT NULL DEFAULT 0, rejected_rows INTEGER NOT NULL DEFAULT 0, opted_out_rows INTEGER NOT NULL DEFAULT 0, duplicate_rows INTEGER NOT NULL DEFAULT 0);'''


def quote(value):
    if value is None:
        return 'NULL'
    if isinstance(value, (int, float)):
        return str(value)
    if '\x00' in str(value):
        raise ValueError('NUL in normalized source field')
    return "'" + str(value).replace("'", "''") + "'"


def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'1102tools-sam-public-loader'}), timeout=120) as response:
        return json.load(response)


def newest(kind):
    url = BASE + 'listfiles?' + urllib.parse.urlencode({'domain':DOMAINS[kind], 'privacy':'Public'})
    payload = fetch_json(url)
    # The fileextract service has returned both bare lists and list envelopes.
    if isinstance(payload, dict):
        payload = payload.get('_embedded', {}).get('customS3ObjectSummaryList') or next((payload[k] for k in ('fileList','files','data') if isinstance(payload.get(k), list)), [])
    candidates = []
    for entry in payload:
        if entry.get('privacy','Public') != 'Public':
            continue
        name = entry.get('displayKey') or entry.get('fileName') or entry.get('name')
        if name and re.fullmatch(PATTERNS[kind], name, re.I):
            modified = str(entry.get('dateModified') or '')
            try:
                date = dt.datetime.fromisoformat(modified.replace('Z','+00:00')).date()
            except ValueError:
                date = dt.datetime.strptime(modified, '%b %d,%Y').date()
            candidates.append((date.isoformat(), name))
    if not candidates:
        raise ValueError(f'No expected public {kind} file in listing')
    modified, name = max(candidates)
    # SAM service dateModified is ISO; normalize rather than assuming host date.
    date = dt.datetime.strptime(re.search(r'(\d{8})\.ZIP$',name,re.I).group(1),'%Y%m%d').date().isoformat() if kind == 'entities' else dt.datetime.strptime('20'+re.search(r'(\d{5})\.ZIP$',name,re.I).group(1),'%Y%j').date().isoformat()
    source = BASE + 'download/' + urllib.parse.quote(DOMAINS[kind], safe='/') + '/' + urllib.parse.quote(name) + '?privacy=Public'
    return {'file_name':name, 'file_date':date, 'source_url':source}


def download(metadata, destination):
    with urllib.request.urlopen(urllib.request.Request(metadata['source_url'], headers={'User-Agent':'1102tools-sam-public-loader'}), timeout=600) as response, destination.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def validate_zip(path):
    if not zipfile.is_zipfile(path):
        return
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC integrity failed')
        for member in archive.infolist():
            if member.filename.startswith('/') or '..' in Path(member.filename).parts or member.flag_bits & 1:
                raise ValueError('Unsafe or encrypted ZIP member')


def validate_count(kind, count, existing, allow_small=False):
    if count == 0 or (count < MIN_ROWS[kind] and not allow_small):
        raise ValueError(f'Only {count} {kind}; refusing to replace data')
    if existing and count < existing * MIN_KEEP_RATIO:
        raise ValueError(f'{count} {kind} below {MIN_KEEP_RATIO} keep ratio of {existing}')


def prepare(kind, path, local_path, audit=None):
    """Fully parse into bounded-memory SQLite. Duplicate IDs are rejected."""
    validate_zip(path)
    if kind == 'entities':
        from sam_entity_extract import iter_rows
    else:
        from sam_exclusion_extract import iter_rows
    db = sqlite3.connect(local_path)
    try:
        db.executescript('\n'.join(table_sql(kind)))
        fields = ENTITY_FIELDS if kind == 'entities' else EXCLUSION_FIELDS
        count = 0
        iterator = iter_rows(path, audit=audit) if kind == 'entities' else iter_rows(path)
        for source in iterator:
            row = dict(source)
            if kind == 'entities':
                row['entity_id'] = hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                if db.execute('SELECT 1 FROM entities WHERE entity_id=?',(row['entity_id'],)).fetchone():
                    if audit is not None:
                        audit['duplicate_rows'] = audit.get('duplicate_rows',0) + 1
                    continue
            if kind == 'entities':
                for key in ['naics_codes','business_type_codes','sba_business_type_codes']:
                    row[key + '_json'] = json.dumps(row.get(key, []), separators=(',',':'))
                for code in set(row.get('naics_codes', [])):
                    db.execute('INSERT INTO entity_naics VALUES (?,?)', (row['entity_id'],code))
                for key, group in [('business_type_codes','business'), ('sba_business_type_codes','sba')]:
                    for code in set(row.get(key, [])):
                        db.execute('INSERT INTO entity_business_types VALUES (?,?,?)', (row['entity_id'],code,group))
            if isinstance(row.get('record_json'), (dict,list)):
                row['record_json'] = json.dumps(row['record_json'], ensure_ascii=False, separators=(',',':'))
            values = [row.get(f) for f in fields]
            statement = f'INSERT INTO {kind} ({",".join(fields)}) VALUES ({",".join(quote(v) for v in values)});'
            if len(statement.encode()) > MAX_STATEMENT_BYTES:
                raise ValueError('Normalized row exceeds D1 SQL statement limit')
            db.execute(f'INSERT INTO {kind} ({",".join(fields)}) VALUES ({",".join("?" for _ in fields)})', values)
            count += 1
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Prepared SQLite integrity failure')
        return count, Path(local_path).stat().st_size
    finally:
        db.close()


class D1:
    def __init__(self, target, database):
        if 'opportunit' in database.lower() or database == '8875076f-cbb2-4ce8-9ea1-b152323fbbb0':
            raise ValueError('Refusing to target opportunities database')
        self.target, self.database = target, database

    def run(self, *args):
        result = subprocess.run(['npx','--no-install','wrangler','d1','execute',self.database,f'--{self.target}','--yes',*args],cwd=WORKER_DIR,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode:
            # Keep CLI output to one readable error; raw imports can contain data.
            diagnostic = subprocess.CalledProcessError(result.returncode,result.args,output=result.stdout,stderr=result.stderr)
            output = re.sub(r'\x1b\[[0-9;]*m','',result.stderr+'\n'+result.stdout)
            match = re.search(r'\[ERROR\][ \t]*([^\n]*)',output)
            detail = match[1].strip() if match else ''
            if match and not detail:
                tail = output[match.end():].lstrip('\n ')
                detail = tail.split('\n',1)[0].strip() if tail else ''
            # Never echo SQL, request payloads, stack traces, or auth headers.
            if re.search(r'\b(?:INSERT|UPDATE|DELETE|SELECT|CREATE|ALTER|DROP|Authorization|Bearer)\b|https?://|[{}]|Logs were written|^at ',detail,re.I):
                detail = ''
            code = re.search(r'\[code:\s*\d+\]',output)
            detail = detail[:300] or 'Cloudflare provided no readable error detail'
            if code and code[0] not in detail:
                detail += ' '+code[0]
            raise RuntimeError(f'D1 execute failed (exit {result.returncode}): {detail}') from diagnostic
        return result.stdout

    def query(self, sql):
        output = json.loads(self.run('--json','--command',sql))
        return output[0]['results']

    def execute_file(self, statements):
        with tempfile.NamedTemporaryFile('w',suffix='.sql',encoding='utf-8') as output:
            output.write('\n'.join(statements)); output.flush()
            self.run('--file',output.name)

    def identifier(self):
        config = (WORKER_DIR / 'wrangler.jsonc').read_text()
        clean = re.sub(r'^\s*//[^\n]*', '', config, flags=re.M)
        try:
            bindings = json.loads(clean)['d1_databases']
            return next(b['database_id'] for b in bindings if b.get('database_name') == self.database or b.get('binding') == self.database)
        except (ValueError,KeyError,StopIteration):
            if re.fullmatch(r'[0-9a-f-]{36}',self.database):
                return self.database
            raise ValueError('Database UUID unavailable; use --database UUID')

    def api(self, payload=None):
        account = os.environ.get('CLOUDFLARE_ACCOUNT_ID') or '846d3e41e48446abcd3570c0959f9fb5'
        token = os.environ['CLOUDFLARE_API_TOKEN']
        url = f'https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{self.identifier()}' + ('/query' if payload is not None else '')
        request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=120) as response:
            result = json.load(response)
        if not result.get('success'):
            raise RuntimeError('D1 API rejected request: ' + json.dumps(result.get('errors',[])))
        return result['result']

    def size(self):
        if self.target == 'local':
            return self.query('PRAGMA page_count')[0]['page_count'] * self.query('PRAGMA page_size')[0]['page_size']
        return int(self.api()['file_size'])

    def atomic(self, statements):
        """One D1 query batch: verified rollback including table renames."""
        if self.target == 'local':
            self.execute_file(statements)
            return
        result = self.api({'sql':'\n'.join(statements)})
        if any(not r.get('success',True) for r in result):
            raise RuntimeError('Atomic promotion rejected')


def stage_statements(local_path, kind, suffix):
    db = sqlite3.connect(local_path)
    try:
        tables = [kind] + (['entity_naics','entity_business_types'] if kind == 'entities' else [])
        for table in tables:
            prefix = f'INSERT INTO {table}{suffix} VALUES '
            values, size = [], len(prefix)
            for row in db.execute(f'SELECT * FROM {table}'):
                value = '(' + ','.join(quote(v) for v in row) + ')'
                length = len(value.encode()) + 1
                if values and size + length >= MAX_STATEMENT_BYTES - 1000:
                    yield prefix + ','.join(values) + ';'
                    values, size = [], len(prefix)
                values.append(value); size += length
            if values:
                yield prefix + ','.join(values) + ';'
    finally:
        db.close()


def chunks(statements):
    batch, size = [], 0
    for statement in statements:
        length = len(statement.encode()) + 1
        if length > MAX_STATEMENT_BYTES:
            raise ValueError('Statement exceeds D1 limit')
        if batch and size + length > CHUNK_BYTES:
            yield batch
            batch, size = [], 0
        batch.append(statement); size += length
    if batch:
        yield batch


def promotion_sql(kind, suffix, status):
    tables = [kind] + (['entity_naics','entity_business_types'] if kind == 'entities' else [])
    statements = []
    for table in tables:
        statements += [f'ALTER TABLE {table} RENAME TO {table}_previous;', f'ALTER TABLE {table}{suffix} RENAME TO {table};']
    fields = list(status)
    statements.append(f'INSERT OR REPLACE INTO extract_status ({",".join(fields)}) VALUES ({",".join(quote(status[k]) for k in fields)});')
    statements.extend(f'DROP TABLE {table}_previous;' for table in tables)
    return statements


def ensure_audit_columns(db):
    columns = {row['name'] for row in db.query('PRAGMA table_info(extract_status)')}
    additions = [f'ALTER TABLE extract_status ADD COLUMN {key} INTEGER NOT NULL DEFAULT 0;' for key in ['source_rows','rejected_rows','opted_out_rows','duplicate_rows'] if key not in columns]
    if additions:
        db.execute_file(additions)


def file_sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def refuse_leftovers(db):
    pattern = re.compile(r'^(?:entities|entity_naics|entity_business_types|exclusions)_(?:stage_[0-9a-f]{12}|previous(?:_[0-9a-f]{12})?)$')
    names = sorted(row['name'] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'") if pattern.fullmatch(row['name']))
    if names:
        raise ValueError('Reload refused: leftover tables require inspected cleanup: ' + ', '.join(names))


def load(db, kind, path, metadata, allow_small=False, prepared=None):
    refuse_leftovers(db)
    start = time.monotonic()
    if getattr(db,'target',None) == 'remote' and kind == 'exclusions' and not zipfile.is_zipfile(path):
        raise ValueError('Remote exclusions require intact source ZIP; standalone CSV has no full-file count trailer')
    with tempfile.TemporaryDirectory(prefix='sam-public-') as directory:
        local_path = Path(directory) / 'prepared.sqlite'
        audit = {}
        if prepared is None:
            count, size = prepare(kind,path,local_path,audit)
        else:
            # Internal reuse of a completed full-file validation checkpoint.
            # Still verify the source bytes, schema and SQLite integrity before D1 writes.
            cached = Path(prepared['path'])
            if prepared.get('parser_sha256') != file_sha256(ROOT / 'scripts' / ('sam_entity_extract.py' if kind == 'entities' else 'sam_exclusion_extract.py')):
                raise ValueError('Prepared checkpoint parser changed')
            if file_sha256(path) != prepared['sha256']:
                raise ValueError('Prepared checkpoint source SHA mismatch')
            connection = sqlite3.connect(cached)
            try:
                fields = ENTITY_FIELDS if kind == 'entities' else EXCLUSION_FIELDS
                if [r[1] for r in connection.execute(f'PRAGMA table_info({kind})')] != fields:
                    raise ValueError('Prepared checkpoint schema mismatch')
                if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Prepared checkpoint SQLite integrity failure')
                count = connection.execute(f'SELECT COUNT(*) FROM {kind}').fetchone()[0]
                if count != prepared['count']:
                    raise ValueError('Prepared checkpoint row count mismatch')
            finally:
                connection.close()
            size = cached.stat().st_size
            audit.update(prepared['audit'])
            start -= prepared.get('prepare_seconds',0)
            local_path = cached
        child_counts = {}
        if kind == 'entities':
            connection = sqlite3.connect(local_path)
            try:
                child_counts = {table:connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ['entity_naics','entity_business_types']}
            finally:
                connection.close()
        db.execute_file([STATUS_SQL] + [s.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ') for s in table_sql(kind) if not s.startswith('CREATE INDEX')])
        ensure_audit_columns(db)
        current = db.query(f'SELECT COUNT(*) AS n FROM {kind}')[0]['n']
        validate_count(kind,count,current,allow_small)
        existing_bytes = db.size()
        if existing_bytes + size > MAX_DATABASE_BYTES * .9:
            raise ValueError('Insufficient D1 capacity for live plus staged copy')
        suffix = '_stage_' + uuid.uuid4().hex[:12]
        tables = [kind] + (['entity_naics','entity_business_types'] if kind == 'entities' else [])
        phase = 'creating empty staging tables'
        try:
            stage_schema = table_sql(kind,suffix)
            db.execute_file([s for s in stage_schema if not s.startswith('CREATE INDEX')])
            indexes = [s for s in stage_schema if s.startswith('CREATE INDEX')]
            for index,statement in enumerate(indexes,1):
                # Create indexes on empty staging tables, before indexed uploads.
                phase = f'creating empty-stage index {index}/{len(indexes)}'
                print(f'{kind}: {phase}: {statement}',file=sys.stderr,flush=True)
                db.execute_file([statement])
            for index,batch in enumerate(chunks(stage_statements(local_path,kind,suffix)),1):
                phase = f'uploading indexed chunk {index}'
                print(f'{kind}: importing indexed chunk {index} ({sum(len(s.encode()) for s in batch)} bytes)', file=sys.stderr,flush=True)
                db.execute_file(batch)
            phase = 'checking staged row counts'
            staged_count = db.query(f'SELECT COUNT(*) AS n FROM {kind}{suffix}')[0]['n']
            if staged_count != count:
                raise ValueError('Staged count differs from validated count')
            for table,expected in child_counts.items():
                actual = db.query(f'SELECT COUNT(*) AS n FROM {table}{suffix}')[0]['n']
                if actual != expected:
                    raise ValueError(f'{table} staged count {actual} differs from validated {expected}')
            # Observe D1 while the complete old and staged copies coexist.
            # These diagnostics are output-only, not extract_status columns.
            peak_bytes = db.size()
            status = dict(kind=kind,**metadata,loaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),row_count=count,sha256=file_sha256(path),database_bytes=size,load_seconds=round(time.monotonic()-start,3))
            status.update(source_rows=int(audit.get('source_rows',count)), rejected_rows=int(audit.get('rejected_rows',0)), opted_out_rows=int(audit.get('opted_out_rows',0)),duplicate_rows=int(audit.get('duplicate_rows',0)))
            phase = 'atomic promotion'
            db.atomic(promotion_sql(kind,suffix,status))
        except BaseException as failure:
            failure.add_note(f'{kind}: failed while {phase}')
            try:
                db.execute_file([f'DROP TABLE IF EXISTS {table}{suffix};' for table in tables])
            except Exception:
                failure.add_note('Stage cleanup also failed; the next reload will refuse leftover tables')
            raise
        status['database_bytes'] = db.size()
        status['load_seconds'] = round(time.monotonic()-start,3)
        db.atomic([f"UPDATE extract_status SET database_bytes={status['database_bytes']}, load_seconds={status['load_seconds']} WHERE kind={quote(kind)};"])
        status.update(existing_database_bytes=existing_bytes, prepared_database_bytes=size,
                      peak_database_bytes=peak_bytes, database_limit_bytes=MAX_DATABASE_BYTES,
                      peak_headroom_bytes=MAX_DATABASE_BYTES-peak_bytes,
                      peak_headroom_percent=round(100*(MAX_DATABASE_BYTES-peak_bytes)/MAX_DATABASE_BYTES,3))
        return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument('--remote',dest='target',action='store_const',const='remote')
    targets.add_argument('--local',dest='target',action='store_const',const='local')
    parser.add_argument('--database',default='sam-gov-entities')
    parser.add_argument('--kind',choices=['entities','exclusions','all'],default='all')
    parser.add_argument('--file',type=Path)
    parser.add_argument('--file-date')
    parser.add_argument('--file-name')
    parser.add_argument('--allow-small',action='store_true')
    parser.add_argument('--force',action='store_true')
    args = parser.parse_args(argv)
    if args.allow_small and args.target != 'local':
        parser.error('--allow-small is restricted to local fixtures')
    if args.file and (args.kind == 'all' or not args.file_date):
        parser.error('--file requires one --kind and --file-date')
    if args.target == 'remote' and args.file and not re.fullmatch(PATTERNS[args.kind],args.file_name or args.file.name,re.I):
        parser.error('Remote local-file loads require the expected public ZIP filename (use --file-name for extracted entities)')
    db = D1(args.target,args.database)
    refuse_leftovers(db)
    db.execute_file([STATUS_SQL])
    output = []
    for kind in ['entities','exclusions'] if args.kind == 'all' else [args.kind]:
        metadata = {'file_name':args.file_name or args.file.name,'file_date':args.file_date,'source_url': BASE + 'download/' + urllib.parse.quote(DOMAINS[kind],safe='/') + '/' + urllib.parse.quote(args.file_name or args.file.name) + '?privacy=Public'} if args.file else newest(kind)
        current = db.query(f"SELECT file_name,file_date FROM extract_status WHERE kind={quote(kind)}")
        if not args.force and current and (metadata['file_date'],metadata['file_name']) <= (current[0]['file_date'],current[0]['file_name']):
            output.append({'kind':kind,'skipped':'source unchanged','file_name':metadata['file_name']}); continue
        with tempfile.TemporaryDirectory(prefix='sam-download-') as directory:
            path = args.file or Path(directory) / metadata['file_name']
            if not args.file:
                download(metadata,path)
            output.append(load(db,kind,path,metadata,args.allow_small))
    print(json.dumps(output,indent=2))


def readable_error(failure):
    message = '; '.join([str(failure),*getattr(failure,'__notes__',[])])
    for secret in [os.environ.get('CLOUDFLARE_API_TOKEN'),os.environ.get('CLOUDFLARE_D1_TOKEN')]:
        if secret:
            message = message.replace(secret,'[redacted]')
    message = re.sub(r'\x1b\[[0-9;]*m','',message)
    return 'SAM public load failed: ' + ' '.join(message.split())[:1500]


if __name__ == '__main__':
    try:
        main()
    except Exception as failure:
        print(readable_error(failure),file=sys.stderr)
        sys.exit(1)
