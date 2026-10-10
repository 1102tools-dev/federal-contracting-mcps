// The eight hosted BLS OEWS tools, answered from the D1 copy of the OEWS
// release bundled with bls-oews-mcp (see schema.sql and
// scripts/load_bls_oews.py). Each tool mirrors the Python server
// (servers/bls-oews-mcp/src/bls_oews_mcp/server.py) step for step: the same
// validation order, messages, keys, and number formatting.

import CONTRACT from "../tools-contract.json" with {type: "json"};
import {PyFloat, fixed, group, intStr, parseJson, pyType, repr, round, str, strip, floatRepr, type Py} from "./pyjson.ts";

type Row = Record<string, any>;
export interface Statement {
  bind(...values: unknown[]): Statement;
  all<T = Row>(): Promise<{results: T[]}>;
}
export interface Database {
  prepare(sql: string): Statement;
  batch<T = Row>(statements: Statement[]): Promise<{results: T[]}[]>;
}

/** Deliberate tool errors (Python ValueError): "Error executing tool <name>: <message>". */
export class ToolError extends Error {}

/** The reviewed tool definitions, unchanged. */
export const TOOLS = CONTRACT;

// ---------- constants (servers/bls-oews-mcp/src/bls_oews_mcp/constants.py) ----------

const MAX_SERIES = 50;
const SPECIAL_VALUES = new Set(["-", "#", "*", "N/A"]);
const DATATYPE_LABELS: Record<string, string> = {
  "01": "Employment", "02": "Employment RSE (%)", "03": "Hourly Mean Wage", "04": "Annual Mean Wage",
  "05": "Mean Wage RSE (%)", "06": "Hourly 10th Percentile", "07": "Hourly 25th Percentile", "08": "Hourly Median",
  "09": "Hourly 75th Percentile", "10": "Hourly 90th Percentile", "11": "Annual 10th Percentile",
  "12": "Annual 25th Percentile", "13": "Annual Median", "14": "Annual 75th Percentile", "15": "Annual 90th Percentile",
  "16": "Employment per 1,000 Jobs", "17": "Location Quotient",
};
const HOURLY = new Set(["03", "06", "07", "08", "09", "10"]);
const COUNT = new Set(["01"]);
const RATIO = new Set(["16", "17"]);
const RSE = new Set(["02", "05"]);
const IGCE_DATATYPES = ["04", "11", "13", "15"];
// igce_wage_benchmark: each annual figure with BLS's matching hourly figure,
// and the datatypes it requests for them.
const IGCE_BENCHMARKS = [
  ["Annual Mean Wage", "Hourly Mean Wage"], ["Annual 10th Percentile", "Hourly 10th Percentile"],
  ["Annual 25th Percentile", "Hourly 25th Percentile"], ["Annual Median", "Hourly Median"],
  ["Annual 75th Percentile", "Hourly 75th Percentile"], ["Annual 90th Percentile", "Hourly 90th Percentile"],
];
const IGCE_REQUEST = ["03", "04", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15"];
// Maps keep insertion order; plain objects would sort numeric-looking keys.
const COMMON_SOC_CODES = new Map<string, Py>([
  ["111021", "General and Operations Managers"], ["113021", "Computer and Information Systems Managers"],
  ["131082", "Project Management Specialists"], ["131111", "Management Analysts"],
  ["132011", "Accountants and Auditors"], ["151211", "Computer Systems Analysts"],
  ["151212", "Information Security Analysts"], ["151232", "Computer User Support Specialists (Help Desk)"],
  ["151241", "Computer Network Architects"], ["151242", "Database Administrators"],
  ["151244", "Network and Computer Systems Administrators"], ["151251", "Computer Programmers"],
  ["151252", "Software Developers"], ["151253", "Software Quality Assurance Analysts"],
  ["151254", "Web Developers"], ["152051", "Data Scientists"], ["273042", "Technical Writers"],
  ["436014", "Secretaries and Administrative Assistants"],
]);
const COMMON_METROS = new Map<string, Py>([
  ["0047900", "Washington DC"], ["0042660", "Seattle"], ["0012580", "Baltimore"], ["0037980", "Philadelphia"],
  ["0035620", "New York City"], ["0031080", "Los Angeles"], ["0041860", "San Francisco"], ["0038060", "Phoenix"],
  ["0016980", "Chicago"], ["0012420", "Austin"], ["0014460", "Boston"], ["0019100", "Dallas"],
  ["0026420", "Houston"], ["0041740", "San Diego"], ["0019820", "Detroit"],
]);
const STATE_FIPS = [
  "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15", "16", "17", "18", "19", "20", "21", "22",
  "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39", "40", "41",
  "42", "44", "45", "46", "47", "48", "49", "50", "51", "53", "54", "55", "56", "66", "72", "78",
];
const PREFIX: Record<string, string> = {national: "OEUN", state: "OEUS", metro: "OEUM"};
const NO_DATA = () => new Map<string, Py>([["raw", null], ["formatted", "No data"], ["numeric", null], ["suppressed", true]]);
const BLS_NOTICE = "BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.";

// ---------- argument validation (pydantic, as the SDK runs it) ----------

type Args = Record<string, unknown>;
type Schema = {type?: string; anyOf?: Schema[]; enum?: string[]; items?: Schema; default?: unknown};
type Issue = {loc: string; type: string; msg: string; input: unknown};

// Fields in the Python signature's order, which is the order pydantic checks
// them in (tools-contract.json lists properties sorted by name).
const FIELD_ORDER: Record<string, string[]> = {
  compare_metros: ["occ_code", "metro_codes", "datatype", "year"],
  compare_occupations: ["occ_codes", "scope", "area_code", "datatype", "year"],
  detect_latest_year: [],
  get_data_status: [],
  get_wage_data: ["occ_code", "scope", "area_code", "industry", "datatypes", "year"],
  igce_wage_benchmark: ["occ_code", "scope", "area_code", "burden_low", "burden_high", "year"],
  list_common_metros: [],
  list_common_soc_codes: [],
};
const PYDANTIC_DOCS = "https://errors.pydantic.dev/2.13/v/";
const I64_LIMIT = 2 ** 63;

// Rust's char::is_whitespace, which pydantic-core trims before parsing a float.
const RUST_SPACE = "\t\n\v\f\r \x85\xa0                　";
const rustTrim = (text: string) => {
  let start = 0;
  let end = text.length;
  while (start < end && RUST_SPACE.includes(text[start])) start++;
  while (end > start && RUST_SPACE.includes(text[end - 1])) end--;
  return text.slice(start, end);
};

/** Rust's f64::from_str. */
function rustFloat(text: string): number | undefined {
  if (!/^[+-]?(inf|infinity|nan|(\d+\.?\d*|\.\d+)(e[+-]?\d+)?)$/i.test(text)) return undefined;
  const negative = text.startsWith("-");
  const body = text.replace(/^[+-]/, "").toLowerCase();
  if (body.startsWith("inf")) return negative ? -Infinity : Infinity;
  if (body === "nan") return NaN;
  return Number(text);
}

/** pydantic-core's str -> float: trimmed, else with underscores between digits removed. */
function pydanticFloat(text: string): number | undefined {
  const plain = rustFloat(rustTrim(text));
  if (plain !== undefined) return plain;
  if (text.startsWith("_") || text.endsWith("_") || /[^0-9]_|_[^0-9]/.test(text)) return undefined;
  return rustFloat(text.replaceAll("_", ""));
}

/** Python float() of a string (for published values), or undefined. */
function pyFloat(text: string): number | undefined {
  const s = strip(text).toLowerCase();
  if (/^[+-]?(inf|infinity)$/.test(s)) return s.startsWith("-") ? -Infinity : Infinity;
  if (/^[+-]?nan$/.test(s)) return NaN;
  if (!/^[+-]?(\d(_?\d)*(\.(\d(_?\d)*)?)?|\.\d(_?\d)*)(e[+-]?\d(_?\d)*)?$/.test(s)) return undefined;
  return Number(s.replaceAll("_", ""));
}

type Result = {ok: true; value: unknown} | {ok: false; issues: Issue[]};
const ok = (value: unknown): Result => ({ok: true, value});
const fail = (loc: string, type: string, msg: string, input: unknown): Result => ({ok: false, issues: [{loc, type, msg, input}]});
const isNumber = (v: unknown): v is number | PyFloat => typeof v === "number" || v instanceof PyFloat;
const numberOf = (v: number | PyFloat) => (v instanceof PyFloat ? v.value : v);

/** int in lax mode: bools and whole floats convert. */
function laxInt(value: unknown, loc: string): Result {
  if (typeof value === "boolean") return ok(value ? 1 : 0);
  if (typeof value === "bigint" || (typeof value === "number" && Number.isInteger(value))) return ok(value);
  if (isNumber(value)) {
    const f = numberOf(value);
    if (!Number.isFinite(f)) return fail(loc, "finite_number", "Input should be a finite number", value);
    if (!Number.isInteger(f)) return fail(loc, "int_from_float", "Input should be a valid integer, got a number with a fractional part", value);
    if (f >= I64_LIMIT || f <= -I64_LIMIT) return fail(loc, "int_parsing_size", "Unable to parse input string as an integer, exceeded maximum size", value);
    return ok(Number.isSafeInteger(f) ? f : BigInt(f));
  }
  return fail(loc, "int_type", "Input should be a valid integer", value);
}

/** One value against one contract schema, with pydantic's lax coercions and error locations. */
function validate(value: unknown, schema: Schema, loc: string): Result {
  if (schema.anyOf) {
    // Optional[X] is X that also takes None.
    const branches = schema.anyOf.filter(s => s.type !== "null");
    if (value === null && branches.length < schema.anyOf.length) return ok(null);
    if (branches.length === 1) return validate(value, branches[0], loc);
    // Union[str, int] in smart mode: an exact type first, then lax int;
    // when both fail pydantic reports each branch (loc.str, loc.int).
    if (typeof value === "string") return ok(value);
    const int = laxInt(value, `${loc}.int`);
    if (int.ok) return int;
    return {ok: false, issues: [{loc: `${loc}.str`, type: "string_type", msg: "Input should be a valid string", input: value}, ...int.issues]};
  }
  if (schema.enum) {
    if (typeof value === "string" && schema.enum.includes(value)) return ok(value);
    const quoted = schema.enum.map(e => `'${e}'`);
    return fail(loc, "literal_error", `Input should be ${quoted.slice(0, -1).join(", ")} or ${quoted.at(-1)}`, value);
  }
  switch (schema.type) {
    case "string":
      return typeof value === "string" ? ok(value) : fail(loc, "string_type", "Input should be a valid string", value);
    case "number": {
      if (typeof value === "boolean") return ok(new PyFloat(value ? 1 : 0));
      if (isNumber(value)) return ok(new PyFloat(numberOf(value)));
      if (typeof value === "bigint" && Number.isFinite(Number(value))) return ok(new PyFloat(Number(value)));
      if (typeof value === "string") {
        const parsed = pydanticFloat(value);
        return parsed === undefined ? fail(loc, "float_parsing", "Input should be a valid number, unable to parse string as a number", value) : ok(new PyFloat(parsed));
      }
      return fail(loc, "float_type", "Input should be a valid number", value);
    }
    case "array": {
      if (!Array.isArray(value)) return fail(loc, "list_type", "Input should be a valid list", value);
      const issues: Issue[] = [];
      const items = value.map((item, i) => {
        const result = validate(item, schema.items!, `${loc}.${i}`);
        if (!result.ok) issues.push(...result.issues);
        return result.ok ? result.value : undefined;
      });
      return issues.length ? {ok: false, issues} : ok(items);
    }
  }
  throw new Error(`unsupported schema at ${loc}`);
}

/** pydantic's input_value: the repr, cut to 25 + 24 UTF-8 bytes when over 50. */
function inputValue(value: unknown): string {
  const text = repr(value);
  const bytes = new TextEncoder().encode(text);
  if (bytes.length <= 50) return text;
  const isStart = (i: number) => i >= bytes.length || (bytes[i] & 0xc0) !== 0x80;
  let head = 25;
  while (!isStart(head)) head--;
  let tail = bytes.length - 24;
  while (!isStart(tail)) tail++;
  const decode = (part: Uint8Array) => new TextDecoder().decode(part);
  return `${decode(bytes.slice(0, head))}...${decode(bytes.slice(tail))}`;
}

/** Validate tool arguments as the SDK does: JSON-looking strings pre-parsed
 * (pre_parse_json), pydantic validation in signature order, extra keys
 * forbidden, and pydantic's error text when anything fails. */
export function validateArgs(name: string, args: Args): Record<string, any> {
  const tool = TOOLS.find(t => t.name === name)!;
  const properties = tool.inputSchema.properties as Record<string, Schema>;
  const required: string[] = (tool.inputSchema as {required?: string[]}).required ?? [];
  // pre_parse_json: a string argument that parses to a list, object or null
  // replaces the value (strings, numbers and booleans do not).
  const input: Args = {...args};
  for (const key of Object.keys(input)) {
    const value = input[key];
    if (!Object.hasOwn(properties, key) || typeof value !== "string") continue;
    try {
      const parsed = parseJson(value);
      if (parsed === null || (typeof parsed === "object" && !(parsed instanceof PyFloat))) input[key] = parsed;
    } catch {
      // Not JSON; validate the string itself.
    }
  }
  const issues: Issue[] = [];
  const out: Record<string, any> = {};
  for (const key of FIELD_ORDER[name]) {
    const schema = properties[key];
    if (!Object.hasOwn(input, key)) {
      if (required.includes(key)) issues.push({loc: key, type: "missing", msg: "Field required", input});
      else out[key] = schema.type === "number" ? new PyFloat(schema.default as number) : schema.default;
      continue;
    }
    const result = validate(input[key], schema, key);
    if (result.ok) out[key] = result.value;
    else issues.push(...result.issues);
  }
  for (const key of Object.keys(input)) {
    if (!Object.hasOwn(properties, key)) issues.push({loc: key, type: "extra_forbidden", msg: "Extra inputs are not permitted", input: input[key]});
  }
  if (issues.length) {
    throw new ToolError(`${issues.length} validation error${issues.length > 1 ? "s" : ""} for ${name}Arguments\n`
      + issues.map(i => `${i.loc}\n  ${i.msg} [type=${i.type}, input_value=${inputValue(i.input)}, input_type=${pyType(i.input)}]\n    For further information visit ${PYDANTIC_DOCS}${i.type}`).join("\n"));
  }
  return out;
}

// ---------- validators and normalizers (server.py) ----------

const ASCII_DIGITS = /^[0-9]+$/;

function coerceDigits(value: unknown, field: string, length?: number): string {
  if (value === null || value === undefined) throw new ToolError(`${field} cannot be None.`);
  if (typeof value === "boolean") throw new ToolError(`${field} must be an integer or digit-string, not bool.`);
  let s: string;
  if (typeof value === "number" || typeof value === "bigint") s = intStr(value);
  else if (typeof value === "string") s = strip(value);
  else throw new ToolError(`${field} must be an integer or string. Got ${pyType(value)}.`);
  if (!s) throw new ToolError(`${field} cannot be empty.`);
  if (!ASCII_DIGITS.test(s)) {
    throw new ToolError(`${field}=${repr(value)} must contain only ASCII digits 0-9 (no dashes, letters, whitespace, or Unicode digit characters).`);
  }
  if (length !== undefined && s.length !== length) throw new ToolError(`${field}=${repr(value)} must be exactly ${length} digits. Got ${s.length}.`);
  return s;
}

function validateSoc(value: unknown, field = "occ_code"): string {
  if (value === null || value === undefined) throw new ToolError(`${field} cannot be None.`);
  if (typeof value === "boolean") throw new ToolError(`${field} must be an integer or digit-string, not bool.`);
  let s: string;
  if (typeof value === "number" || typeof value === "bigint") s = intStr(value);
  else if (typeof value === "string") {
    if (/[\0\n\r\t]/.test(value)) {
      throw new ToolError(`${field}=${repr(value)} contains control characters. SOC codes are 6 digits with an optional single dash: '15-1252'.`);
    }
    s = strip(value).replaceAll("-", "");
  } else throw new ToolError(`${field} must be an integer or string. Got ${pyType(value)}.`);
  if (!s) throw new ToolError(`${field} cannot be empty.`);
  if (!ASCII_DIGITS.test(s)) {
    throw new ToolError(`${field}=${repr(value)} must be a SOC code like '15-1252' or '151252' (6 ASCII digits, optional single dash after the first 2). No letters, whitespace, or Unicode digits.`);
  }
  if (s.length !== 6) {
    throw new ToolError(`${field}=${repr(value)} must be exactly 6 digits (got ${s.length}). SOC codes are 'XX-XXXX' format, e.g. '15-1252' (Software Developers).`);
  }
  return s;
}

function validateDatatype(value: unknown, field = "datatype"): string {
  const s = coerceDigits(value, field, 2);
  if (!(s in DATATYPE_LABELS)) {
    throw new ToolError(`${field}=${repr(value)} is not a known OEWS datatype. Valid: ${Object.keys(DATATYPE_LABELS).sort().join(", ")}.`);
  }
  return s;
}

function normalizeArea(input: unknown): string {
  if (input === null || input === undefined) throw new ToolError("area_code cannot be None.");
  const area = typeof input === "number" || typeof input === "bigint" ? str(input) : strip(str(input));
  if (!area) throw new ToolError("area_code cannot be empty.");
  if (!ASCII_DIGITS.test(area)) throw new ToolError(`area_code=${repr(input)} must contain only ASCII digits 0-9. Got characters other than digits.`);
  if (area.length === 7) return area;
  if (area.length === 5) return `00${area}`;
  if (area.length === 2) return `${area}00000`;
  if (area.length === 1) return `0${area}00000`;
  throw new ToolError(`Unrecognized area code '${area}' (length ${area.length}). Expected: 1-2 digit state FIPS (e.g., '6' for CA, '51' for VA), 5-digit MSA (e.g., '47900'), or 7-digit full code (e.g., '0047900').`);
}

function checkAreaForScope(scope: string, area: string, field = "area_code") {
  if (scope === "state") {
    if (!area.endsWith("00000")) {
      throw new ToolError(`${field}=${repr(area)} does not look like a state FIPS code. scope='state' takes a 2-digit FIPS (e.g. '51' for VA). For MSA codes use scope='metro'.`);
    }
    const fips = area.slice(0, 2);
    if (!STATE_FIPS.includes(fips)) {
      throw new ToolError(`${field} FIPS ${repr(fips)} is not a state/territory OEWS publishes. Valid FIPS: ${STATE_FIPS.join(", ")}.`);
    }
  } else if (scope === "metro" && area.endsWith("00000")) {
    throw new ToolError(`${field}=${repr(area)} looks like a 2-digit state FIPS, not an MSA code. scope='metro' takes a 5-digit MSA (e.g. '47900' for the DC metro). For states use scope='state'.`);
  }
}

const blank = (v: unknown) => v === null || (typeof v === "string" && !strip(v));

// ---------- the active release in D1 ----------

const ACTIVE = "(SELECT version FROM active_release WHERE id = 1)";
const RELEASE_SQL = "SELECT r.manifest, r.footnotes FROM active_release a JOIN release r ON r.version = a.version WHERE a.id = 1";

interface Release {
  manifest: Row;
  footnotes: Record<string, string>;
  year: string; // OEWS_CURRENT_YEAR
  name: string; // OEWS_RELEASE_NAME
}

function release(rows: Row[]): Release {
  if (!rows.length) throw new Error("no active OEWS release in D1");
  const manifest = JSON.parse(rows[0].manifest);
  return {manifest, footnotes: JSON.parse(rows[0].footnotes), year: manifest.release.year, name: manifest.release.description};
}

const loadRelease = async (db: Database) => release((await db.prepare(RELEASE_SQL).all()).results);

/** The year check needs the release; fetch it only when a year is passed. */
type Year = {value: unknown; checked?: Release};

async function validateYear(year: Year, db: Database, field = "year"): Promise<void> {
  const value = year.value;
  if (value === null) return;
  if (typeof value === "boolean") throw new ToolError(`${field} must be a year, not bool.`);
  let s: string;
  if (typeof value === "number" || typeof value === "bigint") s = intStr(value);
  else if (typeof value === "string") s = strip(value);
  else throw new ToolError(`${field} must be an integer or year-string. Got ${pyType(value)}.`);
  if (!s) return;
  if (!/^[0-9]{4}$/.test(s)) {
    throw new ToolError(`${field}=${repr(value)} must be a 4-digit year (e.g. '2024' or 2024). Decimals, whitespace, and leading zeros beyond 4 digits are rejected.`);
  }
  yearRange(Number(s), year.checked = await loadRelease(db), field);
}

function yearRange(y: number, rel: Release, field = "year") {
  const current = Number(rel.year);
  if (y > current) {
    throw new ToolError(`${field}=${y} is beyond the latest OEWS release (${rel.name}, data year ${rel.year}). BLS publishes OEWS about a year in arrears, so ${y} estimates do not exist yet. Omit the year or pass ${rel.year}.`);
  }
  if (y < current) {
    throw new ToolError(`${field}=${y} is before the current OEWS release. This server answers from the current release only (${rel.name}, data year ${rel.year}). For historical OEWS data, download from bls.gov/oes/tables.htm. Omit the year argument to get current data.`);
  }
}

interface Lookup {
  rel: Release;
  cells: Map<string, Row>;
  occupations: Map<string, string>;
  areas: Map<string, string>;
}

/** One D1 batch: the active release, the cells for the series, and the names. */
async function lookup(db: Database, year: Year, keys: string[], occupations: string[], areas: string[]): Promise<Lookup> {
  const unique = (list: string[]) => [...new Set(list)];
  const keyList = unique(keys);
  const occList = unique(occupations);
  const areaList = unique(areas);
  const marks = (list: unknown[]) => list.map(() => "?").join(", ");
  const statements = [db.prepare(RELEASE_SQL)];
  if (keyList.length) statements.push(db.prepare(`SELECT * FROM cell WHERE version = ${ACTIVE} AND key IN (${marks(keyList)})`).bind(...keyList));
  if (occList.length) statements.push(db.prepare(`SELECT code, name FROM occupation WHERE version = ${ACTIVE} AND code IN (${marks(occList)})`).bind(...occList));
  if (areaList.length) statements.push(db.prepare(`SELECT code, name FROM area WHERE version = ${ACTIVE} AND code IN (${marks(areaList)})`).bind(...areaList));
  const results = await db.batch(statements);
  const rel = release(results[0].results);
  // A release switched between the year check and this batch: check again.
  if (year.checked && year.checked.year !== rel.year) yearRange(Number(strip(str(year.value))), rel);
  let i = 1;
  const cells = keyList.length ? new Map(results[i++].results.map(r => [r.key as string, r])) : new Map();
  const occ = occList.length ? new Map(results[i++].results.map(r => [r.code as string, r.name as string])) : new Map();
  const area = areaList.length ? new Map(results[i++].results.map(r => [r.code as string, r.name as string])) : new Map();
  return {rel, cells, occupations: occ, areas: area};
}

function source(rel: Release): Py {
  const meta = rel.manifest;
  const data = meta.sources["oe.data.0.Current"];
  return {
    kind: "bundled_bls_oews_files",
    publisher: "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics",
    data_year: meta.data_year,
    release: meta.release.description,
    published: data.last_modified ?? null,
    retrieved: meta.retrieved,
    data_file: data.url,
    data_file_sha256: data.sha256,
    tables: "https://www.bls.gov/oes/tables.htm",
    notice: BLS_NOTICE,
  };
}

function seriesId(prefix: string, area: string, industry: string, occ: string, datatype: string) {
  return `${prefix}${area}${industry}${occ}${datatype}`;
}

function checkSeriesCount(ids: string[]) {
  if (ids.length > MAX_SERIES) throw new ToolError(`Too many series (${ids.length}). Max ${MAX_SERIES} per request. Split into multiple calls.`);
}

/** snapshot.lookup + _safe_footnotes: the published value and footnote texts, or undefined. */
function entry(data: Lookup, sid: string): {value: string; notes: string[]} | undefined {
  const row = data.cells.get(sid.slice(0, 23));
  const dt = sid.slice(23);
  const value = row?.[`v${dt}`];
  if (value === null || value === undefined) return undefined;
  const codes = String(row![`f${dt}`] ?? "").split(",").map(strip).filter(Boolean);
  return {value, notes: codes.map(c => data.rel.footnotes[c] ?? "").filter(Boolean)};
}

/** _parse_value for a published value string. */
function parseValue(raw: string, dt: string, notes: string[]): Map<string, Py> {
  const out = (formatted: string, numeric: Py, suppressed: boolean) =>
    new Map<string, Py>([["raw", raw], ["formatted", formatted], ["numeric", numeric], ["suppressed", suppressed]]);
  const stripped = strip(raw);
  if (SPECIAL_VALUES.has(stripped) || stripped === "") {
    return out(notes.length ? `[Not published] ${notes[0]}` : `[Suppressed: ${stripped || "(empty)"}]`, null, true);
  }
  const n = pyFloat(stripped);
  if (n === undefined) return out(`[Unparseable: ${stripped}]`, null, false);
  if (COUNT.has(dt)) return out(group(intStr(Math.trunc(n))), Math.trunc(n), false);
  if (RSE.has(dt)) return out(`${group(fixed(n, 1))}%`, new PyFloat(n), false);
  if (RATIO.has(dt)) return out(group(fixed(n, 2)), new PyFloat(n), false);
  if (HOURLY.has(dt)) return out(`$${group(fixed(n, 2))}/hr`, new PyFloat(n), false);
  return out(`$${group(intStr(Math.trunc(n)))}`, Math.trunc(n), false);
}

const parsed = (data: Lookup, sid: string, dt: string) => {
  const hit = entry(data, sid);
  return hit ? parseValue(hit.value, dt, hit.notes) : NO_DATA();
};
const hasNumeric = (values: Iterable<Py>) => [...values].some(v => v instanceof Map && v.get("numeric") !== null);
const title = (data: Lookup, occ: string) => data.occupations.get(occ) ?? (COMMON_SOC_CODES.get(occ) as string | undefined) ?? null;

// ---------- tools ----------

interface WageResult {
  response: Map<string, Py>;
  data: Lookup;
}

async function wageData(db: Database, a: Record<string, any>, extraOccupations: string[] = []): Promise<WageResult> {
  const {scope, area_code} = a;
  const occ = validateSoc(a.occ_code);
  const industry = coerceDigits(a.industry, "industry", 6);
  const year: Year = {value: a.year};
  await validateYear(year, db);
  const requested: string[] = a.datatypes === null ? [...IGCE_DATATYPES] : a.datatypes;
  if (!requested.length) throw new ToolError("datatypes cannot be empty. Pass None for defaults or specify at least one code.");
  const datatypes = [...new Set(requested.map(dt => validateDatatype(dt, "datatypes[i]")))];
  let area = "0000000";
  if (scope !== "national") {
    if (blank(area_code)) throw new ToolError(`area_code is required for scope='${scope}'.`);
    area = normalizeArea(area_code);
    checkAreaForScope(scope, area);
  }
  if (industry !== "000000" && scope !== "national") {
    throw new ToolError("Industry-specific estimates are only available at the national level (scope='national'). Cannot combine state/metro scope with industry filter.");
  }
  const ids = datatypes.map(dt => seriesId(PREFIX[scope], area, industry, occ, dt));
  checkSeriesCount(ids);
  const data = await lookup(db, year, ids.map(id => id.slice(0, 23)), [occ, ...extraOccupations], [area]);

  const wages = new Map<string, Py>();
  let found = false;
  for (const id of ids) {
    const dt = id.slice(-2);
    wages.set(DATATYPE_LABELS[dt], parsed(data, id, dt));
    found ||= entry(data, id) !== undefined;
  }
  const areaName = data.areas.get(area) ?? null;
  const response = new Map<string, Py>([
    ["occ_code", occ],
    ["occ_title", title(data, occ)],
    ["scope", scope],
    ["area_code", scope !== "national" ? area_code : null],
    ["area_name", areaName],
    ["industry", industry],
    ["data_year", found ? data.rel.year : null],
    ["period", found ? "Annual" : null],
    ["wages", wages],
  ]);
  if (!hasNumeric(wages.values())) {
    response.set("no_data", true);
    let cause: string;
    if (!data.occupations.has(occ)) {
      cause = `occ_code=${occ} is not an occupation in the ${data.rel.name} OEWS release; the SOC code may not exist or may have been retired. Verify it at bls.gov/soc.`;
    } else if (areaName === null) {
      cause = `area_code=${repr(area_code)} is not an OEWS area in the ${data.rel.name} release.`;
    } else {
      cause = "BLS publishes no estimate for this occupation at this area/industry level (or every requested cell is unreleased).";
    }
    response.set("no_data_reason", `No wage values for occ_code=${occ} scope=${scope} area_code=${repr(area_code)} industry=${industry}. ${cause}`);
  }
  if (scope === "national" && area_code !== null) {
    response.set("_note", `area_code=${repr(area_code)} was ignored because scope='national'. Use scope='state' or scope='metro' for geographic breakdowns.`);
  }
  response.set("source", source(data.rel));
  return {response, data};
}

export async function getWageData(db: Database, args: Args) {
  return (await wageData(db, validateArgs("get_wage_data", args))).response;
}

export async function compareMetros(db: Database, args: Args) {
  const a = validateArgs("compare_metros", args);
  const occ = validateSoc(a.occ_code);
  const datatype = validateDatatype(a.datatype);
  const year: Year = {value: a.year};
  await validateYear(year, db);
  if (!a.metro_codes.length) throw new ToolError("metro_codes list cannot be empty.");
  // Dedup on the normalized code: '47900' and '0047900' are one series.
  const labels = new Map<string, string>();
  const collapsed: string[] = [];
  for (const code of a.metro_codes) {
    const label = strip(str(code));
    const area = normalizeArea(code);
    if (area.endsWith("00000")) {
      throw new ToolError(`metro_codes[${repr(code)}] looks like a 2-digit state FIPS. compare_metros requires MSA codes (5 or 7 digits). For states, use compare_occupations with scope='state' instead.`);
    }
    const id = seriesId("OEUM", area, "000000", occ, datatype);
    if (labels.has(id)) collapsed.push(label);
    else labels.set(id, label);
  }
  const ids = [...labels.keys()];
  checkSeriesCount(ids);
  const data = await lookup(db, year, ids.map(id => id.slice(0, 23)), [occ], ids.map(id => id.slice(4, 11)));
  const metros = new Map<string, Py>(ids.map(id => [labels.get(id)!, parsed(data, id, datatype)]));
  const response = new Map<string, Py>([
    ["occ_code", occ],
    ["occ_title", title(data, occ)],
    ["datatype", DATATYPE_LABELS[datatype]],
    ["metros", metros],
    ["metro_names", new Map(ids.map(id => [labels.get(id)!, data.areas.get(id.slice(4, 11)) ?? null]))],
  ]);
  if (metros.size && !hasNumeric(metros.values())) {
    response.set("no_data", true);
    response.set("no_data_reason", `No BLS data for occ_code=${occ} across any of the requested metros. Likely cause: the SOC code does not exist, is retired, or is not surveyed at MSA level. Verify the SOC at bls.gov/soc.`);
  }
  if (collapsed.length) response.set("_note", `Inputs ${repr(collapsed)} normalized to the same series as another input and were collapsed (first spelling wins).`);
  response.set("source", source(data.rel));
  return response;
}

export async function compareOccupations(db: Database, args: Args) {
  const a = validateArgs("compare_occupations", args);
  const {scope, area_code} = a;
  if (!a.occ_codes.length) throw new ToolError("occ_codes list cannot be empty.");
  const datatype = validateDatatype(a.datatype);
  const year: Year = {value: a.year};
  await validateYear(year, db);
  let area = "0000000";
  if (scope !== "national") {
    if (blank(area_code)) throw new ToolError(`area_code required for scope='${scope}'.`);
    area = normalizeArea(area_code);
    checkAreaForScope(scope, area);
  }
  // Dedup on the normalized SOC: '15-1252' and '151252' are one series.
  const codes = new Map<string, string>();
  const collapsed: string[] = [];
  for (const code of a.occ_codes) {
    const label = strip(str(code));
    if (!label) continue;
    const occ = validateSoc(code);
    const id = seriesId(PREFIX[scope], area, "000000", occ, datatype);
    if (codes.has(id)) collapsed.push(label);
    else codes.set(id, occ);
  }
  const ids = [...codes.keys()];
  if (!ids.length) throw new ToolError("occ_codes contained no usable SOC codes.");
  checkSeriesCount(ids);
  const data = await lookup(db, year, ids.map(id => id.slice(0, 23)), [...codes.values()], [area]);
  const occupations = new Map<string, Py>(ids.map(id => {
    const occ = codes.get(id)!;
    return [`${occ} (${title(data, occ) ?? occ})`, parsed(data, id, datatype)];
  }));
  const response = new Map<string, Py>([
    ["scope", scope],
    ["area_code", scope !== "national" ? area_code : null],
    ["area_name", data.areas.get(area) ?? null],
    ["datatype", DATATYPE_LABELS[datatype]],
    ["occupations", occupations],
  ]);
  if (!hasNumeric(occupations.values())) {
    response.set("no_data", true);
    response.set("no_data_reason", `No BLS data for any requested occupation at scope=${scope} area_code=${repr(area_code)}. Likely causes: nonexistent or retired SOC codes, or SOCs not surveyed at this geographic level. Verify at bls.gov/soc.`);
  }
  if (collapsed.length) response.set("_note", `Inputs ${repr(collapsed)} normalized to the same series as another input and were collapsed (first spelling wins).`);
  response.set("source", source(data.rel));
  return response;
}

export async function igceWageBenchmark(db: Database, args: Args) {
  const a = validateArgs("igce_wage_benchmark", args);
  const low: PyFloat = a.burden_low;
  const high: PyFloat = a.burden_high;
  if (low.value <= 0 || high.value <= 0) {
    throw new ToolError(`Burden multipliers must be positive. Got low=${floatRepr(low)}, high=${floatRepr(high)}.`);
  }
  if (low.value > high.value) throw new ToolError(`burden_low (${floatRepr(low)}) must be <= burden_high (${floatRepr(high)}).`);
  if (high.value > 10) {
    throw new ToolError(`burden_high=${floatRepr(high)} is implausibly large. Reasonable max ~4.0x for high-overhead (SCIF/deployed) work.`);
  }
  // Each annual benchmark rides with BLS's published hourly wage (BLS computes
  // annual as hourly x 2080). "03" also detects annual-only occupations (BLS
  // publishes no hourly mean for jobs off a 2080-hour year, such as pilots
  // and teachers).
  const normalized = strip(str(a.occ_code).replaceAll("-", ""));
  const {response: wage, data} = await wageData(db, {...a, industry: "000000", datatypes: IGCE_REQUEST}, [normalized]);
  const wages = wage.get("wages") as Map<string, Map<string, Py>>;
  const numeric = (label: string) => wages.get(label)?.get("numeric") ?? null;
  const annualOnly = numeric("Hourly Mean Wage") === null && numeric("Annual Mean Wage") !== null;
  const benchmarks = new Map<string, Py>();
  for (const [label, hourlyLabel] of IGCE_BENCHMARKS) {
    const item = wages.get(label) ?? new Map<string, Py>();
    const annual = item.get("numeric");
    if (typeof annual === "number" && annual !== 0 && !item.get("suppressed")) {
      const published = numeric(hourlyLabel);
      const hourly = published instanceof PyFloat ? published.value : round(annual / 2080, 2);
      benchmarks.set(label, {
        annual: `$${group(intStr(annual))}`,
        hourly_base: `$${fixed(hourly, 2)}`,
        hourly_burdened_low: `$${fixed(round(hourly * low.value, 2), 2)}`,
        hourly_burdened_high: `$${fixed(round(hourly * high.value, 2), 2)}`,
        numeric_annual: annual,
        numeric_hourly: new PyFloat(hourly),
      });
    } else {
      benchmarks.set(label, {annual: item.get("formatted") ?? "No data", suppressed: true});
    }
  }
  const occTitle = title(data, normalized);
  const response = new Map<string, Py>([
    ["occ_code", a.occ_code],
    ["occ_title", occTitle ?? a.occ_code],
    ["scope", a.scope],
    ["area_code", a.area_code],
    ["area_name", wage.get("area_name")!],
    ["data_year", wage.get("data_year") || data.rel.year],
    ["wage_period", data.rel.name],
    ["burden_range", `${floatRepr(low)}x - ${floatRepr(high)}x`],
    ["benchmarks", benchmarks],
    ["_escalation_note", `${data.rel.name} wages; escalate to the period of performance. OEWS wages are estimates for ${data.rel.name}, so these base and burdened rates are ${data.rel.name} rates, not current ones.`],
    ["_note", "BLS wages are base wages only (no fringe/overhead/G&A/profit). Burdened rates are estimates."],
  ]);
  if (wage.get("no_data")) {
    response.set("no_data", true);
    response.set("no_data_reason", wage.get("no_data_reason")!);
  }
  if (annualOnly) {
    response.set("annual_only", true);
    response.set("_hourly_warning", "BLS publishes no hourly wage for this occupation because it does not generally work a 2080-hour year (think pilots or teachers). The hourly figures above are derived as annual/2080 and may materially misstate the true hourly rate. Benchmark against the annual figures instead.");
  }
  if (occTitle === null) {
    response.set("_title_warning", `occ_code=${repr(a.occ_code)} is not an occupation in the ${data.rel.name} OEWS release. Verify the code at bls.gov/soc before relying on the benchmark -- typos or retired SOCs produce all-zero benchmarks.`);
  }
  response.set("source", source(data.rel));
  return response;
}

export async function detectLatestYear(db: Database, args: Args) {
  validateArgs("detect_latest_year", args);
  const rel = await loadRelease(db);
  const meta = rel.manifest;
  const year = meta.data_year;
  return {
    latest_year: year,
    default_year: rel.year,
    release: meta.release.description,
    published: meta.sources["oe.data.0.Current"].last_modified ?? null,
    retrieved: meta.retrieved,
    newer_data_available: false,
    message: `OEWS ${year} (${meta.release.description} estimates) is the bundled release and the default for every tool. BLS publishes the next release (May ${Number(year) + 1} estimates) in spring ${Number(year) + 2}; check bls.gov/oes for newer data.`,
    source: source(rel),
  } satisfies Py;
}

export async function getDataStatus(db: Database, args: Args) {
  validateArgs("get_data_status", args);
  const rel = await loadRelease(db);
  const meta = rel.manifest;
  const sources = new Map<string, Py>(Object.keys(meta.sources).sort().map(name => {
    const src = meta.sources[name];
    return [name, {url: src.url, sha256: src.sha256, published: src.last_modified ?? null}];
  }));
  return {
    service: "BLS OEWS (bundled release)",
    status: "bundled",
    data_year: meta.data_year,
    release: meta.release.description,
    retrieved: meta.retrieved,
    counts: meta.counts,
    sources,
    api_key_required: false,
    next_release: `BLS publishes the next OEWS release (May ${Number(meta.data_year) + 1} estimates) in spring ${Number(meta.data_year) + 2}.`,
    source: source(rel),
  } satisfies Py;
}

export async function listCommonSocCodes(db: Database, args: Args) {
  validateArgs("list_common_soc_codes", args);
  return {soc_codes: COMMON_SOC_CODES, source: source(await loadRelease(db))} satisfies Py;
}

export async function listCommonMetros(db: Database, args: Args) {
  validateArgs("list_common_metros", args);
  return {metros: COMMON_METROS, source: source(await loadRelease(db))} satisfies Py;
}

export const HANDLERS: Record<string, (db: Database, args: Args) => Promise<Py>> = {
  compare_metros: compareMetros,
  compare_occupations: compareOccupations,
  detect_latest_year: detectLatestYear,
  get_data_status: getDataStatus,
  get_wage_data: getWageData,
  igce_wage_benchmark: igceWageBenchmark,
  list_common_metros: listCommonMetros,
  list_common_soc_codes: listCommonSocCodes,
};
