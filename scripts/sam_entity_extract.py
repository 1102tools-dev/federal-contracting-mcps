"""Strict streaming reader for SAM's PUBLIC V2 monthly entity extract.

Layout: https://open.gsa.gov/api/sam-entity-extracts-api/v1/SAM_Entity_Management_Public_V2_Extract_Layout.pdf
The public service sometimes wraps the ZIP inside another ZIP. NPDY rows are
validated but never returned. Fully consume the generator before publishing.
"""
from contextlib import contextmanager, ExitStack
from datetime import datetime
import io
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

HEADER = re.compile(r"BOF PUBLIC V2 (\d{8}) (\d{8}) (\d{7}) (\d{7})")
SCALAR_INDEX = {'uei':0,'cage_code':3,'legal_business_name':11,'dba_name':12,
 'purpose_of_registration':6,'address_line_1':15,'address_line_2':16,'city':17,
 'state':18,'zip_code':19,'country':21,'primary_naics':32,'entity_structure':27,'entity_url':26}
DATES = {'registration_date':7,'expiration_date':8,'last_update_date':9,'activation_date':10}

@contextmanager
def _text(path):
    with ExitStack() as stack:
        source = stack.enter_context(open(path, 'rb'))
        for depth in range(3):
            if not zipfile.is_zipfile(source):
                source.seek(0)
                yield stack.enter_context(io.TextIOWrapper(source, encoding='utf-8-sig', errors='strict'))
                return
            source.seek(0)
            archive = stack.enter_context(zipfile.ZipFile(source))
            members = archive.infolist()
            if len(members) != 1:
                raise ValueError('Entity ZIP must contain exactly one member')
            name = members[0].filename
            if PurePosixPath(name).name != name or '\\' in name:
                raise ValueError('Unsafe entity ZIP member path')
            member = stack.enter_context(archive.open(members[0]))
            if name.lower().endswith('.zip'):
                source = stack.enter_context(tempfile.SpooledTemporaryFile(max_size=8*1024*1024))
                shutil.copyfileobj(member, source)
                source.seek(0)
            else:
                yield stack.enter_context(io.TextIOWrapper(member, encoding='utf-8-sig', errors='strict'))
                return
        raise ValueError('Too many nested entity ZIPs')

def _date(value):
    if not value:
        return None
    if not re.fullmatch(r'\d{8}', value):
        raise ValueError(f'Invalid entity date {value!r}')
    return datetime.strptime(value, '%Y%m%d').date().isoformat()

def _list(a, counter, column, pattern):
    value = a[column]
    values = value.split('~') if value.strip() else []
    if not re.fullmatch(r'\d{4}', a[counter]) or int(a[counter]) != len(values):
        raise ValueError(f'Entity repeating field count mismatch at column {column+1}')
    if any(not re.fullmatch(pattern, v) for v in values):
        raise ValueError(f'Invalid entity repeating field at column {column+1}')
    return values

def parse_row(line):
    """Validate one actual 142-column row and return its public projection."""
    a = line.rstrip('\r\n').split('|')
    if len(a) != 142 or a[-1] != '!end':
        raise ValueError(f'Invalid entity row shape: {len(a)} columns (expected 142 and !end)')
    business = _list(a,30,31,r'[A-Z0-9]{2}')
    naics = _list(a,33,34,r'\d{6}[YNE ]?')
    sba = _list(a,116,117,r'[A-Z0-9]{2}(?:\d{8})?')
    _list(a,35,36,r'[A-Z0-9]{4}')
    _list(a,112,113,r'\d{6}[YNE ]{4,16}')
    _list(a,119,120,r'(?:ANY|STA[A-Z0-9]{2}|CTY[A-Z]{2}\d{3}|MSA\d{4})')
    if a[115].strip() not in ('', 'D'):
        raise ValueError('Unexpected entity exclusion flag')
    if a[118].strip() not in ('', 'NPDY'):
        raise ValueError('Unexpected public-display flag')
    if a[5] not in ('A','E','A~E'):
        raise ValueError('Unknown monthly entity extract status')
    if not re.fullmatch(r'[A-Z0-9]{12}',a[0]):
        raise ValueError('Invalid entity UEI')
    if a[3].strip() and not re.fullmatch(r'[A-Z0-9]{5}',a[3].strip()):
        raise ValueError('Invalid entity CAGE')
    row = {key:a[index].strip() or None for key,index in SCALAR_INDEX.items()}
    row.update({key:_date(a[index].strip()) for key,index in DATES.items()})
    # A~E occurs once in the real 2026-10 source and is ambiguous; preserve it.
    row['registration_status'] = {'A':'Active','E':'Inactive'}.get(a[5],a[5])
    row['uei_status'] = None
    row['exclusion_status_flag'] = 'Y' if a[115].strip() == 'D' else 'N'
    row['public_display_flag'] = 'N' if a[118].strip() == 'NPDY' else 'Y'
    row['naics_codes'] = [v[:6] for v in naics]
    row['business_type_codes'] = business
    row['sba_business_type_codes'] = [v[:2] for v in sba]
    registration = {'ueiSAM':row['uei'],'cageCode':row['cage_code'],
        'legalBusinessName':row['legal_business_name'],'dbaName':row['dba_name'],
        'registrationStatus':row['registration_status'],'purposeOfRegistrationCode':row['purpose_of_registration'],
        'registrationDate':row['registration_date'],'activationDate':row['activation_date'],
        'registrationExpirationDate':row['expiration_date'],'lastUpdateDate':row['last_update_date'],
        'publicDisplayFlag':row['public_display_flag'],'exclusionStatusFlag':row['exclusion_status_flag']}
    row['record_json'] = {'entityRegistration':registration,'coreData':{
        'physicalAddress':{'addressLine1':row['address_line_1'],'addressLine2':row['address_line_2'],
        'city':row['city'],'stateOrProvinceCode':row['state'],'zipCode':row['zip_code'],
        'zipCodePlus4':a[20].strip() or None,'countryCode':row['country']},
        'businessTypes':{'businessTypeList':[{'businessTypeCode':v} for v in business],
        'sbaBusinessTypeList':[dict(sbaBusinessTypeCode=v[:2],**({'certificationExitDate':_date(v[2:])} if len(v)>2 else {})) for v in sba]}},
        'assertions':{'goodsAndServices':{'primaryNaics':row['primary_naics'],
        'naicsList':[dict(naicsCode=v[:6], **({'sbaSmallBusiness':v[6:]} if v[6:] in ('Y','N') else {})) for v in naics]}}}
    return row

def _quarantined(fields, reason):
    """Identity of a skipped row, so search can say this company's record was dropped."""
    # UEI, CAGE and name come before any field seen to hold a stray pipe.
    return {'uei': fields[0].strip(), 'cage_code': fields[3].strip(), 'legal_business_name': fields[11].strip(), 'reason': reason}


def iter_rows(path, *, audit=None):
    """Yield visible entities; reject bad headers, rows, ZIP CRCs, or truncation."""
    with _text(path) as stream:
        first = stream.readline().rstrip('\r\n')
        header = HEADER.fullmatch(first)
        if not header:
            raise ValueError('Invalid PUBLIC V2 entity header')
        _date(header[2])
        expected = int(header[3]); count = 0
        metrics = audit if audit is not None else {}
        metrics.update(source_rows=0, rejected_rows=0, opted_out_rows=0, returned_rows=0, quarantine_reasons={}, quarantined=[])
        for line in stream:
            if line.startswith('EOF '):
                if line.rstrip('\r\n') != 'EOF' + first[3:]:
                    raise ValueError('Entity trailer does not match header')
                if count != expected:
                    raise ValueError(f'Entity record count mismatch: expected {expected}, read {count}')
                if metrics['rejected_rows'] / max(expected, 1) > 0.001:
                    raise ValueError('Entity quarantine exceeds 0.1% source rows')
                if stream.read():
                    raise ValueError('Data after entity trailer')
                return
            count += 1
            metrics['source_rows'] += 1
            fields = line.rstrip('\r\n').split('|')
            if len(fields) > 142 and fields[-1] == '!end' and re.fullmatch(r'[A-Z0-9]{12}', fields[0]):
                metrics['rejected_rows'] += 1
                reasons = metrics['quarantine_reasons']
                reasons['unescaped_pipe_expanded_row'] = reasons.get('unescaped_pipe_expanded_row', 0) + 1
                metrics['quarantined'].append(_quarantined(fields, 'unescaped_pipe_expanded_row'))
                continue
            # SAM sometimes merges two registrations into one row (two dates joined by ~), with status A, E or A~E.
            if len(fields) == 142 and fields[-1] == '!end' and any(re.fullmatch(r'\d{8}~\d{8}', fields[i].strip()) for i in DATES.values()):
                metrics['rejected_rows'] += 1
                reasons = metrics['quarantine_reasons']
                reasons['ambiguous_merged_registration'] = reasons.get('ambiguous_merged_registration', 0) + 1
                metrics['quarantined'].append(_quarantined(fields, 'ambiguous_merged_registration'))
                continue
            try:
                row = parse_row(line)
            except ValueError as e:
                raise ValueError(f'Entity source row {count}: {e}') from e
            if row['public_display_flag'] == 'Y':
                metrics['returned_rows'] += 1
                yield row
            else:
                metrics['opted_out_rows'] += 1
        raise ValueError('Missing entity trailer (truncated extract)')
