// The emulator against GSA's own recorded answers (servers/gsa-calc-mcp/tests/
// fixtures): every answer whose whole result set is in the recording must come
// back identical except `took`; the others must agree on their first page up
// to ties; and copies holding each answer's complete bucket counts must give
// the same aggregations (percentiles past small sets excepted: GSA estimates
// them with TDigest, the copy gives true values).
import assert from "node:assert/strict";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {Forward} from "../src/args.ts";
import {emulate} from "../src/emulator.ts";
import {PyFloat, dumps, type Py} from "../src/pyjson.ts";
import {float32Text, parseQuery} from "../src/rules.ts";
import {extendedStats, histogram, percentiles} from "../src/stats.ts";
import {d1} from "./d1.ts";
import {NIGHT, SCHEMA, buildDatabase, fixtureAnswers, fixtureDatabase, syntheticRecords, type SourceRecord} from "./fixture-db.ts";

const ANSWERS = Object.fromEntries(fixtureAnswers().map(a => [a.name, a]));
// GSA_CALC_TEST_DB: the same records built by scripts/load_gsa_calc.py (test/fixture_recording.py).
const fixtureDb = d1(fixtureDatabase());
const body = async (db: any, query: string, took = 0) => {
  const answer = await emulate(db, query, {took});
  assert.equal(answer.status, 200, "text" in answer ? answer.text : "");
  return (answer as {body: Record<string, any>}).body;
};
const without = (o: Record<string, Py>, ...keys: string[]) => Object.fromEntries(Object.entries(o).filter(([k]) => !keys.includes(k)));

test("answers whose whole result set was recorded come back identical (took aside)", async () => {
  for (const name of ["exact_grade", "literal_keyword", "graduate_exact_before", "ordinary_exact_control", "graduate_literal_keyword"]) {
    const {query, raw} = ANSWERS[name];
    const got = await body(fixtureDb, query, raw.took);
    assert.equal(dumps(got, 1), dumps(raw, 1), name);
  }
});

test("partly recorded answers agree on their first page, up to ties", async () => {
  for (const name of ["delimiter_exact_before", "approximate_population_control", "mixed_grade", "no_exact_grade"]) {
    const {query, raw} = ANSWERS[name];
    const got = await body(fixtureDb, query);
    const expected = raw.hits.hits as any[];
    const page = got.hits.hits.slice(0, expected.length) as any[];
    // The same sort values in the same order, and at each value the same records.
    assert.equal(dumps(page.map(h => h.sort)), dumps(expected.map(h => h.sort)), name);
    const group = (hits: any[]) => {
      const by = new Map<string, string[]>();
      for (const h of hits) by.set(dumps(h.sort), [...(by.get(dumps(h.sort)) ?? []), h._id].sort());
      return [...by.entries()];
    };
    assert.deepEqual(group(page), group(expected), name);
    const sources = new Map(expected.map(h => [h._id, dumps(without(h, "sort"))]));
    for (const h of page) assert.equal(dumps(without(h, "sort")), sources.get(h._id), `${name} ${h._id}`);
  }
});

test("complete bucket counts give GSA's aggregations", async () => {
  const report: string[] = [];
  for (const [name, base] of [["delimiter_exact_before", 9_000_000], ["mixed_grade", 9_100_000], ["no_exact_grade", 9_200_000]] as const) {
    const {query, raw} = ANSWERS[name];
    const got = await body(d1(buildDatabase(syntheticRecords(raw, base))), query);
    assert.deepEqual(got.hits.total, raw.hits.total);
    for (const [agg, value] of Object.entries(raw.aggregations as Record<string, Py>)) {
      const same = dumps(got.aggregations[agg]) === dumps(value);
      if (raw.aggregations.wage_stats.count > 24 && (agg === "histogram_percentiles" || agg === "median_price")) {
        report.push(`${name} ${agg}: ${dumps(got.aggregations[agg])} vs GSA ${dumps(value)}`);
        continue;
      }
      assert.ok(same, `${name} ${agg}\n  got ${dumps(got.aggregations[agg])}\n  GSA ${dumps(value)}`);
    }
    assert.deepEqual(Object.keys(got.aggregations), Object.keys(raw.aggregations));
  }
  // n = 91: GSA's TDigest estimates; the copy's true values (floor(q*n)-th price).
  assert.equal(report.length, 2);
});

test("stats: exact sums, floor percentiles, NaN sampling variance for one rate", () => {
  const one = extendedStats([[Math.fround(176.1), 1]], 2);
  assert.equal(dumps(one), dumps(ANSWERS.literal_keyword.raw.aggregations.wage_stats));
  const empty = extendedStats([], 2);
  assert.equal(dumps(empty), dumps(ANSWERS.graduate_literal_keyword.raw.aggregations.wage_stats));
  const values = [1, 2, 3, 4].map(v => [Math.fround(v * 1.1), 1] as [number, number]);
  assert.deepEqual((percentiles(values, [10, 25, 50, 75, 90]).values as any)["50.0"], new PyFloat(Math.fround(3.3)));
  assert.deepEqual(histogram([], {buckets: 12, shardSize: 600, initialBuffer: 6000}), []);
  // Past the 6,000-value buffer the merge phase runs; it still gives 12 buckets covering every value.
  const many: [number, number][] = Array.from({length: 7000}, (_, i) => [Math.fround(20 + i * 0.07), 1]);
  const buckets = histogram(many, {buckets: 12, shardSize: 600, initialBuffer: 6000}) as any[];
  assert.equal(buckets.length, 12);
  assert.equal(buckets.reduce((s, b) => s + b.doc_count, 0), 7000);
  assert.equal(float32Text(28.9), "28.9");
  assert.equal(float32Text(100), "100.0");
  assert.equal(float32Text(50.7295), "50.7295");
});

function tinyCopy(records: SourceRecord[]) {
  return d1(buildDatabase(records));
}
const rec = (id: number, fields: Record<string, Py>): SourceRecord => ({_id: String(id), _source: {
  security_clearance: false, vendor_name: "ACME LLC", idv_piid: "47QTEST", business_size: "S", labor_category: "Analyst", min_years_experience: 3,
  sin: "541611", worksite: "Customer_Facility", education_level: "Bachelors", id, current_price: new PyFloat(50.5), _timestamp: "old", ...fields,
}});

test("rules: matching, filters, exclude, ordering, paging", async () => {
  const db = tinyCopy([
    rec(1, {labor_category: "Senior Analyst", current_price: new PyFloat(80.25)}),
    rec(2, {labor_category: "analyst ii", vendor_name: "Analytic Partners", current_price: new PyFloat(60.1)}),
    rec(3, {labor_category: "Engineer", vendor_name: "ANALYST GROUP INC", sin: "541330ENG,541611", current_price: new PyFloat(99.99)}),
    rec(4, {labor_category: "Engineer", sin: "5416110", security_clearance: true, education_level: "High School Equivalent", min_years_experience: 12}),
    rec(5, {labor_category: "Data*Scientist", business_size: "O", current_price: new PyFloat(28.9), education_level: "Masters"}),
  ]);
  const ids = async (query: string) => (await body(db, query)).hits.hits.map((h: any) => Number(h._id));
  // keyword: every 2-4 character gram of the lowercased phrase in one field value; * is an ordinary character.
  assert.deepEqual(await ids("keyword=ANALYST&page=1&page_size=100&ordering=current_price&sort=asc"), [2, 1, 3]);
  assert.deepEqual(await ids("keyword=data%2Ascien&page=1&page_size=100&ordering=current_price&sort=asc"), [5]);
  assert.deepEqual(await ids("keyword=data+scien&page=1&page_size=100&ordering=current_price&sort=asc"), []);
  assert.deepEqual(await ids("keyword=47qtest&page=1&page_size=2&ordering=current_price&sort=desc"), [3, 1]);
  assert.deepEqual(await ids("keyword=analyst+senior&page=1&page_size=100&ordering=current_price&sort=asc"), [], "grams across a space must be there too");
  assert.deepEqual(await ids("keyword=A&page=1&page_size=100&ordering=current_price&sort=asc"), [], "1 character: no grams, nothing");
  assert.deepEqual(await ids("keyword=ii&page=1&page_size=100&ordering=current_price&sort=asc"), [2], "2 characters: a substring");
  // search: exact field value, cut at a colon.
  assert.deepEqual(await ids("search=labor_category:Engineer%3A+Sr.&page=1&page_size=100&ordering=current_price&sort=asc"), [4, 3]);
  assert.deepEqual(await ids("search=labor_category:engineer&page=1&page_size=100&ordering=current_price&sort=asc"), []);
  // filters
  const one = (filter: string) => ids(`filter=${filter}&page=1&page_size=100&ordering=current_price&sort=asc`);
  assert.deepEqual(await one("sin:541611"), [5, 2, 1, 3]);
  assert.deepEqual(await one("sin:541330eng"), [3]);
  assert.deepEqual(await one("price_range:28.9%2C60.1"), [5, 4, 2]);
  assert.deepEqual(await one("experience_range:10%2C999"), [4]);
  assert.deepEqual(await one("min_years_experience:12"), [4]);
  assert.deepEqual(await one("education_level:HS%7CMA"), [5, 4]);
  assert.deepEqual(await one("education_level:ba"), [5, 4, 2, 1, 3], "unknown codes are ignored");
  assert.deepEqual(await one("security_clearance:yes"), [4]);
  assert.deepEqual(await one("security_clearance:true"), [5, 4, 2, 1, 3]);
  assert.deepEqual(await one("business_size:O"), [5]);
  assert.deepEqual(await one("business_size:o"), []);
  assert.deepEqual(await one("worksite:Virtual"), [5, 4, 2, 1, 3]);
  assert.deepEqual(await one("worksite:customer"), [5, 4, 2, 1, 3]);
  assert.deepEqual(await one("worksite:contractor"), []);
  assert.deepEqual(await ids("filter=business_size:O&filter=business_size:S&page=1&page_size=100"), [4, 2, 1, 3], "the same field twice: the last wins");
  // exclude drops records from hits and aggregations.
  const excluded = await body(db, "filter=sin:541611&page=1&page_size=100&ordering=current_price&sort=asc&exclude=5%7C2");
  assert.deepEqual(excluded.hits.hits.map((h: any) => h._id), ["1", "3"]);
  assert.equal(excluded.aggregations.wage_stats.count, 2);
  // ordering pairs in turn, ties by _id; text by code point; sort values per pair.
  const ordered = await body(db, "filter=business_size:S&page=1&page_size=100&ordering=labor_category&sort=desc&ordering=current_price&sort=asc");
  assert.deepEqual(ordered.hits.hits.map((h: any) => h._id), ["2", "1", "4", "3"]);
  assert.equal(dumps(ordered.hits.hits[2].sort), '["Engineer",50.5]');
  // Several pairs leave idv_piid out; sort=desc alone is current_price descending; a match_all adds _score 1.0.
  const pairs = await body(db, "filter=business_size:S&page=1&page_size=1&ordering=idv_piid&sort=desc&ordering=current_price&sort=asc");
  assert.equal(dumps(pairs.hits.hits[0].sort), "[50.5]");
  assert.deepEqual(await ids("keyword=analyst&page=1&page_size=100&sort=desc"), [3, 1, 2]);
  const all = await body(db, "page=1&page_size=1&ordering=current_price&sort=asc");
  assert.equal(dumps([all.hits.max_score, all.hits.hits[0]._score, all.hits.hits[0].sort]), "[null,1.0,[28.9,1.0]]");
  // paging: page_size 0 and 501 are answered; page 0 and past 10,000 are refused with an empty 406.
  assert.deepEqual(await ids("filter=business_size:S&page=2&page_size=3&ordering=current_price&sort=asc"), [3]);
  assert.deepEqual(await ids("filter=business_size:S&page=1&page_size=0"), []);
  assert.equal((await ids("filter=business_size:S&page=1&page_size=501")).length, 4);
  assert.deepEqual(await emulate(db, "filter=business_size:S&page=101&page_size=100"), {status: 406, text: ""});
  assert.deepEqual(await emulate(db, "filter=business_size:S&page=0&page_size=10"), {status: 406, text: ""});
  // _source gets the night's _timestamp, in place.
  const hit = (await body(db, "search=idv_piid:47QTEST&page=1&page_size=1")).hits.hits[0];
  assert.equal(hit._source._timestamp, NIGHT.timestamp);
  assert.equal(hit._index, NIGHT.version);
  assert.deepEqual(Object.keys(hit._source).slice(-2), ["current_price", "_timestamp"]);
});

test("suggest-contains: matching values, most records first, top 100", async () => {
  const records = Array.from({length: 120}, (_, i) => rec(100 + i, {vendor_name: `Booz Unit ${String(i).padStart(3, "0")}`}));
  records.push(rec(300, {vendor_name: "Booz Unit 000"}), rec(301, {vendor_name: "BOOZ ALLEN"}));
  const answer = await body(tinyCopy(records), "suggest-contains=vendor_name:booz&page=1&page_size=100&ordering=current_price&sort=asc");
  const agg = answer.aggregations.vendor_name;
  assert.deepEqual(answer.hits.total, {value: 122, relation: "eq"});
  assert.equal(agg.buckets.length, 100);
  assert.deepEqual(agg.buckets.slice(0, 2), [{key: "Booz Unit 000", doc_count: 2}, {key: "BOOZ ALLEN", doc_count: 1}]);
  assert.equal(agg.sum_other_doc_count, 21);
  assert.equal(agg.doc_count_error_upper_bound, 0);
  assert.deepEqual(Object.keys(answer.aggregations), ["vendor_name"]);
});

test("hits.total stops at 10,000 (gte); wage_stats counts every match", async () => {
  const records = Array.from({length: 10_001}, (_, i) => rec(1000 + i, {current_price: new PyFloat(20 + (i % 500) / 4)}));
  const answer = await body(tinyCopy(records), "filter=sin:541611&page=1&page_size=1&ordering=current_price&sort=asc");
  assert.deepEqual(answer.hits.total, {value: 10_000, relation: "gte"});
  assert.equal(answer.aggregations.wage_stats.count, 10_001);
  assert.equal(answer.aggregations.current_price.buckets.length, 500);
});

test("an empty copy forwards; a night's rows outside the window are not read", async () => {
  const empty = new DatabaseSync(":memory:");
  empty.exec(SCHEMA);
  await assert.rejects(emulate(d1(empty), "keyword=x&page=1&page_size=1"), (e: unknown) => e instanceof Forward);
  const db = buildDatabase([rec(1, {}), rec(2, {})]);
  db.exec("UPDATE records SET v_to = 1 WHERE id = 2");
  assert.deepEqual((await body(d1(db), "keyword=analyst&page=1&page_size=10")).hits.total, {value: 1, relation: "eq"});
  assert.deepEqual(parseQuery("ordering=bogus"), {status: 406, text: ""});
});

test("one D1 round trip per query", async () => {
  const start = fixtureDb.log.length;
  await body(fixtureDb, ANSWERS.mixed_grade.query);
  const statements = fixtureDb.log.slice(start);
  assert.equal(new Set(statements.map(s => s.batch)).size, 1);
  for (const s of statements) assert.ok(s.values.length <= 100);
});
