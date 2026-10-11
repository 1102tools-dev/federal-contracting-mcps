"""Snapshot Acquisition.gov's FAR Overhaul resources into the hosted D1 database.

The hosted Acquisition.gov MCP (acquisition-gov.1102tools.com) answers every
tool from this snapshot instead of fetching www.acquisition.gov per call. Each
run fetches the RFO index, all 53 part pages and the three guidance resources,
plus every agency deviation PDF that is new to the index and the least recently
checked existing ones (--revalidate), one request at a time and at least 3
seconds apart. It stops without switching snapshots on HTTP 429 or 403, or when
the index is missing or much smaller than the one being served. Pages and PDFs
are parsed with the acquisition-gov-mcp package's own code, in child processes.

Readers only ever see a complete snapshot: rows are staged under a new snapshot
id and meta.current moves to it in one statement at the end. A run that stops
part-way leaves the current snapshot serving, and the next run resumes the staged
one. Parsed content is stored once per content hash and parser version and shared
between snapshots. The previous snapshot is kept for in-flight requests and
rollback; older ones and unreferenced content are deleted.

    uv run --frozen --project servers/acquisition-gov-mcp python scripts/load_acquisition_gov.py --remote
    ... --local deploy/acquisition-gov/.wrangler/acquisition-gov.sqlite
    ... --record DIR   also save every raw response (parity fixtures)
    ... --replay DIR   rebuild from saved responses; no network
    ... --raw-cache DIR   opt-in local raw cache for reload testing
    ... --raw-cache DIR --reparse   force offline extraction from stored responses

Remote mode uses the D1 HTTP API with CLOUDFLARE_D1_TOKEN (or CLOUDFLARE_API_TOKEN)
and the database id from --database-id, ACQUISITION_GOV_D1_DATABASE_ID, or
deploy/acquisition-gov/wrangler.jsonc.
"""
from __future__ import annotations

import shutil, tempfile
import httpx
from urllib.parse import urljoin
import argparse, asyncio, datetime as dt, hashlib, json, os, re, sqlite3, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "deploy/acquisition-gov"
ACCOUNT_ID = "846d3e41e48446abcd3570c0959f9fb5"
MIN_INTERVAL = 3.0
os.environ["FEDERAL_API_MIN_INTERVAL_SECONDS"] = str(max(MIN_INTERVAL, float(os.environ.get("FEDERAL_API_MIN_INTERVAL_SECONDS") or 0)))
sys.path.insert(0, str(ROOT / "servers/acquisition-gov-mcp/src"))  # the package this script parses with

from acquisition_gov_mcp import __version__, _html, _pdf, constants, server  # noqa: E402

# Bump when the stored layout or derived data changes, so content is re-parsed.
FORMAT = 5
PARSER_VERSION = f"{__version__}+{FORMAT}"
HTML = (("text/html",), constants.MAX_HTML_BYTES)
PDF = (("application/pdf",), constants.MAX_PDF_BYTES)
PARTS = range(1, 54)
USER_AGENT = f"{constants.USER_AGENT} (daily snapshot; +https://github.com/1102tools-dev/federal-contracting-mcps)"
LABELS = ("Issued", "Date", "Effective", "Expiration", "Expires")
CHUNK_CHARS = 30_000
STATEMENT_BYTES = 90_000     # D1 allows 100 KB per SQL statement
REQUEST_BYTES = 900_000      # SQL per D1 HTTP API request
PARSE_SECONDS = 300
MIN_KEEP_RATIO = 0.6
RESUME_HOURS = 36


class Abort(SystemExit):
    """Stop without switching snapshots; the current one keeps serving."""


# ---------- parsing (child processes) ----------

def source_id(kind: str, url: str) -> str:
    return _html._source_id(kind, url)


def read_pdf(body: bytes, start: int, end: int | None) -> list:
    """_read_pdf exactly as the package's isolated PDF worker reports it."""
    try:
        return list(_pdf._read_pdf(body, page_start=start, page_end=end))
    except _pdf.PdfPageRangeError as exc:
        return ["", "error", [str(exc)], {}, exc.total_pages, 0]
    except Exception as exc:  # noqa: BLE001 - mirrors _pdf_worker
        return ["", "error", [f"PDF parsing failed: {type(exc).__name__}."], {}, 0, 0]


def labeled_date_patterns() -> dict:
    """The compiled patterns _pdf._labeled_date searches with, captured rather than copied."""
    real, captured = _pdf.re, {}

    class Capture:
        def __getattr__(self, name):
            return getattr(real, name)

        def compile(self, pattern, flags=0):
            captured["pattern"] = real.compile(pattern, flags)
            return captured["pattern"]

    _pdf.re = Capture()
    try:
        patterns = {}
        for label in LABELS:
            _pdf._labeled_date("", label)
            patterns[label] = captured.pop("pattern")
        return patterns
    finally:
        _pdf.re = real


def labeled_dates(joined: str, pages: list[dict] | None = None) -> dict:
    """Every position where each labeled-date pattern matches the full joined text.

    _labeled_date over the pages a call selects returns the first match that
    starts at or after the first selected page and ends within the last one, so
    storing every match lets the Worker answer any page range.
    """
    found = {}
    for label, pattern in labeled_date_patterns().items():
        matches = []
        for hit in re.finditer(re.escape(label), joined, re.I):
            start = hit.start()
            while start > 0 and joined[start - 1].isspace():
                start -= 1
            line_start = joined.rfind("\n", 0, hit.start()) + 1
            if re.fullmatch(r"[ \t]*\d+[.)]\s*", joined[line_start:hit.start()]):
                start = line_start
            for position in range(start, hit.start() + 1):
                match = pattern.match(joined, position)
                if match:
                    matches.append([position, match.end(), _pdf._normalize_date(match.group(1))])
        found[label] = matches
    # Keep only the current date in adjacent letterhead-date clusters, and
    # never merge a cover date with an attachment on the following page.
    page_texts = [(page["start"], page["text"]) for page in pages] if pages is not None else [(0, joined)]
    found["Standalone"] = [[offset + m.start(), offset + m.end(), _pdf._normalize_date(m.group(1))]
                           for offset, text in page_texts for m in _pdf._standalone_date_matches(text)]
    found["EffectiveRelative"] = [[m.start(), m.end(), "relative"]
                                  for m in _pdf._EFFECTIVE_RELATIVE.finditer(joined)]
    return found


def applicability(page: int, text: str) -> list:
    """[start, end] of each line _extract_document_fields reports as applicability.

    Offsets, not text: a long matching line would not fit beside the page in one row.
    """
    return [list(span) for span in _pdf._applicability_spans(text)]


def parse_pdf(body: bytes, source_url: str | None = None) -> dict:
    """Agency deviation PDF: each page as _read_pdf extracts it, for any page range."""
    first = read_pdf(body, 1, 1)
    if first[4] == 0:
        return {"kind": "pdf", "info": {"failure": first}}
    total, pages, offset = first[4], [], 0
    for number in range(1, total + 1):
        text, _, warnings, _, _, _ = first if number == 1 else read_pdf(body, number, number)
        prefix = f"[Page {number}]\n"
        if not text.startswith(prefix):
            raise RuntimeError(f"unexpected page text layout on page {number}")
        text = text[len(prefix):]
        failure = next((m.group(1) for w in warnings if (m := re.fullmatch(rf"Page {number} extraction failed: (\w+)\.", w))), None)
        over_cap = any("parser limit" in w for w in warnings)
        # The existing Worker reconstructs PDF warnings from page failure
        # flags. Preserve recovery disclosure in the already-visible page body
        # and suppress incomplete rule fragments when outlined words are lost.
        if any("contains outlined text that could not be recovered" in w for w in warnings):
            failure = "OutlinedTextRecoveryError"
            link = f"Read the official PDF: {source_url}" if source_url else "Open the official PDF using the source_url link in this tool response."
            text = f"[Parser notice: Important words drawn as outlines could not be extracted on page {number}; rules may be missing. {link}]"
        else:
            notices = [w for w in warnings if "text was recovered with OCR" in w]
            if notices:
                text = "\n".join(f"[Parser notice: {notice}]" for notice in notices) + "\n" + text
        pages.append({"page": number, "start": offset, "text": text, "failure": failure, "over_cap": over_cap,
                      "applicability": applicability(number, text)})
        offset += len(text) + 1
    joined = "\n".join(p["text"] for p in pages)
    window = max(sum(len(p["text"]) for p in pages[i:i + constants.MAX_PDF_PAGES]) for i in range(len(pages)))
    return {"kind": "pdf", "info": {"total_pages": total, "dates": labeled_dates(joined, pages), "max_window_characters": window},
            "pages": pages}


def parse_guidance_pdf(body: bytes) -> dict:
    text, status, warnings, fields, total, _ = read_pdf(body, 1, constants.MAX_PDF_PAGES)
    lines = text.splitlines()
    keys, offset = [], 0
    for i, line in enumerate(lines):
        keys.append([i, " ".join(line.split()).casefold(), offset, offset + len(line)])
        offset += len(line) + 1
    return {"kind": "guidance_pdf", "info": {"status": status, "warnings": warnings, "fields": fields, "total_pages": total},
            "streams": {"text": text, "lines": "\n".join(lines)}, "headings": keys}


def heading_key(heading) -> str:
    return " ".join(heading.get_text(" ", strip=True).split()).casefold()


def section_spans(node) -> tuple[str, list]:
    """Each heading's section, as _extract_section walks it, as a span of one stream.

    _extract_section collects every text node after the heading (its own text
    included) until the next heading of the same or a higher level. Recording
    the text nodes once, in document order, gives every section as a contiguous
    run of them.
    """
    headings = list(node.find_all(re.compile(r"^h[1-6]$")))
    position = {id(h): i for i, h in enumerate(headings)}
    lines, spans, open_ = [], [[0, 0] for _ in headings], []
    for element in node.descendants:
        if isinstance(element, _html.Tag) and re.fullmatch(r"h[1-6]", element.name or ""):
            level = int(element.name[1])
            for i, open_level in list(open_):
                if level <= open_level:
                    spans[i][1] = len(lines)
                    open_.remove((i, open_level))
            if id(element) in position:
                i = position[id(element)]
                spans[i][0] = len(lines)
                open_.append((i, level))
        elif type(element) in (_html.NavigableString, _html.CData):
            text = " ".join(str(element).split())
            if text:
                lines.append(text)
    for i, _ in open_:
        spans[i][1] = len(lines)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    rows = []
    for i, (h, (first, last)) in enumerate(zip(headings, spans)):
        start = offsets[first]
        end = offsets[last] - 1 if last > first else start
        rows.append([i, heading_key(h), start, end])
    return "\n".join(lines), rows


def parse_html(body: bytes, part: int | None, verify: int = 40) -> dict:
    """A part or guidance page as _parse_html_document reads it, plus every heading's section."""
    original, captured = _html._extract_section, {}

    def capture(node, section):
        captured["node"] = node
        return original(node, section)

    _html._extract_section = capture
    text_error = None
    try:
        page = _html._parse_html_document(body, part=part, heading=None, cursor=None, maximum=constants.MAX_OUTPUT_CHARACTERS)
        dates = {"issuance_date": page["issuance_date"], "updated_date": page["updated_date"]}
    except (ValueError, RuntimeError) as exc:
        if "node" not in captured:
            return {"kind": "html", "info": {"error": str(exc)}}
        text_error, dates = str(exc), {"issuance_date": None, "updated_date": None}
    except Exception:  # noqa: BLE001 - mirrors _html_worker
        return {"kind": "html", "info": {"error": "HTML parsing failed."}}
    finally:
        _html._extract_section = original
    node = captured["node"]
    text = "" if text_error else original(node, None)
    stream, headings = section_spans(node)
    # Check the spans against the package's own section extraction.
    counts = {}
    for _, key, _, _ in headings:
        counts[key] = counts.get(key, 0) + 1
    unique = [h for h in headings if counts[h[1]] == 1 and h[1] and len(h[1]) <= 500]
    step = max(1, len(unique) // verify)
    for _, key, start, end in unique[::step]:
        heading = next(h for h in node.find_all(re.compile(r"^h[1-6]$")) if heading_key(h) == key)
        expected = original(node, " ".join(heading.get_text(" ", strip=True).split()))
        if expected != stream[start:end]:
            raise RuntimeError(f"section span differs from _extract_section for heading {key[:80]!r}")
    return {"kind": "html", "info": {**dates, "text_error": text_error},
            "streams": {"text": text, "sections": stream}, "headings": headings}


def parse_index(body: bytes, final_url: str) -> dict:
    parts = _html._parse_index(body, final_url)
    if not parts:
        return {"kind": "index", "info": {"error": "The Acquisition.gov index structure was not recognized; no results can be confirmed."}}
    return {"kind": "index", "info": {"parts": len(parts)}, "parts": parts}


def parse_worker(kind: str, arguments: dict) -> None:
    body = sys.stdin.buffer.read()
    if kind == "index":
        result = parse_index(body, arguments["final_url"])
    elif kind == "html":
        result = parse_html(body, arguments.get("part"))
    elif kind == "guidance_pdf":
        result = parse_guidance_pdf(body)
    else:
        result = parse_pdf(body, source_url=arguments.get("source_url"))
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


async def parse(kind: str, body: bytes, **arguments) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable, __file__, "--parse-worker", kind, json.dumps(arguments),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, errors = await asyncio.wait_for(process.communicate(body), PARSE_SECONDS)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        if kind in ("pdf", "guidance_pdf"):
            failure = ["", "error", ["PDF parsing exceeded its time budget; request fewer pages or inspect the source document."], {}, 0, 0]
            return {"kind": kind, "info": {"failure": failure} if kind == "pdf" else
                    {"status": "error", "warnings": failure[2], "fields": {}, "total_pages": 0}, "streams": {"text": "", "lines": ""}, "headings": []}
        return {"kind": kind, "info": {"error": "HTML parsing exceeded its 40-second time budget."}}
    if process.returncode:
        raise RuntimeError(f"{kind} parser failed: {errors.decode('utf-8', 'replace')[-2000:]}")
    return json.loads(output)


# ---------- fetching ----------

def fatal(message: str) -> bool:
    return ("rate limited the request" in message or "cooldown remains active" in message
            or message.startswith("Acquisition.gov returned HTTP 403"))


def unavailable(result: dict | None) -> bool:
    """Only an origin's explicit 404/410 is a durable recorded absence."""
    return bool(result and not result.get("transient")
                and re.match(r"^Acquisition\.gov returned HTTP (?:404|410)\b", result.get("error", "")))


def transient(message: str) -> bool:
    return (message.startswith(("Network error calling", "System curl"))
            or any(message.startswith(f"Acquisition.gov returned HTTP {code}") for code in range(500, 600)))


class Recorder:
    """Raw responses as fetched, so a snapshot can be rebuilt or replayed offline."""

    def __init__(self, path: Path):
        self.path = path
        (path / "bodies").mkdir(parents=True, exist_ok=True)
        manifest = path / "manifest.json"
        self.entries = json.loads(manifest.read_text()) if manifest.exists() else {}

    @staticmethod
    def key(url: str, kind) -> str:
        return f"{url} {kind[0][0]}"

    def save(self, url: str, kind, result: dict):
        entry = {k: v for k, v in result.items() if k not in ("body", "parsed")}
        if "body" in result:
            if hashlib.sha256(result["body"]).hexdigest() != result.get("sha256"):
                raise Abort(f"Raw response hash mismatch for {url}")
            body = self.path / "bodies" / result["sha256"]
            try:
                valid = (body.stat().st_size == len(result["body"])
                         and hashlib.sha256(body.read_bytes()).hexdigest() == result["sha256"])
            except OSError:
                valid = False
            if not valid:
                # A verified incoming recording can repair a damaged raw cache.
                with tempfile.NamedTemporaryFile(dir=body.parent, prefix=body.name + ".", suffix=".partial", delete=False) as saved:
                    partial = Path(saved.name)
                    saved.write(result["body"])
                try:
                    os.replace(partial, body)
                finally:
                    partial.unlink(missing_ok=True)
        self.entries[self.key(url, kind)] = entry
        manifest = self.path / "manifest.json"
        partial = manifest.with_suffix(".partial")
        partial.write_text(json.dumps(self.entries, indent=1, sort_keys=True))
        os.replace(partial, manifest)

    def has(self, url: str, kind) -> bool:
        """A recorded body, or an error that a retry would not change."""
        entry = self.entries.get(self.key(url, kind))
        return entry is not None and not entry.get("transient")

    def load(self, url: str, kind) -> dict | None:
        entry = self.entries.get(self.key(url, kind))
        if entry is None:
            return None
        result = dict(entry)
        if result.get("url") != url:
            raise Abort(f"Corrupt raw cache metadata for {url}: URL mismatch")
        if "sha256" in entry:
            sha = entry["sha256"]
            try:
                if not re.fullmatch(r"[a-f0-9]{64}", sha):
                    raise ValueError("invalid hash")
                path = self.path / "bodies" / sha
                if path.stat().st_size > kind[1]:
                    raise ValueError("body exceeds allowed size")
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != sha:
                    raise ValueError("body hash mismatch")
                if entry.get("url") != url or entry.get("content_type") not in kind[0]:
                    raise ValueError("metadata mismatch")
                server._validated_url(entry["final_url"])
            except (OSError, ValueError, KeyError) as exc:
                raise Abort(f"Corrupt raw cache for {url}: {exc}") from exc
            result["body"] = body
        return result


async def _conditional_curl_once(url: str, *, max_bytes: int, headers: dict) -> tuple[httpx.Response, bytes]:
    """One HTTPS fetch, with a streaming body bound independent of curl version."""
    url = server._validated_url(url)
    executable = shutil.which("curl")
    if not executable:
        raise RuntimeError("System curl fallback is unavailable.")
    with tempfile.TemporaryDirectory(prefix="acquisition-gov-mcp-") as temporary:
        headers_path = Path(temporary) / "headers"
        process = await asyncio.create_subprocess_exec(
            executable, "--disable", "--silent", "--show-error", "--proto", "=https",
            "--max-time", str(int(constants.DEFAULT_TIMEOUT)), "--max-filesize", str(max_bytes),
            "--max-redirs", "0", "--header", f"User-Agent: {USER_AGENT}",
            "--header", "Accept: text/html,application/pdf", "--header", "Accept-Encoding: identity",
            *[arg for k, v in headers.items() for arg in ("--header", f"{k}: {v}")],
            "--dump-header", str(headers_path), "--output", "-",
            "--write-out", "%{stderr}\nSTATUS:%{http_code}\nTYPE:%{content_type}\nREDIRECT:%{redirect_url}\n", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        async def bounded_read(stream, limit):
            chunks = []
            size = 0
            while chunk := await stream.read(65536):
                size += len(chunk)
                if size > limit:
                    raise RuntimeError(f"Acquisition.gov curl response exceeds the {limit}-byte limit.")
                chunks.append(chunk)
            return b"".join(chunks)
        tasks = [asyncio.create_task(bounded_read(process.stdout, max_bytes)),
                 asyncio.create_task(bounded_read(process.stderr, 8192)),
                 asyncio.create_task(process.wait())]
        try:
            try:
                body, errors, _ = await asyncio.wait_for(asyncio.gather(*tasks), constants.DEFAULT_TIMEOUT + 2)
            except asyncio.TimeoutError as exc:
                raise RuntimeError("System curl timed out calling Acquisition.gov.") from exc
            if process.returncode:
                raise RuntimeError(f"System curl could not retrieve Acquisition.gov: exit {process.returncode}; {errors.decode('utf-8', 'replace').strip()[:300]}")
            metadata = dict(line.split(":", 1) for line in errors.decode("utf-8", "replace").splitlines() if ":" in line)
            if not {"STATUS", "TYPE", "REDIRECT"}.issubset(metadata):
                raise RuntimeError("System curl returned incomplete response metadata.")
            status = int(metadata["STATUS"])
            raw_headers = headers_path.read_text(encoding="iso-8859-1")
            blocks = [block for block in re.split(r"\r?\n\r?\n", raw_headers) if block.strip()]
            lines = blocks[-1].splitlines() if blocks else []
            headers = dict((k.strip(), v.strip()) for line in lines[1:] if ":" in line for k, v in [line.split(":", 1)])
            normalized = httpx.Headers(headers)
            if metadata["TYPE"] and "content-type" not in normalized:
                normalized["content-type"] = metadata["TYPE"]
            if metadata["REDIRECT"] and "location" not in normalized:
                normalized["location"] = metadata["REDIRECT"]
            return httpx.Response(status, headers=normalized, content=body), body
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class Fetcher:
    """Normal package fetches, or opt-in paced conditional requests and offline raw replay."""

    def __init__(self, recorder: Recorder | None = None, replay: Recorder | None = None, retry_pause: float = 30.0,
                 max_cooldown: float = 0.0, log=print, raw_cache: Recorder | None = None, reparse: bool = False):
        self.recorder, self.replay, self.retry_pause = recorder, replay, retry_pause
        self.max_cooldown, self.log = max_cooldown, log
        self.allow_missing = False
        self.requests = self.bytes = self.downloads = self.checks = self.cache_bytes = 0
        self.raw_cache = raw_cache
        self.reparse = reparse
        self.cache: dict[tuple, dict] = {}
        server.USER_AGENT = USER_AGENT

    async def fetch(self, url: str, kind) -> dict:
        """Body, final URL and fetch time, or the error message a tool would have raised."""
        key = (url, kind)
        if key in self.cache:
            return self.cache[key]
        if self.replay:
            result = self.replay.load(url, kind)
            if result is None:
                if self.allow_missing:
                    return None
                raise Abort(f"{url} is not in the replayed recording")
        elif self.reparse:
            if self.raw_cache is None:
                raise Abort("Re-parse requires a local raw response cache")
            result = self.raw_cache.load(url, kind)
            permanent_error = unavailable(result)
            if result is None or ("body" not in result and not permanent_error):
                raise Abort(f"{url} has no complete raw cached copy; import a recording or run a full reload first")
            # Unposted resources can truthfully remain recorded unavailable offline.
            # They have no document to extract; transient failures are incomplete.
            if "body" in result:
                self.cache_bytes += len(result["body"])
        else:
            result = await self._fetch(url, kind)
        if result is not None and "body" in result:
            if self.replay:
                self.bytes += len(result["body"])
        if self.raw_cache and not self.reparse and result is not None and ("body" in result or unavailable(result)):
            # Guard failures and temporary outages never replace verified raw data.
            self.raw_cache.save(url, kind, result)
        if self.recorder:
            self.recorder.save(url, kind, result)
        self.cache[key] = result
        return result

    async def _fetch(self, url: str, kind) -> dict:
        attempt = waits = 0
        while attempt < 2:
            try:
                cached = self.raw_cache.load(url, kind) if self.raw_cache else None
                result = await self._download(url, kind, cached if cached and "body" in cached else None)
            except (RuntimeError, ValueError) as exc:
                message = str(exc)
                cooldown = re.search(r"cooldown remains active for approximately (\d+) seconds", message)
                if cooldown and int(cooldown.group(1)) <= self.max_cooldown and waits < 5:
                    waits += 1
                    # Retry-After from an earlier 429, recorded by the package's pacer.
                    self.log(f"Acquisition.gov asked us to wait {cooldown.group(1)} s; waiting.")
                    await asyncio.sleep(int(cooldown.group(1)) + 5)
                    continue
                if "rate limited the request" in message and self.max_cooldown and "Retry-After=" in message and waits < 5:
                    waits += 1
                    continue  # the next attempt reports the recorded cooldown
                if fatal(message):
                    raise Abort(f"Stopping without switching snapshots: {message}")
                if transient(message) and attempt == 0:
                    attempt += 1
                    await asyncio.sleep(self.retry_pause)
                    continue
                return {"url": url, "error": message, "transient": transient(message), "fetched_at": server._now()}
            return result
        raise AssertionError("unreachable")


    async def _download(self, url: str, kind, cached=None) -> dict:
        """Bounded conditional requests using the same allowlist and three-second pacer."""
        allowed, max_bytes = kind
        if self.raw_cache is None:
            self.requests += 1
            body, content_type, final_url = await server._fetch_bytes(url, allowed_types=allowed, max_bytes=max_bytes)
            self.downloads += 1
            self.bytes += len(body)
            return {"url": url, "final_url": final_url, "content_type": content_type, "body": body,
                    "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": server._now()}
        # Cached HTML is refreshed normally; cached PDFs use origin validators.
        headers = {}
        if cached and kind == PDF:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        current = server._validated_url(url)
        for redirect in range(constants.MAX_REDIRECTS + 1):
            self.requests += 1
            async with server._pacer.request_slot() as pacing:
                if shutil.which("curl"):
                    response, body = await _conditional_curl_once(current, max_bytes=max_bytes, headers=headers)
                else:
                    try:
                        async with server._get_client().stream("GET", current, headers=headers) as response:
                            body = await server._bounded_httpx_body(response, max_bytes=max_bytes)
                    except httpx.RequestError as exc:
                        raise RuntimeError(f"Network error calling Acquisition.gov: {exc}") from exc
                pacing.observe_response(response)
                pacing.raise_if_rate_limited(response, service="Acquisition.gov")
            if response.status_code in server._REDIRECTS:
                location = response.headers.get("location")
                if not location or redirect >= constants.MAX_REDIRECTS:
                    raise RuntimeError("Acquisition.gov exceeded the redirect limit or omitted Location.")
                current = server._validated_url(urljoin(current, location))
                # Validators belong to the original cached final resource only.
                if cached and current != cached["final_url"]:
                    headers = {}
                continue
            if response.status_code == 304:
                if not cached or not headers or current != cached["final_url"]:
                    raise RuntimeError("Acquisition.gov returned an unexpected HTTP 304.")
                self.checks += 1
                self.cache_bytes += len(cached["body"])
                result = dict(cached, fetched_at=server._now())
                result["etag"] = response.headers.get("etag", cached.get("etag"))
                result["last_modified"] = response.headers.get("last-modified", cached.get("last_modified"))
                return result
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Acquisition.gov returned HTTP {response.status_code}: {body[:500].decode('utf-8', 'replace')}")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in allowed:
                raise RuntimeError(f"Unexpected Content-Type {content_type!r} from Acquisition.gov.")
            if response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
                raise RuntimeError("Unexpected compressed Acquisition.gov response; identity encoding is required.")
            self.downloads += 1
            self.bytes += len(body)
            return {"url": url, "final_url": current, "content_type": content_type, "body": body,
                    "sha256": hashlib.sha256(body).hexdigest(), "fetched_at": server._now(),
                    "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified")}
        raise RuntimeError("Acquisition.gov exceeded the redirect limit.")


# ---------- D1 ----------

def quote(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if "\x00" in text:
        return "(" + " || char(0) || ".join(quote(part) for part in text.split("\x00")) + ")"
    return "'" + text.replace("'", "''") + "'"


def inserts(table: str, columns: list[str], rows: list[list]) -> list[str]:
    """Multi-row INSERT OR REPLACE statements, each under the D1 statement limit."""
    head = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES "
    statements, values, size = [], [], len(head)
    for row in rows:
        value = "(" + ", ".join(quote(v) for v in row) + ")"
        length = len(value.encode("utf-8")) + 2
        if length + len(head) > STATEMENT_BYTES:
            raise ValueError(f"row too large for one statement in {table}")
        if values and size + length > STATEMENT_BYTES:
            statements.append(head + ", ".join(values) + ";")
            values, size = [], len(head)
        values.append(value)
        size += length
    if values:
        statements.append(head + ", ".join(values) + ";")
    return statements


def split_text(text: str, chars: int = CHUNK_CHARS) -> list[tuple[int, int, str]]:
    """(start, length, piece) pieces small enough for one row each."""
    pieces, start = [], 0
    while start < len(text) or not pieces:
        size = chars
        while size > 1 and len(quote(text[start:start + size]).encode("utf-8")) > STATEMENT_BYTES - 500:
            size //= 2
        piece = text[start:start + size]
        pieces.append((start, len(piece), piece))
        start += len(piece)
        if not piece:
            break
    return pieces


class LocalD1:
    """A sqlite file with the same schema, for wrangler dev, tests and parity runs."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def query(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params)]

    def execute(self, statements: list[str]) -> None:
        if statements:
            self.db.executescript("\n".join(statements))
            self.db.commit()


class RemoteD1:
    """The D1 HTTP API (the same endpoint wrangler d1 execute --remote uses)."""

    def __init__(self, database_id: str, token: str, account_id: str = ACCOUNT_ID):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = token
        self.calls = 0

    def _post(self, payload: dict) -> list:
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(4):
            request = urllib.request.Request(self.url, data=data, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "1102tools-acquisition-gov-loader"})
            self.calls += 1
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    body = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:1000].decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API returned {exc.code}: {detail}") from None
            except urllib.error.URLError as exc:
                if attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise RuntimeError(f"D1 HTTP API unreachable: {exc.reason}") from None
            if not body.get("success"):
                raise RuntimeError(f"D1 query failed: {json.dumps(body.get('errors'))[:1000]}")
            return body["result"]
        raise AssertionError("unreachable")

    def query(self, sql: str, params=()) -> list[dict]:
        return self._post({"sql": sql, "params": list(params)})[0]["results"]

    def execute(self, statements: list[str]) -> None:
        batch, size = [], 0
        for statement in statements:
            length = len(statement.encode("utf-8")) + 1
            if batch and size + length > REQUEST_BYTES:
                self._post({"sql": "\n".join(batch)})
                batch, size = [], 0
            batch.append(statement)
            size += length
        if batch:
            self._post({"sql": "\n".join(batch)})


def database_id(argument: str | None) -> str:
    value = argument or os.environ.get("ACQUISITION_GOV_D1_DATABASE_ID")
    if not value:
        config = json.loads(re.sub(r"^\s*//.*$", "", (WORKER_DIR / "wrangler.jsonc").read_text(), flags=re.M))
        value = config["d1_databases"][0]["database_id"]
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
        raise SystemExit("Set --database-id or ACQUISITION_GOV_D1_DATABASE_ID to the acquisition-gov D1 database id.")
    return value


# ---------- snapshot ----------

def doc_id(kind: str, sha256: str, **inputs) -> str:
    material = json.dumps([PARSER_VERSION, kind, sha256, inputs], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def doc_statements(doc: str, parsed: dict) -> list[str]:
    """Every row of one parsed document; the docs row comes last so it marks the content complete."""
    statements = []
    for table in ("chunks", "headings", "pages", "index_parts", "index_deviations"):
        statements.append(f"DELETE FROM {table} WHERE doc = {quote(doc)};")
    rows = [[doc, stream, seq, start, length, piece]
            for stream, text in parsed.get("streams", {}).items()
            for seq, (start, length, piece) in enumerate(split_text(text))]
    statements += inserts("chunks", ["doc", "stream", "seq", "start", "length", "body"], rows)
    statements += inserts("headings", ["doc", "idx", "key", "start", "end"], [[doc, *h] for h in parsed.get("headings", [])])
    rows = []
    for page in parsed.get("pages", []):
        extra = json.dumps(page["applicability"], ensure_ascii=False) if page["applicability"] else None
        for seq, (_, _, piece) in enumerate(split_text(page["text"])):
            rows.append([doc, page["page"], seq, page["start"], len(page["text"]), page["failure"], page["over_cap"], extra if seq == 0 else None, piece])
    statements += inserts("pages", ["doc", "page", "seq", "start", "length", "failure", "over_cap", "applicability", "body"], rows)
    if "parts" in parsed:
        parts, deviations, seq = [], [], 0
        for ordinal, item in enumerate(parsed["parts"]):
            card = {k: v for k, v in item.items() if k != "agency_deviations"}
            parts.append([doc, ordinal, item["part"], item["updated_date"], len(item["agency_deviations"]), json.dumps(card, ensure_ascii=False)])
            for deviation in item["agency_deviations"]:
                deviations.append([doc, seq, item["part"], deviation["agency"], deviation["source_id"], deviation["source_url"], json.dumps(deviation, ensure_ascii=False)])
                seq += 1
        statements += inserts("index_parts", ["doc", "ordinal", "part", "updated_date", "deviations", "item"], parts)
        statements += inserts("index_deviations", ["doc", "seq", "part", "agency", "source_id", "url", "item"], deviations)
    info = dict(parsed["info"])
    if "parts" in parsed:
        info["agencies"] = agency_table(parsed["parts"])
    statements += inserts("docs", ["id", "kind", "info"], [[doc, parsed["kind"], json.dumps(info, ensure_ascii=False)]])
    return statements


def agency_table(parts: list) -> list:
    """Posted agency labels with server._matching_agency_names' normalized form and acronym."""
    names = sorted({d["agency"] for p in parts for d in p["agency_deviations"]})
    normalize = lambda text: re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()  # noqa: E731

    def acronym(name):
        match = re.search(r"(?:\(([A-Z][A-Z0-9]{1,9})\)|(?:^|\s)([A-Z][A-Z0-9]{1,9}))$", name)
        return (match.group(1) or match.group(2)) if match else None

    table = [[name, normalize(name), acronym(name)] for name in names]
    # Cross-check against the package's matcher.
    for name, norm, _ in table:
        if not norm:
            continue
        direct = {n for n, m, _ in table if norm in m}
        aliases = {a for n, _, a in table if n in direct} - {None}
        expected = direct | {n for n, _, a in table if a in aliases}
        if expected != server._matching_agency_names(parts, name):
            raise RuntimeError(f"agency normalization differs from the package for {name!r}")
    return table


class Loader:
    def __init__(self, db, fetcher: Fetcher, revalidate: int = 100, full: bool = False, log=print, now=None, reparse: bool = False):
        self.db, self.fetcher, self.revalidate, self.full, self.log = db, fetcher, revalidate, full, log
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat())
        self.reparse = reparse or fetcher.reparse
        self.generation = None
        self.parsers = asyncio.Semaphore(2)
        self.pending: list[asyncio.Task] = []
        self.stored: set[str] = set()  # source keys this run wrote fresh rows for
        self.counts = {"fetched": 0, "parsed": 0, "reused": 0, "fetch_errors": 0, "transient_kept": 0, "carried_forward": 0}

    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self.db.query("SELECT key, value FROM meta")}

    def setup(self) -> tuple[int | None, int]:
        self.db.execute([(WORKER_DIR / "schema.sql").read_text()])
        self.fetcher.reparse = self.reparse or self.fetcher.reparse
        meta = self.meta()
        current = int(meta["current"]) if "current" in meta else None
        staging = int(meta["staging"]) if "staging" in meta else None
        if self.reparse or staging is None or staging == current:
            staging = max([current or 0] + [r["id"] for r in self.db.query("SELECT id FROM snapshots")]) + 1
            self.db.execute([f"DELETE FROM sources WHERE snapshot = {staging};",
                             *inserts("snapshots", ["id", "started_at"], [[staging, self.now()]]),
                             *inserts("meta", ["key", "value"], [["staging", str(staging)]])])
        self.generation = f"reparse:{staging}:{time.time_ns()}" if self.reparse else None
        return current, staging

    def existing_docs(self, ids: list[str]) -> set[str]:
        found = set()
        for start in range(0, len(ids), 90):
            batch = ids[start:start + 90]
            found |= {r["id"] for r in self.db.query(f"SELECT id FROM docs WHERE id IN ({', '.join('?' * len(batch))})", batch)}
        return found

    async def store(self, snapshot: int, key: str, fetched: dict, kind: str, parse_kind: str | None, **inputs) -> dict:
        """Write one source row, parsing and storing its content unless it is already stored."""
        row = {"snapshot": snapshot, "key": key, "url": fetched["url"], "final_url": fetched.get("final_url"),
               "source_id": None, "retrieved_at": fetched["fetched_at"], "content_sha256": fetched.get("sha256"),
               "error": fetched.get("error"), "doc": None}
        self.counts["fetched"] += 1
        if "error" in fetched:
            self.counts["fetch_errors"] += 1
        else:
            if kind:
                row["source_id"] = source_id(kind, fetched["final_url"])
            if parse_kind:
                if parse_kind == "index":
                    inputs["final_url"] = fetched["final_url"]
                row["doc"] = doc_id(parse_kind, fetched["sha256"], **inputs, **({"generation": self.generation} if self.generation else {}))
                if row["doc"] not in self.existing_docs([row["doc"]]):
                    async with self.parsers:
                        parse_arguments = dict(inputs)
                        if parse_kind == "pdf":
                            parse_arguments["source_url"] = fetched["final_url"]
                        parsed = await parse(parse_kind, fetched["body"], **parse_arguments)
                    self.db.execute(doc_statements(row["doc"], parsed))
                    self.counts["parsed"] += 1
                    fetched["parsed"] = parsed
                else:
                    self.counts["reused"] += 1
        self.db.execute(inserts("sources", list(row), [list(row.values())]))
        self.stored.add(key)
        return row

    def later(self, coroutine):
        self.pending.append(asyncio.ensure_future(coroutine))

    async def run(self) -> dict:
        try:
            return await self._run()
        except Abort:
            # Store what was already fetched, so the next run resumes after it.
            await self.drain()
            raise

    async def _run(self) -> dict:
        started = time.monotonic()
        current, staging = self.setup()
        self.log(f"current snapshot {current}, staging {staging}")
        previous_sources = {r["key"]: r for r in self.db.query("SELECT * FROM sources WHERE snapshot = ?", [current])} if current else {}
        staged = {r["key"]: r for r in self.db.query("SELECT * FROM sources WHERE snapshot = ?", [staging])}

        # The index decides which deviation PDFs exist; stop if it is unusable.
        index = await self.fetcher.fetch(constants.RFO_INDEX_URL, HTML)
        if "error" in index:
            raise Abort(f"Index unavailable; stopping without switching snapshots: {index['error']}")
        index_row = await self.store(staging, "index", index, None, "index")
        info = json.loads(self.db.query("SELECT info FROM docs WHERE id = ?", [index_row["doc"]])[0]["info"])
        if "error" in info:
            raise Abort(f"Index not parseable; stopping without switching snapshots: {info['error']}")
        deviations = self.db.query("SELECT url FROM index_deviations WHERE doc = ? ORDER BY seq", [index_row["doc"]])
        urls = list(dict.fromkeys(r["url"] for r in deviations))
        old_count = sum(1 for k in previous_sources if k.startswith("pdf:"))
        if old_count and len(urls) < MIN_KEEP_RATIO * old_count:
            raise Abort(f"The index lists {len(urls)} deviation PDFs but the current snapshot has {old_count}; stopping.")
        self.log(f"index: {info['parts']} parts, {len(deviations)} deviation links, {len(urls)} PDFs")

        for n in PARTS:
            fetched = await self.fetcher.fetch(f"{constants.RFO_INDEX_URL}/far-overhaul-part-{n}", HTML)
            self.later(self.store(staging, f"part:{n}", fetched, "model-part", "html", part=n))
        for name, url in constants.GUIDANCE_URLS.items():
            pdf = name == "deviation_guidance"
            fetched = await self.fetcher.fetch(url, PDF if pdf else HTML)
            self.later(self.store(staging, f"guidance:{name}", fetched, "guidance", "guidance_pdf" if pdf else "html"))
        await self.drain()

        # Deviation PDFs: new ones, failed ones, and the least recently checked.
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=RESUME_HOURS)).replace(microsecond=0).isoformat()
        # A recently staged PDF is reusable only if this parser produced its
        # derived data. A new parser must not resume by skipping old date
        # matches merely because the upstream bytes were fetched recently.
        # Error rows have no parsed document and are retried on resume.
        done = {k for k, r in staged.items() if not self.reparse and k.startswith("pdf:")
                and r["retrieved_at"] >= cutoff and r["error"] is None
                and r["doc"] == doc_id("pdf", r["content_sha256"])}
        wanted = [u for u in urls if f"pdf:{u}" not in done]
        new = [u for u in wanted if f"pdf:{u}" not in previous_sources
               or previous_sources[f"pdf:{u}"]["error"]
               or staged.get(f"pdf:{u}", {}).get("error")]
        known = sorted((u for u in wanted if u not in set(new)), key=lambda u: previous_sources[f"pdf:{u}"]["retrieved_at"])
        fetch = new + (known if self.full or self.reparse else known[:self.revalidate])
        self.log(f"PDFs: {len(new)} new or failed, {len(fetch) - len(new)} rechecked, {len(done)} already staged")
        for i, url in enumerate(fetch, 1):
            fetched = await self.fetcher.fetch(url, PDF)
            if fetched is None:  # --allow-missing: absent from a partial recording
                urls.remove(url)
                continue
            old = previous_sources.get(f"pdf:{url}")
            if fetched.get("transient") and old and not old["error"]:
                self.counts["transient_kept"] += 1  # keep the last good copy
                continue
            self.later(self.store(staging, f"pdf:{url}", fetched, None, "pdf"))
            if i % 50 == 0:
                self.log(f"  {i}/{len(fetch)} PDFs ({time.monotonic() - started:.0f}s)")
        await self.drain()

        # Indexed PDFs that neither this run nor the resumed one stored fresh
        # (not rechecked, or a transient failure) carry over from the current
        # snapshot; staged PDFs the index no longer lists are dropped.
        keep = [f"pdf:{u}" for u in urls]
        carried = [k for k in keep if k in previous_sources and k not in done and k not in self.stored]
        for start in range(0, len(carried), 80):
            batch = carried[start:start + 80]
            self.db.execute([f"INSERT OR REPLACE INTO sources SELECT {staging}, key, url, final_url, source_id, retrieved_at, "
                             f"content_sha256, error, doc FROM sources WHERE snapshot = {current} AND key IN ({', '.join(quote(k) for k in batch)});"])
        self.counts["carried_forward"] = len(carried)
        staged_now = {r["key"] for r in self.db.query("SELECT key FROM sources WHERE snapshot = ? AND key LIKE 'pdf:%'", [staging])}
        stale = sorted(staged_now - set(keep))
        for start in range(0, len(stale), 80):
            self.db.execute([f"DELETE FROM sources WHERE snapshot = {staging} AND key IN ({', '.join(quote(k) for k in stale[start:start + 80])});"])
        missing = [k for k in keep if k not in staged_now]
        if missing:
            raise Abort(f"{len(missing)} indexed PDFs have no stored copy (first: {missing[0]}); stopping without switching.")
        return self.switch(current, staging, started, len(urls))

    async def drain(self):
        while self.pending:
            pending, self.pending = self.pending, []
            await asyncio.gather(*pending)

    def switch(self, current: int | None, staging: int, started: float, pdfs: int) -> dict:
        stats = {"snapshot": staging, "completed_at": self.now(), "parser_version": PARSER_VERSION, "pdfs": pdfs,
                 "requests": self.fetcher.requests, "bytes": self.fetcher.bytes,
                 "downloads": self.fetcher.downloads, "conditional_checks": self.fetcher.checks, "cache_bytes": self.fetcher.cache_bytes,
                 "mode": "reparse" if self.reparse else "reload", "seconds": round(time.monotonic() - started, 1), **self.counts}
        statements = [f"UPDATE snapshots SET completed_at = {quote(stats['completed_at'])}, stats = {quote(json.dumps(stats))} WHERE id = {staging};"]
        statements += inserts("meta", ["key", "value"], [["current", str(staging)]] + ([["previous", str(current)]] if current else []))
        statements.append("DELETE FROM meta WHERE key = 'staging';")
        self.db.execute(statements)
        keep = [staging] + ([current] if current else [])
        ids = ", ".join(str(i) for i in keep)
        self.db.execute([f"DELETE FROM sources WHERE snapshot NOT IN ({ids});",
                         f"DELETE FROM snapshots WHERE id NOT IN ({ids});",
                         *(f"DELETE FROM {t} WHERE doc NOT IN (SELECT doc FROM sources WHERE doc IS NOT NULL);"
                           for t in ("chunks", "headings", "pages", "index_parts", "index_deviations")),
                         "DELETE FROM docs WHERE id NOT IN (SELECT doc FROM sources WHERE doc IS NOT NULL);"])
        return stats


async def record_only(recorder: Recorder, log=print) -> dict:
    """Fetch every resource the tools can request into a recording, resuming where it stopped.

    Nothing is parsed or stored in a database; build from the recording with --replay.
    """
    fetcher = Fetcher(recorder=recorder, max_cooldown=3600, log=log)
    started, skipped = time.monotonic(), 0

    async def get(url, kind):
        nonlocal skipped
        if recorder.has(url, kind):
            skipped += 1
            return recorder.load(url, kind)
        return await fetcher.fetch(url, kind)

    index = await get(constants.RFO_INDEX_URL, HTML)
    if "error" in index:
        raise Abort(f"Index unavailable: {index['error']}")
    parts = _html._parse_index(index["body"], index["final_url"])
    urls = list(dict.fromkeys(d["source_url"] for p in parts for d in p["agency_deviations"]))
    log(f"index: {len(parts)} parts, {len(urls)} PDFs")
    for n in PARTS:
        await get(f"{constants.RFO_INDEX_URL}/far-overhaul-part-{n}", HTML)
    for name, url in constants.GUIDANCE_URLS.items():
        await get(url, PDF if name == "deviation_guidance" else HTML)
    for i, url in enumerate(urls, 1):
        await get(url, PDF)
        if i % 25 == 0:
            log(f"  {i}/{len(urls)} PDFs, {fetcher.requests} requests, {fetcher.bytes / 1e6:.0f} MB, {time.monotonic() - started:.0f}s")
    errors = sum(1 for e in recorder.entries.values() if "error" in e)
    return {"pdfs": len(urls), "requests": fetcher.requests, "skipped": skipped, "bytes": fetcher.bytes,
            "errors": errors, "seconds": round(time.monotonic() - started, 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--remote", action="store_true", help="write to the hosted D1 database")
    target.add_argument("--local", type=Path, help="write to this sqlite file")
    parser.add_argument("--database-id")
    parser.add_argument("--record", type=Path, help="also save every raw response here")
    parser.add_argument("--replay", type=Path, help="use responses saved by --record; no network")
    parser.add_argument("--revalidate", type=int, default=100, help="also recheck this many least recently fetched PDFs")
    parser.add_argument("--full", action="store_true", help="recheck every PDF (an opt-in raw cache skips unchanged validator-backed bodies)")
    parser.add_argument("--raw-cache", type=Path, help="opt-in local raw response cache (recording format); serving cache is unchanged")
    parser.add_argument("--reparse", action="store_true", help="force extraction of every stored raw resource, without upstream network")
    parser.add_argument("--allow-missing", action="store_true", help="with --replay: leave out PDFs a partial recording lacks")
    parser.add_argument("--record-only", action="store_true", help="with --record: fetch everything into the recording, resuming; no database")
    parser.add_argument("--parse-worker", nargs=2, metavar=("KIND", "ARGS"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.parse_worker:
        return parse_worker(args.parse_worker[0], json.loads(args.parse_worker[1]))
    if args.reparse and not args.raw_cache:
        raise SystemExit("--reparse needs --raw-cache DIR.")
    if args.reparse and (args.replay or args.record_only or args.allow_missing):
        raise SystemExit("--reparse cannot be combined with --replay, --record-only, or --allow-missing.")
    if args.record_only:
        if not args.record:
            raise SystemExit("--record-only needs --record DIR.")
        stats = asyncio.run(record_only(Recorder(args.record), log=lambda m: print(m, file=sys.stderr, flush=True)))
        print(json.dumps(stats, indent=2))
        return
    if args.remote:
        token = os.environ.get("CLOUDFLARE_D1_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
        if not token:
            raise SystemExit("Set CLOUDFLARE_D1_TOKEN.")
        db = RemoteD1(database_id(args.database_id), token)
    elif args.local:
        db = LocalD1(args.local)
    else:
        raise SystemExit("Pass --remote or --local PATH.")
    fetcher = Fetcher(Recorder(args.record) if args.record else None, Recorder(args.replay) if args.replay else None,
                      raw_cache=Recorder(args.raw_cache) if args.raw_cache else None, reparse=args.reparse)
    fetcher.allow_missing = args.allow_missing
    stats = asyncio.run(Loader(db, fetcher, revalidate=args.revalidate, full=args.full or bool(args.replay), reparse=args.reparse,
                               log=lambda m: print(m, file=sys.stderr, flush=True)).run())
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
