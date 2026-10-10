// The seven GSA Per Diem tools, ported from the gsa-perdiem-mcp package's
// server.py in hosted mode. Bundled fiscal years are answered from D1 (see
// data.ts); city resolution and other years call the live GSA Per Diem API
// with the operator's key (see upstream.ts). Results match the Python
// server's field for field, including key order, int/float types, and the
// text of every message.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {ArgumentError, validateArguments, type PyInt} from "./args.ts";
import {DataUnavailable, STANDARD, Snapshot, type Area, type AreaRecord, type Database, type Year} from "./data.ts";
import {
  add, cmp, dumps, float, isDict, isFloat, mul, num, numStr, pyLen, pySlice, quote, repr, round2,
  squash, strip, title, PyFloat,
} from "./py.ts";
import {BASE_URL, DeadlineExceeded, ToolError, Upstream} from "./upstream.ts";

export {DataUnavailable, DeadlineExceeded, ToolError};
export type {Database};

// The reviewed contract (sorted by name) in the order the Python server
// registers and lists its tools.
const TOOL_ORDER = [
  "get_data_status", "lookup_city_perdiem", "lookup_zip_perdiem", "lookup_state_rates",
  "get_mie_breakdown", "estimate_travel_cost", "compare_locations",
];

/** tools/list: exactly the tool definitions in tools-contract.json. */
export const TOOLS: {name: string}[] = TOOL_ORDER.map(name => {
  const tool = (CONTRACT as {name: string}[]).find(t => t.name === name);
  if (!tool) throw new Error(`tools-contract.json lacks ${name}`);
  return tool;
});
if (TOOLS.length !== CONTRACT.length) throw new Error("tools-contract.json lists a tool this Worker does not serve");

/** A ValueError raised by a tool: shown to the caller as the tool error. */
export class ValueError extends Error {}

/** Another Python exception that escapes a tool (e.g. OverflowError); also shown as the tool error. */
export class PythonError extends Error {}

export interface Context {
  snapshot: Snapshot;
  upstream: Upstream;
  /** Today's date in UTC (the container ran in UTC). */
  today: Date;
}

type Dict = Record<string, any>;
type Months = Map<string, unknown>;

/** A parsed rate entry (_parse_rate_entry / _from_area_record). */
interface Rate {
  city: string | null;
  county: string;
  state?: string;
  meals: unknown;
  is_standard_rate: boolean;
  lodging_by_month: Months;
  lodging_min: unknown;
  lodging_max: unknown;
  has_seasonal_variation: boolean;
  has_monthly_data: boolean;
  months_without_data?: string[];
  _area_id?: Area;
}

// ---------------------------------------------------------------------------
// Defensive helpers
// ---------------------------------------------------------------------------

const safeDict = (value: unknown): Dict => (isDict(value) ? value : {});

function asList(value: unknown): unknown[] {
  if (value === null || value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

const PY_WS = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PY_INT = new RegExp(`^[${PY_WS}]*([+-]?)(\\p{Nd}(?:_?\\p{Nd})*)[${PY_WS}]*$`, "u");
const PY_FLOAT = new RegExp(
  `^[${PY_WS}]*([+-]?)(?:(inf|infinity|nan)|((?:\\p{Nd}(?:_?\\p{Nd})*)?(?:\\.(?:\\p{Nd}(?:_?\\p{Nd})*)?)?)(?:[eE]([+-]?\\p{Nd}(?:_?\\p{Nd})*))?)[${PY_WS}]*$`,
  "iu",
);
const ND = /\p{Nd}/u;

/** Unicode decimal digits to ASCII, as Python's int() and float() read them. */
function asciiDigits(text: string): string {
  let out = "";
  for (const ch of text) {
    if (ch >= "0" && ch <= "9") out += ch;
    else if (ND.test(ch)) {
      // Nd digits come in runs of ten starting at zero.
      let cp = ch.codePointAt(0)!;
      let value = 0;
      while (ND.test(String.fromCodePoint(cp - 1))) {
        cp--;
        value++;
      }
      out += String(value % 10);
    } else out += ch;
  }
  return out;
}

/** Python int(text), or null for ValueError. */
function pyIntText(text: string): number | null {
  const match = PY_INT.exec(text);
  if (!match) return null;
  const value = Number(asciiDigits(match[2]).replaceAll("_", ""));
  return match[1] === "-" ? -value : value;
}

/** Python float(text), or null for ValueError. */
function pyFloatText(text: string): number | null {
  const match = PY_FLOAT.exec(text);
  if (!match) return null;
  const sign = match[1] === "-" ? -1 : 1;
  if (match[2]) return match[2].toLowerCase() === "nan" ? NaN : sign * Infinity;
  const mantissa = match[3];
  if (!mantissa || mantissa === "." || !/\p{Nd}/u.test(mantissa)) return null;
  const exponent = match[4] === undefined ? "" : "e" + asciiDigits(match[4]).replaceAll("_", "");
  return sign * Number(asciiDigits(mantissa).replaceAll("_", "") + exponent);
}

/** int(float): truncation, with Python's errors for NaN and infinity. */
function intOfFloat(value: number): number {
  if (Number.isNaN(value)) throw new ValueError("cannot convert float NaN to integer");
  if (!Number.isFinite(value)) throw new PythonError("cannot convert float infinity to integer");
  return Math.trunc(value) || 0;
}

const isPyNull = (value: unknown) => value === null || value === undefined || value === "" || value === "null" || value === "None";

/** _safe_int: None/''/'null'/unparseable -> default. OverflowError escapes, as in Python. */
function safeInt(value: unknown, fallback = 0): number {
  if (isPyNull(value)) return fallback;
  const attempt = (convert: () => number | null): number | null => {
    try {
      return convert();
    } catch (error) {
      if (error instanceof ValueError) return null;
      throw error;
    }
  };
  const first = attempt(() => {
    if (typeof value === "boolean") return value ? 1 : 0;
    if (typeof value === "number") return value;
    if (isFloat(value)) return intOfFloat(value.value);
    if (typeof value === "string") return pyIntText(value);
    return null; // TypeError
  });
  if (first !== null) return first;
  const second = attempt(() => {
    const f = toPyFloat(value);
    return f === null ? null : intOfFloat(f);
  });
  return second ?? fallback;
}

/** float(value), or null for TypeError/ValueError. */
function toPyFloat(value: unknown): number | null {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number") return value;
  if (isFloat(value)) return value.value;
  if (typeof value === "string") return pyFloatText(value);
  return null;
}

/** _safe_number: a float; 0.0 for None/NaN/infinite/unparseable. */
function safeNumber(value: unknown): PyFloat {
  if (isPyNull(value)) return float(0);
  const f = toPyFloat(value);
  return f === null || !Number.isFinite(f) ? float(0) : float(f);
}

function clamp(value: PyInt, field: string, lo: number, hi: number): number {
  if (value < lo) throw new ValueError(`${field} must be >= ${lo}. Got ${value}.`);
  if (value > hi) throw new ValueError(`${field} exceeds maximum of ${hi}. Got ${value}.`);
  return Number(value);
}

const currentFiscalYear = (ctx: Context) =>
  ctx.today.getUTCMonth() + 1 >= 10 ? ctx.today.getUTCFullYear() + 1 : ctx.today.getUTCFullYear();

function validateFiscalYear(ctx: Context, value: PyInt | null, field = "fiscal_year"): number {
  if (value === null) return currentFiscalYear(ctx);
  const current = currentFiscalYear(ctx);
  const lo = 2020;
  const hi = current + 1;
  if (value < lo || value > hi) {
    throw new ValueError(
      `${field}=${value} is out of range. GSA Per Diem data covers FY${lo} through FY${hi} (current FY is ${current}).`,
    );
  }
  return Number(value);
}

const USPS_STATES = new Set([
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
  "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
  "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
  "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
  "WY",
  "AS", "GU", "MP", "PR", "VI",
]);

const OCONUS_STATES = new Set(["AK", "HI", "AS", "GU", "MP", "PR", "VI"]);

const OCONUS_NOTE =
  "GSA per diem covers CONUS only. Rates for Alaska, Hawaii, and the " +
  "territories (non-foreign OCONUS) are set by DoD's Defense Travel " +
  "Management Office at travel.dod.mil; foreign rates by the State " +
  "Department at aoprals.state.gov. Do NOT apply the CONUS standard " +
  "rate to these locations.";

const pyTypeName = (value: unknown) =>
  value === null || value === undefined ? "NoneType" : typeof value === "string" ? "str" : typeof value === "boolean" ? "bool"
    : isFloat(value) ? "float" : typeof value === "number" || typeof value === "bigint" ? "int" : Array.isArray(value) ? "list" : "dict";

function validateState(value: unknown, field = "state"): string {
  if (value === null || value === undefined) throw new ValueError(`${field} is required.`);
  if (typeof value !== "string") throw new ValueError(`${field} must be a 2-letter USPS code. Got ${pyTypeName(value)}.`);
  const s = strip(value).toUpperCase();
  if (pyLen(s) !== 2 || !/^\p{L}+$/u.test(s)) {
    throw new ValueError(`${field} must be a 2-letter USPS code (e.g., 'DC', 'VA'). Got ${repr(value)}.`);
  }
  if (!USPS_STATES.has(s)) {
    throw new ValueError(
      `${field}=${repr(value)} is not a valid USPS state/territory code. Common codes: AL, AK, AZ, AR, CA, CO, CT, DC, ...`,
    );
  }
  return s;
}

const ZIP5 = /^[0-9]{5}(?:-[0-9]{4})?$/;

function validateZip(value: string, field = "zip_code"): string {
  let s = strip(value);
  if (!ZIP5.test(s)) {
    throw new ValueError(
      `${field} must be a 5-digit US ZIP (ZIP+4 also accepted, e.g., '02101' or '02101-1234'). Got ${repr(value)}.`,
    );
  }
  return s.slice(0, 5);
}

const CITY_INVALID = /[\x00-\x1f\\]/;

function validateCity(value: unknown, field = "city"): string {
  if (value === null || value === undefined) throw new ValueError(`${field} is required.`);
  if (typeof value !== "string") throw new ValueError(`${field} must be a string. Got ${pyTypeName(value)}.`);
  if (CITY_INVALID.test(value)) {
    throw new ValueError(
      `${field}=${repr(value)} contains control characters or backslashes. Use plain city names like 'Boston' or 'Saint Louis'.`,
    );
  }
  const slashless = value.replaceAll("/", " ");
  const s = squash(slashless);
  if (!s) throw new ValueError(`${field} cannot be empty or whitespace.`);
  if (pyLen(s) > 100) throw new ValueError(`${field} exceeds 100 chars. Got ${pyLen(s)}.`);
  if (s.includes("..")) throw new ValueError(`${field}=${repr(slashless)} contains '..' which is not a valid city name.`);
  return s;
}

const MONTH_SHORTS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTH_LOOKUP = new Map<string, string>([
  ...MONTH_SHORTS.map(m => [m.toLowerCase(), m] as [string, string]),
  ...MONTH_FULL.map((m, i) => [m.toLowerCase(), MONTH_SHORTS[i]] as [string, string]),
]);

function validateTravelMonth(value: string | null, field = "travel_month"): string | null {
  if (value === null) return null;
  const s = strip(value);
  if (!s) return null;
  const month = MONTH_LOOKUP.get(s.toLowerCase());
  if (month === undefined) {
    throw new ValueError(`${field}=${repr(value)} must be an exact month: 'Jan'-'Dec' or 'January'-'December' (case-insensitive).`);
  }
  return month;
}

function validateCounty(value: unknown, field = "county"): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") throw new ValueError(`${field} must be a string county name like 'Fairfax'.`);
  const s = squash(value);
  if (!s) return null;
  if (pyLen(s) > 80 || CITY_INVALID.test(s)) throw new ValueError(`${field}=${repr(value)} is not a valid county name.`);
  return s;
}

// ---------------------------------------------------------------------------
// Response parsing helpers
// ---------------------------------------------------------------------------

/** min()/max(): the first extreme element, compared numerically. */
function extreme(values: unknown[], better: (a: number, b: number) => boolean): unknown {
  let best = values[0];
  for (const v of values.slice(1)) if (better(num(v), num(best))) best = v;
  return best;
}
const pyMin = (values: unknown[]) => extreme(values, (a, b) => a < b);
const pyMax = (values: unknown[]) => extreme(values, (a, b) => a > b);
/** Python truthiness of a JSON value. */
function pyBool(value: unknown): boolean {
  if (value === null || value === undefined || value === false) return false;
  if (typeof value === "string" || Array.isArray(value)) return value.length > 0;
  if (typeof value === "number" || isFloat(value)) return num(value) !== 0;
  if (typeof value === "bigint") return value !== 0n;
  if (value instanceof Map) return value.size > 0;
  if (typeof value === "object") return Object.keys(value).length > 0;
  return true;
}

/** str(value) for a JSON value that is not a string. */
function pyStr(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === true) return "True";
  if (value === false) return "False";
  if (value === null || value === undefined) return "None";
  if (typeof value === "number" || typeof value === "bigint" || isFloat(value)) return numStr(value);
  return repr(value);
}

function parseRateEntry(raw: unknown): Rate {
  const entry = safeDict(raw);
  const monthsRaw = asList(safeDict(entry.months).month);
  const months: Months = new Map();
  const monthsWithoutData: string[] = [];
  for (const item of monthsRaw) {
    const m = safeDict(item);
    const short = m.short;
    if (typeof short !== "string" || !short) continue;
    // A null or unparseable value must NOT become $0.
    const value = safeInt(m.value, 0);
    if (value > 0) months.set(short, value);
    else monthsWithoutData.push(short);
  }
  let city: unknown = pyBool(entry.city) ? entry.city : "";
  if (typeof city !== "string") city = city !== null && city !== undefined ? pyStr(city) : "";
  city = squash(city as string);
  const isStandard = strip(city as string).toLowerCase() === "standard rate";
  const lodging = [...months.values()];
  const lodgingMin = lodging.length ? pyMin(lodging) : 0;
  const lodgingMax = lodging.length ? pyMax(lodging) : 0;
  let county = entry.county;
  if (typeof county !== "string" || !county) county = "N/A";
  const out: Rate = {
    city: (city as string) || null,
    county,
    meals: safeInt(entry.meals, 0),
    is_standard_rate: isStandard,
    lodging_by_month: months,
    lodging_min: lodgingMin,
    lodging_max: lodgingMax,
    has_seasonal_variation: lodging.length > 0 && num(lodgingMin) !== num(lodgingMax),
    has_monthly_data: months.size > 0,
  };
  if (monthsWithoutData.length) out.months_without_data = monthsWithoutData;
  return out;
}

const PY_PUNCT = /['\u2019\u2018.,\-/]/g;

function normalizeForMatch(s: string): string {
  return squash(s.toLowerCase().replace(PY_PUNCT, " "));
}

/** The query is one whole slash-separated part of an NSA name ("Woburn" in
 * "Burlington / Woburn"), never a substring of a part ("Milton" in "Hamilton"). */
function isCompositePart(query: string, nsaName: string): boolean {
  const q = normalizeForMatch(query);
  return q !== "" && nsaName.split("/").some(part => normalizeForMatch(part) === q);
}

function normalizeCityForUrl(city: string): string {
  const s = squash(city.replaceAll("'", " ").replaceAll("\u2019", " ").replaceAll("-", " "));
  try {
    return quote(s);
  } catch {
    throw new PythonError("'utf-8' codec can't encode character: surrogates not allowed");
  }
}

// ---------------------------------------------------------------------------
// Rate records and resolution
// ---------------------------------------------------------------------------

function fromAreaRecord(rec: AreaRecord): Rate {
  const months: Months = new Map(Object.entries(rec.lodging_by_month));
  const values = [...months.values()];
  const lo = pyMin(values);
  const hi = pyMax(values);
  return {
    city: rec.destination,
    county: rec.location_defined,
    state: rec.state,
    meals: rec.meals,
    is_standard_rate: rec.is_standard_rate,
    lodging_by_month: months,
    lodging_min: lo,
    lodging_max: hi,
    has_seasonal_variation: num(lo) !== num(hi),
    has_monthly_data: true,
    _area_id: rec.area_id,
  };
}

function parsedEntries(response: unknown): Rate[] {
  const rates = asList(safeDict(response).rates);
  if (!rates.length) return [];
  return asList(safeDict(rates[0]).rate).map(parseRateEntry).filter(p => p.city);
}

function rateSignature(p: Rate): string {
  const items = [...p.lodging_by_month.entries()].sort((a, b) => cmp(a[0], b[0])).map(([k, v]) => [k, num(v)]);
  return JSON.stringify([items, num(p.meals)]);
}

function formatLodgingRange(rate: Rate): string {
  const lo = rate.lodging_min ?? 0;
  const hi = rate.lodging_max ?? 0;
  if (!rate.has_monthly_data) return "no monthly lodging data available";
  if (rate.has_seasonal_variation) return `$${numStr(lo)}-$${numStr(hi)}/night`;
  return `$${numStr(lo)}/night`;
}

function candidateSummary(p: Rate): Dict {
  const out: Dict = {
    destination: p.city,
    location_defined: p.county,
    is_standard_rate: p.is_standard_rate,
    lodging_range: formatLodgingRange(p),
    lodging_by_month: p.lodging_by_month,
    mie_daily: p.meals,
    max_daily_total: add(p.lodging_max, p.meals),
  };
  if (p.state) out.state = p.state;
  return out;
}

const apiSource = (path: string) => ({kind: "gsa_per_diem_api", endpoint: `${BASE_URL}/${path}`});

function areaIdFor(snap: Year, state: string, p: Rate): Area | undefined {
  if (p._area_id !== undefined) return p._area_id;
  if (p.is_standard_rate) return STANDARD;
  return snap.destinationId(state, p.city!);
}

function isFullStateList(snap: Year | null, state: string, nsa: Rate[]): boolean {
  if (snap === null) return nsa.length >= 2;
  const names = new Set(snap.stateDestinationIds(state).map(i => snap.destinations.get(i)!.name));
  const cities = new Set(nsa.map(p => p.city));
  return names.size > 0 && [...names].every(n => cities.has(n));
}

async function censusSuggestion(snap: Year | null, state: string, city: string): Promise<Dict | null> {
  if (snap === null) return null;
  const [areas, counties] = await snap.censusAreas(state, city);
  if (areas.size !== 1) return null;
  const rec = fromAreaRecord(snap.areaRate([...areas][0], state));
  const out = candidateSummary(rec);
  out.basis = "Census 2020 place/county records" +
    (counties.length ? ` place ${repr(city)} in ${counties.map(c => title(c.split("|").slice(1).join("|"))).join(", ")} County` : "") +
    "; not a GSA determination";
  return out;
}

interface Resolution {
  status: "resolved" | "ambiguous" | "unresolved" | "no_data" | "invalid_county";
  rate?: Rate;
  match_type?: string;
  other_candidates?: (string | null)[];
  candidates?: Rate[];
  suggestion?: Dict | null;
}

async function resolveCity(ctx: Context, response: unknown, city: string, state: string, year: number): Promise<Resolution> {
  const parsed = parsedEntries(response);
  if (!parsed.length) return {status: "no_data"};
  const snap = await ctx.snapshot.year(year);
  const q = normalizeForMatch(city);

  const exact = parsed.filter(p => normalizeForMatch(p.city!) === q);
  if (exact.length) return {status: "resolved", rate: exact[0], match_type: "exact"};

  // A list of every rate area in the state means GSA did not recognize the
  // city; no name match inside that list is GSA's answer.
  const standard = parsed.filter(p => p.is_standard_rate);
  const nsa = parsed.filter(p => !p.is_standard_rate);
  if (standard.length && nsa.length && isFullStateList(snap, state, nsa)) {
    return {status: "unresolved", suggestion: await censusSuggestion(snap, state, city)};
  }

  const composite = nsa.filter(p => isCompositePart(city, p.city!));
  if (composite.length === 1) return {status: "resolved", rate: composite[0], match_type: "composite"};

  const candidates = [...nsa, ...standard.slice(0, 1)];
  if (candidates.length === 1) {
    const only = candidates[0];
    return {status: "resolved", rate: only, match_type: only.is_standard_rate ? "standard_fallback" : "api_resolved"};
  }

  // GSA returned several rate areas; break the tie only when Census places
  // the city in exactly one of them.
  if (snap !== null) {
    const [areas] = await snap.censusAreas(state, city);
    const hits = candidates.filter(p => {
      const id = areaIdFor(snap, state, p);
      return id !== undefined && areas.has(id);
    });
    if (hits.length === 1) {
      const chosen = hits[0];
      return {
        status: "resolved", rate: chosen, match_type: "census_tiebreak",
        other_candidates: candidates.filter(p => p !== chosen).map(p => p.city),
      };
    }
  }
  return {status: "ambiguous", candidates};
}

async function resolveCityByCounty(snap: Year, city: string, state: string, county: string): Promise<Resolution> {
  const area = await snap.areaForCounty(state, county, city);
  if (area === null) return {status: "invalid_county"};
  return {status: "resolved", rate: fromAreaRecord(snap.areaRate(area, state)), match_type: "county"};
}

async function lookupCity(ctx: Context, city: string, state: string, year: number, county: string | null): Promise<[Resolution, Dict]> {
  const snap = await ctx.snapshot.year(year);
  if (county && snap !== null) return [await resolveCityByCounty(snap, city, state, county), snap.source];
  const path = `city/${normalizeCityForUrl(city)}/state/${state}/year/${year}`;
  const response = await ctx.upstream.get(path);
  if (county) {
    // No bundled data for this year: filter GSA's candidates by county text.
    const cq = normalizeForMatch(county);
    const parsed = parsedEntries(response).filter(p => cq && normalizeForMatch(pyStr(p.county || "")).includes(cq));
    if (parsed.length === 1) return [{status: "resolved", rate: parsed[0], match_type: "county"}, apiSource(path)];
    return [{status: "invalid_county"}, apiSource(path)];
  }
  return [await resolveCity(ctx, response, city, state, year), apiSource(path)];
}

function unresolvedPayload(res: Resolution, city: string, state: string): Dict {
  const out: Dict = {status: res.status};
  if (res.status === "ambiguous") {
    out.candidates = res.candidates!.map(candidateSummary);
    out.note = `GSA lists more than one rate area for ${city}, ${state}. Per diem follows the ` +
      "county or locality of the work location; supplying county selects one.";
  } else if (res.status === "unresolved") {
    out.note = `GSA's city lookup did not recognize ${repr(city)} in ${state}; it returned every ` +
      "rate area in the state rather than a match. Supplying county, or using " +
      "lookup_zip_perdiem, determines the rate.";
    if (res.suggestion) out.census_suggestion = res.suggestion;
  } else if (res.status === "invalid_county") {
    out.note = `The supplied county is not a recognized ${state} county or county-equivalent, ` +
      "or does not match the supplied city or locality's county for a special rate area. " +
      "Check the work location's city and county.";
  }
  return out;
}

function matchNote(matchType: string | undefined, queryCity: string, best: Rate, others?: (string | null)[]): string | null {
  if (matchType === undefined || matchType === "exact") return null;
  if (matchType === "composite") return `${repr(queryCity)} is part of a composite NSA name.`;
  if (matchType === "standard_fallback") {
    return `GSA resolved ${repr(queryCity)} to the Standard Rate: it is not in a listed non-standard area for this state.`;
  }
  if (matchType === "api_resolved") {
    return `GSA resolved ${repr(queryCity)} to the ${repr(best.city)} rate area (county: ${pyStr(best.county)}). ` +
      "This is the API's own city-to-county resolution, not a name-match failure.";
  }
  if (matchType === "census_tiebreak") {
    return `GSA listed several rate areas for ${repr(queryCity)} (${repr([best.city, ...(others ?? [])])}). ` +
      `Census 2020 place records put ${repr(queryCity)} only in the ${repr(best.city)} area, so that rate is shown.`;
  }
  if (matchType === "county") return "Rate determined from GSA's county definitions for the supplied county.";
  return null;
}

function noRatesHint(ctx: Context, year: number): string {
  if (year > currentFiscalYear(ctx)) {
    return ` FY${year} rates may simply not be published yet; GSA posts new-FY rates in late August.`;
  }
  return "";
}

const firstLastDay = (meals: unknown) => round2(num(meals) * 0.75);

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

const LIVE_TOOLS = ["lookup_city_perdiem", "estimate_travel_cost", "compare_locations"];
const BUNDLED_TOOLS = ["lookup_zip_perdiem", "lookup_state_rates", "get_mie_breakdown"];

async function getDataStatus(ctx: Context): Promise<Dict> {
  const manifest = await ctx.snapshot.manifest();
  const fiscalYears = manifest.fiscal_years ?? {};
  const years = Object.keys(fiscalYears).map(Number).sort((a, b) => a - b);
  const sources: Dict = {};
  for (const fy of years) {
    const meta = fiscalYears[String(fy)];
    sources[String(fy)] = {
      zip_file: meta.zip.url,
      zip_file_published: meta.zip.published ?? null,
      zip_file_sha256: meta.zip.sha256,
      rate_file: meta.rates.url,
      mie_file: meta.mie.url,
      mie_file_covers: meta.mie.covers ?? null,
    };
  }
  return {
    service: "GSA Per Diem",
    current_fiscal_year: currentFiscalYear(ctx),
    bundled_fiscal_years: years,
    bundled_sources: sources,
    bundled_tools: BUNDLED_TOOLS,
    live_api_tools: LIVE_TOOLS,
    live_api_also_used_for: "ZIP, state, and M&IE lookups for fiscal years not bundled" +
      (years.length ? ` (bundled: FY${years[0]}-FY${years[years.length - 1]})` : ""),
    live_lookup_access: ctx.upstream.keyConfigured ? "hosted_publisher_key" : "hosted_key_missing",
  };
}

async function lookupCityPerdiem(ctx: Context, args: Dict): Promise<Dict> {
  const city = validateCity(args.city, "city");
  const state = validateState(args.state, "state");
  const year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");
  const county = validateCounty(args.county);
  const query: Dict = {city, state, fiscal_year: year};
  if (county) query.county = county;

  if (OCONUS_STATES.has(state)) return {query, oconus: true, error: OCONUS_NOTE};

  const [res, source] = await lookupCity(ctx, city, state, year, county);
  if (res.status === "no_data") {
    return {query, error: `No rates found for ${city}, ${state} in FY${year}.` + noRatesHint(ctx, year)};
  }
  if (res.status !== "resolved") return {query, ...unresolvedPayload(res, city, state), source};
  const best = res.rate!;
  const out: Dict = {
    query,
    status: "resolved",
    matched_city: best.city,
    match_type: res.match_type,
    match_note: matchNote(res.match_type, city, best, res.other_candidates),
    county: best.county,
    is_standard_rate: best.is_standard_rate,
    lodging_by_month: best.lodging_by_month,
    lodging_range: formatLodgingRange(best),
    mie_daily: best.meals,
    mie_first_last_day: firstLastDay(best.meals),
    max_daily_total: add(best.lodging_max, best.meals),
    has_monthly_data: best.has_monthly_data,
    source,
  };
  if (res.other_candidates?.length) out.other_candidates = res.other_candidates;
  if (best.months_without_data?.length) out.months_without_data = best.months_without_data;
  return out;
}

async function lookupZipPerdiem(ctx: Context, args: Dict): Promise<Dict> {
  const zip5 = validateZip(args.zip_code, "zip_code");
  const year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");
  const county = validateCounty(args.county);
  const base: Dict = {zip_code: zip5, fiscal_year: year};
  if (county) base.county = county;

  let candidates: Rate[];
  let source: Dict;
  const [snap, entries] = await ctx.snapshot.yearWithZip(year, zip5);
  if (snap !== null) {
    const areas = snap.zipAreas(entries);
    candidates = areas.map(([a, st]) => fromAreaRecord(snap.areaRate(a, st)));
    source = snap.source;
    if (county && candidates.length) {
      const wanted = new Set<Area>();
      for (const st of new Set(areas.map(([, st]) => st))) {
        const area = await snap.areaForCounty(st, county);
        if (area !== null) wanted.add(area);
      }
      if (!wanted.size) {
        return {
          ...base, status: "invalid_county",
          note: "No county or county-equivalent in this ZIP's state(s) matches the supplied county.",
          source,
        };
      }
      candidates = candidates.filter(p => wanted.has(p._area_id!));
    }
  } else {
    const path = `zip/${zip5}/year/${year}`;
    candidates = parsedEntries(await ctx.upstream.get(path));
    source = apiSource(path);
    if (county) {
      const cq = normalizeForMatch(county);
      candidates = candidates.filter(p => normalizeForMatch(pyStr(p.county || "")).includes(cq));
    }
  }

  if (!candidates.length) {
    return {
      ...base,
      error: (county ? "No rate area for this ZIP matches the supplied county." : "No rates found for this ZIP.") +
        noRatesHint(ctx, year) +
        (county ? "" : " If this ZIP is in Alaska, Hawaii, or a territory: " + OCONUS_NOTE),
      source,
    };
  }

  const distinct = new Set(candidates.map(rateSignature));
  if (distinct.size > 1) {
    return {
      ...base,
      status: "ambiguous",
      candidates: candidates.map(candidateSummary),
      note: `ZIP ${zip5} spans ${candidates.length} per diem rate areas with different rates. ` +
        "GSA assigns rates by the county or locality of the work location, not by " +
        "ZIP; supplying county selects one.",
      source,
    };
  }

  const best = candidates.find(p => !p.is_standard_rate) ?? candidates[0];
  const out: Dict = {
    ...base,
    status: "resolved",
    matched_city: best.city,
    match_type: county ? "county" : "zip",
    county: best.county,
    is_standard_rate: best.is_standard_rate,
    lodging_by_month: best.lodging_by_month,
    lodging_range: formatLodgingRange(best),
    mie_daily: best.meals,
    mie_first_last_day: firstLastDay(best.meals),
    max_daily_total: add(best.lodging_max, best.meals),
    has_monthly_data: best.has_monthly_data,
    source,
  };
  // "county" above is the rate area's definition; keep the caller's input too.
  if (county) out.county_supplied = county;
  if (candidates.length > 1) out.same_rate_areas = candidates.map(p => p.city);
  return out;
}

async function lookupStateRates(ctx: Context, args: Dict): Promise<Dict> {
  const state = validateState(args.state, "state");
  const year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");

  if (OCONUS_STATES.has(state)) return {state, fiscal_year: year, oconus: true, error: OCONUS_NOTE};

  const snap = await ctx.snapshot.year(year);
  let standard: Dict | null = null;
  let parsed: Rate[];
  let source: Dict;
  if (snap !== null) {
    parsed = snap.stateDestinationIds(state).map(i => fromAreaRecord(snap.areaRate(i, state)));
    parsed.sort((a, b) => cmp(a.city!, b.city!));
    const std = fromAreaRecord(snap.areaRate(STANDARD, state));
    standard = {lodging: std.lodging_max, mie: std.meals};
    source = snap.source;
  } else {
    const path = `state/${state}/year/${year}`;
    parsed = parsedEntries(await ctx.upstream.get(path));
    source = apiSource(path);
    if (!parsed.length) {
      return {
        state, fiscal_year: year, nsa_count: 0, rates: [],
        note: `The API returned no rate data for ${state} in FY${year}.` + noRatesHint(ctx, year),
        source,
      };
    }
    const stdRows = parsed.filter(p => p.is_standard_rate);
    if (stdRows.length) standard = {lodging: stdRows[0].lodging_max, mie: stdRows[0].meals};
  }
  const nsaOnly = parsed.filter(p => !p.is_standard_rate);
  const out: Dict = {
    state,
    fiscal_year: year,
    nsa_count: nsaOnly.length,
    rates: nsaOnly.map(r => ({
      city: r.city,
      county: r.county,
      lodging_max: r.lodging_max,
      lodging_min: r.lodging_min,
      mie: r.meals,
      max_daily: add(r.lodging_max, r.meals),
      seasonal: r.has_seasonal_variation,
      // Season months, so "Virginia Beach in July" needs no second call.
      ...(r.has_seasonal_variation ? {lodging_by_month: r.lodging_by_month} : {}),
    })),
    source,
  };
  if (standard) out.standard_rate = standard;
  return out;
}

async function getMieBreakdown(ctx: Context, args: Dict): Promise<Dict> {
  const year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");
  const snap = await ctx.snapshot.year(year);
  if (snap !== null) {
    const out: Dict = {
      fiscal_year: year,
      tiers: snap.mie_tiers.map(t => ({
        total: t.total,
        breakfast: t.breakfast,
        lunch: t.lunch,
        dinner: t.dinner,
        incidental: t.incidental,
        first_last_day_75pct: t.first_last_day,
      })),
      source: snap.source,
    };
    const covers = typeof snap.source.mie_file_covers === "string" ? snap.source.mie_file_covers : "";
    const first = /^FY(\d{4})\b/.exec(covers);
    if (first && Number(first[1]) !== year) {
      out.mie_note = `GSA names its M&IE breakdown file for FY${first[1]}, the first fiscal ` +
        `year it applies to; GSA lists it for ${covers}, which includes FY${year}.`;
    }
    return out;
  }

  const path = `conus/mie/${year}`;
  const data = await ctx.upstream.get(path);
  let tiersRaw: unknown;
  if (Array.isArray(data)) {
    tiersRaw = data;
  } else {
    const d = safeDict(data);
    tiersRaw = d.mieData;
    if (tiersRaw === null || tiersRaw === undefined) tiersRaw = d.rates;
  }
  const out = asList(tiersRaw).map(item => {
    const t = safeDict(item);
    const total = safeNumber(t.total);
    let firstLast: PyFloat;
    if (t.FirstLastDay === null || t.FirstLastDay === undefined) {
      firstLast = total.value ? round2(total.value * 0.75) : float(0);
    } else {
      firstLast = safeNumber(t.FirstLastDay);
    }
    return {
      total,
      breakfast: safeNumber(t.breakfast),
      lunch: safeNumber(t.lunch),
      dinner: safeNumber(t.dinner),
      incidental: safeNumber(t.incidental),
      first_last_day_75pct: firstLast,
    };
  });
  return {fiscal_year: year, tiers: out, source: apiSource(path)};
}

const MONTH_NUMBER = new Map(MONTH_SHORTS.map((m, i) => [m, i + 1]));

function fiscalYearForMonth(ctx: Context, month: string): number {
  const n = MONTH_NUMBER.get(month)!;
  const year = ctx.today.getUTCFullYear();
  const calYear = n >= ctx.today.getUTCMonth() + 1 ? year : year + 1;
  return n >= 10 ? calYear + 1 : calYear;
}

async function estimateTravelCost(ctx: Context, args: Dict): Promise<Dict> {
  const city = validateCity(args.city, "city");
  const state = validateState(args.state, "state");
  const numNights = clamp(args.num_nights, "num_nights", 1, 365);
  const travelMonth = validateTravelMonth(args.travel_month, "travel_month");
  let year: number;
  let fyBasis: string;
  if (args.fiscal_year === null && travelMonth) {
    year = validateFiscalYear(ctx, fiscalYearForMonth(ctx, travelMonth), "fiscal_year");
    fyBasis = `next ${travelMonth} (FY${year})`;
  } else {
    year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");
    fyBasis = args.fiscal_year !== null ? "requested" : "current fiscal year";
  }
  const county = validateCounty(args.county);
  const query: Dict = {city, state, fiscal_year: year};
  if (county) query.county = county;

  if (OCONUS_STATES.has(state)) return {query, oconus: true, error: OCONUS_NOTE};

  const [res, source] = await lookupCity(ctx, city, state, year, county);
  if (res.status === "no_data") {
    return {query, error: `No rates found for ${city}, ${state} in FY${year}.` + noRatesHint(ctx, year)};
  }
  if (res.status !== "resolved") {
    return {
      query,
      ...unresolvedPayload(res, city, state),
      error: `No single per diem rate can be determined for ${city}, ${state}; no estimate was produced.`,
      source,
    };
  }
  const best = res.rate!;

  let monthFallbackNote: string | null = null;
  let nightly: unknown;
  let rateMonth: string;
  if (travelMonth && best.lodging_by_month.has(travelMonth)) {
    nightly = best.lodging_by_month.get(travelMonth);
    rateMonth = travelMonth;
  } else {
    nightly = best.lodging_max;
    rateMonth = "MAX";
    if (travelMonth) monthFallbackNote = `No published lodging rate for ${travelMonth}; used the max monthly rate instead.`;
  }

  const dailyMie = best.meals;
  // A $0 lodging or M&IE rate is missing data, not a real rate.
  if (num(nightly) <= 0 || num(dailyMie) <= 0) {
    return {
      query,
      matched_city: best.city,
      match_type: res.match_type,
      error: `Rate data for ${repr(best.city)} is incomplete (nightly lodging=${pyStr(nightly)}, M&IE=${pyStr(dailyMie)}); ` +
        "refusing to build an estimate that prices a component at $0. Try lookup_state_rates or a different fiscal year." +
        noRatesHint(ctx, year),
    };
  }

  const lodgingTotal = mul(nightly, numNights);
  const travelDays = numNights + 1;
  const firstLastMie = round2(num(dailyMie) * 0.75);
  let mieTotal: unknown;
  if (travelDays <= 1) mieTotal = firstLastMie;
  else if (travelDays === 2) mieTotal = mul(firstLastMie, 2);
  else mieTotal = add(mul(dailyMie, travelDays - 2), mul(firstLastMie, 2));

  const out: Dict = {
    destination: best.city,
    state,
    fiscal_year: year,
    fiscal_year_basis: fyBasis,
    status: "resolved",
    match_type: res.match_type,
    match_note: matchNote(res.match_type, city, best, res.other_candidates),
    num_nights: numNights,
    travel_days: travelDays,
    nightly_lodging: nightly,
    lodging_total: lodgingTotal,
    daily_mie: dailyMie,
    first_last_day_mie: firstLastMie,
    mie_total: round2(num(mieTotal)),
    grand_total: round2(num(add(lodgingTotal, mieTotal))),
    rate_month: rateMonth,
    source,
    _note: "Per diem only (lodging + M&IE). Airfare and ground transport not included.",
  };
  if (monthFallbackNote) out.month_fallback_note = monthFallbackNote;
  if (rateMonth !== "MAX" && numNights > 1) {
    out.rate_month_note = `All ${numNights} nights are priced at the FY${year} ${rateMonth} rate. ` +
      "If the trip crosses into another month or fiscal year, add only each month's " +
      "lodging_total using the applicable fiscal year. Calculate M&IE once for the entire trip, " +
      "using the applicable daily rate and 75% only on the actual departure and return days. " +
      "Do not add the separate estimates' mie_total or grand_total: each assumes a new trip.";
  }
  if (travelDays >= 31) {
    out.long_term_note = "Long stay (31 or more travel days): an agency may prescribe a reduced " +
      "per diem rate (41 CFR 301-11.22), and agency rules such as DoD's Joint " +
      "Travel Regulations may reduce long-term TDY rates. This estimate uses " +
      "GSA's full maximum rates.";
  }
  if (res.other_candidates?.length) out.other_candidates = res.other_candidates;
  return out;
}

const MAX_COMPARE_LOCATIONS = 25;

async function compareLocations(ctx: Context, args: Dict): Promise<Dict> {
  const locations: Record<string, string>[] = args.locations;
  if (!locations.length) throw new ValueError("locations must be a non-empty list of {city, state} dicts.");
  if (locations.length > MAX_COMPARE_LOCATIONS) {
    throw new ValueError(
      `compare_locations accepts up to ${MAX_COMPARE_LOCATIONS} locations. Got ${locations.length}. Batch your comparisons.`,
    );
  }

  const year = validateFiscalYear(ctx, args.fiscal_year, "fiscal_year");
  const results: Dict[] = [];

  // Pre-validate everything first so bad input fails before any API call.
  const prepared: [string, string, string | null][] = [];
  locations.forEach((loc, i) => {
    try {
      const city = validateCity(loc.city ?? null, `locations[${i}].city`);
      const state = validateState(loc.state ?? null, `locations[${i}].state`);
      const county = validateCounty(loc.county ?? null, `locations[${i}].county`);
      prepared.push([city, state, county]);
    } catch (error) {
      if (!(error instanceof ValueError)) throw error;
      results.push({location: `${loc.city ?? "?"}, ${loc.state ?? "?"}`, error: error.message});
    }
  });

  for (const [city, state, county] of prepared) {
    // Label rows by the query, not the matched entry.
    const label = `${city}, ${state}`;
    if (OCONUS_STATES.has(state)) {
      results.push({location: label, oconus: true, error: OCONUS_NOTE});
      continue;
    }
    try {
      const [res] = await lookupCity(ctx, city, state, year, county);
      if (res.status === "resolved") {
        const best = res.rate!;
        results.push({
          location: label,
          status: "resolved",
          matched_city: best.city,
          match_type: res.match_type,
          is_standard_rate: best.is_standard_rate,
          lodging_max: best.lodging_max,
          lodging_min: best.lodging_min,
          mie: best.meals,
          max_daily_total: add(best.lodging_max, best.meals),
          seasonal: best.has_seasonal_variation,
        });
      } else if (res.status === "no_data") {
        results.push({location: label, error: "no rates found" + noRatesHint(ctx, year)});
      } else {
        const entry: Dict = {location: label, ...unresolvedPayload(res, city, state)};
        if ("candidates" in entry) {
          entry.candidates = entry.candidates.map((c: Dict) => ({destination: c.destination, max_daily_total: c.max_daily_total}));
        }
        results.push(entry);
      }
    } catch (error) {
      if (!(error instanceof ToolError)) throw error;
      results.push({location: label, error: pySlice(error.message, 200)});
    }
  }

  // Stable, highest first; rows without a total sort as 0.
  const total = (row: Dict) => num(row.max_daily_total ?? 0);
  results.sort((a, b) => total(b) - total(a));
  return {fiscal_year: year, locations: results};
}

type Handler = (ctx: Context, args: Dict) => Promise<Dict>;

export const HANDLERS: Record<string, Handler> = {
  lookup_city_perdiem: lookupCityPerdiem,
  lookup_zip_perdiem: lookupZipPerdiem,
  lookup_state_rates: lookupStateRates,
  get_mie_breakdown: getMieBreakdown,
  estimate_travel_cost: estimateTravelCost,
  compare_locations: compareLocations,
  get_data_status: getDataStatus,
};

export interface CallResult {
  content: {type: "text"; text: string}[];
  structuredContent?: unknown;
  isError: boolean;
}

/**
 * tools/call as the MCP SDK answers it. Every exception a Python tool can
 * raise becomes "Error executing tool <name>: <message>". DeadlineExceeded
 * propagates (HTTP 504, as the container answered); DataUnavailable and
 * unexpected failures become a generic temporary-unavailability error.
 */
export async function callTool(ctx: Context, name: unknown, args: Record<string, unknown>): Promise<CallResult> {
  const handler = typeof name === "string" && Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
  if (!handler) return errorResult(`Unknown tool: ${name}`);
  let data: Dict;
  try {
    data = await handler(ctx, validateArguments(name as string, args));
  } catch (error) {
    if (error instanceof DeadlineExceeded) throw error;
    if (error instanceof ArgumentError || error instanceof ValueError || error instanceof ToolError || error instanceof PythonError) {
      return errorResult(`Error executing tool ${name}: ${error.message}`);
    }
    console.log(JSON.stringify({
      event: "tool_failed", tool: name,
      reason: error instanceof DataUnavailable ? "data_unavailable" : error instanceof Error ? error.name : "unknown",
    }));
    return errorResult(`Error executing tool ${name}: GSA Per Diem data is temporarily unavailable. Try again shortly.`);
  }
  return {content: [{type: "text", text: dumps(data)}], structuredContent: data, isError: false};
}

const errorResult = (text: string): CallResult => ({content: [{type: "text", text}], isError: true});
