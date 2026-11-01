// GSA CALC+'s rules, in one place: how its API reads a query string, which
// records each search mode, filter and exclude matches, how hits are ordered,
// and the fixed parts of its answer's shape. emulator.ts applies these to the
// copy in D1; nothing else in the Worker decides what matches.
//
// Sources: the recorded fixtures (servers/gsa-calc-mcp/tests/fixtures, night of
// 2026-10-10) and GSA's answers to the night-1 probes and full pull
// (deploy/gsa-calc/PROBE_FINDINGS.md, whose "Settled" section records the
// evidence for the choices below). "Unreachable" marks behavior the Python
// server never asks for, emulated so recorded probes compare cleanly.
import {PyFloat, floatRepr, type Py} from "./pyjson.ts";

// ---------- answer shape ----------

export const SHARDS = {total: 5, successful: 5, skipped: 0, failed: 0};
// Elasticsearch's track_total_hits default: hits.total stops at 10,000 ("gte").
export const TRACK_TOTAL_HITS = 10_000;
// index.max_result_window: from + size may not pass 10,000.
export const RESULT_WINDOW = 10_000;
// The aggregations of a search or browse answer, in GSA's key order.
// education_level_counts is left out when nothing matched (fixture graduate_literal_keyword).
export const AGGREGATIONS = ["labor_category", "security_clearance", "histogram_percentiles", "min_years_experience", "worksite",
  "wage_histogram", "education_level", "current_price", "business_size", "wage_stats", "median_price", "education_level_counts"] as const;
// Terms aggregation sizes: labor_category and current_price stop at 500 buckets
// (the whole index has 133,371 titles and 84,741 prices); the other fields have
// fewer values than that (min_years_experience: all 39 listed).
export const TERMS_SIZE: Record<string, number> = {
  labor_category: 500, security_clearance: 500, min_years_experience: 500, worksite: 500, education_level: 500, current_price: 500,
  business_size: 500,
};
// suggest-contains lists at most 100 values (server.py; probes).
export const SUGGEST_SIZE = 100;
export const PERCENTS = [10, 25, 30, 35, 50, 65, 70, 75, 90];
export const MEDIAN_PERCENTS = [50];
// variable_width_histogram: 12 buckets; shard_size and initial_buffer at Elasticsearch's defaults.
export const HISTOGRAM = {buckets: 12, shardSize: 600, initialBuffer: 6000};
// extended_stats sigma for std_deviation_bounds.
export const SIGMA = 2;

// The education_level_counts filters (in this order) and the education_level
// filter: GSA's code -> the education_level words it counts (whole-index
// counts: HS 41,093 = High School + High School Equivalent; "None" and
// "MD DO" belong to no code).
export const EDUCATION_WORDS: Record<string, string[]> = {
  AA: ["Associates"],
  BA: ["Bachelors"],
  HS: ["High School", "High School Equivalent"],
  MA: ["Masters"],
  PHD: ["PhD"],
  TEC: ["Other Tech School or Certification"],
};
// worksite:customer is applied (185,410 = Customer_Facility); other values,
// Customer_Facility included, are ignored. contractor by analogy. Unreachable.
const WORKSITE_WORDS: Record<string, string> = {customer: "Customer_Facility", contractor: "Contractor_Facility"};

// ---------- reading the query string ----------

export const SEARCH_FIELDS = ["labor_category", "vendor_name", "idv_piid"] as const;
// Fields GSA sorts by, with the records column and how its sort value is written.
export const ORDERINGS: Record<string, {column: string; kind: "float" | "int" | "text"}> = {
  current_price: {column: "price", kind: "float"},
  labor_category: {column: "labor_category", kind: "text"},
  vendor_name: {column: "vendor_name", kind: "text"},
  education_level: {column: "education_level", kind: "text"},
  min_years_experience: {column: "min_years_experience", kind: "int"},
  next_year_price: {column: "next_year_price", kind: "float"},
  idv_piid: {column: "idv_piid", kind: "text"},
  business_size: {column: "business_size", kind: "text"},
};

export type Mode =
  | {kind: "browse"}
  | {kind: "keyword"; text: string}
  | {kind: "search"; field: string; value: string}
  | {kind: "suggest"; field: string; term: string};

export interface Filter {
  field: string;
  value: string;
}

export interface Query {
  mode: Mode;
  filters: Filter[];
  page: number;
  pageSize: number;
  orderings: {field: string; desc: boolean}[];
  exclude: string[];
  // No keyword, search or filter (a match_all): GSA then also sorts by _score, all 1.0.
  scoreSort: boolean;
}

/** GSA's error answer to a query it refuses (406 with an empty body, probes). */
export interface Refusal {
  status: number;
  text: string;
}
const REFUSED: Refusal = {status: 406, text: ""};

/** "field:value" as GSA splits it: the value stops at the next colon (fixture
 * delimiter_exact_before and probe search=labor_category:Engineer 1: Sr. ...: 95 = "Engineer 1"). */
function fieldValue(text: string): [string, string] {
  const parts = text.split(":");
  return [parts[0], parts[1] ?? ""];
}

const WHOLE = /^\d+$/;

/** The query string a client sent, as GSA reads it, or GSA's refusal. */
export function parseQuery(qs: string): Query | Refusal {
  const params = new URLSearchParams(qs);
  // The last value of a repeated parameter (Django's QueryDict.get); the same
  // filter field twice: the last one wins (business_size:S then :O = O's 107,309).
  const last = (name: string) => params.getAll(name).at(-1) ?? null;
  const byField = new Map<string, string>();
  for (const text of params.getAll("filter")) {
    const [field, value] = fieldValue(text);
    byField.delete(field);
    byField.set(field, value);
  }
  const filters = [...byField].map(([field, value]) => ({field, value}));
  const keyword = last("keyword");
  const search = last("search");
  const suggest = last("suggest-contains");
  let mode: Mode = {kind: "browse"};
  // Precedence when several are sent (unreachable: the Python server sends one).
  if (keyword !== null) mode = {kind: "keyword", text: keyword};
  else if (search !== null) {
    const [field, value] = fieldValue(search);
    mode = {kind: "search", field, value};
  } else if (suggest !== null && !filters.length) {
    // With a filter GSA drops the suggestion and answers a plain search (probe: business_size:S's 244,025). Unreachable.
    const [field, term] = fieldValue(suggest);
    mode = {kind: "suggest", field, term};
  }
  const pageText = last("page") ?? "1";
  const sizeText = last("page_size") ?? "100";
  if (!WHOLE.test(pageText) || !WHOLE.test(sizeText)) return REFUSED;
  const page = Number(pageText);
  const pageSize = Number(sizeText);
  // page 0 and page * page_size past 10,000 are refused; page_size 0 and 501 are answered.
  if (page < 1 || page * pageSize > RESULT_WINDOW) return REFUSED;
  // ordering/sort pairs, applied in order. With several pairs GSA leaves
  // idv_piid out (the pull's 6 pairs sort by 5 values); sort=desc alone sorts by
  // current_price descending.
  const sorts = params.getAll("sort");
  let orderings: Query["orderings"] = [];
  for (const [i, field] of params.getAll("ordering").entries()) {
    if (!Object.hasOwn(ORDERINGS, field)) return REFUSED;
    orderings.push({field, desc: (sorts[i] ?? "asc").toLowerCase() === "desc"});
  }
  if (orderings.length > 1) orderings = orderings.filter(o => o.field !== "idv_piid");
  if (!orderings.length) orderings.push({field: "current_price", desc: (sorts[0] ?? "asc").toLowerCase() === "desc"});
  const exclude = (last("exclude") ?? "").split("|").filter(Boolean);
  const scoreSort = mode.kind === "browse" && !filters.length && !exclude.length;
  return {mode, filters, page, pageSize, orderings, exclude, scoreSort};
}

// ---------- matching ----------

/** Text as GSA compares it: lowercased. terms.folded holds the same (the
 * loader writes Python's str.lower()); change both together. */
export const fold = (text: string) => text.toLowerCase();

// GSA indexes labor_category, vendor_name and idv_piid with a 2-4 character
// n-gram tokenizer over the whole lowercased value (spaces and punctuation are
// ordinary characters), and analyzes the keyword the same way with every gram
// required (operator AND), field by field. Settled against all 61 keyword
// probes: max gram 4, per field (max 3 or across fields miss up to 276 records).
export const NGRAM = {min: 2, max: 4};

/** The grams a keyword (or suggest-contains term) needs in one field value: its
 * longest grams (min(4, length) characters), which hold all the shorter ones.
 * null for a 1-character term, which matches nothing. `*` is an ordinary character. */
export function keywordGrams(text: string): string[] | null {
  const chars = [...fold(text)];
  if (chars.length < NGRAM.min) return null;
  const size = Math.min(NGRAM.max, chars.length);
  return [...new Set(Array.from({length: chars.length - size + 1}, (_, i) => chars.slice(i, i + size).join("")))];
}

// The field's values holding every gram (one JSON array of grams per statement,
// so any keyword length stays within D1's 100 bound parameters).
const termsHolding = (field: string) =>
  `SELECT value FROM terms t WHERE field = '${field}' AND NOT EXISTS (SELECT 1 FROM json_each(?) AS g WHERE instr(t.folded, g.value) = 0)`;

export interface Where {
  sql: string;
  values: unknown[];
}

// The night the Worker reads: records with v_from <= current < v_to.
const CURRENT = "(SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'current')";
const isSearchField = (field: string) => (SEARCH_FIELDS as readonly string[]).includes(field);

/** The SQL condition (on records r) for the records a query matches, with its bound values. */
export function where(query: Query): Where {
  const parts = [`r.v_from <= ${CURRENT}`, `${CURRENT} < r.v_to`];
  const values: unknown[] = [];
  const {mode} = query;
  if (mode.kind === "keyword") {
    // Any of the three fields holds every gram.
    const grams = keywordGrams(mode.text);
    if (grams) {
      parts.push(`r.rid IN (${SEARCH_FIELDS.map(f => `SELECT rid FROM records WHERE ${f} IN (${termsHolding(f)})`).join(" UNION ")})`);
      values.push(...SEARCH_FIELDS.map(() => JSON.stringify(grams)));
    } else parts.push("0");
  } else if (mode.kind === "search") {
    // Exact and case-sensitive on one field (probes: lowercase or a trailing space finds 0).
    if (isSearchField(mode.field)) {
      parts.push(`r.${mode.field} = ?`);
      values.push(mode.value);
    } else parts.push("0");
  } else if (mode.kind === "suggest") {
    // The keyword rule on one field (probe suggest-contains=vendor_name:& finds 0).
    const grams = keywordGrams(mode.term);
    if (isSearchField(mode.field) && grams) {
      parts.push(`r.${mode.field} IN (${termsHolding(mode.field)})`);
      values.push(JSON.stringify(grams));
    } else parts.push("0");
  }
  for (const filter of query.filters) {
    const condition = filterCondition(filter);
    if (!condition) continue;
    parts.push(condition.sql);
    values.push(...condition.values);
  }
  if (query.exclude.length) {
    // _ids are decimal strings; anything else can't name a record.
    const ids = query.exclude.filter(id => /^(0|[1-9]\d{0,15})$/.test(id)).map(Number);
    parts.push("r.id NOT IN (SELECT value FROM json_each(?))");
    values.push(JSON.stringify(ids));
  }
  return {sql: parts.join(" AND "), values};
}

/** Two numbers "lo,hi", or null. */
function bounds(text: string): [number, number] | null {
  const [lo, hi, ...rest] = text.split(",");
  if (rest.length || lo === undefined || hi === undefined) return null;
  const pair = [Number(lo.trim()), Number(hi.trim())] as [number, number];
  return lo.trim() && hi.trim() && pair.every(Number.isFinite) ? pair : null;
}

/** A GLOB pattern (on '#' || lower(sin) || '#', sin stored as ',' || list || ',')
 * for one SIN code among the tokens Elasticsearch's standard tokenizer makes of
 * the list: it splits at commas except a comma between two digits, so in
 * "541620,561210FAC" 541620 is not a token, while in "561210FAC,541620" it is.
 * Reproduces GSA's count for every probed code (541611 29,133; 54161 370;
 * 54151S 129,043; 541330ENG 30,879; 541620 3,488). */
export function sinPattern(code: string): string | null {
  const c = code.toLowerCase();
  if (!c) return null;
  const escaped = c.replace(/[*?[]/g, ch => `[${ch}]`);
  const digit = (ch: string | undefined) => ch !== undefined && ch >= "0" && ch <= "9";
  return `${digit(c[0]) ? "*[^0-9]," : "*,"}${escaped}${digit(c.at(-1)) ? ",[^0-9]*" : ",*"}`;
}

/** One filter=field:value as a condition; null where GSA ignores it. */
function filterCondition({field, value}: Filter): Where | null {
  switch (field) {
    case "price_range": {
      // A range query on GSA's float field: the bounds round to float32 and are inclusive (probes at 28.9).
      const b = bounds(value);
      return b ? {sql: "r.price >= ? AND r.price <= ?", values: [Math.fround(b[0]), Math.fround(b[1])]} : {sql: "0", values: []};
    }
    case "experience_range": {
      const b = bounds(value);
      return b ? {sql: "r.min_years_experience >= ? AND r.min_years_experience <= ?", values: b} : {sql: "0", values: []};
    }
    case "min_years_experience":
      // An exact match (52,604 for 5, as experience_range:5,5). Unreachable.
      return WHOLE.test(value) ? {sql: "r.min_years_experience = ?", values: [Number(value)]} : null;
    case "education_level": {
      // Codes, pipe = OR; unknown codes ("ba", "Bachelors") are ignored, and a filter of none is no filter.
      const words = value.split("|").flatMap(code => EDUCATION_WORDS[code] ?? []);
      return words.length ? {sql: "r.education_level IN (SELECT value FROM json_each(?))", values: [JSON.stringify(words)]} : null;
    }
    case "business_size":
      // Exact (business_size:s finds 0).
      return {sql: "r.business_size = ?", values: [value]};
    case "security_clearance":
      // yes/no only; "true" and "Yes" are ignored.
      if (value === "yes" || value === "no") return {sql: "r.security_clearance = ?", values: [value === "yes" ? 1 : 0]};
      return null;
    case "sin": {
      const pattern = sinPattern(value);
      return pattern ? {sql: "('#' || lower(r.sin) || '#') GLOB ?", values: [pattern]} : {sql: "0", values: []};
    }
    case "worksite":
      return Object.hasOwn(WORKSITE_WORDS, value) ? {sql: "r.worksite = ?", values: [WORKSITE_WORDS[value]]} : null;
    default:
      // vendor_name, labor_category (server.py notes) and anything else.
      return null;
  }
}

// ---------- ordering ----------

/** ORDER BY for the hits: each ordering pair in turn, missing values last
 * (Elasticsearch's default), then _id ascending. GSA's own ties come back in
 * shard order, so hit order is compared up to ties. Text sorts by code point. */
export function orderBy(query: Query): string {
  const keys = query.orderings.map(({field, desc}) => {
    const column = `r.${ORDERINGS[field].column}`;
    return `${column} IS NULL, ${column} ${desc ? "DESC" : "ASC"}`;
  });
  return [...keys, "r.id ASC"].join(", ");
}

/** A hit's sort values: the ordering fields' values as GSA writes them. A float
 * field gives its float32 value as Java's Float.toString prints it (the source
 * value, for prices of up to 7 significant digits); a match_all adds _score
 * (1.0, the whole-index probes: [20.1, 1.0]). Missing values are null (no record lacks a price). */
export function sortValues(query: Query, row: Record<string, any>): Py[] {
  const values: Py[] = query.orderings.map(({field}) => {
    const {column, kind} = ORDERINGS[field];
    const value = row[column];
    if (value === null || value === undefined) return null;
    if (kind === "float") return new PyFloat(Number(float32Text(value)));
    return value;
  });
  if (query.scoreSort) values.push(new PyFloat(1));
  return values;
}

// ---------- aggregation keys ----------

/** The shortest decimal that reads back as the same float32 (Java's Float.toString digits). */
export function float32Text(value: number): string {
  const f = Math.fround(value);
  if (!Number.isFinite(f) || f === 0) return floatRepr(f);
  for (let digits = 1; digits <= 9; digits++) {
    const text = f.toPrecision(digits);
    if (Math.fround(Number(text)) === f) return floatRepr(Number(text));
  }
  return floatRepr(f);
}

/** A terms bucket key as GSA writes it: strings throughout. current_price keys
 * are the float32 price as Java prints it ("51.8", whole dollars "110.0" as in
 * fixture approximate_population_control), security_clearance "true"/"false",
 * min_years_experience the number's digits. */
export function termsKey(field: string, value: unknown): string {
  if (field === "current_price") return float32Text(value as number);
  if (field === "security_clearance") return value ? "true" : "false";
  return String(value);
}

/** _source with the night's _timestamp (GSA sets one value per nightly build).
 * The loader keeps the key in its place when it stores _source; if it is
 * missing, it goes where GSA puts it: before cont_beg_dtg, else last. */
export function withTimestamp(source: Record<string, Py>, timestamp: string | null): Record<string, Py> {
  if (timestamp === null) return source;
  if (Object.hasOwn(source, "_timestamp")) {
    source._timestamp = timestamp;
    return source;
  }
  const out: Record<string, Py> = {};
  for (const [key, value] of Object.entries(source)) {
    if (key === "cont_beg_dtg") out._timestamp = timestamp;
    out[key] = value;
  }
  if (!Object.hasOwn(out, "_timestamp")) out._timestamp = timestamp;
  return out;
}
