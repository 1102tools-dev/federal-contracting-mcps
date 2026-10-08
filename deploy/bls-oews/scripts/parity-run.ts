// The Worker side of scripts/parity.py: POST each case to the Worker over a
// SQLite file built by scripts/load_bls_oews.py --local, and print one JSON
// line per case with the HTTP status and raw response body.
//
//   node scripts/parity-run.ts <d1.sqlite> <cases.json>
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import worker from "../src/worker.ts";
import {d1} from "../test/d1.ts";

const [database, casesFile] = process.argv.slice(2);
const db = d1(new DatabaseSync(database, {readOnly: true}));
const env = {DB: db, REQUEST_LIMITER: {limit: async () => ({success: true})}, RELEASE_SHA: "parity"};
const cases: {name: string; method?: string; params?: unknown; tool?: string; arguments?: unknown}[] = JSON.parse(readFileSync(casesFile, "utf8"));

for (const item of cases) {
  const params = item.tool ? {name: item.tool, arguments: item.arguments} : item.params;
  const body = JSON.stringify({jsonrpc: "2.0", id: 1, method: item.method ?? "tools/call", params});
  const start = db.log.length;
  const response = await worker.fetch(new Request("https://bls-oews.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json"}, body}), env as any);
  const statements = db.log.slice(start);
  console.log(JSON.stringify({name: item.name, status: response.status, body: await response.text(),
    statements: statements.length, round_trips: new Set(statements.map(s => s.batch)).size}));
}
