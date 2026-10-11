import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sam_entity_extract',ROOT/'scripts/sam_entity_extract.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
FIXTURE = ROOT/'tests/fixtures/sam_public/entities.dat'

class EntityExtractTests(unittest.TestCase):
    def parse(self,text):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'entity.dat';p.write_text(text)
            return list(m.iter_rows(p))

    def test_real_slice(self):
        rows=list(m.iter_rows(FIXTURE))
        self.assertGreaterEqual(len(rows),20)
        first=rows[0]
        self.assertEqual(first['uei'],'VZCLHNYYTGM7')
        self.assertEqual(first['business_type_codes'],['2X','LJ','A5'])
        self.assertEqual(first['primary_naics'],'561210')
        self.assertEqual(len(first['naics_codes']),25)
        self.assertEqual(first['expiration_date'],'2027-06-04')
        self.assertEqual(first['exclusion_status_flag'],'N')
        self.assertEqual(first['record_json']['entityRegistration']['registrationDate'],'2026-05-29')
        self.assertEqual(first['record_json']['assertions']['goodsAndServices']['naicsList'][0],{'naicsCode':'238220','sbaSmallBusiness':'Y'})

    def test_real_sba_certification_dates(self):
        rows=list(m.iter_rows(FIXTURE.with_name('entities-sba.dat')))
        self.assertEqual(len(rows),3)
        for row in rows:
            sba=row['record_json']['coreData']['businessTypes']['sbaBusinessTypeList']
            self.assertTrue(any('certificationExitDate' in item for item in sba))
            self.assertEqual(row['sba_business_type_codes'],[item['sbaBusinessTypeCode'] for item in sba])

    def test_truncated_and_malformed_never_pass(self):
        text=FIXTURE.read_text()
        for bad in [text.rsplit('EOF',1)[0], text.replace('!end','!broken',1),text.replace('0025|','0026|',1),text.replace('0905712','0000000',1)+'trailing']:
            with self.subTest(bad=bad[-80:]),self.assertRaises(ValueError):self.parse(bad)

    def test_no_public_display_filtered(self):
        lines=FIXTURE.read_text().splitlines(True)
        a=lines[1].rstrip('\n').split('|');a[118]='NPDY';lines[1]='|'.join(a)+'\n'
        self.assertEqual(len(self.parse(''.join(lines))),len(lines)-3)

    def test_exclusion_flag_v2_to_v3(self):
        row=FIXTURE.read_text().splitlines()[1].split('|')
        row[115]='D'
        self.assertEqual(m.parse_row('|'.join(row))['record_json']['entityRegistration']['exclusionStatusFlag'],'Y')
        row[115]='unknown'
        with self.assertRaisesRegex(ValueError,'exclusion flag'):m.parse_row('|'.join(row))

    def test_header_count_and_trailer(self):
        text=FIXTURE.read_text()
        with self.assertRaises(ValueError):self.parse(text.replace('0000035','0000034'))
        with self.assertRaises(ValueError):self.parse(text.replace('BOF PUBLIC V2','BOF FOUO V2'))

    def test_nested_public_zip(self):
        with tempfile.TemporaryDirectory() as td:
            inner=Path(td)/'inner.zip';outer=Path(td)/'outer.zip'
            with zipfile.ZipFile(inner,'w') as z:z.write(FIXTURE,'entities.dat')
            with zipfile.ZipFile(outer,'w') as z:z.write(inner,'entities.zip')
            self.assertEqual(len(list(m.iter_rows(outer))),35)


    def test_quarantine_is_bounded_and_audited(self):
        # Public real row duplicated only to create enough records for 0.1% cap.
        row=FIXTURE.read_text().splitlines()[1]
        bad=row.replace('|!end','|extra|!end')
        h='PUBLIC V2 00000000 20261005 0001000 0008359'
        audit={}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'entities.dat'
            p.write_text('BOF '+h+'\n'+(row+'\n')*999+bad+'\nEOF '+h+'\n')
            self.assertEqual(len(list(m.iter_rows(p,audit=audit))),999)
            self.assertEqual(audit['source_rows'],1000)
            self.assertEqual(audit['rejected_rows'],1)
            self.assertEqual(audit['quarantine_reasons'],{'unescaped_pipe_expanded_row':1})
            p.write_text(p.read_text().replace(row,bad,1))
            with self.assertRaisesRegex(ValueError,'0.1%'):list(m.iter_rows(p))

    def test_unsafe_zip_path(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bad.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../entities.dat',FIXTURE.read_bytes())
            with self.assertRaises(ValueError):list(m.iter_rows(p))
