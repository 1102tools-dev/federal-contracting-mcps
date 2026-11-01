// The emulator against GSA's own answers: every query in one or more
// recordings (scripts/load_gsa_calc.py's format: manifest.jsonl +
// bodies/NNNNN.json.gz; the full pull, the probes, parity.py --record) is
// answered by emulate() over a local copy of the same night, and the two
// answers compared part by part:
//
// - status, top-level keys, hits.total: exact.
// - hits: the same sort values in the same order, and at each sort value the
//   same records (GSA's ties come back in shard order); a tie group cut by the
//   page edge only needs the same size. Each record's _source byte for byte.
// - aggregations: terms buckets, wage_stats and education_level_counts exact
//   (std devs and variances within 1e-9 relative); percentiles and the
//   histogram are measured, not required (GSA's TDigest and 5-shard
//   clustering). Terms with GSA error bounds above 0 are approximate on GSA's
//   side and counted apart.
// - documented GSA noise, counted apart: sum_of_squares one unit in the last
//   place off the exactly rounded sum (GSA adds shard partials with Kahan
//   summation), and terminated_early: true on some suggest-contains answers.
//
//   node scripts/compare-emulator.ts <d1.sqlite> <recording dir>... [--json report.json] [--only TEXT] [--show N]
//
// Exits 1 if any answer differs in a part that must be exact.
import {gunzipSync} from "node:zlib";
import {readFileSync, writeFileSync} from "node:fs";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {emulate} from "../src/emulator.ts";
import {PyFloat, dumps, parseJson} from "../src/pyjson.ts";
import {d1} from "../test/d1.ts";

const args = process.argv.slice(2);
const flag = (name: string) => {
  const i = args.indexOf(name);
  if (i < 0) return undefined;
  const [value] = args.splice(i, 2).slice(1);
  return value;
};
const jsonOut = flag("--json");
const only = flag("--only");
const show = Number(flag("--show") ?? "20");
const [database, ...recordings] = args;
if (!database || !recordings.length) throw new Error("usage: node scripts/compare-emulator.ts <d1.sqlite> <recording dir>... [--json F] [--only TEXT] [--show N]");
const sqlite = new DatabaseSync(database, {readOnly: true});
const db = d1(sqlite);
const version = (sqlite.prepare("SELECT value FROM meta WHERE key = 'version'").get() as {value?: string} | undefined)?.value;

type Obj = Record<string, any>;
const num = (v: unknown) => (v instanceof PyFloat ? v.value : typeof v === "number" ? v : NaN);
const MEASURED = new Set(["histogram_percentiles", "median_price", "wage_histogram"]);
const NEAR = new Set(["variance", "variance_population", "variance_sampling", "std_deviation", "std_deviation_population", "std_deviation_sampling",
  "upper", "lower", "upper_population", "lower_population", "upper_sampling", "lower_sampling"]);

/** Differences in the parts that must be exact (empty when none), and measured ones. */
function compare(query: string, gsa: Obj, ours: Obj): {exact: string[]; approximate: string[]; measured: Obj} {
  const exact: string[] = [];
  const approximate: string[] = [];
  const measured: Obj = {};
  const noise: string[] = [];
  const keys = (o: Obj) => Object.keys(o).filter(k => k !== "terminated_early");
  if ("terminated_early" in gsa) noise.push("terminated_early");
  if (dumps(keys(gsa)) !== dumps(keys(ours))) exact.push(`keys ${dumps(Object.keys(gsa))} vs ${dumps(Object.keys(ours))}`);
  if (dumps(gsa.hits?.total) !== dumps(ours.hits?.total)) exact.push(`hits.total ${dumps(gsa.hits?.total)} vs ${dumps(ours.hits?.total)}`);
  if (dumps(gsa.hits?.max_score) !== dumps(ours.hits?.max_score)) exact.push(`hits.max_score ${dumps(gsa.hits?.max_score)} vs ${dumps(ours.hits?.max_score)}`);
  // Hits, up to ties.
  const theirs: Obj[] = gsa.hits?.hits ?? [];
  const mine: Obj[] = ours.hits?.hits ?? [];
  if (theirs.length !== mine.length) exact.push(`${theirs.length} hits vs ${mine.length}`);
  else {
    if (dumps(theirs.map(h => h.sort)) !== dumps(mine.map(h => h.sort))) exact.push("hit sort values differ");
    const groups = (hits: Obj[]) => {
      const out: [string, string[]][] = [];
      for (const h of hits) {
        const key = dumps(h.sort);
        if (out.length && out[out.length - 1][0] === key) out[out.length - 1][1].push(h._id);
        else out.push([key, [h._id]]);
      }
      return out.map(([k, ids]) => [k, ids.sort()] as [string, string[]]);
    };
    const [a, b] = [groups(theirs), groups(mine)];
    const page = Number(new URLSearchParams(query).get("page") ?? "1");
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const edge = i === a.length - 1 || (i === 0 && page > 1);
      if (dumps(a[i][1]) === dumps(b[i][1])) continue;
      if (edge && a[i][1].length === b[i][1].length) noise.push("tie cut by the page edge");
      else exact.push(`records at sort ${a[i][0]} differ`);
    }
    if (dumps(theirs.map(h => h._id)) !== dumps(mine.map(h => h._id))) noise.push("tie order");
    const sources = new Map(theirs.map(h => [h._id, dumps({...h, sort: undefined})]));
    for (const h of mine) {
      const expected = sources.get(h._id);
      if (expected !== undefined && expected !== dumps({...h, sort: undefined})) exact.push(`hit ${h._id} differs`);
    }
  }
  const aggs: Obj = gsa.aggregations ?? {};
  const mineAggs: Obj = ours.aggregations ?? {};
  if (dumps(Object.keys(aggs)) !== dumps(Object.keys(mineAggs))) exact.push(`aggregations ${dumps(Object.keys(aggs))} vs ${dumps(Object.keys(mineAggs))}`);
  for (const [name, value] of Object.entries(aggs)) {
    const other = mineAggs[name];
    if (dumps(value) === dumps(other)) continue;
    if (MEASURED.has(name)) {
      if (name === "wage_histogram") {
        measured.histogram = {gsa: value.buckets.length, ours: other?.buckets?.length ?? 0};
      } else {
        const diffs = Object.entries(value.values as Obj).map(([q, v]) => Math.abs(num(v) - num(other?.values?.[q])));
        measured[name] = Math.max(...diffs.filter(d => !Number.isNaN(d)), 0);
      }
      continue;
    }
    if (name === "wage_stats") {
      for (const [key, v] of Object.entries(value as Obj)) {
        const o = other?.[key];
        if (key === "std_deviation_bounds") {
          for (const [b, bv] of Object.entries(v as Obj)) {
            if (dumps(bv) !== dumps(o?.[b]) && !(Math.abs(num(bv) - num(o?.[b])) <= 1e-9 * Math.abs(num(bv)))) exact.push(`wage_stats.${b} ${dumps(bv)} vs ${dumps(o?.[b])}`);
          }
        } else if (key === "sum_of_squares" && dumps(v) !== dumps(o) && Math.abs(num(v) - num(o)) <= ulp(num(v))) {
          noise.push("sum_of_squares last digit");
        } else if (dumps(v) !== dumps(o) && !(NEAR.has(key) && Math.abs(num(v) - num(o)) <= 1e-9 * Math.abs(num(v)))) {
          exact.push(`wage_stats.${key} ${dumps(v)} vs ${dumps(o)}`);
        }
      }
      continue;
    }
    // Terms: GSA's own counts are approximate when its error bound is above 0
    // (5 shards, each sending its top list). GSA then undercounts, never
    // overcounts: a key both lists hold must not have more records in GSA's
    // answer. (On night 1, 28 answers undercount by 1 or 2 more than GSA's
    // stated bound; counted apart.)
    const bound = value?.doc_count_error_upper_bound ?? 0;
    const counts = new Map<string, number>((other?.buckets ?? []).map((b: Obj) => [b.key, b.doc_count]));
    const shared = (value?.buckets ?? []).filter((b: Obj) => counts.has(b.key));
    const over = shared.filter((b: Obj) => b.doc_count > counts.get(b.key)!);
    if (bound > 0 && !over.length) {
      approximate.push(name);
      if (shared.some((b: Obj) => counts.get(b.key)! > b.doc_count + bound)) noise.push(`${name} undercount beyond GSA's stated bound`);
    } else {
      exact.push(`${name} differs${over.length ? ` (GSA counts more: ${over.slice(0, 3).map((b: Obj) => `${dumps(b.key)} ${b.doc_count} vs ${counts.get(b.key)}`).join(", ")})` : ""}`);
    }
  }
  return {exact, approximate, measured, noise};
}

/** One unit in the last place of a double. */
function ulp(x: number): number {
  const a = Math.abs(x);
  if (!Number.isFinite(a)) return NaN;
  const e = Math.max(Math.floor(Math.log2(a)), -1022);
  let u = 2 ** (e - 52);
  // log2 can land one off near powers of two.
  if (a / 2 ** e >= 2) u *= 2;
  else if (a / 2 ** e < 1) u /= 2;
  return u;
}

const rows: Obj[] = [];
const indexes = new Set<string>();
for (const dir of recordings) {
  const entries = new Map<string, Obj>();
  for (const line of readFileSync(join(dir, "manifest.jsonl"), "utf8").split("\n")) if (line.trim()) entries.set(JSON.parse(line).query, JSON.parse(line));
  for (const [query, entry] of entries) {
    if (only && !query.includes(only)) continue;
    // An answer from another night's index can't match this copy.
    if (entry.index && version && entry.index !== version) {
      rows.push({query, kind: "other night", index: entry.index});
      continue;
    }
    const text = gunzipSync(readFileSync(join(dir, "bodies", `${String(entry.n).padStart(5, "0")}.json.gz`))).toString("utf8");
    let answer;
    try {
      answer = await emulate(db, query.replace(/^repeat:/, ""), {took: 0});
    } catch (error) {
      rows.push({query, kind: "different", exact: [`emulator failed: ${(error as Error).message}`]});
      continue;
    }
    if (entry.status !== 200 || !("body" in answer)) {
      const same = entry.status === answer.status;
      rows.push({query, kind: same ? "identical" : "different", exact: same ? [] : [`status ${entry.status} vs ${answer.status}`],
        gsa_text: entry.status !== 200 ? text.slice(0, 200) : undefined});
      continue;
    }
    const gsa = parseJson(text) as Obj;
    for (const h of gsa.hits?.hits ?? []) if (h._index) indexes.add(h._index);
    const ours = {...answer.body, took: gsa.took};
    if (dumps(gsa) === dumps(ours)) {
      rows.push({query, kind: "identical"});
      continue;
    }
    const result = compare(query, gsa, ours);
    const kind = result.exact.length ? "different" : result.approximate.length ? "gsa-approximate"
      : Object.keys(result.measured).length ? "percentiles/histogram only" : result.noise.length ? "gsa noise only" : "identical";
    const categories = [...(result.exact.length ? ["different"] : []), ...result.approximate.map(a => `gsa-approximate ${a}`),
      ...Object.keys(result.measured).map(m => `measured ${m}`), ...new Set(result.noise.map(n => `noise ${n}`))];
    rows.push({query, kind, categories, ...result});
  }
}

const counts: Record<string, number> = {};
for (const row of rows) counts[row.kind] = (counts[row.kind] ?? 0) + 1;
const percentileGaps = rows.flatMap(r => [r.measured?.histogram_percentiles, r.measured?.median_price]).filter(x => typeof x === "number") as number[];
const histogramRows = rows.filter(r => r.measured?.histogram).length;
if (indexes.size && (indexes.size > 1 || !indexes.has(version ?? ""))) console.log(`WARNING: recordings are from ${[...indexes].join(", ")}; the copy is ${version}`);
for (const row of rows.filter(r => r.kind === "different").slice(0, show)) console.log(`DIFF ${row.query}\n  ${row.exact.slice(0, 6).join("\n  ")}`);
console.log(`${rows.length} recorded answers: ${Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ")}.`);
if (percentileGaps.length) {
  const sorted = [...percentileGaps].sort((a, b) => a - b);
  console.log(`Percentiles differ in ${percentileGaps.length} aggregations: median gap $${sorted[Math.floor(sorted.length / 2)].toFixed(4)}, `
    + `max $${sorted[sorted.length - 1].toFixed(4)}. Histograms differ in ${histogramRows} answers.`);
}
const byCategory: Record<string, number> = {};
for (const row of rows) for (const c of row.categories ?? []) byCategory[c] = (byCategory[c] ?? 0) + 1;
console.log(`Answers per category (one answer can be in several): ${Object.entries(byCategory).sort().map(([k, n]) => `${k} ${n}`).join("; ")}.`);
if (jsonOut) writeFileSync(jsonOut, JSON.stringify({version, indexes: [...indexes], counts, rows}, null, 1) + "\n");
process.exitCode = counts.different ? 1 : 0;
