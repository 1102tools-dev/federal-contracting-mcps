// The hosted GSA CALC+ tools: a line-by-line port of the Python server
// (servers/gsa-calc-mcp/src/gsa_calc_mcp/server.py), with the same checks in
// the same order, the same messages and the same keys. Where Python calls
// _get(query string) on GSA's API, these call emulate() on the copy in D1
// (emulator.ts), which answers that query string with GSA's body.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {ToolError, validateArgs, type PyInt} from "./args.ts";
import {casefold} from "./casefold.ts";
import {emulate, type Database, type EmulatorOptions} from "./emulator.ts";
import {PyFloat, floatRepr, intStr, repr, round, type Py} from "./pyjson.ts";
import {SPACE, cpLen, escapeRegex, strip} from "./text.ts";
import {
  LOW_SAMPLE_MIN_RATES, MAX_PAGE_SIZE, clamp, clampTextLen, fail, showFloat, stripOrNone, validateEducationLevel, validateEsWindow,
  validateExperienceRange, validateNoControlChars, validateOrdering, validatePriceRange, validateSin, validateSort,
  validateWafSafe, validateWorksite,
} from "./validate.ts";

export {type Database};

/** The reviewed tool definitions, sorted by name. */
export const TOOLS = [...CONTRACT].sort((a, b) => (a.name < b.name ? -1 : 1));

const SERVICE = "GSA CALC+";
type Obj = Record<string, any>;
type Handler = (db: Database, args: Record<string, unknown>, options: EmulatorOptions) => Promise<Py>;

// ---------- defensive response parsing (server.py) ----------

const isDict = (value: unknown): value is Obj =>
  typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype;
const safeDict = (value: unknown): Obj => (isDict(value) ? value : {});
const asList = (value: unknown): unknown[] => (value === null || value === undefined ? [] : Array.isArray(value) ? value : isDict(value) ? [value] : []);
const get = (d: Obj, key: string, fallback: unknown = null) => (Object.hasOwn(d, key) ? d[key] : fallback);

/** A Python int (bool excluded): a whole JS number or a bigint. */
const isInt = (v: unknown): v is number | bigint => typeof v === "bigint" || (typeof v === "number" && Number.isInteger(v));
/** A Python float: PyFloat, or a JS number with a fraction. */
const isFloat = (v: unknown): v is number | PyFloat => v instanceof PyFloat || (typeof v === "number" && !Number.isInteger(v));
const num = (v: number | bigint | PyFloat): number => (v instanceof PyFloat ? v.value : Number(v));

/** (key, doc_count) from a bucket item, or null. */
function safeBucketKey(b: unknown): [any, any] | null {
  if (!isDict(b)) return null;
  const key = get(b, "key");
  const count = get(b, "doc_count");
  if (key === null || count === null) return null;
  return [key, count];
}

// Python float() of a str: whitespace stripped, underscores between digits, inf/infinity/nan.
const PY_FLOAT = /^[+-]?(?:inf|infinity|nan|(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?)$/i;

/** _safe_number: a real number (the value itself, so floats stay floats), rejecting None, bools, NaN and Inf. */
function safeNumber(value: unknown): number | bigint | PyFloat | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (typeof value === "string") {
    const text = strip(value);
    if (!PY_FLOAT.test(text)) return null;
    const body = text.replace(/^[+-]/, "").toLowerCase();
    const parsed = body === "nan" ? NaN : body.startsWith("inf") ? Infinity : Number(text.replaceAll("_", ""));
    return Number.isFinite(parsed) ? new PyFloat(parsed) : null;
  }
  if (!(typeof value === "number" || typeof value === "bigint" || value instanceof PyFloat)) return null;
  if (isFloat(value) && !Number.isFinite(num(value))) return null;
  return value;
}

/** round(value, places) as Python does it: an int stays an int, a float rounds half-even on its binary value. */
function pyRound(value: number | bigint | PyFloat, places: number): number | bigint | PyFloat {
  return isFloat(value) ? new PyFloat(round(num(value), places)) : value;
}
const fl = (x: number) => new PyFloat(x);

// ---------- GSA errors (_get, _format_error) ----------

const HTML_ERROR = /<(?:!doctype|html)/i;
const TITLE = /<title[^>]*>([\s\S]*?)<\/title>/i;
const H1 = /<h1[^>]*>([\s\S]*?)<\/h1>/i;

/** _clean_error_body: HTML error pages reduced to their title and heading. */
function cleanErrorBody(text: string): string {
  if (!text) return "";
  if (!HTML_ERROR.test(text)) return [...text].slice(0, 400).join("");
  const pieces: string[] = [];
  const t = TITLE.exec(text);
  if (t) pieces.push(strip(t[1]));
  const h = H1.exec(text);
  if (h && (!t || strip(h[1]) !== strip(t[1]))) pieces.push(strip(h[1]));
  return pieces.length ? pieces.join(" - ") : "upstream returned HTML error page";
}

const unavailable = (reason: string) =>
  `The government's ${SERVICE} API isn't responding right now (${reason}). This is on the government's side; try again in a few minutes.`;

function formatError(status: number, body: string): string {
  const cleaned = cleanErrorBody(body);
  if (status === 403) {
    return "HTTP 403: Forbidden. GSA's web application firewall blocked this request. This typically happens when the query contains characters "
      + "that look like injection attempts (single quotes, angle brackets, path traversal sequences). Remove special characters from your "
      + "search terms and try again.";
  }
  if (status === 406) {
    return "HTTP 406: Not Acceptable. Common causes: (1) keyword or query string is too long; (2) page number is out of valid range; (3) ordering "
      + `field name is invalid. Valid ordering: current_price, labor_category, vendor_name, education_level, min_years_experience, next_year_price, idv_piid, business_size. API response: ${cleaned}`;
  }
  if (status === 429) return `The government's ${SERVICE} API is limiting requests right now. This is on the government's side. Wait a few minutes before trying again.`;
  if (status >= 500) return unavailable(`error ${status}`);
  if (status === 400) return `HTTP 400: Bad request. Check filter format (field:value) and page_size (max 500). API response: ${cleaned}`;
  return `HTTP ${status}: ${cleaned}`;
}

/** _get: GSA's answer to a query string, here from the copy. */
async function getData(db: Database, qs: string, options: EmulatorOptions): Promise<Obj> {
  const answer = await emulate(db, qs, options);
  if (!("body" in answer)) throw new ToolError(formatError(answer.status, [...answer.text].slice(0, 500).join("")));
  return answer.body;
}

// ---------- filter and query helpers ----------

interface FilterArgs {
  education_level?: string | null;
  experience_min?: PyInt | null;
  experience_max?: PyInt | null;
  price_min?: number | null;
  price_max?: number | null;
  business_size?: string | null;
  security_clearance?: string | null;
  sin?: string | null;
}

/** _build_filters: the field:value pieces (values are encoded later). */
function buildFilters(a: FilterArgs): string[] {
  const filters: string[] = [];
  const int = (v: PyInt) => intStr(v);
  if (a.education_level) filters.push(`education_level:${a.education_level}`);
  // experience_range, not min_years_experience (an exact term match on GSA).
  const [emin, emax] = [a.experience_min ?? null, a.experience_max ?? null];
  if (emin !== null && emax !== null) filters.push(`experience_range:${int(emin)},${int(emax)}`);
  else if (emin !== null) filters.push(`experience_range:${int(emin)},999`);
  else if (emax !== null) filters.push(`experience_range:0,${int(emax)}`);
  const [pmin, pmax] = [a.price_min ?? null, a.price_max ?? null];
  if (pmin !== null && pmax !== null) filters.push(`price_range:${floatRepr(pmin)},${floatRepr(pmax)}`);
  else if (pmin !== null) filters.push(`price_range:${floatRepr(pmin)},999999`);
  else if (pmax !== null) filters.push(`price_range:0,${floatRepr(pmax)}`);
  if (a.business_size) filters.push(`business_size:${a.business_size}`);
  if (a.security_clearance) filters.push(`security_clearance:${a.security_clearance}`);
  if (a.sin) filters.push(`sin:${a.sin}`);
  return filters;
}

const ALWAYS_SAFE = /[A-Za-z0-9_.\-~]/;

/** urllib.parse.quote_plus: UTF-8, uppercase hex, spaces as '+'. Lone
 * surrogates raise UnicodeEncodeError, as in Python. */
export function quotePlus(text: string): string {
  const points = [...text];
  const lone = points.findIndex(ch => ch.length === 1 && /[\ud800-\udfff]/.test(ch));
  if (lone >= 0) {
    let end = lone;
    while (end + 1 < points.length && points[end + 1].length === 1 && /[\ud800-\udfff]/.test(points[end + 1])) end++;
    const which = end === lone
      ? `character '\\u${points[lone].charCodeAt(0).toString(16)}' in position ${lone}`
      : `characters in position ${lone}-${end}`;
    throw new ToolError(`'utf-8' codec can't encode ${which}: surrogates not allowed`);
  }
  let out = "";
  for (const ch of points) {
    if (ch === " ") out += "+";
    else if (ALWAYS_SAFE.test(ch)) out += ch;
    else for (const byte of new TextEncoder().encode(ch)) out += `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
  }
  return out;
}

interface QueryArgs {
  keyword?: string | null;
  search_field?: string | null;
  search_value?: string | null;
  suggest_field?: string | null;
  suggest_term?: string | null;
  filters?: string[] | null;
  page?: number;
  page_size?: number;
  ordering?: string;
  sort?: string;
  exclude?: string | null;
}

/** _build_query_string: the full query string, every value URL-encoded. */
export function buildQueryString(q: QueryArgs): string {
  const {keyword = null, search_field = null, search_value = null, suggest_field = null, suggest_term = null, filters = null,
    page = 1, page_size = 100, ordering = "current_price", sort = "asc", exclude = null} = q;
  const parts: string[] = [];
  // Precedence: keyword > search > suggest. Combinations are refused.
  const modes = Number(keyword !== null) + Number(Boolean(search_field && search_value)) + Number(Boolean(suggest_field && suggest_term));
  if (modes > 1) {
    fail("Only one search mode allowed per query: keyword, search (field+value), or suggest (field+term). Combining silently drops the lower-priority modes.");
  }
  if (keyword !== null) parts.push(`keyword=${quotePlus(keyword)}`);
  else if (search_field && search_value) parts.push(`search=${search_field}:${quotePlus(search_value)}`);
  else if (suggest_field && suggest_term) parts.push(`suggest-contains=${suggest_field}:${quotePlus(suggest_term)}`);
  for (const f of filters ?? []) {
    if (!f) continue;
    const colon = f.indexOf(":");
    if (colon >= 0) parts.push(`filter=${f.slice(0, colon)}:${quotePlus(f.slice(colon + 1))}`);
    else parts.push(`filter=${quotePlus(f)}`);
  }
  parts.push(`page=${page}`);
  parts.push(`page_size=${Math.min(page_size, MAX_PAGE_SIZE)}`);
  parts.push(`ordering=${quotePlus(ordering)}`);
  parts.push(`sort=${quotePlus(sort)}`);
  if (exclude) parts.push(`exclude=${quotePlus(exclude)}`);
  return parts.join("&");
}

// ---------- statistics from a response ----------

/** _extract_stats: key statistics from the aggregations; never throws. */
function extractStats(data: unknown): Obj {
  const d = safeDict(data);
  const aggs = safeDict(get(d, "aggregations"));
  const wageStats = safeDict(get(aggs, "wage_stats"));
  const percentiles = safeDict(get(safeDict(get(aggs, "histogram_percentiles")), "values"));
  const edCounts = asList(get(safeDict(get(aggs, "education_level_counts")), "buckets"));
  const bizSize = asList(get(safeDict(get(aggs, "business_size")), "buckets"));
  // Counts only: GSA ignores a worksite filter, but the counts show the mix.
  const worksites = asList(get(safeDict(get(aggs, "worksite")), "buckets"));
  const stdBounds = safeDict(get(wageStats, "std_deviation_bounds"));

  const hits = safeDict(get(d, "hits"));
  const hitsTotal = get(hits, "total");
  let totalValue: unknown;
  let capped: boolean;
  if (isDict(hitsTotal)) {
    totalValue = get(hitsTotal, "value", 0);
    capped = get(hitsTotal, "relation") === "gte";
  } else if (isInt(hitsTotal) || typeof hitsTotal === "boolean") {
    // ES 6 legacy format: total is just an int.
    totalValue = hitsTotal;
    capped = false;
  } else {
    totalValue = 0;
    capped = false;
  }
  const wageCount = get(wageStats, "count");
  const trueCount = isInt(wageCount) || typeof wageCount === "boolean" ? wageCount : totalValue;

  const roundOrNone = (v: unknown) => {
    const n = safeNumber(v);
    return n !== null ? pyRound(n, 2) : null;
  };
  const bucketDict = (buckets: unknown[]) => {
    const out = new Map<string, Py>();
    for (const b of buckets) {
      const pair = safeBucketKey(b);
      if (pair !== null) out.set(pair[0], pair[1]);
    }
    return out;
  };
  // Percentile keys are "10.0" strings in GSA's answer.
  const pct = (key: string) => (Object.hasOwn(percentiles, key) ? safeNumber(percentiles[key]) : null);
  // avg - 2 sigma goes negative on wide populations; floor it at $0 and say so.
  const outlierBounds: Obj = {lower: safeNumber(get(stdBounds, "lower")), upper: safeNumber(get(stdBounds, "upper"))};
  if (outlierBounds.lower !== null && num(outlierBounds.lower) < 0) {
    outlierBounds.lower = 0;
    outlierBounds.lower_clamped_to_zero = true;
  }
  return {
    total_rates: trueCount !== null ? trueCount : 0,
    hits_capped: capped,
    min_rate: safeNumber(get(wageStats, "min")),
    max_rate: safeNumber(get(wageStats, "max")),
    avg_rate: roundOrNone(get(wageStats, "avg")),
    std_deviation: roundOrNone(get(wageStats, "std_deviation")),
    percentiles: {p10: pct("10.0"), p25: pct("25.0"), p50_median: pct("50.0"), p75: pct("75.0"), p90: pct("90.0")},
    outlier_bounds_2sigma: outlierBounds,
    education_breakdown: bucketDict(edCounts),
    business_size_breakdown: bucketDict(bizSize),
    worksite_breakdown: bucketDict(worksites),
  };
}

/** _title_summary: labor category titles behind a result (GSA lists at most 500). */
function titleSummary(data: unknown, topN: number): Obj {
  const agg = safeDict(get(safeDict(get(safeDict(data), "aggregations")), "labor_category"));
  const pairs = asList(get(agg, "buckets")).map(safeBucketKey).filter(p => p !== null) as [any, any][];
  const other = get(agg, "sum_other_doc_count");
  const complete = !((isInt(other) || typeof other === "boolean") && Number(other) > 0);
  const out: Obj = {top: pairs.slice(0, topN).map(([k, c]) => ({title: k, count: c})), distinct: complete ? pairs.length : null};
  if (!complete) {
    out.distinct_min = pairs.length;
    out.records_in_titles_not_listed = other;
  }
  return out;
}

/** _population_scope: off-title matches from GSA's cross-field keyword search. */
function populationScope(data: unknown, keyword: string): Obj {
  const agg = safeDict(get(safeDict(get(safeDict(data), "aggregations")), "labor_category"));
  // re.escape(keyword) with '*' as a wildcard; Python's '.' stops only at '\n'.
  const pattern = new RegExp(escapeRegex(keyword).replaceAll("\\*", "[^\\n]*"), "iu");
  const pairsOf = (value: unknown) => asList(value).map(safeBucketKey).filter(p => p !== null) as [any, any][];
  const buckets = get(agg, "buckets");
  const offTitle = pairsOf(buckets).filter(p => typeof p[0] === "string" && !pattern.test(p[0]));
  const errorBound = get(agg, "doc_count_error_upper_bound", 0);
  const complete = Array.isArray(buckets) && buckets.length > 0
    && buckets.every(b => {
      const p = safeBucketKey(b);
      return p !== null && typeof p[0] === "string" && Boolean(p[0]);
    })
    && pyEquals(get(agg, "sum_other_doc_count"), 0)
    && pyEquals(errorBound, 0);
  const titles = pairsOf(buckets).filter(p => typeof p[0] === "string");
  const folded = casefold(keyword);
  const exact = titles.filter(p => casefold(p[0]) === folded);
  const variants = titles.filter(p => casefold(p[0]) !== folded);
  return {
    search_fields: ["labor_category", "vendor_name", "idv_piid"],
    off_title_matches_detected: offTitle.length > 0,
    title_list_complete: complete,
    title_only_population_verified: complete && !offTitle.length,
    off_title_examples: offTitle.slice(0, 5).map(([k, c]) => ({title: k, count: c})),
    exact_title_population_verified: complete && !variants.length,
    exact_title_rate_count: complete ? exact.reduce((sum, [, c]) => sum + Number(c), 0) : null,
    non_exact_title_examples: variants.slice(0, 5).map(([k, c]) => ({title: k, count: c})),
  };
}

/** Python == between a parsed JSON value and an int. */
const pyEquals = (value: unknown, n: number) =>
  (typeof value === "number" || typeof value === "bigint" || typeof value === "boolean") ? Number(value) === n
    : value instanceof PyFloat ? value.value === n : false;

/** _attach_pagination_flags: an empty page past the end is not "no data". */
function attachPaginationFlags(response: Obj, page: number, pageSize: number, total: unknown): Obj {
  if (!(isInt(total) || typeof total === "boolean") || Number(total) <= 0) return response;
  const t = Number(total);
  const offset = (page - 1) * pageSize;
  if (offset >= t) {
    const lastPage = Math.max(1, Math.floor((t + pageSize - 1) / pageSize));
    response.paged_past_end = true;
    response.paged_past_end_reason = `No data on page ${page}; last page with data is page ${lastPage} (${t} total records at page_size ${pageSize}).`;
  }
  return response;
}

const withStats = (data: Obj, stats: Obj): Obj => ({...data, _stats: stats});

// ---------- core search tools ----------

async function keywordSearch(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("keyword_search", raw);
  validateNoControlChars(a.keyword, "keyword");
  let keyword = stripOrNone(a.keyword);
  if (keyword === null) fail("keyword cannot be empty. For unfiltered browsing use filtered_browse() instead.");
  keyword = clampTextLen(keyword, "keyword", 500);
  keyword = validateWafSafe(keyword, "keyword");
  const page = clamp(a.page, "page", 1, 100_000);
  const pageSize = clamp(a.page_size, "page_size", 1, MAX_PAGE_SIZE);
  validateEsWindow(page, pageSize);
  const [emin, emax] = validateExperienceRange(a.experience_min, a.experience_max);
  const [pmin, pmax] = validatePriceRange(a.price_min, a.price_max);
  const education = validateEducationLevel(a.education_level);
  validateWorksite(a.worksite);
  const sin = validateSin(a.sin);
  const ordering = validateOrdering(a.ordering);
  const sort = validateSort(a.sort);
  validateNoControlChars(a.exclude, "exclude");
  let exclude = stripOrNone(a.exclude);
  exclude = clampTextLen(exclude, "exclude", 500);
  exclude = validateWafSafe(exclude, "exclude");

  const filters = buildFilters({education_level: education, experience_min: emin, experience_max: emax, price_min: pmin, price_max: pmax,
    business_size: a.business_size, security_clearance: a.security_clearance, sin});
  const qs = buildQueryString({keyword, filters, page, page_size: pageSize, ordering, sort, exclude});
  const data = await getData(db, qs, options);
  const stats = extractStats(data);
  return attachPaginationFlags(withStats(data, stats), page, pageSize, stats.total_rates);
}

async function exactSearch(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("exact_search", raw);
  const field: string = a.field;
  validateNoControlChars(a.value, "value");
  let value = stripOrNone(a.value);
  if (value === null) fail("value cannot be empty. Use suggest_contains() to discover valid values.");
  value = clampTextLen(value, "value", 500)!;
  value = validateWafSafe(value, "value")!;
  const page = clamp(a.page, "page", 1, 100_000);
  const pageSize = clamp(a.page_size, "page_size", 1, MAX_PAGE_SIZE);
  validateEsWindow(page, pageSize);
  const [emin, emax] = validateExperienceRange(a.experience_min, a.experience_max);
  const [pmin, pmax] = validatePriceRange(a.price_min, a.price_max);
  const education = validateEducationLevel(a.education_level);
  const ordering = validateOrdering(a.ordering);
  const sort = validateSort(a.sort);

  const filters = buildFilters({education_level: education, experience_min: emin, experience_max: emax, price_min: pmin, price_max: pmax,
    business_size: a.business_size});
  // GSA's exact-field search cuts a value at its colon: use literal keyword search, then prove exactness.
  const literalFallback = value.includes(":");
  const qs = buildQueryString({
    keyword: literalFallback ? value : null, search_field: literalFallback ? null : field, search_value: literalFallback ? null : value,
    filters, page, page_size: pageSize, ordering, sort,
  });
  const data = await getData(db, qs, options);
  if (literalFallback) {
    const aggs = safeDict(get(data, "aggregations"));
    const count = get(safeDict(get(aggs, "wage_stats")), "count");
    const agg = safeDict(get(aggs, field));
    const pairs = asList(get(agg, "buckets")).map(safeBucketKey);
    const folded = casefold(value);
    const verified = isInt(count)
      && pyEquals(get(agg, "sum_other_doc_count"), 0)
      && pyEquals(get(agg, "doc_count_error_upper_bound"), 0)
      && pairs.every(p => p !== null && typeof p[0] === "string" && casefold(p[0]) === folded)
      && pairs.reduce((sum, p) => sum + (p !== null ? Number(p[1]) : 0), 0) === Number(count)
      && (Number(count) === 0 || pairs.length > 0);
    if (!verified) {
      fail(`GSA cannot verify the complete exact ${field} population for '${value}'. Its exact-field search truncates values at a colon; `
        + "literal keyword search can also include other field matches, and capped or approximate aggregations cannot prove exactness. "
        + "Use keyword_search with the full value to inspect actual rows and their scope, or suggest_contains to discover another "
        + "exact value. Do not treat that wider keyword population as exact-title or exact-vendor statistics.");
    }
  }
  const stats = extractStats(data);
  const result = withStats(data, stats);
  if (literalFallback) {
    result._exact_match_note = "GSA exact-field search truncates colon-containing values. Used literal keyword search; the complete, non-approximate "
      + `${field} aggregation verifies every rate row has the exact value. Statistics are unchanged source ceiling rates, not paid prices.`;
  }
  return attachPaginationFlags(result, page, pageSize, stats.total_rates);
}

async function suggestContains(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("suggest_contains", raw);
  return await suggest(db, a.field, a.term, options);
}

/** suggest_contains after argument validation (vendor_rate_card calls it too). */
async function suggest(db: Database, field: string, rawTerm: string, options: EmulatorOptions): Promise<Obj> {
  validateNoControlChars(rawTerm, "term");
  let term = stripOrNone(rawTerm);
  if (term === null || cpLen(term) < 2) fail("suggest_contains requires at least 2 non-whitespace characters.");
  term = clampTextLen(term, "term", 500)!;
  term = validateWafSafe(term, "term")!;

  const qs = buildQueryString({suggest_field: field, suggest_term: term});
  const data = await getData(db, qs, options);
  const fieldAgg = safeDict(get(safeDict(get(data, "aggregations")), field));
  const buckets = asList(get(fieldAgg, "buckets"));
  // GSA returns at most 100 values; sum_other_doc_count counts the records under values left off.
  const other = get(fieldAgg, "sum_other_doc_count");
  const otherRecords = isInt(other) && Number(other) > 0 ? other : 0;
  const rawErrorBound = get(fieldAgg, "doc_count_error_upper_bound");
  const errorBound = isInt(rawErrorBound) ? rawErrorBound : null;
  const approximate = !pyEquals(errorBound, 0);
  const suggestions: Obj[] = [];
  for (const b of buckets) {
    const pair = safeBucketKey(b);
    if (pair !== null) suggestions.push({value: pair[0], count: pair[1], count_is_approximate: approximate});
  }
  const hits = safeDict(get(data, "hits"));
  const totalObj = get(hits, "total");
  const total = isDict(totalObj) ? get(totalObj, "value", 0) : isInt(totalObj) || typeof totalObj === "boolean" ? totalObj : 0;
  const lowerBound = isDict(totalObj) && get(totalObj, "relation") === "gte";
  const result: Obj = {
    field,
    search_term: term,
    suggestions,
    counts_are_approximate: approximate,
    doc_count_error_upper_bound: errorBound,
    total_matching_records: total,
    total_matching_records_is_lower_bound: lowerBound,
    truncated: Number(otherRecords) > 0,
    other_records: otherRecords,
  };
  const notes: string[] = [];
  if (approximate) {
    notes.push(errorBound !== null && Number(errorBound) > 0
      ? `Suggestion counts are approximate: GSA reports that each count may undercount by up to ${intStr(errorBound)} records.`
      : "Suggestion counts are approximate: GSA does not provide a known upper bound on their count error.");
  }
  if (lowerBound) {
    notes.push(`GSA reports at least ${pyStr(total)} matching records, not an exact total. Its suggestion response caps hits.total and omits wage_stats. `
      + "Narrow the term or use keyword_search/exact_search for full statistics.");
  }
  if (notes.length) result._count_note = notes.join(" ");
  return result;
}

async function filteredBrowse(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("filtered_browse", raw);
  const page = clamp(a.page, "page", 1, 100_000);
  const pageSize = clamp(a.page_size, "page_size", 1, MAX_PAGE_SIZE);
  validateEsWindow(page, pageSize);
  const [emin, emax] = validateExperienceRange(a.experience_min, a.experience_max);
  const [pmin, pmax] = validatePriceRange(a.price_min, a.price_max);
  const education = validateEducationLevel(a.education_level);
  validateWorksite(a.worksite);
  const sin = validateSin(a.sin);
  const ordering = validateOrdering(a.ordering);
  const sort = validateSort(a.sort);

  const filters = buildFilters({education_level: education, experience_min: emin, experience_max: emax, price_min: pmin, price_max: pmax,
    business_size: a.business_size, security_clearance: a.security_clearance, sin});
  // An unfiltered browse returns 265k+ records; require at least one filter.
  if (!filters.length) {
    fail("filtered_browse requires at least one filter. Typical filters: education_level='MA', experience_min=5, sin='54151S', "
      + "business_size='S', price_min=50. For keyword search use keyword_search().");
  }
  const qs = buildQueryString({filters, page, page_size: pageSize, ordering, sort});
  const data = await getData(db, qs, options);
  const stats = extractStats(data);
  return attachPaginationFlags(withStats(data, stats), page, pageSize, stats.total_rates);
}

// ---------- workflow tools ----------

interface BenchmarkArgs {
  labor_category: string;
  education_level: string | null;
  experience_min: PyInt | null;
  experience_max: PyInt | null;
  business_size: string | null;
  sin: string | PyInt | null;
  security_clearance: string | null;
}

async function igceBenchmark(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  return await benchmark(db, validateArgs("igce_benchmark", raw) as BenchmarkArgs, options);
}

/** igce_benchmark after argument validation (price_reasonableness_check calls it too). */
async function benchmark(db: Database, a: BenchmarkArgs, options: EmulatorOptions): Promise<Obj> {
  validateNoControlChars(a.labor_category, "labor_category");
  let laborCategory = stripOrNone(a.labor_category);
  if (laborCategory === null) fail("labor_category cannot be empty.");
  laborCategory = clampTextLen(laborCategory, "labor_category", 500)!;
  laborCategory = validateWafSafe(laborCategory, "labor_category")!;
  const [emin, emax] = validateExperienceRange(a.experience_min, a.experience_max);
  const education = validateEducationLevel(a.education_level);
  const sin = validateSin(a.sin);

  const filters = buildFilters({education_level: education, experience_min: emin, experience_max: emax, business_size: a.business_size, sin,
    security_clearance: a.security_clearance});
  const qs = buildQueryString({keyword: laborCategory, filters, page: 1, page_size: 10});
  const data = await getData(db, qs, options);
  const stats = extractStats(data);
  return {
    labor_category: laborCategory,
    filters_applied: filters,
    ...stats,
    // Which titles were pooled: "Senior Software Engineer" matches 53 titles, not one.
    matched_titles: titleSummary(data, 10),
    population_scope: populationScope(data, laborCategory),
    _note: "Ceiling rates (NTE), not prices paid. Sample size matters for IGCE reliability. GSA's keyword search matches labor titles, "
      + "vendor names and contract numbers. A literal phrase can match any of these fields. Statistics pool all those matches, including "
      + "off-title rows when a vendor or contract matches (see population_scope and matched_titles). Phrase-matching titles can still "
      + "combine grades or specialties; title-only does not mean an exact-title or comparable population. For exact-title rates, discover "
      + "a title with suggest_contains and use exact_search on labor_category. Different spellings remain separate searches ('Cyber "
      + "Security' vs 'Cybersecurity'). Statistics are on current-year ceiling rates.",
  };
}

const NO_ANALYSIS = () => ({z_score: null, vs_median: null, iqr_position: null, delta_from_avg: null, delta_from_avg_pct: null});

async function priceReasonablenessCheck(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("price_reasonableness_check", raw);
  const proposed: number = a.proposed_rate;
  const laborCategory: string = a.labor_category;
  if (Number.isNaN(proposed) || !Number.isFinite(proposed)) {
    fail(`proposed_rate must be a finite number. Got ${floatRepr(proposed)}. NaN comparisons fall through to 'above P75' / 'equal' silently.`);
  }
  if (proposed <= 0) fail(`proposed_rate must be > 0. Got ${showFloat(proposed)}.`);
  const proposedRate = fl(proposed);

  const bench = await benchmark(db, a as BenchmarkArgs, options);
  if (Number(bench.total_rates ?? 0) === 0) {
    return {
      status: "NO_DATA",
      proposed_rate: proposedRate,
      message: `No comparable ceiling rates found for '${laborCategory}' with the given filters.`,
    };
  }
  const scope = bench.population_scope ?? {};
  if (!scope.title_only_population_verified) {
    const offTitle = scope.off_title_matches_detected;
    return {
      ...bench,
      status: offTitle ? "MIXED_SEARCH_FIELDS" : "UNVERIFIED_POPULATION",
      proposed_rate: proposedRate,
      message: (offTitle
        ? "GSA's keyword search also matched vendor names or contract numbers, returning labor titles that do not contain the requested phrase. "
        : "GSA's labor title aggregation is missing or incomplete, so off-title vendor/contract matches cannot be ruled out. ")
        + "These pooled statistics do not establish a comparable title population, so no high/low verdict is given. Use suggest_contains "
        + "and exact_search on labor_category to inspect title-only rates, then select comparable requirements.",
      analysis: NO_ANALYSIS(),
    };
  }
  if (!scope.exact_title_population_verified) {
    const exactCount = scope.exact_title_rate_count;
    const titleNote = exactCount === 0 ? `No exact '${laborCategory}' rates match these filters. `
      : exactCount !== null && exactCount !== undefined ? `${exactCount} exact '${laborCategory}' rates match these filters. `
      : "The exact-title rate count is not verified. ";
    const sampleNote = exactCount !== null && exactCount !== undefined && exactCount > 0 && exactCount < LOW_SAMPLE_MIN_RATES
      ? `That exact-title sample is below the ${LOW_SAMPLE_MIN_RATES}-rate minimum for this comparison. ` : "";
    return {
      ...bench,
      status: "MIXED_LABOR_TITLES",
      proposed_rate: proposedRate,
      message: "The keyword phrase matches different labor titles, which can include other grades or specialties. These pooled statistics "
        + "do not establish comparability for the requested exact title, so no high/low verdict is given. " + titleNote + sampleNote
        + "Use exact_search on labor_category with the supported education, experience and business-size filters to inspect that title; "
        + "it does not accept SIN or clearance filters, so check those requirements in the records and retain paging limits. "
        + "select comparable requirements before analyzing a proposal.",
      analysis: NO_ANALYSIS(),
    };
  }

  const avg = bench.avg_rate as number | bigint | PyFloat | null;
  const delta = avg !== null ? fl(round(proposed - num(avg), 2)) : null;
  const deltaPct = avg !== null && num(avg) > 0 ? fl(round(((proposed - num(avg)) / num(avg)) * 100, 1)) : null;
  const n = Number(bench.total_rates ?? 0);
  if (n < LOW_SAMPLE_MIN_RATES) {
    // A literal phrase can shrink the population to one rate; a high/low call on that is noise.
    return {
      ...bench,
      status: "LOW_SAMPLE",
      proposed_rate: proposedRate,
      message: `Only ${intStr(bench.total_rates)} comparable rate${n !== 1 ? "s" : ""} found for '${laborCategory}'. That sample is too small for a high/low `
        + `verdict (this check needs at least ${LOW_SAMPLE_MIN_RATES}). The statistics are shown for reference only. Use exact_search `
        + "with its supported eligibility filters to inspect the exact title. Do not combine different grades or specialties merely to "
        + "reach the sample minimum; select comparable requirements.",
      analysis: {z_score: null, vs_median: null, iqr_position: null, delta_from_avg: delta, delta_from_avg_pct: deltaPct},
    };
  }
  const std = bench.std_deviation as number | bigint | PyFloat | null;
  const percentiles = bench.percentiles ?? {};
  const median = percentiles.p50_median ?? null;
  const p25 = percentiles.p25 ?? null;
  const p75 = percentiles.p75 ?? null;
  const zScore = avg !== null && std !== null && num(std) > 0 ? fl(round((proposed - num(avg)) / num(std), 2)) : null;
  let iqrPosition: string | null = null;
  if (p25 !== null && p75 !== null) {
    iqrPosition = proposed < num(p25) ? "below P25 (low)" : proposed <= num(p75) ? "within IQR P25-P75 (typical)" : "above P75 (high)";
  }
  // Don't force "above" when the median is missing.
  const vsMedian = median === null ? "unknown (median unavailable)"
    : proposed < num(median) ? "below" : proposed > num(median) ? "above" : "equal";
  const analysis: Obj = {z_score: zScore, vs_median: vsMedian, iqr_position: iqrPosition, delta_from_avg: delta, delta_from_avg_pct: deltaPct};
  if (zScore === null) {
    analysis.z_score_reason = "Z-score unavailable: the average or standard deviation is missing, or the standard deviation is zero. A zero "
      + "z-score would incorrectly claim the proposed rate equals the population average.";
  }
  return {...bench, proposed_rate: proposedRate, analysis};
}

const ACRONYM = /^[A-Z0-9&]{2,6}$/;
const LEGAL_SUFFIX = new RegExp(`[${SPACE},]+(?:INC|INCORPORATED|LLC|L\\.L\\.C|CORP|CORPORATION|CO|COMPANY|LTD|LLP|LP|PLLC|PC)\\.?$`, "iu");

/** _contains_whole_word: the term not inside a longer run of letters or digits. */
export const containsWholeWord = (name: string, term: string) =>
  new RegExp(`(?<![A-Za-z0-9])${escapeRegex(term)}(?![A-Za-z0-9])`, "iu").test(name);

async function vendorRateCard(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("vendor_rate_card", raw);
  validateNoControlChars(a.vendor_name, "vendor_name");
  let vendorName = stripOrNone(a.vendor_name);
  if (vendorName === null || cpLen(vendorName) < 2) fail("vendor_name must be at least 2 non-whitespace characters.");
  vendorName = clampTextLen(vendorName, "vendor_name", 500)!;
  vendorName = validateWafSafe(vendorName, "vendor_name")!;
  const page = clamp(a.page, "page", 1, 100_000);
  const pageSize = clamp(a.page_size, "page_size", 1, MAX_PAGE_SIZE);
  validateEsWindow(page, pageSize);
  const ordering = validateOrdering(a.ordering);
  const sort = validateSort(a.sort);

  // Step 1: discover the exact name.
  const discovery = await suggest(db, "vendor_name", vendorName, options);
  let suggestions: Obj[] = discovery.suggestions ?? [];
  if (!suggestions.length) {
    return {
      vendor_search: vendorName,
      error: `No vendor found matching '${vendorName}'. CALC+ lists vendors by their registered legal name, not acronyms or brand names: `
        + "for example SAIC is 'SCIENCE APPLICATIONS INTERNATIONAL CORPORATION', so search 'Science Applications'. Try part of "
        + "the legal name, or a shorter or different term.",
    };
  }
  // suggest-contains is a substring match: prefer names with the term as a whole word.
  const valueText = (s: Obj) => {
    const v = s.value;
    return v === null || v === undefined || v === "" || v === 0 || v === false ? "" : typeof v === "string" ? v : repr(v);
  };
  const wholeWord = suggestions.filter(s => containsWholeWord(valueText(s), vendorName!));
  let matchNote: string | null = null;
  if (wholeWord.length) {
    suggestions = [...wholeWord, ...suggestions.filter(s => !wholeWord.includes(s))];
  } else if (ACRONYM.test(vendorName) || LEGAL_SUFFIX.test(vendorName)) {
    // An acronym, or a full name ending in INC/LLC/..., is a specific company.
    return {
      vendor_search: vendorName,
      error: `No vendor named '${vendorName}'. It only appears inside longer names: ${suggestions.slice(0, 5).map(s => repr(s.value ?? null)).join(", ")}. `
        + "CALC+ lists vendors by their registered legal name, not acronyms or brand names: for example SAIC is 'SCIENCE APPLICATIONS "
        + "INTERNATIONAL CORPORATION', so search 'Science Applications'. Try part of the legal name.",
      _candidates: suggestions.slice(0, 10).map(s => ({value: s.value ?? null, count: s.count ?? null})),
    };
  } else {
    matchNote = `'${vendorName}' matched only inside the longer name '${pyStr(suggestions[0].value)}', not as a whole word. Confirm this `
      + "is the intended vendor before using these rates.";
  }
  const exactName = suggestions[0].value;
  let multiMatchNote: string | null = null;
  if (suggestions.length > 1) {
    multiMatchNote = `${suggestions.length} vendors matched '${vendorName}'. Picked the one with the most rate records (${pyStr(suggestions[0].count ?? null)})`
      + `${wholeWord.length && wholeWord.length < suggestions.length ? " among names with it as a whole word" : ""}. `
      + "If this isn't the intended vendor, pass a more specific term.";
  }

  // Step 2: one page of rates for that vendor.
  const qs = buildQueryString({search_field: "vendor_name", search_value: exactName, page, page_size: pageSize, ordering, sort});
  const data = await getData(db, qs, options);
  const hitsList = asList(get(safeDict(get(data, "hits")), "hits"));
  const rates: Obj[] = [];
  for (const h of hitsList) {
    if (!isDict(h)) continue;
    const src = safeDict(get(h, "_source"));
    rates.push({
      labor_category: get(src, "labor_category"),
      current_price: safeNumber(get(src, "current_price")),
      next_year_price: safeNumber(get(src, "next_year_price")),
      education_level: get(src, "education_level"),
      min_years_experience: get(src, "min_years_experience"),
      sin: get(src, "sin"),
      idv_piid: get(src, "idv_piid"),
      business_size: get(src, "business_size"),
      // One title often has two prices, one per site; without this they look like duplicates.
      worksite: get(src, "worksite"),
      contract_end: get(src, "contract_end"),
    });
  }
  const hitsTotal = get(safeDict(get(data, "hits")), "total");
  const total = isDict(hitsTotal) ? get(hitsTotal, "value", 0) : isInt(hitsTotal) || typeof hitsTotal === "boolean" ? hitsTotal : 0;

  // Pagination metadata, so a 100-row page is not taken for the whole card.
  const returned = rates.length;
  const startRow = (page - 1) * pageSize + 1;
  const endRow = (page - 1) * pageSize + returned;
  const hasMore = returned > 0 && endRow < Number(total);
  // total counts rows; distinct titles come from the (500-capped) labor_category aggregation.
  const titles = titleSummary(data, 0);
  const response: Obj = {
    vendor: exactName,
    total_rates: total,
    distinct_labor_categories: titles.distinct || null,
    page,
    returned,
    returned_range: returned ? `rows ${startRow}-${endRow} of ${pyStr(total)}` : null,
    has_more: hasMore,
    next_page: hasMore ? page + 1 : null,
    rates,
    _stats: extractStats(data),
  };
  if (Object.hasOwn(titles, "distinct_min")) response.distinct_labor_categories_min = titles.distinct_min;
  if (hasMore) {
    response._truncation_note = `Partial rate card: rows are ordered by ${ordering} (${sort}), so this slice is biased toward the start of that ordering `
      + "(alphabetical by labor category with the defaults). Categories later in the ordering, like 'Software Engineer' or 'Systems "
      + `Engineer', may not appear until later pages. Call again with page=${page + 1} to continue; do not present a partial slice as `
      + "the complete card.";
  }
  if (matchNote) response._match_note = matchNote;
  if (multiMatchNote) {
    response._note = multiMatchNote;
    response._candidates = suggestions.slice(0, 10).map(s => ({value: s.value ?? null, count: s.count ?? null}));
  }
  return attachPaginationFlags(response, page, pageSize, isInt(total) || typeof total === "boolean" ? total : null);
}

/** str() of a JSON value in an f-string. */
const pyStr = (value: unknown) => (typeof value === "string" ? value : repr(value));

async function sinAnalysis(db: Database, raw: Record<string, unknown>, options: EmulatorOptions) {
  const a = validateArgs("sin_analysis", raw);
  const sinCode = validateSin(a.sin_code);
  if (sinCode === null) fail("sin_code cannot be empty.");
  const pageSize = clamp(a.page_size, "page_size", 1, MAX_PAGE_SIZE);
  const qs = buildQueryString({filters: [`sin:${sinCode}`], page: 1, page_size: pageSize, ordering: "current_price", sort: "asc"});
  const data = await getData(db, qs, options);
  const stats = extractStats(data);
  const result: Obj = {
    sin: sinCode,
    ...stats,
    // The titles on the SIN, most rates first.
    labor_categories: titleSummary(data, 25),
  };
  if (!stats.total_rates) {
    // A valid-looking SIN with zero records is usually a retired code, not an empty market.
    result._note = "0 records for this SIN. It may be retired under MAS consolidation (for example 541512/541513 work now falls under "
      + "54151S). Verify the current MAS SIN or use keyword_search on the labor category instead.";
  }
  return result;
}

export const HANDLERS: Record<string, Handler> = {
  keyword_search: keywordSearch,
  exact_search: exactSearch,
  suggest_contains: suggestContains,
  filtered_browse: filteredBrowse,
  igce_benchmark: igceBenchmark,
  price_reasonableness_check: priceReasonablenessCheck,
  vendor_rate_card: vendorRateCard,
  sin_analysis: sinAnalysis,
} as Record<string, Handler>;

