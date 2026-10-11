"""Small saved PDF loader recording and Python expectations for Worker regressions."""
import importlib.util
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('loader', ROOT / 'scripts/load_acquisition_gov.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
body = (ROOT / 'servers/acquisition-gov-mcp/tests/fixtures/content-round' / f'{sys.argv[1]}.pdf').read_bytes()
parsed = loader.parse_pdf(body)
print(json.dumps({'sql': '\n'.join(loader.doc_statements('content-round-sample', parsed)),
                 'ranges': [{'start': start, 'end': end, 'expected': loader.read_pdf(body, start, end)}
                            for start, end in ((1, 3), (1, 1), (2, 2), (3, 3))]}))
