// A small copy of GSA CALC+ for tests, built from the recorded GSA answers in
// servers/gsa-calc-mcp/tests/fixtures (night of 2026-10-10): schema.sql, then
// every distinct hit inserted the way scripts/load_gsa_calc.py stores a record
// (float32 prices, ',sin,', clearance 1/0, _source text with its key order,
// the three search fields in terms). GSA_CALC_TEST_DB names a database built
// some other way (the loader's build) instead.
import {createHash} from "node:crypto";
import {mkdtempSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {fileURLToPath} from "node:url";
import {dumpsPython, parseJson, PyFloat, type Py} from "../src/pyjson.ts";
import {fold} from "../src/rules.ts";

const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const FIXTURES = join(ROOT, "servers/gsa-calc-mcp/tests/fixtures");
export const SCHEMA = readFileSync(join(ROOT, "deploy/gsa-calc/schema.sql"), "utf8");
export const NIGHT = {current: "1", version: "ceilingrates-2026-10-10_02-00-02", timestamp: "2026-10-10T02:00:03Z"};

export interface FixtureAnswer {
  name: string;
  query: string;
  raw: Record<string, any>;
  arguments: Record<string, unknown>;
  tool?: string;
}

/** The nine recorded GSA answers: name, the query string sent, the parsed body (floats kept as PyFloat). */
export function fixtureAnswers(): FixtureAnswer[] {
  const out: FixtureAnswer[] = [];
  for (const file of ["literal_colon_title_source_2026_10.json", "nurse_grade_source_2026_10.json"]) {
    const data = parseJson(readFileSync(join(FIXTURES, file), "utf8")) as Record<string, any>;
    for (const [name, entry] of Object.entries(data)) {
      const url: string = entry.url ?? entry.source_url;
      out.push({name, query: url.split("?")[1], raw: entry.raw, arguments: entry.arguments, tool: entry.tool});
    }
  }
  return out;
}

export interface SourceRecord {
  _id: string;
  _source: Record<string, Py>;
}

/** Every distinct hit in the recorded answers. */
export function fixtureRecords(): SourceRecord[] {
  const seen = new Map<string, SourceRecord>();
  for (const answer of fixtureAnswers()) {
    for (const hit of answer.raw.hits.hits) if (!seen.has(hit._id)) seen.set(hit._id, {_id: hit._id, _source: hit._source});
  }
  return [...seen.values()];
}

const num = (v: unknown): number | null => (v instanceof PyFloat ? v.value : typeof v === "number" ? v : null);
const f32 = (v: unknown) => {
  const n = num(v);
  return n === null ? null : Math.fround(n);
};

/** A SQLite copy holding `records` as night 1 (meta current/version/timestamp). */
export function buildDatabase(records: SourceRecord[], night: Partial<typeof NIGHT> = NIGHT, path?: string): DatabaseSync {
  const file = path ?? join(mkdtempSync(join(tmpdir(), "gsa-calc-")), "d1.sqlite");
  const db = new DatabaseSync(file);
  db.exec(SCHEMA);
  const meta = db.prepare("INSERT INTO meta (key, value) VALUES (?, ?)");
  for (const [key, value] of Object.entries(night)) if (value !== undefined) meta.run(key, value);
  const record = db.prepare(`INSERT INTO records (id, v_from, labor_category, vendor_name, idv_piid, price, next_year_price, education_level,
    min_years_experience, worksite, business_size, security_clearance, sin, hash) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  const source = db.prepare("INSERT INTO sources (rid, json) VALUES (?, ?)");
  const term = db.prepare("INSERT OR IGNORE INTO terms (field, value, folded) VALUES (?, ?, ?)");
  const text = (v: unknown) => (typeof v === "string" ? v : null);
  db.exec("BEGIN");
  for (const {_id, _source: s} of records) {
    const {_timestamp, ...rest} = s;
    void _timestamp;
    const clearance = s.security_clearance === true ? 1 : s.security_clearance === false ? 0 : null;
    const sin = typeof s.sin === "string" ? `,${s.sin},` : null;
    const result = record.run(Number(_id), text(s.labor_category), text(s.vendor_name), text(s.idv_piid), f32(s.current_price),
      f32(s.next_year_price), text(s.education_level), num(s.min_years_experience), text(s.worksite), text(s.business_size), clearance, sin,
      createHash("sha256").update(dumpsPython(rest)).digest("hex"));
    source.run(result.lastInsertRowid, dumpsPython(s));
    for (const field of ["labor_category", "vendor_name", "idv_piid"]) {
      const value = text(s[field]);
      if (value !== null) term.run(field, value, fold(value));
    }
  }
  db.exec("COMMIT");
  return db;
}

/** The fixture copy: GSA_CALC_TEST_DB, or every recorded hit. */
export function fixtureDatabase(): DatabaseSync {
  if (process.env.GSA_CALC_TEST_DB) return new DatabaseSync(process.env.GSA_CALC_TEST_DB, {readOnly: true});
  return buildDatabase(fixtureRecords());
}

/** Records with the marginal counts of a recorded answer whose buckets are all
 * listed (sum_other_doc_count 0): each aggregation's buckets dealt out over
 * `n` records, so a search matching them gets the same aggregations as GSA's
 * answer (they are marginal counts). Prices come from the current_price buckets. */
export function syntheticRecords(raw: Record<string, any>, base: number, vendor = "SYNTHETIC VENDOR"): SourceRecord[] {
  const aggs = raw.aggregations;
  const n: number = aggs.wage_stats.count;
  const deal = (agg: string, convert: (key: string) => Py) => {
    const values: Py[] = [];
    for (const b of aggs[agg].buckets) for (let i = 0; i < b.doc_count; i++) values.push(convert(b.key));
    if (values.length !== n) throw new Error(`${agg} lists ${values.length} of ${n} records`);
    return values;
  };
  const prices = deal("current_price", key => (key.includes(".") ? new PyFloat(Number(key)) : Number(key)));
  const titles = deal("labor_category", key => key);
  const clearance = deal("security_clearance", key => key === "true");
  const years = deal("min_years_experience", key => Number(key));
  const worksite = deal("worksite", key => key);
  const education = deal("education_level", key => key);
  const size = deal("business_size", key => key);
  return prices.map((price, i) => ({
    _id: String(base + i),
    _source: {
      security_clearance: clearance[i], vendor_name: vendor, idv_piid: `SYN${base + i}`, business_size: size[i], labor_category: titles[i],
      min_years_experience: years[i], sin: "541611", worksite: worksite[i], education_level: education[i], id: base + i, current_price: price,
      _timestamp: NIGHT.timestamp,
    },
  }));
}

/** Made-up records that reach the tool branches GSA's few recorded answers
 * don't (test/branch-cases.json): a verified exact title with 40 rates (the
 * high/low verdict), one with 25 equal rates (no z-score), a title phrase
 * inside a vendor name (MIXED_SEARCH_FIELDS), 520 titles sharing a word (the
 * 500-title cap: UNVERIFIED_POPULATION), and vendors for the whole-word,
 * multi-match and paging notes. Their names match none of the recorded queries. */
export function branchRecords(): SourceRecord[] {
  const out: SourceRecord[] = [];
  let id = 8_000_000;
  const add = (fields: Record<string, Py>) => {
    id += 1;
    const price = fields.current_price as number;
    out.push({_id: String(id), _source: {
      security_clearance: id % 9 === 0, next_year_price: new PyFloat(Math.round(price * 103) / 100), vendor_name: "BRANCH VENDOR LLC",
      idv_piid: `47QBRANCH${id % 97}`, business_size: id % 3 ? "S" : "O", labor_category: "Branch Title", min_years_experience: id % 15,
      sin: id % 2 ? "541611,54151S" : "541330ENG", worksite: ["Customer_Facility", "Contractor_Facility", "Virtual"][id % 3],
      education_level: ["Bachelors", "Masters", "High School", "PhD"][id % 4], id, _timestamp: NIGHT.timestamp, ...fields,
      current_price: new PyFloat(price),
    }});
  };
  for (let i = 0; i < 40; i++) add({labor_category: "Verified Quantum Auditor", vendor_name: `AUDIT FIRM ${i % 7} LLC`, current_price: 60 + ((i * 37) % 53) + (i % 4) * 0.25});
  for (let i = 0; i < 25; i++) add({labor_category: "Flat Rate Courier", vendor_name: `COURIER CO ${i % 3}`, current_price: 42.5});
  for (let i = 0; i < 12; i++) add({labor_category: `Courier Dispatcher ${i}`, vendor_name: "RAPID COURIER SERVICES, INC.", current_price: 30 + i});
  for (let i = 0; i < 520; i++) add({labor_category: `Gizmo Fitter ${String(i).padStart(3, "0")}`, vendor_name: `GIZMO SHOP ${i % 11}`, current_price: 50 + (i % 90)});
  for (let i = 0; i < 30; i++) add({labor_category: `Zeta Role ${i}`, vendor_name: "MEGAZORPX HOLDINGS", current_price: 70 + i});
  for (let i = 0; i < 8; i++) add({labor_category: `Zeta Role ${i}`, vendor_name: "ZORP INDUSTRIES", current_price: 90 + i});
  for (let i = 0; i < 3; i++) add({labor_category: "Zeta Role 0", vendor_name: "ZORPLAND LLC", current_price: 95 + i});
  return out;
}

// node test/fixture-db.ts OUT.sqlite [--branches]: write the fixture copy (with the branch records) to a file
// (for scripts/parity.py --db).
if ((import.meta as {main?: boolean}).main && process.argv[2]) {
  const records = process.argv.includes("--branches") ? [...fixtureRecords(), ...branchRecords()] : fixtureRecords();
  buildDatabase(records, NIGHT, process.argv[2]).close();
  console.log(`wrote ${process.argv[2]}`);
}
