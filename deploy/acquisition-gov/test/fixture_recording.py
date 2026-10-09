"""Write a small recording of Acquisition.gov for offline tests and CI parity.

The full recording (scripts/load_acquisition_gov.py --record) is about 0.5 GB
and lives outside git. This one is built from the package's test fixtures
plus generated PDFs, in the same layout (manifest.json + bodies/), so the
loader can --replay it and scripts/parity.py can compare both servers on it:

- the index, part 10 and the FAQ page from servers/acquisition-gov-mcp/tests/fixtures,
  a generated part 12 and policy page, and HTTP 404 for every other part;
- at the NASA link, the real three-page NSF deviation PDF fixture;
- at the GSA link, a generated 45-page PDF with about 11,000 characters a
  page and one page over 200,000, so 25-page windows hit the package's
  200,000-character extraction cap at many different offsets (no posted PDF
  does yet), with labeled dates on and across page breaks and applicability
  lines throughout;
- a generated deviation guidance PDF.

    python deploy/acquisition-gov/test/fixture_recording.py OUT_DIR
"""
from __future__ import annotations

import hashlib, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "servers/acquisition-gov-mcp/tests/fixtures"
BASE = "https://www.acquisition.gov"
INDEX = f"{BASE}/far-overhaul/far-part-deviation-guide"
UPLOADS = f"{BASE}/sites/default/files/page_file_uploads"
FETCHED_AT = "2026-10-01T12:00:00+00:00"
NOT_FOUND = b"<!DOCTYPE html>\n<html><head><title>Page not found</title></head><body>Not found</body></html>"

WORDS = ("contracting officer agency deviation clause solicitation offeror award subpart paragraph "
         "acquisition procurement commercial product service requirement policy procedure section").split()


def pdf(pages: list[list[str]]) -> bytes:
    """A minimal PDF: each page's lines as Helvetica text, one line apart."""
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for lines in pages:
        stream = ("BT /F1 9 Tf 11 TL 20 770 Td\n" + "".join(f"({escape(line)}) Tj T*\n" for line in lines) + "ET").encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % len(objects))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def long_deviation() -> bytes:
    rng = random.Random(1102)

    def line(n: int, prefix: str = "") -> str:
        text = prefix
        while len(text) < n:
            text += rng.choice(WORDS) + " "
        return text.strip()

    pages = []
    for number in range(1, 46):
        lines = [line(rng.randint(700, 1000)) for _ in range(12)]
        # Applicability lines at varying places, so the cap cuts some of them.
        lines[rng.randrange(12)] = line(900, f"This deviation applies to page {number} work: ")
        lines[rng.randrange(12)] = line(40, "Applicability. ")
        if number == 1:
            lines[0] = "Issued: May 2, 2025"
        if number == 3:
            lines[-1] = "Effective date:"
        if number == 4:
            lines[0] = "June 1, 2025 for new solicitations"
        if number == 6:
            lines[2] = "Date: 07/04/2025"
        if number == 20:
            lines[5] = "This class deviation Expires on December 31, 2026."
        if number == 33:
            lines[3] = "Effective date: February 30, 2026"
        if number == 35:
            lines = [line(210_000, "A page over the cap on its own, which applies to everything: ")]
        if number == 40:
            lines = []
        pages.append(lines)
    return pdf(pages)


def guidance_pdf() -> bytes:
    return pdf([
        ["May 2, 2025", "MEMORANDUM FOR CHIEF ACQUISITION OFFICERS", "", "SUBJECT: Deviation guidance",
         "BACKGROUND", "Agencies may issue class deviations. Date: May 2, 2025"],
        ["Implementation", "Each agency adopts the model text through a deviation.", "Applicability of the guidance"],
        ["Questions", "Direct questions to the FAR Council."],
    ])


def part_12() -> bytes:
    return b"""<!doctype html><html><body><main>
<h1 class="visual-hidden">FAR Part 12</h1>
<h1>FAR Overhaul Part 12 - Commercial Products and Services</h1>
<p>Issuance Date: June 1, 2025</p>
<h2>12.101 Policy.</h2><p>Agencies shall conduct market research.</p>
<div><h3>12.102 Applicability.</h3><p>This part applies to commercial products.</p><table><tr><td>Cell text</td></tr></table></div>
<h2>Definitions.</h2><p>First definitions.</p>
<h3>Definitions.</h3><p>Repeated heading.</p>
<h2>12.103 Special [characters] (here).</h2><p>Text with &amp; entity.</p>
</main></body></html>"""


def policy_page() -> bytes:
    return b"""<!doctype html><html><body><main><h1>FAR Overhaul - Policy and Guidance</h1>
<h2>Executive Order:</h2><p>Restoring common sense to federal procurement.</p>
<h2>OMB Guidance:</h2><p>Memorandum M-25-26.</p>
<h2>FAR Council Guidance:</h2><p>First guidance.</p>
<h2>FAR Council Guidance:</h2><p>Second guidance.</p>
</main></body></html>"""


def write(out: Path) -> None:
    (out / "bodies").mkdir(parents=True, exist_ok=True)
    manifest = {}

    def body(url: str, kind: str, data: bytes) -> None:
        sha = hashlib.sha256(data).hexdigest()
        (out / "bodies" / sha).write_bytes(data)
        manifest[f"{url} {kind}"] = {"url": url, "final_url": url, "content_type": kind, "sha256": sha, "fetched_at": FETCHED_AT}

    def missing(url: str, kind: str) -> None:
        manifest[f"{url} {kind}"] = {"url": url, "error": f"Acquisition.gov returned HTTP 404: {NOT_FOUND[:500].decode()}",
                                     "transient": False, "fetched_at": FETCHED_AT}

    body(INDEX, "text/html", (FIXTURES / "rfo-index.html").read_bytes())
    for part in range(1, 54):
        url = f"{INDEX}/far-overhaul-part-{part}"
        if part == 10:
            body(url, "text/html", (FIXTURES / "rfo-part-10.html").read_bytes())
        elif part == 12:
            body(url, "text/html", part_12())
        else:
            missing(url, "text/html")
    body(f"{BASE}/far-overhaul/faqs", "text/html", (FIXTURES / "rfo-guidance.html").read_bytes())
    body(f"{BASE}/far-overhaul/policy-and-guidance", "text/html", policy_page())
    body(f"{UPLOADS}/FAR-Council-Deviation-Guidance-on-FAR-Overhaul.pdf", "application/pdf", guidance_pdf())
    body(f"{UPLOADS}/GSA_RFO_Deviation_Part-10.pdf", "application/pdf", long_deviation())
    body(f"{UPLOADS}/NASA_RFO_Deviation_Part-10.pdf", "application/pdf", (FIXTURES / "nsf-part1-2026-09-13.pdf").read_bytes())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))


if __name__ == "__main__":
    write(Path(sys.argv[1]))
