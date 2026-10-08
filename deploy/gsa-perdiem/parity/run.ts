// Parity harness: sends every request in corpus.json to the Worker (here) and
// to the gsa-perdiem-mcp Python server (python_side.py), with the same GSA
// API fixtures on both sides, and compares the answers.
//
//   cd deploy/gsa-perdiem && node parity/run.ts [--python-results FILE] [--db FILE]
//
// Compared per request: HTTP status; for tool calls content[0].text byte for
// byte, isError, and structuredContent (as JSON); for other methods the whole
// JSON-RPC message. Also the GSA API requests each scenario made (path, key
// header present, User-Agent). Exit status 1 on any unexplained difference.
import {execFileSync} from "node:child_process";
import {readFileSync, writeFileSync} from "node:fs";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {serve} from "../src/mcp.ts";
import {BASE_URL, type CacheLike} from "../src/upstream.ts";
import {ROOT, d1, loadedDatabaseFile} from "../test/d1.ts";

const HERE = new URL(".", import.meta.url);
const corpus = JSON.parse(readFileSync(new URL("corpus.json", HERE), "utf8"));
const arg = (name: string) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : undefined;
};

// Differences that are expected and justified; keyed "scenario#request".
const EXPECTED: Record<string, string> = {};

interface Outcome {name: string; responses: {status: number; body: string}[]; upstream: {path: string; key_header: boolean; user_agent: string | null}[]}

class MemoryCache implements CacheLike {
  private entries = new Map<string, string>();
  async match(request: Request) {
    const hit = this.entries.get(request.url);
    return hit === undefined ? undefined : new Response(hit);
  }
  async put(request: Request, response: Response) {
    this.entries.set(request.url, await response.text());
  }
}

async function workerSide(dbPath: string): Promise<Outcome[]> {
  const db = d1(new DatabaseSync(dbPath));
  const outcomes: Outcome[] = [];
  for (const scenario of corpus.scenarios) {
    const key: string = scenario.key ?? corpus.key;
    db.sqlite.exec("DELETE FROM upstream_calls; UPDATE upstream_state SET next_start = 0, cooldown_until = 0;");
    const fixtures: Record<string, any> = scenario.fixtures ?? {};
    const upstream: Outcome["upstream"] = [];
    const fetchMock = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.startsWith(BASE_URL + "/")) throw new Error("unexpected upstream URL " + url);
      const path = url.slice(BASE_URL.length + 1);
      const headers = new Headers(init?.headers);
      upstream.push({path, key_header: headers.get("x-api-key") === key.trim(), user_agent: headers.get("user-agent")});
      const fixture = fixtures[path];
      if (!fixture) return new Response("no fixture for this path", {status: 404, headers: {"content-type": "text/plain"}});
      if (fixture.error === "connect") throw new TypeError("connection refused");
      if (fixture.error === "timeout") throw new DOMException("The operation timed out.", "TimeoutError");
      // Bytes, so the mock adds no Content-Type the fixture lacks.
      return new Response(new TextEncoder().encode(fixture.body), {status: fixture.status, headers: fixture.headers});
    }) as typeof fetch;
    const env = {DB: db, REQUEST_LIMITER: {limit: async () => ({success: true})}, PERDIEM_API_KEY: key};
    const runtime = {
      now: () => new Date(scenario.today + "T12:00:00Z"),
      cache: new MemoryCache(),
      fetch: fetchMock,
      upstream: {interval: 0, hourlyCap: scenario.hourly_cap ?? 950},
    };
    const responses = [];
    for (const body of scenario.requests) {
      const request = new Request("https://gsa-perdiem.1102tools.com/mcp", {
        method: "POST", body, headers: {"Content-Type": "application/json", Accept: "application/json, text/event-stream"},
      });
      const response = await serve(request, env, runtime);
      responses.push({status: response.status, body: await response.text()});
    }
    outcomes.push({name: scenario.name, responses, upstream});
  }
  return outcomes;
}

function pythonSide(): Outcome[] {
  const file = arg("--python-results");
  if (file) return JSON.parse(readFileSync(file, "utf8"));
  const pkg = join(ROOT, "servers/gsa-perdiem-mcp");
  const out = execFileSync(join(pkg, ".venv/bin/python"), [join(ROOT, "deploy/gsa-perdiem/parity/python_side.py"), join(ROOT, "deploy/gsa-perdiem/parity/corpus.json")], {
    cwd: pkg, env: {...process.env, PYTHONPATH: join(pkg, "src")}, maxBuffer: 1 << 28, encoding: "utf8",
  });
  return JSON.parse(out);
}

function canonical(value: unknown): string {
  return JSON.stringify(value, (_k, v) => (v && typeof v === "object" && !Array.isArray(v)
    ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v));
}

function compare(py: {status: number; body: string}, ts: {status: number; body: string}): string[] {
  const problems: string[] = [];
  if (py.status !== ts.status) problems.push(`HTTP status ${py.status} vs ${ts.status}`);
  let a: any;
  let b: any;
  try {
    a = JSON.parse(py.body);
    b = JSON.parse(ts.body);
  } catch {
    if (py.body !== ts.body) problems.push(`body ${JSON.stringify(py.body.slice(0, 300))} vs ${JSON.stringify(ts.body.slice(0, 300))}`);
    return problems;
  }
  const content = a?.result?.content;
  if (Array.isArray(content)) {
    const textA = content[0]?.text;
    const textB = b?.result?.content?.[0]?.text;
    if (textA !== textB) problems.push(`text differs:\n--- python\n${textA}\n--- worker\n${textB}`);
    if (a.result.isError !== b?.result?.isError) problems.push(`isError ${a.result.isError} vs ${b?.result?.isError}`);
    if (canonical(a.result.structuredContent) !== canonical(b?.result?.structuredContent)) {
      problems.push(`structuredContent differs:\n--- python\n${canonical(a.result.structuredContent)}\n--- worker\n${canonical(b?.result?.structuredContent)}`);
    }
    const rest = (m: any) => canonical({...m, result: {...m.result, content: undefined, structuredContent: undefined, isError: undefined}});
    if (rest(a) !== rest(b)) problems.push(`envelope ${rest(a)} vs ${rest(b)}`);
  } else if (canonical(a) !== canonical(b)) {
    problems.push(`message differs:\n--- python\n${canonical(a).slice(0, 2000)}\n--- worker\n${canonical(b).slice(0, 2000)}`);
  }
  return problems;
}

const dbPath = arg("--db") ?? loadedDatabaseFile();
const worker = await workerSide(dbPath);
const python = pythonSide();
let calls = 0;
let identical = 0;
let expected = 0;
const failures: string[] = [];
corpus.scenarios.forEach((scenario: any, s: number) => {
  scenario.requests.forEach((body: string, r: number) => {
    calls++;
    const problems = compare(python[s].responses[r], worker[s].responses[r]);
    if (!problems.length) {
      identical++;
      return;
    }
    const id = `${s}#${r}`;
    if (EXPECTED[id]) {
      expected++;
      return;
    }
    failures.push(`[${scenario.name} #${r}] ${body}\n${problems.join("\n")}`);
  });
  if (canonical(python[s].upstream) !== canonical(worker[s].upstream)) {
    failures.push(`[${scenario.name}] upstream requests differ:\n--- python\n${JSON.stringify(python[s].upstream)}\n--- worker\n${JSON.stringify(worker[s].upstream)}`);
  }
});
const upstreamCalls = python.reduce((n, o) => n + o.upstream.length, 0);
for (const failure of failures) console.log(failure + "\n");
const summary = {calls, identical, expected_differences: expected, unexplained_differences: failures.length, upstream_calls: upstreamCalls};
console.log(JSON.stringify(summary));
if (arg("--write-python-results")) writeFileSync(arg("--write-python-results")!, JSON.stringify(python));
process.exit(failures.length ? 1 : 0);
