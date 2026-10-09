// The five hosted Acquisition.gov tools, answered from the D1 snapshot that
// scripts/load_acquisition_gov.py builds (see schema.sql). Each tool mirrors
// the Python server (servers/acquisition-gov-mcp/src/acquisition_gov_mcp/
// server.py) step for step: the same validation order, messages and keys.
// Where the package fetches a page, the Worker reads that page's stored copy:
// fetch errors are the ones the snapshot run saw, and fields that record when
// a source was retrieved carry the snapshot's fetch time.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {ToolError, validateArgs, type PyInt} from "./args.ts";
import {casefold} from "./casefold.ts";
import {intStr, repr, type Py} from "./pyjson.ts";
import {WORD, cpLen, cpSlice, escapeRegex, pySorted, splitlines, squash, strip} from "./text.ts";

export {ToolError};

type Row = Record<string, any>;
export interface Statement {
  bind(...values: unknown[]): Statement;
  all<T = Row>(): Promise<{results: T[]}>;
}
export interface Database {
  prepare(sql: string): Statement;
  batch<T = Row>(statements: Statement[]): Promise<{results: T[]}[]>;
}

/** The reviewed tool definitions, unchanged. */
export const TOOLS = CONTRACT;

// ---------- constants (constants.py) ----------

const DEFAULT_MAX_CHARACTERS = 20_000;
const MAX_OUTPUT_CHARACTERS = 40_000;
const MAX_PDF_PAGES = 25;
const MAX_PDF_TEXT_CHARACTERS = 200_000;
const GUIDANCE = ["faq", "policy_and_guidance", "deviation_guidance"];

// ---------- validation (server.py, _html.py) ----------

function validatePart(part: PyInt): number {
  if (part < 1 || part > 53) throw new ToolError(`part must be from 1 through 53. Got ${intStr(part)}.`);
  return Number(part);
}

const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function validateDate(value: string | null, field: string): string | null {
  if (value === null) return null;
  const text = strip(value);
  // \d matches any Unicode digit; date.fromisoformat then takes ASCII digits only.
  if (!/^\p{Nd}{4}-\p{Nd}{2}-\p{Nd}{2}$/u.test(text)) throw new ToolError(`${field} must use YYYY-MM-DD format. Got ${repr(value)}.`);
  const [year, month, day] = text.split("-").map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const valid = /^[0-9-]+$/.test(text) && year >= 1 && month >= 1 && month <= 12
    && day >= 1 && day <= (month === 2 && leap ? 29 : DAYS[month - 1]);
  if (!valid) throw new ToolError(`${field} is not a valid calendar date: ${repr(value)}.`);
  return text;
}

function validateChunkInputs(cursor: string | null, maximum: PyInt) {
  if (!(maximum >= 1000 && maximum <= MAX_OUTPUT_CHARACTERS)) throw new ToolError(`max_characters must be between 1000 and ${MAX_OUTPUT_CHARACTERS}.`);
  if (cursor !== null && !/^[0-9]{1,9}$/.test(cursor)) throw new ToolError("cursor must be the numeric cursor returned by a prior call.");
}

function validateHeading(section: string | null): string | null {
  if (section === null) return null;
  if (!strip(section) || cpLen(section) > 500) throw new ToolError("section/heading must contain 1 through 500 nonblank characters.");
  return squash(section);
}

/** _chunk's page of a text `length` code points long: [start, end), or its cursor error. */
function chunkWindow(length: number, cursor: string | null, maximum: number): [number, number] {
  const start = cursor === null ? 0 : Number(cursor);
  if (start > length) throw new ToolError(`cursor is outside the source text (length ${length}).`);
  return [start, Math.min(length, start + maximum)];
}

function chunkResult(content: string, [start, end]: [number, number], length: number): Record<string, Py> {
  return {
    content,
    cursor: String(start),
    next_cursor: end < length ? String(end) : null,
    truncated: end < length,
    total_characters: length,
  };
}

// ---------- the current snapshot in D1 ----------

const CURRENT = "(SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'current')";
const SOURCE = "SELECT s.final_url, s.source_id, s.retrieved_at, s.content_sha256, s.error, s.doc, d.info FROM sources s "
  + `LEFT JOIN docs d ON d.id = s.doc WHERE s.snapshot = ${CURRENT} AND s.key = `;
/** The doc id of a source key in the current snapshot (one bound parameter). */
const DOC_OF = `(SELECT doc FROM sources WHERE snapshot = ${CURRENT} AND key = ?)`;
/** The source key of an indexed deviation's PDF (two bound parameters: 'index', source_id). */
const PDF_KEY = `('pdf:' || (SELECT url FROM index_deviations WHERE doc = ${DOC_OF} AND source_id = ? ORDER BY seq LIMIT 1))`;

interface Source {
  final_url: string;
  source_id: string | null;
  retrieved_at: string;
  content_sha256: string;
  info: Record<string, any>;
}

/** A fetched source as the tool saw it, or the error its fetch raised. */
function fetched(rows: Row[], key: string): Source {
  const row = rows[0];
  if (!row) throw new Error(`no ${key} source in the current snapshot`);
  if (row.error !== null) throw new ToolError(row.error);
  if (row.info === null) throw new Error(`${key} has no stored content`);
  return {...row, info: JSON.parse(row.info)} as Source;
}

// Long texts are stored as rows of a stream (chunks.start and length count
// code points), so a call reads only the rows its page overlaps.
const STREAM_END = `SELECT start + length AS total FROM chunks WHERE doc = ${DOC_OF} AND stream = ? ORDER BY seq DESC LIMIT 1`;
const STREAM_ROWS = `SELECT start, body FROM chunks WHERE doc = ${DOC_OF} AND stream = ? AND start < ? AND start + length > ? ORDER BY seq`;

/** stream[from:to], from the rows STREAM_ROWS returned for that range. */
function streamText(rows: Row[], from: number, to: number): string {
  if (!rows.length || to <= from) return "";
  return cpSlice(rows.map(r => r.body).join(""), from - rows[0].start, to - rows[0].start);
}

/** _parse_html_document over a stored page (part or guidance): one page of its
 * whole text, or of one heading's section. Reads the page's source row, and
 * for a section its headings, in one round trip, then the text it returns. */
async function htmlDocument(db: Database, key: string, heading: string | null, cursor: string | null,
  maximum: number): Promise<{src: Source; page: Record<string, Py>}> {
  // Without a heading the page is a window of the text stream, known up front.
  const first = cursor === null ? 0 : Number(cursor);
  const [source, end, rows, headings] = await db.batch([
    db.prepare(SOURCE + "?").bind(key),
    db.prepare(STREAM_END).bind(key, "text"),
    db.prepare(STREAM_ROWS).bind(key, "text", heading === null ? first + maximum : 0, first),
    db.prepare(`SELECT key, start, end FROM headings WHERE doc = ${DOC_OF} AND ? ORDER BY idx`).bind(key, heading === null ? 0 : 1),
  ]);
  const src = fetched(source.results, key);
  const info = src.info;
  if (info.error) throw new ToolError(info.error);
  let content: string;
  let window: [number, number];
  let length: number;
  if (heading === null) {
    if (info.text_error) throw new ToolError(info.text_error);
    length = end.results[0]?.total ?? 0;
    window = chunkWindow(length, cursor, maximum);
    content = streamText(rows.results, window[0], window[1]);
  } else {
    const needle = casefold(heading);
    const pattern = new RegExp(`(?<![${WORD}.])${escapeRegex(needle)}(?![${WORD}.])`, "u");
    const exact = headings.results.filter(h => h.key === needle);
    const candidates = exact.length ? exact : headings.results.filter(h => pattern.test(h.key));
    if (!candidates.length) throw new ToolError(`section ${repr(heading)} was not found in the official source.`);
    if (candidates.length > 1) throw new ToolError(`section ${repr(heading)} matches multiple headings; use a more specific heading.`);
    const {start, end: stop} = candidates[0];
    length = stop - start;
    window = chunkWindow(length, cursor, maximum);
    const {results} = await db.prepare(STREAM_ROWS).bind(key, "sections", start + window[1], start + window[0]).all();
    content = streamText(results, start + window[0], start + window[1]);
  }
  return {src, page: {...chunkResult(content, window, length), issuance_date: info.issuance_date, updated_date: info.updated_date}};
}

interface Index {
  doc: string;
  source_url: string;
  retrieved_at: string;
  content_sha256: string;
  agencies: [string, string, string | null][];
  cards: {ordinal: number; part: number; deviations: number; first: number; item: Record<string, any>}[];
}

async function loadIndex(db: Database): Promise<Index> {
  const [source, parts] = await db.batch([
    db.prepare(SOURCE + "'index'"),
    db.prepare(`SELECT ordinal, part, deviations, item FROM index_parts WHERE doc = ${DOC_OF} ORDER BY ordinal`).bind("index"),
  ]);
  const row = source.results[0];
  if (!row || row.info === null) throw new Error("no index in the current snapshot");
  let first = 0;
  const cards = parts.results.map(r => {
    const card = {ordinal: r.ordinal, part: r.part, deviations: r.deviations, first, item: JSON.parse(r.item)};
    first += r.deviations;
    return card;
  });
  return {doc: row.doc, source_url: row.final_url, retrieved_at: row.retrieved_at, content_sha256: row.content_sha256,
    agencies: JSON.parse(row.info).agencies, cards};
}

/** _matching_agency_names: posted labels containing the query, plus their acronym variants. */
function matchingAgencyNames(agencies: Index["agencies"], query: string | null): Set<string> {
  if (!query) return new Set();
  const needle = casefold(query).replace(/[^a-z0-9]+/g, " ").trim();
  if (!needle) return new Set();
  const direct = agencies.filter(([, normalized]) => normalized.includes(needle));
  const aliases = new Set(direct.map(([, , acronym]) => acronym).filter(a => a !== null));
  return new Set([...direct.map(([name]) => name), ...agencies.filter(([, , acronym]) => acronym !== null && aliases.has(acronym)).map(([name]) => name)]);
}

const agencyFilterOf = (agency: string | null) => (agency !== null && strip(agency) ? casefold(squash(agency)) : null);
const placeholders = (n: number) => Array(n).fill("?").join(", ");

// ---------- tools ----------

type Args = Record<string, unknown>;

async function listRfoParts(db: Database, args: Args): Promise<Py> {
  const a = validateArgs("list_rfo_parts", args);
  const wanted = a.part !== null ? validatePart(a.part) : null;
  const since = validateDate(a.updated_since, "updated_since");
  const agencyFilter = agencyFilterOf(a.agency);
  const index = await loadIndex(db);
  const matched = matchingAgencyNames(index.agencies, agencyFilter);
  // Matching deviations per card: index_deviations.seq runs through the cards in order.
  const perCard = new Map<number, number>();
  if (agencyFilter && matched.size) {
    const {results} = await db.prepare(`SELECT seq FROM index_deviations WHERE doc = ? AND agency IN (${placeholders(matched.size)})`)
      .bind(index.doc, ...matched).all();
    for (const {seq} of results) {
      const card = index.cards.find(c => seq >= c.first && seq < c.first + c.deviations)!;
      perCard.set(card.ordinal, (perCard.get(card.ordinal) ?? 0) + 1);
    }
  }
  const results: Record<string, any>[] = [];
  for (const card of index.cards) {
    const item = card.item;
    if (wanted !== null && item.part !== wanted) continue;
    if (since && item.updated_date && item.updated_date < since) continue;
    const count = agencyFilter ? perCard.get(card.ordinal) ?? 0 : card.deviations;
    if (agencyFilter && !count) continue;
    results.push({...item, agency_deviation_count: count});
  }
  const warnings = ["This index documents posted sources; it does not decide which text governs a procurement."];
  if (agencyFilter && matched.size > 1) {
    warnings.push(`Agency matching includes these posted labels and acronym variants: ${repr(pySorted(matched))}.`);
  }
  for (const item of results) warnings.push(...(item.warnings ?? []));
  if (since && results.some(item => item.updated_date === null)) {
    warnings.push("Entries without an update date were retained; they cannot be confirmed as updated since the requested date.");
  }
  return {source_url: index.source_url, retrieved_at: index.retrieved_at, content_sha256: index.content_sha256,
    count: results.length, results, warnings};
}

async function getRfoPart(db: Database, args: Args): Promise<Py> {
  const a = validateArgs("get_rfo_part", args);
  const wanted = validatePart(a.part);
  validateChunkInputs(a.cursor, a.max_characters);
  const heading = validateHeading(a.section);
  const {src, page} = await htmlDocument(db, `part:${wanted}`, heading, a.cursor, Number(a.max_characters));
  const warnings = ["RFO model text is not operative for an agency unless that agency adopts it through a deviation."];
  if (page.issuance_date === null && page.updated_date === null) {
    warnings.push("The page text does not state issuance or update dates; list_rfo_parts reports dates from the separate index cards.");
  }
  return {
    source_id: src.source_id, source_kind: "model_deviation", agency: null, far_parts: [wanted], source_url: src.final_url,
    effective_date: null, expiration_date: null, applicability_text: null, retrieved_at: src.retrieved_at,
    content_sha256: src.content_sha256, text_extraction_status: "complete", warnings, section: a.section, ...page,
  };
}

async function listRfoAgencyDeviations(db: Database, args: Args): Promise<Py> {
  const a = validateArgs("list_rfo_agency_deviations", args);
  if (!(a.agency && strip(a.agency)) && a.part === null) throw new ToolError("At least one filter is required: agency or part.");
  if (!(a.limit >= 1 && a.limit <= 250)) throw new ToolError("limit must be between 1 and 250.");
  const limit = Number(a.limit);
  const wanted = a.part !== null ? validatePart(a.part) : null;
  const agencyFilter = agencyFilterOf(a.agency);
  const index = await loadIndex(db);
  const matched = matchingAgencyNames(index.agencies, agencyFilter);
  let matches: Row[] = [];
  let selected: Row[] = [];
  if (!agencyFilter || matched.size) {
    let where = "doc = ?";
    const values: unknown[] = [index.doc];
    if (wanted !== null) {
      where += " AND part = ?";
      values.push(wanted);
    }
    if (agencyFilter) {
      where += ` AND agency IN (${placeholders(matched.size)})`;
      values.push(...matched);
    }
    [{results: matches}, {results: selected}] = await db.batch([
      db.prepare(`SELECT agency, source_id, part FROM index_deviations WHERE ${where} ORDER BY seq`).bind(...values),
      db.prepare(`SELECT item FROM index_deviations WHERE ${where} ORDER BY seq LIMIT ?`).bind(...values, limit),
    ]);
  }
  const results = selected.map(r => ({...JSON.parse(r.item), retrieved_at: index.retrieved_at}));
  const names = pySorted(new Set(matches.map(m => m.agency)));
  const warnings = ["Documents are listed as posted; retrieve the PDF before relying on dates or applicability."];
  for (const card of index.cards) {
    if (wanted === null || card.part === wanted) warnings.push(...(card.item.warnings ?? []));
  }
  if (agencyFilter && names.length > 1) warnings.push(`The agency filter matched multiple normalized names: ${repr(names)}.`);
  if (matches.length > limit) {
    warnings.push(`Results were truncated from ${matches.length} to ${limit}. Narrow the agency filter or query individual FAR parts to retrieve the remaining entries.`);
  }
  const duplicates = matches.length - new Set(matches.map(m => `${m.source_id} ${m.part}`)).size;
  if (duplicates) warnings.push(`The official index contains ${duplicates} duplicate entry or entries; they were preserved.`);
  return {source_url: index.source_url, retrieved_at: index.retrieved_at, content_sha256: index.content_sha256,
    count: results.length, total_matches: matches.length, results, warnings};
}

// Python's \b around the applicability phrases, for a page cut by the text cap.
const APPLICABILITY = new RegExp(`(?<![${WORD}])(?:applicability|applies to|applicable to)(?![${WORD}])`, "iu");

interface Page {number: number; text: string; start: number; applicability: string[]}
type Stored = {text: string; start: number; failure: string | null; overCap: boolean; applicability: [number, number][]};
type Read = [text: string, status: string, warnings: string[], fields: Record<string, Py>, total: number, end: number];

/** _extract_document_fields over the selected pages, from each page's stored
 * applicability lines and every labeled-date match in the whole document. */
function documentFields(pages: Page[], dates: Record<string, [number, number, string | null][]>): Record<string, Py> {
  const lines = pages.flatMap(p => p.applicability.map(line => `Page ${p.number}: ${line}`));
  let applicability = lines.slice(0, 12).join("\n");
  if (cpLen(applicability) > 8192) applicability = cpSlice(applicability, 0, 8160) + " [truncated]";
  // The selected pages joined are one stretch of all pages joined; a match
  // _labeled_date finds in them is the first one inside that stretch.
  const from = pages[0].start;
  const to = pages.at(-1)!.start + cpLen(pages.at(-1)!.text);
  const labeled = (label: string) => {
    const match = dates[label].find(([start, end]) => start >= from && end <= to);
    return match ? match[2] : null;
  };
  return {
    issuance_date: labeled("Issued") ?? labeled("Date"),
    effective_date: labeled("Effective"),
    expiration_date: labeled("Expiration") ?? labeled("Expires"),
    applicability_text: applicability || null,
  };
}

/** _read_pdf over the stored pages of one PDF, as the isolated worker reports it. */
function readPdf(info: Record<string, any>, rows: Row[], pageStart: PyInt, pageEnd: PyInt | null): Read {
  const total: number = info.total_pages;
  if (pageStart > total) return ["", "error", [`page_start must be between 1 and ${total}; this PDF has ${total} page(s).`], {}, total, 0];
  const start = Number(pageStart);
  let end = Math.min(total, pageEnd !== null ? Number(pageEnd) : Math.min(total, start + 9));
  const stored = new Map<number, Stored>();
  for (const r of rows) {
    const page = stored.get(r.page);
    if (page) page.text += r.body;
    else stored.set(r.page, {text: r.body, start: r.start, failure: r.failure, overCap: !!r.over_cap,
      applicability: r.applicability ? JSON.parse(r.applicability) : []});
  }
  const warnings: string[] = [];
  const pages: Page[] = [];
  let empty = 0;
  let extracted = 0;
  for (let number = start; number <= end; number++) {
    const page = stored.get(number);
    if (!page) throw new Error(`page ${number} is missing from the stored PDF`);
    if (page.failure) warnings.push(`Page ${number} extraction failed: ${page.failure}.`);
    let cleaned = page.text;
    let applicability = page.applicability.map(([from, to]) => squash(cpSlice(page.text, from, to)));
    const remaining = MAX_PDF_TEXT_CHARACTERS - extracted;
    // A page over the cap on its own was stored cut at the cap.
    if (page.overCap || cpLen(cleaned) > remaining) {
      cleaned = cpSlice(cleaned, 0, remaining);
      applicability = splitlines(cleaned).map(squash).filter(line => APPLICABILITY.test(line));
      warnings.push(`Extracted text reached the ${MAX_PDF_TEXT_CHARACTERS}-character parser limit; request a smaller page range.`);
    }
    extracted += cpLen(cleaned);
    if (!cleaned) empty++;
    pages.push({number, text: cleaned, start: page.start, applicability});
    if (extracted >= MAX_PDF_TEXT_CHARACTERS) {
      end = number;
      break;
    }
  }
  if (start > 1 || end < total) warnings.push(`Only pages ${start} through ${end} of ${total} were examined; dates and applicability may appear elsewhere.`);
  let status: string;
  if (empty === pages.length) {
    status = "unextractable";
    warnings.push("Selected pages contain no extractable text and may be scanned images.");
  } else if (empty || warnings.some(w => w.includes("parser limit"))) {
    status = "partial";
    warnings.push(`${empty} selected page(s) contained no extractable text.`);
  } else {
    status = "complete";
  }
  const numbered = pages.map(p => `[Page ${p.number}]\n${p.text}`).join("\n\n");
  return [numbered, status, warnings, documentFields(pages, info.dates), total, end];
}

async function getRfoAgencyDeviation(db: Database, args: Args): Promise<Py> {
  const a = validateArgs("get_rfo_agency_deviation", args);
  const sourceId: string = a.source_id;
  if (!/^agency-deviation-[a-f0-9]{20}$/.test(sourceId)) throw new ToolError("source_id must come from list_rfo_agency_deviations.");
  const pageStart = BigInt(a.page_start);
  const pageEnd = a.page_end === null ? null : BigInt(a.page_end);
  if (pageStart < 1n || (pageEnd !== null && (pageEnd < pageStart || pageEnd - pageStart + 1n > BigInt(MAX_PDF_PAGES)))) {
    throw new ToolError(`page_start/page_end must select 1 through ${MAX_PDF_PAGES} pages in increasing order.`);
  }
  const last = pageEnd ?? pageStart + 9n;
  const bound = (n: bigint) => Number(n > 1_000_000_000n ? 1_000_000_000n : n);
  const [index, discovered, pdf, pageRows] = await db.batch([
    db.prepare(SOURCE + "'index'"),
    db.prepare(`SELECT item FROM index_deviations WHERE doc = ${DOC_OF} AND source_id = ? ORDER BY seq`).bind("index", sourceId),
    db.prepare(SOURCE + PDF_KEY).bind("index", sourceId),
    db.prepare("SELECT page, start, failure, over_cap, applicability, body FROM pages WHERE doc = "
      + `(SELECT doc FROM sources WHERE snapshot = ${CURRENT} AND key = ${PDF_KEY}) AND page >= ? AND page <= ? ORDER BY page, seq`)
      .bind("index", sourceId, bound(pageStart), bound(last)),
  ]);
  const indexRow = index.results[0];
  if (!indexRow) throw new Error("no index in the current snapshot");
  if (!discovered.results.length) throw new ToolError("source_id is not present in the current official RFO index.");
  const entries = discovered.results.map(r => JSON.parse(r.item));
  const parts = [...new Set(entries.flatMap(e => e.far_parts as number[]))].sort((x, y) => x - y);
  const target = {...entries[0], far_parts: parts};
  const src = fetched(pdf.results, `pdf:${target.source_url}`);
  const failure: Read | undefined = src.info.failure;
  let [text, status, warnings, fields, total, end] = failure
    ? [failure[0], failure[1], [...failure[2]], failure[3], failure[4], failure[5]] as Read
    : readPdf(src.info, pageRows.results, a.page_start, a.page_end);
  const totalExtracted = cpLen(text);
  const truncated = totalExtracted > MAX_OUTPUT_CHARACTERS;
  if (truncated) {
    text = cpSlice(text, 0, MAX_OUTPUT_CHARACTERS);
    warnings.push(`Page-numbered text was truncated at ${MAX_OUTPUT_CHARACTERS} characters; request a smaller page range to retrieve the omitted text.`);
  }
  if (entries.length > 1) {
    warnings.push(`The same source appears ${entries.length} times in the official index; duplicate metadata was preserved.`);
  }
  return {
    ...target, ...fields, source_url: src.final_url, retrieved_at: src.retrieved_at, index_retrieved_at: indexRow.retrieved_at,
    content_sha256: src.content_sha256, text_extraction_status: status, warnings, total_pages: total, page_start: a.page_start,
    page_end: end, page_numbered_text: text, returned_characters: cpLen(text), total_extracted_characters: totalExtracted,
    text_truncated: truncated, duplicate_index_entries: entries.slice(1),
  };
}

async function getRfoGuidance(db: Database, args: Args): Promise<Py> {
  const a = validateArgs("get_rfo_guidance", args);
  validateChunkInputs(a.cursor, DEFAULT_MAX_CHARACTERS);
  const heading = validateHeading(a.heading);
  if (!GUIDANCE.includes(a.resource)) throw new ToolError("resource must be faq, policy_and_guidance, or deviation_guidance.");
  const key = `guidance:${a.resource}`;
  if (a.resource === "deviation_guidance") {
    // Its headings are its lines: the first line containing the heading starts
    // the text, in the lines stream. Without one it is the whole text stream.
    const stream = heading === null ? "text" : "lines";
    const first = a.cursor === null ? 0 : Number(a.cursor);
    const [source, end, found, rows] = await db.batch([
      db.prepare(SOURCE + "?").bind(key),
      db.prepare(STREAM_END).bind(key, stream),
      db.prepare(`SELECT start FROM headings WHERE doc = ${DOC_OF} AND instr(key, ?) > 0 ORDER BY idx LIMIT 1`).bind(key, heading === null ? "" : casefold(heading)),
      db.prepare(STREAM_ROWS).bind(key, stream, heading === null ? first + DEFAULT_MAX_CHARACTERS : 0, first),
    ]);
    const src = fetched(source.results, key);
    const total = end.results[0]?.total ?? 0;
    let offset = 0;
    if (heading !== null) {
      if (!found.results.length) throw new ToolError(`heading ${repr(heading)} was not found in the guidance PDF.`);
      offset = found.results[0].start;
    }
    const window = chunkWindow(total - offset, a.cursor, DEFAULT_MAX_CHARACTERS);
    let content: string;
    if (heading === null) {
      content = streamText(rows.results, window[0], window[1]);
    } else {
      const {results} = await db.prepare(STREAM_ROWS).bind(key, stream, offset + window[1], offset + window[0]).all();
      content = streamText(results, offset + window[0], offset + window[1]);
    }
    const page = chunkResult(content, window, total - offset);
    return {
      source_id: src.source_id, source_kind: "nonregulatory_guidance", agency: "FAR Council", far_parts: [],
      source_url: src.final_url, updated_date: null, ...src.info.fields, retrieved_at: src.retrieved_at,
      content_sha256: src.content_sha256, text_extraction_status: src.info.status,
      warnings: [...src.info.warnings, "Guidance is not codified regulatory text."], total_pages: src.info.total_pages,
      heading, ...page,
    };
  }
  const {src, page} = await htmlDocument(db, key, heading, a.cursor, DEFAULT_MAX_CHARACTERS);
  return {
    source_id: src.source_id, source_kind: "nonregulatory_guidance", agency: "Acquisition.gov", far_parts: [],
    source_url: src.final_url, effective_date: null, expiration_date: null, applicability_text: null,
    retrieved_at: src.retrieved_at, content_sha256: src.content_sha256, text_extraction_status: "complete",
    warnings: ["Guidance is not codified regulatory text."], heading, ...page,
  };
}

export const HANDLERS: Record<string, (db: Database, args: Args) => Promise<Py>> = {
  list_rfo_parts: listRfoParts,
  get_rfo_part: getRfoPart,
  list_rfo_agency_deviations: listRfoAgencyDeviations,
  get_rfo_agency_deviation: getRfoAgencyDeviation,
  get_rfo_guidance: getRfoGuidance,
};
