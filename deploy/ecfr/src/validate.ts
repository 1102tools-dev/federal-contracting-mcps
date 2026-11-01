// The Python server's input checks (server.py), with the same messages and
// order, so a bad argument gets the same answer here as from the container.
// Regular expressions use Python's classes: \s is str.isspace, \d any
// decimal digit, \b a Unicode word boundary.
import {ToolError, type PyInt} from "./args.ts";
import {intStr, repr} from "./pyjson.ts";
import {SPACE, WORD, cpLen, pyInt, strip} from "./text.ts";

const S = `[${SPACE}]`;
const END_OF_WORD = `(?![${WORD}])`;

export const TITLE_48_CHAPTERS: Record<string, string> = {
  "1": "FAR (Parts 1-99)",
  "2": "DFARS (Parts 200-299)",
  "3": "HHSAR (Parts 300-399)",
  "4": "AGAR (Parts 400-499)",
  "5": "GSAR (Parts 500-599)",
  "6": "DOSAR (Parts 600-699)",
  "7": "AIDAR (Parts 700-799)",
  "8": "VAAR (Parts 800-899)",
  "9": "DEAR (Parts 900-999)",
  "10": "DTAR (Parts 1000-1099)",
  "12": "TAR (Parts 1200-1299)",
  "13": "CAR (Parts 1300-1399)",
  "14": "DIAR (Parts 1400-1499)",
  "15": "EPAAR (Parts 1500-1599)",
  "16": "FEHBAR, OPM health benefits (Parts 1600-1699)",
  "17": "OPM (Parts 1700-1799)",
  "18": "NFS (Parts 1800-1899)",
  "19": "USAGM, Broadcasting Board of Governors (Parts 1900-1999)",
  "20": "NRCAR (Parts 2000-2099)",
  "21": "LIFAR, OPM group life insurance (Parts 2100-2199)",
  "23": "SSAAR (Parts 2300-2399)",
  "24": "HUDAR (Parts 2400-2499)",
  "25": "NSFAR (Parts 2500-2599)",
  "28": "JAR (Parts 2800-2899)",
  "29": "DOLAR (Parts 2900-2999)",
  "30": "HSAR (Parts 3000-3099)",
  "34": "EDAR, Dept. of Education (Parts 3400-3499)",
  "52": "Dept. of the Navy (Parts 5200-5299)",
  "54": "DLA (Parts 5400-5499)",
  "57": "USADF, African Development Foundation (Parts 5700-5799)",
  "61": "CBCA, Civilian Board of Contract Appeals (Parts 6100-6199)",
  "99": "CAS (Part 9900)",
};
// Object.keys lists integer-like keys in numeric order, which is also the map's order.
const CHAPTER_LIST = Object.entries(TITLE_48_CHAPTERS).map(([k, v]) => `${k} = ${v.split(" (")[0]}`).join("; ");

export const COMMON_FAR_SECTIONS = ["2.101", "4.1102", "6.302-1", "9.104-1", "9.406-2", "12.301", "13.003", "15.305",
  "15.306", "19.502-2", "31.205", "33.103", "42.302", "52.212-1", "52.212-4", "52.212-5"];

const REG_NAMES = "FAR|DFARS|GSAR|VAAR|HSAR|NFS|DEAR|AGAR|AIDAR|CAR|DIAR|DOLAR|DOSAR|DTAR|EDAR|"
  + "EPAAR|HHSAR|HUDAR|JAR|LIFAR|NRCAR|NSFAR|SSAAR|TAR|FEHBAR|AFARS|NMCARS|DLAD";
const SECTION_PREFIX = new RegExp(`^${S}*(?:(?:${REG_NAMES})(?![A-Za-z])${S}*|\\p{Nd}+${S}*C\\.?${S}*F\\.?${S}*R\\.?${S}*|C\\.?F\\.?R\\.?${S}+)`, "iu");
// Labels copied from headings: "\u00a7 9.104-1", "Part 22", "Subpart 15.3", "Section 15.305".
const LABEL_PREFIX = new RegExp(`^${S}*(?:\u00a7+|sections?${END_OF_WORD}\\.?|sec\\.|subpart${END_OF_WORD}|part${END_OF_WORD})${S}*`, "iu");
const CITED_TITLE = new RegExp(`^${S}*(\\p{Nd}+)${S}*C\\.?${S}*F\\.?${S}*R${END_OF_WORD}`, "iu");
const DASHES = /[\u2013\u2014\u2011\u2212]/g;
// Trailing paragraph cites like '15.305(a)' or '52.212-4(c)(2)(xviii)'.
const PAREN_CITE = new RegExp(`(?:${S}*\\([A-Za-z0-9]{1,6}\\))+${S}*$`, "u");
const YMD = /^\p{Nd}{4}-\p{Nd}{2}-\p{Nd}{2}$/u;

const fail = (message: string): never => {
  throw new ToolError(message);
};
const show = (value: PyInt) => intStr(value);

export function clamp(value: PyInt, field: string, lo: number, hi: number): number {
  if (value < lo) fail(`${field} must be >= ${lo}. Got ${show(value)}.`);
  if (value > hi) fail(`${field} exceeds maximum of ${hi}. Got ${show(value)}. Paginate instead.`);
  return Number(value);
}

export function clampStrLen(value: string, field: string, maximum: number): string {
  if (cpLen(value) > maximum) fail(`${field} exceeds maximum length of ${maximum}. Got ${cpLen(value)}.`);
  return value;
}

/** str.strip() of a string, or null when nothing is left (_strip_or_none). */
export function stripOrNone(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const s = strip(value);
  return s || null;
}

function daysIn(year: number, month: number): number {
  return [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

/** _validate_date_ymd: YYYY-MM-DD only (the stripped string), or null. */
export function validateDate(value: string | null, field: string): string | null {
  if (value === null) return null;
  const s = strip(value);
  if (!s) fail(`${field} cannot be empty or whitespace. Use YYYY-MM-DD (e.g. '2026-04-16'), or omit to auto-resolve the latest available date.`);
  if (s.toLowerCase() === "current") fail(`${field}='current' is not accepted. Use a specific YYYY-MM-DD date, or omit ${field} to auto-resolve to the latest available.`);
  if (!YMD.test(s)) fail(`${field} must be YYYY-MM-DD (e.g. '2026-04-16'). Got ${repr(value)}.`);
  const [year, month, day] = s.split("-").map(part => Number(pyInt(part)));
  const problem = year < 1 ? `year ${year} is out of range` : month < 1 || month > 12 ? "month must be in 1..12"
    : day < 1 || day > daysIn(year, month) ? "day is out of range for month" : null;
  if (problem) fail(`${field}=${repr(value)} is not a valid calendar date: ${problem}`);
  return s;
}

/** _validate_title_number: CFR titles are 1-50. */
export function validateTitle(value: PyInt, field = "title_number"): number {
  if (value < 1 || value > 50) fail(`${field} must be between 1 and 50. Got ${show(value)}.`);
  return Number(value);
}

/** The title named in a cite like '2 CFR 200.320', if any. */
export function citedTitle(value: unknown): PyInt | null {
  const match = typeof value === "string" ? CITED_TITLE.exec(value) : null;
  return match ? pyInt(match[1]) : null;
}

export function checkCitedTitle(value: unknown, titleNumber: number, field: string, titleField = "title_number"): void {
  const cited = citedTitle(value);
  if (cited !== null && cited != titleNumber) {
    fail(`${field}=${repr(value)} is in title ${show(cited)}, but ${titleField} is ${titleNumber}. Pass ${titleField}=${show(cited)}.`);
  }
}

/** _coerce_cfr_str: an int or str identifier as a clean string, or null. */
export function coerceCfrStr(value: unknown, field: string, {stripPrefixes = false, stripCites = false, maxlen = 120} = {}): string | null {
  if (value === null || value === undefined) return null;
  const raw = typeof value === "string" ? value : intStr(value as PyInt);
  if (raw.includes("\x00")) fail(`${field}=${repr(value)} contains a null byte.`);
  if (/[\n\r\t]/.test(raw)) fail(`${field}=${repr(value)} must not contain newline/tab characters.`);
  let s = strip(raw);
  if (!s) return null;
  if (stripPrefixes) {
    s = s.replace(DASHES, "-");
    let previous: string | null = null;
    while (s !== previous) {
      previous = s;
      s = s.replace(SECTION_PREFIX, "");
      s = strip(s.replace(LABEL_PREFIX, ""));
    }
    if (!s) return null;
  }
  if (stripCites) {
    s = strip(s.replace(PAREN_CITE, ""));
    if (!s) return null;
  }
  if (cpLen(s) > maxlen) fail(`${field} exceeds maximum length of ${maxlen} chars. Got ${cpLen(s)}.`);
  return s;
}

/** _validate_chapter: in Title 48, one of the chapters it has. */
export function validateChapter(value: unknown, titleNumber: number | null): string | null {
  const s = coerceCfrStr(value, "chapter", {maxlen: 8});
  if (s === null) return null;
  if (titleNumber === 48 && !Object.hasOwn(TITLE_48_CHAPTERS, s)) {
    fail(`chapter=${repr(value)} is not a valid Title 48 chapter. Title 48 chapters: ${CHAPTER_LIST}. For a section or part number, leave chapter out.`);
  }
  return s;
}

/** _safe_int(str(part).split(".")[0]) -> the Title 48 chapter that owns the part. */
export function title48Chapter(part: string): string | null {
  const head = part.split(".")[0];
  const number = ["", "null", "None"].includes(head) ? null : pyInt(head);
  if (number === null) return null;
  if (number < 100) return "1";
  return typeof number === "bigint" ? (number / 100n - (number < 0n && number % 100n !== 0n ? 1n : 0n)).toString() : String(Math.floor(number / 100));
}

/** _check_title48_chapter: the owning chapter, or an error if chapter disagrees. */
export function checkTitle48Chapter(chapter: string | null, identifier: string | null): string | null {
  if (!identifier) return chapter;
  const owner = title48Chapter(identifier);
  if (owner === null || !Object.hasOwn(TITLE_48_CHAPTERS, owner)) return chapter;
  if (chapter && chapter !== owner) {
    fail(`${identifier} is in Title 48 chapter ${owner} (${TITLE_48_CHAPTERS[owner]}), not chapter ${chapter}. Leave chapter out; the number is enough.`);
  }
  return owner;
}
