// GSA CALC+'s rules, in one place: how its API reads a query string, which
// records each search mode, filter and exclude matches, how hits are ordered,
// and the fixed parts of its answer's shape. emulator.ts applies these to the
// copy in D1; nothing else in the Worker decides what matches.
//
// Status: PROVISIONAL where marked. They come from the recorded fixtures
// (servers/gsa-calc-mcp/tests/fixtures, night of 2026-10-10) and the server's
// own live-verified notes. deploy/gsa-calc/PROBE_FINDINGS.md (GSA's answers to
// the probe queries in scripts/probes.txt) overrides anything here.
import {PyFloat, floatRepr, type Py} from "./pyjson.ts";

// ---------- answer shape ----------

export const SHARDS = {total: 5, successful: 5, skipped: 0, failed: 0};
// Elasticsearch's track_total_hits default: hits.total stops at 10,000 ("gte").
export const TRACK_TOTAL_HITS = 10_000;
// index.max_result_window: from + size may not pass 10,000.
export const RESULT_WINDOW = 10_000;
export const MAX_PAGE_SIZE = 500;
// The aggregations of a search or browse answer, in GSA's key order.
// education_level_counts is left out when nothing matched (fixture graduate_literal_keyword).
export const AGGREGATIONS = ["labor_category", "security_clearance", "histogram_percentiles", "min_years_experience", "worksite",
  "wage_histogram", "education_level", "current_price", "business_size", "wage_stats", "median_price", "education_level_counts"] as const;
// Terms aggregation sizes. labor_category and current_price show 500 buckets
// with sum_other_doc_count in the fixtures; min_years_experience shows 30, so
// the others are above Elasticsearch's default of 10. PROVISIONAL: 500 for all.
export const TERMS_SIZE: Record<string, number> = {
  labor_category: 500, security_clearance: 500, min_years_experience: 500, worksite: 500, education_level: 500, current_price: 500,
  business_size: 500,
};
// suggest-contains lists at most 100 values (server.py).
export const SUGGEST_SIZE = 100;
export const PERCENTS = [10, 25, 30, 35, 50, 65, 70, 75, 90];
export const MEDIAN_PERCENTS = [50];
// variable_width_histogram: 12 buckets; shard_size and initial_buffer at Elasticsearch's defaults.
export const HISTOGRAM = {buckets: 12, shardSize: 600, initialBuffer: 6000};
// extended_stats sigma for std_deviation_bounds.
export const SIGMA = 2;

// The education_level_counts filters (in this order) and the education_level
// filter: GSA's code -> the education_level words it counts. From the fixtures:
// HS counts "High School" and "High School Equivalent"; TEC is "Other Tech
// School or Certification". PROVISIONAL until the whole-index vocabulary is read.
export const EDUCATION_WORDS: Record<string, string[]> = {
  AA: ["Associates"],
  BA: ["Bachelors"],
  HS: ["High School", "High School Equivalent"],
  MA: ["Masters"],
  PHD: ["PhD"],
  TEC: ["Other Tech School or Certification"],
};

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
}

/** GSA's error answer to a query it refuses. */
export interface Refusal {
  status: number;
  text: string;
}

// PROVISIONAL error bodies (the Python server's own checks keep its calls from these).
const refuse = (status: number, detail: string): Refusal => ({status, text: JSON.stringify({detail})});

/** "field:value" as GSA splits it: the value stops at the next colon (fixture
 * delimiter_exact_before: "Engineer 1: Sr. ..." searched "Engineer 1"). */
function fieldValue(text: string): [string, string] {
  const parts = text.split(":");
  return [parts[0], parts[1] ?? ""];
}

const WHOLE = /^\d+$/;

/** The query string a client sent, as GSA reads it, or GSA's refusal. */
export function parseQuery(qs: string): Query | Refusal {
  const params = new URLSearchParams(qs);
  // Django's QueryDict.get: the last value of a repeated parameter. PROVISIONAL.
  const last = (name: string) => params.getAll(name).at(-1) ?? null;
  const keyword = last("keyword");
  const search = last("search");
  const suggest = last("suggest-contains");
  let mode: Mode = {kind: "browse"};
  // PROVISIONAL precedence when several are sent (the Python server never does).
  if (keyword !== null) mode = {kind: "keyword", text: keyword};
  else if (search !== null) {
    const [field, value] = fieldValue(search);
    mode = {kind: "search", field, value};
  } else if (suggest !== null) {
    const [field, term] = fieldValue(suggest);
    mode = {kind: "suggest", field, term};
  }
  const filters = params.getAll("filter").map(text => {
    const [field, value] = fieldValue(text);
    return {field, value};
  });
  const pageText = last("page") ?? "1";
  const sizeText = last("page_size") ?? "100";
  if (!WHOLE.test(pageText) || !WHOLE.test(sizeText)) return refuse(406, "Invalid page.");
  const page = Number(pageText);
  const pageSize = Number(sizeText);
  if (page < 1 || pageSize < 1 || pageSize > MAX_PAGE_SIZE) return refuse(406, "Invalid page.");
  if (page * pageSize > RESULT_WINDOW) return refuse(406, "Result window is too large.");
  // ordering/sort pairs, applied in order (the loader sends several).
  const sorts = params.getAll("sort");
  const orderings: Query["orderings"] = [];
  for (const [i, field] of params.getAll("ordering").entries()) {
    if (!Object.hasOwn(ORDERINGS, field)) return refuse(406, "Invalid ordering.");
    orderings.push({field, desc: (sorts[i] ?? "asc").toLowerCase() === "desc"});
  }
  if (!orderings.length) orderings.push({field: "current_price", desc: false});
  const exclude = (last("exclude") ?? "").split("|").filter(Boolean);
  return {mode, filters, page, pageSize, orderings, exclude};
}

// ---------- matching ----------

/** Text as GSA compares it case-insensitively; terms.folded holds the same
 * (the loader writes Python's str.lower()). PROVISIONAL. */
export const fold = (text: string) => text.toLowerCase();

/** A LIKE pattern for "contains term", where * matches any run of characters
 * (keyword and suggest-contains). PROVISIONAL: case-insensitive substring of the
 * whole phrase; ? and every other character literal. */
export function containsPattern(term: string): string {
  const escaped = fold(term).replace(/[\\%_]/g, ch => `\\${ch}`).replaceAll("*", "%");
  return `%${escaped}%`;
}

const termsHaving = (field: string) =>
  `SELECT value FROM terms WHERE field = '${field}' AND folded LIKE ? ESCAPE '\\'`;

export interface Where {
  sql: string;
  values: unknown[];
}

// The night the Worker reads: records with v_from <= current < v_to.
const CURRENT = "(SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'current')";

/** The SQL condition (on records r) for the records a query matches, with its bound values. */
export function where(query: Query): Where {
  const parts = [`r.v_from <= ${CURRENT}`, `${CURRENT} < r.v_to`];
  const values: unknown[] = [];
  const {mode} = query;
  if (mode.kind === "keyword") {
    // Any of the three fields contains the phrase.
    const pattern = containsPattern(mode.text);
    parts.push(`r.rid IN (${SEARCH_FIELDS.map(f => `SELECT rid FROM records WHERE ${f} IN (${termsHaving(f)})`).join(" UNION ")})`);
    values.push(pattern, pattern, pattern);
  } else if (mode.kind === "search") {
    // Exact, case-sensitive match on one field. PROVISIONAL; an unknown field matches nothing.
    if ((SEARCH_FIELDS as readonly string[]).includes(mode.field)) {
      parts.push(`r.${mode.field} = ?`);
      values.push(mode.value);
    } else parts.push("0");
  } else if (mode.kind === "suggest") {
    if ((SEARCH_FIELDS as readonly string[]).includes(mode.field)) {
      parts.push(`r.${mode.field} IN (${termsHaving(mode.field)})`);
      values.push(containsPattern(mode.term));
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

/** One filter=field:value as a condition; null where GSA ignores it. PROVISIONAL
 * except worksite (ignored, live-verified) and education_level (pipe = OR, fixtures). */
function filterCondition({field, value}: Filter): Where | null {
  switch (field) {
    case "price_range": {
      // A range query on GSA's float field: the bounds round to float32 and are inclusive.
      const b = bounds(value);
      return b ? {sql: "r.price >= ? AND r.price <= ?", values: [Math.fround(b[0]), Math.fround(b[1])]} : {sql: "0", values: []};
    }
    case "experience_range": {
      const b = bounds(value);
      return b ? {sql: "r.min_years_experience >= ? AND r.min_years_experience <= ?", values: b} : {sql: "0", values: []};
    }
    case "education_level": {
      const words = value.split("|").flatMap(code => EDUCATION_WORDS[code.trim()] ?? []);
      return {sql: `r.education_level IN (SELECT value FROM json_each(?))`, values: [JSON.stringify(words)]};
    }
    case "business_size":
      return {sql: "r.business_size = ?", values: [value]};
    case "security_clearance":
      if (value === "yes" || value === "no") return {sql: "r.security_clearance = ?", values: [value === "yes" ? 1 : 0]};
      return null;
    case "sin":
      // A whole code inside the comma list (records.sin is ',' || list || ','); ASCII case-insensitive.
      return {sql: "r.sin LIKE ? ESCAPE '\\'", values: [`%,${value.replace(/[\\%_]/g, ch => `\\${ch}`)},%`]};
    default:
      // worksite (live-verified), vendor_name and labor_category (server.py notes) and anything else.
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
 * value, for prices of up to 7 significant digits). Missing values are null. PROVISIONAL. */
export function sortValues(query: Query, row: Record<string, any>): Py[] {
  return query.orderings.map(({field}) => {
    const {column, kind} = ORDERINGS[field];
    const value = row[column];
    if (value === null || value === undefined) return null;
    if (kind === "float") return new PyFloat(Number(float32Text(value)));
    return value;
  });
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
