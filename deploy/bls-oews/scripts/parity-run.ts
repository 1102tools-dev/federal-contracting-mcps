// The Worker side of scripts/parity.py: POST each request body to the Worker
// over a SQLite file built by scripts/load_bls_oews.py --local, and print one
// JSON line per request with the HTTP status, the raw response body, and how
// many D1 statements and round trips it took.
//
//   node scripts/parity-run.ts <d1.sqlite> <requests.json>
//
// requests.json is a list of {name, body}; parity.py writes it from
// test/parity-cases.json so both servers receive the same bytes.
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import worker from "../src/worker.ts";
import {d1} from "../test/d1.ts";

const [database, requestsFile] = process.argv.slice(2);
const db = d1(new DatabaseSync(database, {readOnly: true}));
const env = {DB: db, REQUEST_LIMITER: {limit: async () => ({success: true})}, RELEASE_SHA: "parity"};
const requests: {name: string; body: string}[] = JSON.parse(readFileSync(requestsFile, "utf8"));

for (const {name, body} of requests) {
  const start = db.log.length;
  const response = await worker.fetch(new Request("https://bls-oews.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json"}, body}), env as any);
  const statements = db.log.slice(start);
  console.log(JSON.stringify({name, status: response.status, body: await response.text(),
    statements: statements.length, round_trips: new Set(statements.map(s => s.batch)).size}));
}
