// D1 cost check: copies a local D1 copy (scripts/load_bls_oews.py --local)
// into Miniflare's D1 (the workerd SQLite that D1 runs on), calls each tool
// the way clients do, and prints the rows D1 reports reading and writing per
// call, plus each statement's query plan.
//
//   node scripts/rows-read.ts <d1.sqlite>
import {DatabaseSync} from "node:sqlite";
import {Miniflare, convertV4MiniflareOptions} from "miniflare";
import {callTool} from "../src/worker.ts";

const source = new DatabaseSync(process.argv[2], {readOnly: true});
const mf = new Miniflare(convertV4MiniflareOptions({modules: true, script: "export default {fetch() { return new Response(null); }}", d1Databases: {DB: "bls-oews"}}));
const d1 = await mf.getD1Database("DB");

// Copy every table with literal multi-row INSERTs under D1's statement limit.
const quote = (v: unknown) => (v === null ? "NULL" : typeof v === "number" ? String(v) : `'${String(v).replaceAll("'", "''")}'`);
for (const {sql} of source.prepare("SELECT sql FROM sqlite_master WHERE type = 'table'").all() as {sql: string}[]) await d1.prepare(sql).run();
for (const {name} of source.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all() as {name: string}[]) {
  let rows: string[] = [];
  let size = 0;
  const flush = async () => {
    if (rows.length) await d1.prepare(`INSERT INTO ${name} VALUES ${rows.join(",")}`).run();
    rows = [];
    size = 0;
  };
  for (const row of source.prepare(`SELECT * FROM ${name}`).iterate() as Iterable<Record<string, unknown>>) {
    const values = `(${Object.values(row).map(quote).join(",")})`;
    if (size + values.length > 90_000) await flush();
    rows.push(values);
    size += values.length + 1;
  }
  await flush();
}

// The Worker's D1 calls, recorded with D1's own meta.
type Meta = {rows_read: number; rows_written: number};
let metas: Meta[] = [];
let trips = 0;
let plans = new Map<string, string>();
const wrap = (statement: any, sql: string, values: unknown[] = []): any => ({
  real: statement, sql, values,
  bind: (...next: unknown[]) => wrap(statement.bind(...next), sql, next),
  all: async () => {
    trips++;
    const result = await statement.all();
    metas.push(result.meta);
    return result;
  },
});
const DB = {
  prepare: (sql: string) => wrap(d1.prepare(sql), sql),
  batch: async (statements: any[]) => {
    trips++;
    const results = await d1.batch(statements.map(s => s.real));
    for (const [i, result] of results.entries()) {
      metas.push(result.meta as Meta);
      const shape = statements[i].sql.replace(/\?(, \?)*/g, "?…");
      if (!plans.has(shape)) {
        const plan = source.prepare(`EXPLAIN QUERY PLAN ${statements[i].sql}`).all(...(statements[i].values as any[])) as {detail: string}[];
        plans.set(shape, plan.map(p => p.detail).join("; "));
      }
    }
    return results;
  },
};
const env = {DB, REQUEST_LIMITER: {limit: async () => ({success: true})}};

const fifty = Array.from({length: 50}, (_, i) => String(10000 + i * 20));
const CALLS: [string, Record<string, unknown>][] = [
  ["get_data_status", {}],
  ["detect_latest_year", {}],
  ["list_common_soc_codes", {}],
  ["get_wage_data", {occ_code: "151252"}],
  ["get_wage_data", {occ_code: "151252", scope: "metro", area_code: "47900", datatypes: Array.from({length: 17}, (_, i) => String(i + 1).padStart(2, "0"))}],
  ["get_wage_data", {occ_code: "151252", year: 2025}],
  ["compare_metros", {occ_code: "151252", metro_codes: ["47900", "42660", "12580"]}],
  ["compare_metros", {occ_code: "151252", metro_codes: fifty}],
  ["compare_occupations", {occ_codes: ["151252", "151212", "131082", "152051"], scope: "state", area_code: "51"}],
  ["igce_wage_benchmark", {occ_code: "151252", scope: "metro", area_code: "47900"}],
  ["get_wage_data", {occ_code: "bad"}],
];
console.log("call | D1 round trips | rows read | rows written");
for (const [name, args] of CALLS) {
  metas = [];
  trips = 0;
  const result = await callTool(name, args, env as any);
  const read = metas.reduce((n, m) => n + m.rows_read, 0);
  const written = metas.reduce((n, m) => n + m.rows_written, 0);
  console.log(`${name} ${JSON.stringify(args).slice(0, 70)} | ${trips} (${metas.length} statements) | ${read} | ${written}${result.isError ? " (tool error)" : ""}`);
}
console.log("\nquery plans (on the full local copy):");
for (const [shape, plan] of plans) console.log(`- ${shape}\n    ${plan}`);
await mf.dispose();
