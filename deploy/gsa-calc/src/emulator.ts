// "GSA in a box": answers the query strings the Python server sends to GSA's
// CALC+ API (keyword=, search=field:value, suggest-contains=field:term,
// filter=, page, page_size, ordering/sort, exclude) from the copy in D1
// (schema.sql), with GSA's answer shape: the same keys in the same order, the
// night's index name and _timestamp, hits and all twelve aggregations. Which
// records match and how they sort is decided in rules.ts; the statistics are
// computed in stats.ts.
//
// One D1 round trip per query: the night's meta, the aggregation inputs (one
// scan of the narrow records columns, grouped), and the page of hits with
// their _source text (only the page's rows read from sources).
import {Forward} from "./args.ts";
import {PyFloat, parseJson, type Py} from "./pyjson.ts";
import {
  AGGREGATIONS, EDUCATION_WORDS, HISTOGRAM, MEDIAN_PERCENTS, PERCENTS, SHARDS, SIGMA, SUGGEST_SIZE, TERMS_SIZE, TRACK_TOTAL_HITS,
  orderBy, parseQuery, sortValues, termsKey, where, withTimestamp, type Query,
} from "./rules.ts";
import {extendedStats, histogram, percentiles, terms, type Counted} from "./stats.ts";

type Row = Record<string, any>;
export interface Statement {
  bind(...values: unknown[]): Statement;
  all<T = Row>(): Promise<{results: T[]}>;
}
export interface Database {
  prepare(sql: string): Statement;
  batch<T = Row>(statements: Statement[]): Promise<{results: T[]}[]>;
}

export interface EmulatorOptions {
  /** A fixed `took` (milliseconds), so two answers to one query compare byte for byte (tests and parity). */
  took?: number;
}

/** GSA's answer: 200 with the parsed body, or its error status and text. */
export type Answer = {status: 200; body: Record<string, Py>} | {status: number; text: string};

const META_SQL = "SELECT key, value FROM meta WHERE key IN ('current', 'version', 'timestamp')";
// The columns the aggregations read, and a page of hits reads.
const AGG_COLUMNS = "r.price, r.labor_category, r.education_level, r.min_years_experience, r.worksite, r.business_size, r.security_clearance";
const HIT_COLUMNS = "r.rid, r.id, r.price, r.next_year_price, r.labor_category, r.vendor_name, r.idv_piid, r.education_level, r.min_years_experience, r.business_size";

// Aggregation inputs, one row per (agg, key): 0 prices, 1 matched records,
// 2 records with a labor_category, 3 the top labor categories (ordered and
// cut in SQL, as there can be tens of thousands), 4-8 the small term fields.
const STATS_SELECTS = [
  "SELECT 0 AS agg, price AS key, COUNT(*) AS n FROM m WHERE price IS NOT NULL GROUP BY price",
  "SELECT 1, NULL, COUNT(*) FROM m",
  "SELECT 2, NULL, COUNT(labor_category) FROM m",
  `SELECT * FROM (SELECT 3, labor_category, COUNT(*) AS n FROM m WHERE labor_category IS NOT NULL GROUP BY labor_category ORDER BY n DESC, labor_category LIMIT ${TERMS_SIZE.labor_category})`,
  "SELECT 4, education_level, COUNT(*) FROM m WHERE education_level IS NOT NULL GROUP BY education_level",
  "SELECT 5, min_years_experience, COUNT(*) FROM m WHERE min_years_experience IS NOT NULL GROUP BY min_years_experience",
  "SELECT 6, worksite, COUNT(*) FROM m WHERE worksite IS NOT NULL GROUP BY worksite",
  "SELECT 7, business_size, COUNT(*) FROM m WHERE business_size IS NOT NULL GROUP BY business_size",
  "SELECT 8, security_clearance, COUNT(*) FROM m WHERE security_clearance IS NOT NULL GROUP BY security_clearance",
];
const TERM_AGGS: Record<number, string> = {4: "education_level", 5: "min_years_experience", 6: "worksite", 7: "business_size", 8: "security_clearance"};

/** GSA's answer to one query string, from the copy. Throws Forward when the copy is empty. */
export async function emulate(db: Database, qs: string, options: EmulatorOptions = {}): Promise<Answer> {
  const started = Date.now();
  const query = parseQuery(qs);
  if ("status" in query) return query;
  const match = where(query);
  const suggest = query.mode.kind === "suggest" ? query.mode.field : null;
  const statements = [db.prepare(META_SQL)];
  if (suggest) {
    statements.push(db.prepare(`SELECT r.${suggest} AS key, COUNT(*) AS n FROM records r WHERE ${match.sql} GROUP BY r.${suggest}`).bind(...match.values));
  } else {
    const offset = (query.page - 1) * query.pageSize;
    statements.push(
      db.prepare(`WITH m AS MATERIALIZED (SELECT ${AGG_COLUMNS} FROM records r WHERE ${match.sql}) ${STATS_SELECTS.join(" UNION ALL ")}`).bind(...match.values),
      db.prepare(`SELECT ${HIT_COLUMNS}, s.json FROM records r LEFT JOIN sources s ON s.rid = r.rid WHERE ${match.sql} ORDER BY ${orderBy(query)} LIMIT ? OFFSET ?`)
        .bind(...match.values, query.pageSize, offset),
    );
  }
  const [meta, ...results] = (await db.batch(statements)).map(r => r.results);
  const night = Object.fromEntries(meta.map((row: Row) => [row.key, row.value]));
  // An empty copy (nothing loaded yet): the Python server answers instead.
  if (night.current === undefined || night.version === undefined) throw new Forward("empty_copy");
  const body = suggest ? suggestBody(suggest, results[0] as Row[]) : searchBody(query, results[0] as Row[], results[1] as Row[], night);
  const took = options.took ?? Date.now() - started;
  return {status: 200, body: {took, timed_out: false, _shards: {...SHARDS}, ...body}};
}

/** hits.total: exact up to 10,000, then 10,000 "gte". */
const hitsTotal = (n: number) => (n > TRACK_TOTAL_HITS ? {value: TRACK_TOTAL_HITS, relation: "gte"} : {value: n, relation: "eq"});

/** A search or browse answer: hits and the twelve aggregations. */
function searchBody(query: Query, statsRows: Row[], hitRows: Row[], night: Record<string, string>) {
  const prices: Counted[] = [];
  let total = 0;
  let withTitle = 0;
  const titles: [string, number][] = [];
  const fields: Record<string, [string, number][]> = {education_level: [], min_years_experience: [], worksite: [], business_size: [], security_clearance: []};
  for (const {agg, key, n} of statsRows) {
    if (agg === 0) prices.push([key, n]);
    else if (agg === 1) total = n;
    else if (agg === 2) withTitle = n;
    else if (agg === 3) titles.push([key, n]);
    else fields[TERM_AGGS[agg]].push([termsKey(TERM_AGGS[agg], key), n]);
  }
  prices.sort((a, b) => a[0] - b[0]);
  const priceKeys = new Map<string, number>();
  for (const [value, n] of prices) {
    const key = termsKey("current_price", value);
    priceKeys.set(key, (priceKeys.get(key) ?? 0) + n);
  }
  const educationCounts = new Map<string, number>(fields.education_level);
  const aggregations: Record<string, Py> = {
    // Already the top 500 by count, then key; the rest are counted as other.
    labor_category: {doc_count_error_upper_bound: 0, sum_other_doc_count: withTitle - titles.reduce((s, [, n]) => s + n, 0),
      buckets: titles.map(([key, doc_count]) => ({key, doc_count}))},
    security_clearance: terms(fields.security_clearance, TERMS_SIZE.security_clearance),
    histogram_percentiles: percentiles(prices, PERCENTS),
    min_years_experience: terms(fields.min_years_experience, TERMS_SIZE.min_years_experience),
    worksite: terms(fields.worksite, TERMS_SIZE.worksite),
    wage_histogram: {buckets: histogram(prices, HISTOGRAM)},
    education_level: terms(fields.education_level, TERMS_SIZE.education_level),
    current_price: terms([...priceKeys], TERMS_SIZE.current_price),
    business_size: terms(fields.business_size, TERMS_SIZE.business_size),
    wage_stats: extendedStats(prices, SIGMA),
    median_price: percentiles(prices, MEDIAN_PERCENTS),
  };
  if (total > 0) {
    aggregations.education_level_counts = {buckets: Object.entries(EDUCATION_WORDS).map(([code, words]) =>
      ({key: code, doc_count: words.reduce((s, word) => s + (educationCounts.get(word) ?? 0), 0)}))};
  }
  const hits = hitRows.map(row => {
    // A records row without its _source is a gap in the copy: the Python server answers instead.
    if (typeof row.json !== "string") throw new Forward("missing_source");
    const source = withTimestamp(parseJson(row.json) as Record<string, Py>, night.timestamp ?? null);
    // A match_all sorts by _score too, so each hit carries it (1.0); max_score stays null.
    return {_index: night.version, _id: String(row.id), _score: query.scoreSort ? new PyFloat(1) : null, _source: source, sort: sortValues(query, row)};
  });
  const ordered: Record<string, Py> = {};
  for (const name of AGGREGATIONS) if (Object.hasOwn(aggregations, name)) ordered[name] = aggregations[name];
  return {hits: {total: hitsTotal(total), max_score: null, hits}, aggregations: ordered};
}

/** A suggest-contains answer: the field's matching values, most records first.
 * PROVISIONAL shape: hits.total over the matching records and that one
 * aggregation (the Python server reads only those; server.py notes the answer
 * has no wage_stats). */
function suggestBody(field: string, rows: Row[]) {
  const entries: [string, number][] = rows.map(({key, n}) => [key, n]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  return {hits: {total: hitsTotal(total), max_score: null, hits: []}, aggregations: {[field]: terms(entries, SUGGEST_SIZE)}};
}
