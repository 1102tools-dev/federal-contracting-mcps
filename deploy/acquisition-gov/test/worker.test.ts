// The Worker over a real snapshot: the small recording test/fixture_recording.py
// writes, loaded by scripts/load_acquisition_gov.py --replay into SQLite and
// read through a D1-shaped adapter. Tool-by-tool parity with the Python server
// is scripts/parity.py; this covers the contract, snapshot handling, D1 use,
// failures, the HTTP edge and the Python string helpers.
//
// ACQ_TEST_DB names a database built that way (the hosted tests workflow builds
// it); otherwise the test builds one with ACQ_PYTHON, the package's .venv, or
// `uv run` in the package's project (as the release workflow runs npm test).
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {copyFileSync, existsSync, mkdtempSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {mock, test} from "node:test";
import {fileURLToPath} from "node:url";
import worker, {callTool, handleMessage} from "../src/worker.ts";
import {casefold} from "../src/casefold.ts";
import {dumps} from "../src/pyjson.ts";
import {cpLen, cpSlice, pySorted, splitlines, squash, strip} from "../src/text.ts";
import {TOOLS} from "../src/tools.ts";
import {d1} from "./d1.ts";

const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const SERVER = JSON.parse(read("../../../servers/acquisition-gov-mcp/server.json"));
const FETCHED_AT = "2026-10-01T12:00:00+00:00";
const UPLOADS = "https://www.acquisition.gov/sites/default/files/page_file_uploads";

function fixtureDatabase(): string {
  if (process.env.ACQ_TEST_DB) return process.env.ACQ_TEST_DB;
  const project = join(ROOT, "servers/acquisition-gov-mcp");
  const venv = join(project, ".venv/bin/python");
  // The loader parses with the package, so it needs the package's dependencies.
  const [python, ...prefix] = process.env.ACQ_PYTHON ? [process.env.ACQ_PYTHON]
    : existsSync(venv) ? [venv] : ["uv", "run", "--frozen", "--python", "3.12", "--project", project, "python"];
  const dir = mkdtempSync(join(tmpdir(), "acquisition-gov-"));
  const options = {stdio: ["ignore", "ignore", "inherit"] as any, env: {...process.env, PYTHONPATH: join(project, "src")}};
  execFileSync(python, [...prefix, join(ROOT, "deploy/acquisition-gov/test/fixture_recording.py"), join(dir, "rec")], options);
  execFileSync(python, [...prefix, join(ROOT, "scripts/load_acquisition_gov.py"), "--local", join(dir, "d1.sqlite"), "--replay", join(dir, "rec")], options);
  return join(dir, "d1.sqlite");
}

const FIXTURE = fixtureDatabase();
/** A private copy of the fixture database, so tests can change it. */
function copy() {
  const path = join(mkdtempSync(join(tmpdir(), "acquisition-gov-copy-")), "d1.sqlite");
  copyFileSync(FIXTURE, path);
  const sqlite = new DatabaseSync(path);
  return {sqlite, db: d1(sqlite)};
}

const db = d1(new DatabaseSync(FIXTURE, {readOnly: true}));
const env = (allow = true, DB: unknown = db) => ({DB, REQUEST_LIMITER: {limit: async () => ({success: allow})}, RELEASE_SHA: "abc123"}) as any;
const call = async (name: string, args: Record<string, unknown>, DB: unknown = db) => await callTool(name, args, env(true, DB)) as any;
const data = async (name: string, args: Record<string, unknown>, DB: unknown = db) => {
  const result = await call(name, args, DB);
  assert.equal(result.isError, false, result.content[0].text);
  assert.equal(result.content[0].text, dumps(result.structuredContent, 2));
  return result.structuredContent;
};
const errorText = async (name: string, args: Record<string, unknown>) => {
  const result = await call(name, args);
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent, undefined);
  return result.content[0].text as string;
};
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://acquisition-gov.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers}, body: typeof body === "string" ? body : JSON.stringify(body)});

// ---------- contract and protocol ----------

test("tools/list is the reviewed contract, verbatim", async () => {
  const contract = JSON.parse(read("../tools-contract.json"));
  assert.deepEqual(TOOLS, contract);
  const list = await handleMessage({jsonrpc: "2.0", id: 1, method: "tools/list"}, env()) as any;
  assert.equal(JSON.stringify(list.result.tools), JSON.stringify(contract));
  assert.equal(TOOLS.length, 5);
  for (const tool of TOOLS) assert.doesNotMatch(tool.description, /\blive\b/i, `${tool.name} promises live data`);
});

test("initialize matches the Python server", async () => {
  const init = await handleMessage({jsonrpc: "2.0", id: 1, method: "initialize", params: {protocolVersion: "2025-11-25", capabilities: {}, clientInfo: {name: "t", version: "1"}}}, env());
  assert.equal(dumps(init), `{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-11-25","serverInfo":{"name":"acquisition-gov","version":"${SERVER.version}"}}}`);
  const unknown = await handleMessage({jsonrpc: "2.0", id: 2, method: "tools/call", params: {name: "nope", arguments: {}}}, env()) as any;
  assert.equal(dumps(unknown.result), `{"content":[{"text":"Unknown tool: nope","type":"text"}],"isError":true}`);
});

// ---------- the snapshot ----------

test("answers come from the snapshot and carry its fetch times", async () => {
  const parts = await data("list_rfo_parts", {});
  assert.deepEqual([parts.count, parts.retrieved_at, parts.results.map((p: any) => p.part)], [2, FETCHED_AT, [10, 12]]);
  const part = await data("get_rfo_part", {part: 10, section: "10.001 policy"});
  assert.deepEqual([part.retrieved_at, part.content, part.issuance_date], [FETCHED_AT, "10.001 Policy\nThis is fixture model text, not codified FAR text.", "2025-05-02"]);
  assert.match(await errorText("get_rfo_part", {part: 11}), /^Error executing tool get_rfo_part: Acquisition.gov returned HTTP 404: <!DOCTYPE html>/);
  const deviations = await data("list_rfo_agency_deviations", {part: 10});
  assert.deepEqual(deviations.results.map((d: any) => d.retrieved_at), [FETCHED_AT, FETCHED_AT, FETCHED_AT]);
  const nsf = deviations.results[2];
  const pdf = await data("get_rfo_agency_deviation", {source_id: nsf.source_id});
  assert.deepEqual([pdf.source_url, pdf.total_pages, pdf.page_end, pdf.index_retrieved_at], [`${UPLOADS}/NASA_RFO_Deviation_Part-10.pdf`, 3, 3, FETCHED_AT]);
  assert.match(pdf.page_numbered_text, /^\[Page 1\]\n/);
});

test("one D1 round trip per call; two for a section, heading or agency filter", async () => {
  const trips = async (name: string, args: Record<string, unknown>) => {
    const start = db.log.length;
    await call(name, args);
    const statements = db.log.slice(start);
    for (const s of statements) assert.ok(s.values.length <= 100, "D1 allows 100 bound parameters");
    return new Set(statements.map(s => s.batch)).size;
  };
  const gsa = (await data("list_rfo_agency_deviations", {agency: "general services", limit: 1})).results[0].source_id;
  assert.equal(await trips("list_rfo_parts", {}), 1);
  assert.equal(await trips("list_rfo_parts", {agency: "aeronautics"}), 2);
  assert.equal(await trips("get_rfo_part", {part: 12}), 1);
  assert.equal(await trips("get_rfo_part", {part: 12, section: "12.101 policy."}), 2);
  assert.equal(await trips("list_rfo_agency_deviations", {part: 10}), 2);
  assert.equal(await trips("get_rfo_agency_deviation", {source_id: gsa, page_start: 1, page_end: 25}), 1);
  assert.equal(await trips("get_rfo_guidance", {resource: "deviation_guidance"}), 1);
  assert.equal(await trips("get_rfo_guidance", {resource: "deviation_guidance", heading: "background"}), 2);
  assert.equal(await trips("get_rfo_part", {part: "x"}), 0);
});

test("a page reads only the text rows it overlaps", async () => {
  const {sqlite, db: local} = copy();
  // Re-split part 12's text into 10-character rows.
  const doc = sqlite.prepare("SELECT doc FROM sources WHERE key = 'part:12' AND snapshot = (SELECT value FROM meta WHERE key = 'current')").get()!.doc as string;
  const text = (sqlite.prepare("SELECT group_concat(body, '') AS t FROM (SELECT body FROM chunks WHERE doc = ? AND stream = 'text' ORDER BY seq)").get(doc)!.t) as string;
  sqlite.prepare("DELETE FROM chunks WHERE doc = ? AND stream = 'text'").run(doc);
  for (let i = 0; i * 10 < text.length; i++) {
    sqlite.prepare("INSERT INTO chunks (doc, stream, seq, start, length, body) VALUES (?, 'text', ?, ?, ?, ?)").run(doc, i, i * 10, Math.min(10, text.length - i * 10), text.slice(i * 10, i * 10 + 10));
  }
  const whole = await data("get_rfo_part", {part: 12}, local);
  assert.equal(whole.content, text.slice(0, 20000));
  const start = local.log.length;
  const page = await data("get_rfo_part", {part: 12, cursor: "15", max_characters: 1000}, local);
  assert.equal(page.content, text.slice(15, 1015));
  const rows = local.log.slice(start).find(s => s.sql.includes("start < ?"))!;
  assert.deepEqual(rows.values.slice(-2), [1015, 15]);
});

test("readers see only the current snapshot; a switch is one statement", async () => {
  const {sqlite, db: local} = copy();
  const before = await data("list_rfo_parts", {}, local);
  // A newer snapshot whose index fetch time differs; switching meta.current moves every reader.
  sqlite.exec(`INSERT INTO sources SELECT 99, key, url, final_url, source_id, '2026-10-02T00:00:00+00:00', content_sha256, error, doc
    FROM sources WHERE snapshot = (SELECT value FROM meta WHERE key = 'current')`);
  assert.equal((await data("list_rfo_parts", {}, local)).retrieved_at, before.retrieved_at);
  sqlite.exec("UPDATE meta SET value = '99' WHERE key = 'current'");
  assert.equal((await data("list_rfo_parts", {}, local)).retrieved_at, "2026-10-02T00:00:00+00:00");
});

test("no snapshot or a D1 failure is a generic tool error without arguments in logs", async () => {
  const logged: string[] = [];
  const original = console.log;
  console.log = (line: string) => logged.push(line);
  try {
    const {sqlite, db: empty} = copy();
    sqlite.exec("DELETE FROM meta");
    assert.equal((await call("list_rfo_parts", {agency: "secret-agency"}, empty)).content[0].text,
      "Error executing tool list_rfo_parts: Acquisition.gov data is temporarily unavailable. Try again shortly.");
    const broken = {prepare: () => { throw new Error("D1 down"); }, batch: () => { throw new Error("D1 down"); }};
    const result = await call("get_rfo_part", {part: 9, section: "secret-section"}, broken);
    assert.deepEqual([result.isError, result.structuredContent], [true, undefined]);
    assert.match(result.content[0].text, /temporarily unavailable/);
  } finally {
    console.log = original;
  }
  assert.equal(logged.length, 2);
  for (const line of logged) {
    assert.equal(JSON.parse(line).event, "tool_failed");
    assert.ok(!line.includes("secret"));
  }
});

// ---------- HTTP ----------

test("HTTP edge: health, docs, origin, rate limit, methods, body limits, message kinds", async () => {
  const url = "https://acquisition-gov.1102tools.com";
  const health = await worker.fetch(new Request(`${url}/health`), env());
  assert.deepEqual(await health.json(), {status: "ok", tools: 5, release_sha: "abc123", admission: {processing: 16, waiting: 32, total: 48, deadline_seconds: 55}});
  const unset = await worker.fetch(new Request(`${url}/health`), {...env(), RELEASE_SHA: undefined});
  assert.equal((await unset.json() as any).release_sha, "development");
  assert.equal((await worker.fetch(new Request(`${url}/`), env())).status, 200);
  assert.equal((await worker.fetch(new Request(`${url}/nope`), env())).status, 404);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized"}), env())).status, 202);
  assert.equal((await worker.fetch(post({}, {Origin: "https://evil.example"}), env())).status, 403);
  assert.equal((await worker.fetch(post({}), env(false))).status, 429);
  assert.equal((await worker.fetch(new Request(`${url}/mcp`), env())).status, 405);
  assert.equal((await worker.fetch(post("{"), env())).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(70000)), env())).status, 413);
  const response = await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "list_rfo_parts", arguments: {part: 10}}}), env());
  const body = JSON.parse(await response.text());
  assert.deepEqual(Object.keys(body.result), ["content", "isError", "structuredContent"]);
});

const META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}};
const modern = (method: string, params: Record<string, unknown> = {}, headers: Record<string, string> = {}) =>
  post({jsonrpc: "2.0", id: 7, method, params: {...params, _meta: META}},
    {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, ...(typeof params.name === "string" ? {"Mcp-Name": params.name} : {}), ...headers});

test("2026-07-28 tool calls and listen streams", async () => {
  const stamp = `"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"acquisition-gov","version":"${SERVER.version}"}}`;
  const result = JSON.parse(await (await worker.fetch(modern("tools/call", {name: "get_rfo_part", arguments: {part: 10}}), env())).text());
  assert.deepEqual(Object.keys(result.result), ["content", "isError", "resultType", "structuredContent", "_meta"]);
  const error = await (await worker.fetch(modern("tools/call", {name: "get_rfo_part", arguments: {part: 11}}), env())).text();
  assert.ok(error.endsWith(`"isError":true,"resultType":"complete",${stamp}}}`));
  // Fake timers, so the stream's 15-second keepalive does not hold the test open.
  mock.timers.enable({apis: ["setTimeout"]});
  try {
    const response = await worker.fetch(modern("subscriptions/listen", {notifications: {toolsListChanged: true}}), env());
    assert.equal(response.headers.get("Content-Type"), "text/event-stream");
    const reader = response.body!.getReader();
    const first = new TextDecoder().decode((await reader.read()).value);
    assert.match(first, /^event: message\r\ndata: \{"jsonrpc":"2.0","method":"notifications\/subscriptions\/acknowledged"/);
    await new Promise(resolve => setImmediate(resolve));
    await reader.cancel();
  } finally {
    mock.timers.reset();
  }
});

// ---------- Python string helpers ----------

test("casefold, whitespace, splitlines, code points and sorting match Python", () => {
  assert.equal(casefold("Stra\u00dfe \u03a3\u0391\u03a3 \ufb01x \u13a0 \u01c5"), "strasse \u03c3\u03b1\u03c3 fix \u13a0 \u01c6");
  assert.equal(strip("\x1c\u3000 a b \x85"), "a b");
  assert.equal(squash("  a\t\u2003b\nc  "), "a b c");
  assert.equal(squash("\ufeffa"), "\ufeffa", "U+FEFF is not whitespace in Python");
  assert.deepEqual(splitlines("a\r\nb\rc\x1cd\u2028e\n"), ["a", "b", "c", "d", "e"]);
  assert.deepEqual([splitlines(""), splitlines("\n"), splitlines("a\n\nb")], [[], [""], ["a", "", "b"]]);
  assert.equal(cpLen("a\u{1f600}b"), 3);
  assert.equal(cpSlice("a\u{1f600}bc", 1, 3), "\u{1f600}b");
  assert.deepEqual(pySorted(["b", "\u{1f600}", "\uffff", "B"]), ["B", "b", "\uffff", "\u{1f600}"]);
});

test("timestamp letterhead precedes the attached original's standalone date", async () => {
  const source_id = "agency-deviation-20da883fc4477be46f14";
  for (const page_end of [7, 8]) {
    const result = await data("get_rfo_agency_deviation", {source_id, page_start: 7, page_end});
    assert.equal(result.issuance_date, "2026-02-20");
  }
  const original = await data("get_rfo_agency_deviation", {source_id, page_start: 8, page_end: 8});
  assert.equal(original.issuance_date, "2025-09-26");
});
