// The Worker side of scripts/parity.py: POST each request body to the Worker
// over a SQLite copy of D1 built by scripts/load_ecfr.py, forwarding what the
// copy can't answer to the Python server at <python-url>, and print one JSON
// line per request with the HTTP status, the raw response body, who answered
// (d1 or forwarded), and how many D1 statements and round trips it took.
//
//   node scripts/parity-run.ts <d1.sqlite> <requests.json> <python-url>
//
// requests.json is a list of {name, body, headers}; parity.py writes it from
// test/parity-cases.json so both servers receive the same bytes and headers.
//
// With PARITY_CACHE=1 the Worker has an answer cache: each request is sent
// twice, the second answer is the one reported (a hit where D1 answered), and
// any difference between the two is flagged. A copy without meta 'version'
// gets one in a temporary copy, since the cache needs it.
import {copyFileSync, mkdtempSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {makeWorker} from "../src/worker.ts";
import {d1} from "../test/d1.ts";

const [database, requestsFile, python] = process.argv.slice(2);
const caching = process.env.PARITY_CACHE === "1";
function open(): DatabaseSync {
  const sqlite = new DatabaseSync(database, {readOnly: true});
  if (!caching || sqlite.prepare("SELECT 1 FROM meta WHERE key = 'version'").get()) return sqlite;
  sqlite.close();
  const path = join(mkdtempSync(join(tmpdir(), "ecfr-parity-")), "d1.sqlite");
  copyFileSync(database, path);
  const copy = new DatabaseSync(path);
  copy.exec("INSERT INTO meta (key, value) VALUES ('version', 'parity')");
  return copy;
}
const db = d1(open());
const store = new Map<string, string>();
const ANSWER_CACHE = {
  match: async (key: Request) => (store.has(key.url) ? new Response(store.get(key.url)) : undefined),
  put: async (key: Request, response: Response) => { store.set(key.url, await response.text()); },
};
const env = {DB: db, REQUEST_LIMITER: {limit: async () => ({success: true})}, RELEASE_SHA: "parity", ...(caching ? {ANSWER_CACHE} : {})};
const requests: {name: string; body: string; headers: Record<string, string>}[] = JSON.parse(readFileSync(requestsFile, "utf8"));

// The Python server receives the request as the client sent it.
const worker = makeWorker(async (request, body) => {
  const headers = new Headers(request.headers);
  headers.delete("content-length");
  const response = await fetch(`${python}/mcp`, {method: "POST", headers, body});
  const forwarded = new Response(await response.arrayBuffer(), {status: response.status, headers: response.headers});
  forwarded.headers.set("X-1102tools-Backend", "forwarded");
  return forwarded;
});

for (const {name, body, headers} of requests) {
  delete headers.host;
  const send = () => worker.fetch(new Request("https://ecfr.1102tools.com/mcp", {method: "POST", headers, body}), env as any);
  const start = db.log.length;
  let response = await send();
  const statements = db.log.slice(start);
  let changed = false;
  if (caching) {
    const first = await response.text();
    response = await send();
    const second = await response.clone().text();
    changed = first !== second;
  }
  console.log(JSON.stringify({name, status: response.status, body: await response.text(),
    backend: response.headers.get("X-1102tools-Backend"), cache: response.headers.get("X-1102tools-Cache"), changed,
    statements: statements.length, round_trips: new Set(statements.map(s => s.batch)).size}));
}
