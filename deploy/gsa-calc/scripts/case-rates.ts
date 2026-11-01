// p25/p50/p75 of igce_benchmark for each title, from a local copy (for
// scripts/make_parity_cases.py --db, which places price-check rates there).
//
//   node scripts/case-rates.ts <d1.sqlite> '["Project Manager", ...]'
import {DatabaseSync} from "node:sqlite";
import {callTool} from "../src/rpc.ts";
import {d1} from "../test/d1.ts";

const [database, titles] = process.argv.slice(2);
const env = {DB: d1(new DatabaseSync(database, {readOnly: true})), REQUEST_LIMITER: {limit: async () => ({success: true})}} as any;
const out: Record<string, (number | null)[]> = {};
for (const title of JSON.parse(titles) as string[]) {
  const result = await callTool("igce_benchmark", {labor_category: title}, env) as any;
  const p = result.structuredContent?.percentiles ?? {};
  out[title] = [p.p25, p.p50_median, p.p75].map(v => (v === null || v === undefined ? null : Number(v.value ?? v)));
}
console.log(JSON.stringify(out));
