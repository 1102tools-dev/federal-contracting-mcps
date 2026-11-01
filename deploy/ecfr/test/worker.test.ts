// The Worker over a real copy: the small recording test/fixture_recording.py
// writes, built by scripts/load_ecfr.py build into SQLite and read through a
// D1-shaped adapter. Tool-by-tool parity with the Python server is
// scripts/parity.py; this covers the contract, D1 use, what is forwarded and
// how, failures, the HTTP edge, staging's FORWARD_URL and the Python helpers.
//
// ECFR_TEST_DB names a database built that way (the hosted tests workflow builds
// it); otherwise the test builds one with ECFR_PYTHON, the package's .venv, or
// `uv run` in the package's project.
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {copyFileSync, existsSync, mkdtempSync, readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {mock, test} from "node:test";
import {fileURLToPath} from "node:url";
import {TURNED_AWAY_HEADER} from "../../shared/edge.ts";
import {Forward} from "../src/args.ts";
import {sizeOf} from "../src/assemble.ts";
import {toForwardUrl} from "../src/forward.ts";
import {dumps} from "../src/pyjson.ts";
import {pyInt} from "../src/text.ts";
import {LIVE_TOOLS, TOOLS} from "../src/tools.ts";
import {checkTitle48Chapter, coerceCfrStr, validateDate} from "../src/validate.ts";
import {answerKey} from "../src/rpc.ts";
import {callTool, handleMessage, makeWorker} from "../src/worker.ts";
import {d1} from "./d1.ts";

const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const SERVER = JSON.parse(read("../../../servers/ecfr-mcp/server.json"));

function fixtureDatabase(): string {
  if (process.env.ECFR_TEST_DB) return process.env.ECFR_TEST_DB;
  const project = join(ROOT, "servers/ecfr-mcp");
  const venv = join(project, ".venv/bin/python");
  // The loader parses with the package, so it needs the package's dependencies.
  const [python, ...prefix] = process.env.ECFR_PYTHON ? [process.env.ECFR_PYTHON]
    : existsSync(venv) ? [venv] : ["uv", "run", "--frozen", "--python", "3.12", "--project", project, "python"];
  const dir = mkdtempSync(join(tmpdir(), "ecfr-"));
  const options = {stdio: ["ignore", "ignore", "inherit"] as any, env: {...process.env, PYTHONPATH: join(project, "src")}};
  execFileSync(python, [...prefix, join(ROOT, "deploy/ecfr/test/fixture_recording.py"), join(dir, "rec")], options);
  execFileSync(python, [...prefix, join(ROOT, "scripts/load_ecfr.py"), "build", "--rec", join(dir, "rec"), "--local", join(dir, "d1.sqlite")], options);
  return join(dir, "d1.sqlite");
}

const FIXTURE = fixtureDatabase();
const db = d1(new DatabaseSync(FIXTURE, {readOnly: true}));
/** A private copy of the fixture database, so tests can change it. */
function copy() {
  const path = join(mkdtempSync(join(tmpdir(), "ecfr-copy-")), "d1.sqlite");
  copyFileSync(FIXTURE, path);
  const sqlite = new DatabaseSync(path);
  return {sqlite, db: d1(sqlite)};
}

/** The answer cache's test double (deployed Workers use caches.default). */
function memoryCache() {
  const store = new Map<string, {body: string; control: string}>();
  return {
    store,
    match: async (key: Request) => {
      const entry = store.get(key.url);
      return entry ? new Response(entry.body, {headers: {"Cache-Control": entry.control}}) : undefined;
    },
    put: async (key: Request, response: Response) => { store.set(key.url, {body: await response.text(), control: response.headers.get("Cache-Control") ?? ""}); },
  };
}
const env = (allow = true, DB: unknown = db, extra: Record<string, unknown> = {}) =>
  ({DB, REQUEST_LIMITER: {limit: async () => ({success: allow})}, RELEASE_SHA: "abc123", ...extra}) as any;
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
const forwards = async (name: string, args: Record<string, unknown>, DB: unknown = db) =>
  await assert.rejects(call(name, args, DB), (error: unknown) => error instanceof Forward);
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://ecfr.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers}, body: typeof body === "string" ? body : JSON.stringify(body)});
const toolCall = (name: string, args: Record<string, unknown>, id = 1) => ({jsonrpc: "2.0", id, method: "tools/call", params: {name, arguments: args}});

/** A Worker whose forwarded requests are recorded and answered with a marker. */
function recordingWorker() {
  const sent: {body: string; headers: Headers}[] = [];
  const worker = makeWorker(async (request, body) => {
    sent.push({body: new TextDecoder().decode(body!), headers: request.headers});
    return new Response('{"forwarded":true}', {headers: {"Content-Type": "application/json", "X-1102tools-Backend": "origin"}});
  });
  return {worker, sent};
}

// ---------- contract and protocol ----------

test("tools/list is the reviewed contract, sorted by name", async () => {
  const contract = JSON.parse(read("../tools-contract.json"));
  const sorted = [...contract].sort((a, b) => (a.name < b.name ? -1 : 1));
  assert.deepEqual(TOOLS, sorted);
  const list = await handleMessage({jsonrpc: "2.0", id: 1, method: "tools/list"}, env()) as any;
  assert.equal(JSON.stringify(list.result.tools), JSON.stringify(sorted));
  assert.equal(TOOLS.length, 13);
  assert.deepEqual([...LIVE_TOOLS].sort(), ["compare_versions", "find_recent_changes", "get_corrections", "get_version_history", "search_cfr"]);
});

test("initialize matches the Python server", async () => {
  const init = await handleMessage({jsonrpc: "2.0", id: 1, method: "initialize", params: {protocolVersion: "2025-11-25", capabilities: {}, clientInfo: {name: "t", version: "1"}}}, env());
  assert.equal(dumps(init), `{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-11-25","serverInfo":{"name":"ecfr","version":"${SERVER.version}"}}}`);
  const unknown = await handleMessage({jsonrpc: "2.0", id: 2, method: "tools/call", params: {name: "nope", arguments: {}}}, env()) as any;
  assert.equal(dumps(unknown.result), `{"content":[{"text":"Unknown tool: nope","type":"text"}],"isError":true}`);
});

// ---------- answers from the copy ----------

test("answers come from the copy, at its date", async () => {
  const latest = await data("get_latest_date", {});
  assert.deepEqual([latest.title, latest.up_to_date_as_of, latest.reserved], [48, "2026-10-29", false]);
  assert.match(await errorText("get_latest_date", {title_number: 35}), /^Error executing tool get_latest_date: Title 35 has no available content \(reserved=True\)\./);
  // 2.101 is over 85,000 bytes of content, so the loader stored it in chunks.
  const chunked = (db as any).log.length;
  const definitions = await data("get_cfr_content", {section: "FAR 2.101(b)"});
  assert.ok((db as any).log.slice(chunked).some((s: any) => s.sql.includes("JOIN chunks")));
  assert.deepEqual([definitions.section, definitions.page, definitions.date], ["2.101", 1, "2026-10-29"]);
  assert.ok(definitions.total_pages > 1);
  assert.equal(definitions.hierarchy_metadata[0].url, "https://www.ecfr.gov/on/2026-10-29/title-48/section-2.101");
  const clause = await data("lookup_far_clause", {section_id: "FAR 52.212–3(b)"});
  assert.deepEqual([clause.section, clause.chapter, clause.title], ["52.212-3", "1", 48]);
  const subpart = await data("get_cfr_content", {subpart: "Subpart 15.3"});
  assert.deepEqual([subpart.section_count, subpart.sections[0].section], [9, "15.300"]);
  const pending = await data("get_cfr_content", {section: "3052.225-71"});
  assert.match(pending.warning, /^eCFR links an amendment to this text/);
  const appendix = await data("get_cfr_content", {appendix: "Appendix A to Chapter 2", chapter: "2"});
  assert.deepEqual(appendix.tables[0].rows, [["Rule", "Title"], ["1", "Appeals"], ["2", "Notice [fn 1]"]]);
  const sections = await data("list_sections_in_part", {part_number: "FAR Part 15"});
  assert.deepEqual([sections.chapter, sections.section_count, sections.subparts[0].first_section], ["1", 9, "15.300"]);
  const ancestry = await data("get_ancestry", {section: "15.305"});
  assert.deepEqual(ancestry.ancestors.map((a: any) => a.type), ["title", "chapter", "subchapter", "part", "subpart", "section"]);
  const tree = await data("get_cfr_structure", {chapter: "1", depth: 1});
  assert.equal(tree.children[0].children[0].children_omitted, 1);
  const surety = await data("find_far_definition", {term: "individual surety"});
  assert.equal(surety.matches[0].kind, "definition");
  const agencies = await data("list_agencies", {});
  assert.deepEqual(agencies.agencies[0].cfr_references, [{title: 2, chapter: "XI"}, {title: 48, chapter: "2"}]);
});

test("one D1 round trip per tool call", async () => {
  const trips = async (name: string, args: Record<string, unknown>) => {
    const start = (db as any).log.length;
    await call(name, args);
    const statements = (db as any).log.slice(start);
    for (const s of statements) assert.ok(s.values.length <= 100, "D1 allows 100 bound parameters");
    return new Set(statements.map((s: any) => s.batch)).size;
  };
  assert.equal(await trips("get_latest_date", {}), 1);
  assert.equal(await trips("list_agencies", {summary_only: false}), 1);
  assert.equal(await trips("get_cfr_content", {section: "2.101", page: 2}), 1);
  assert.equal(await trips("get_cfr_content", {part: "52", page: 2}), 1);
  assert.equal(await trips("lookup_far_clause", {section_id: "15.305"}), 1);
  assert.equal(await trips("get_cfr_structure", {part: "15"}), 1);
  assert.equal(await trips("get_cfr_structure", {}), 1);
  assert.equal(await trips("get_ancestry", {appendix: "Appendix A to Chapter 2"}), 1);
  assert.equal(await trips("list_sections_in_part", {part_number: "52", detail: true}), 1);
  assert.equal(await trips("find_far_definition", {term: "supplies"}), 1);
  // Validation errors never reach D1.
  assert.equal(await trips("get_cfr_content", {section: "15.305", page: 0}), 0);
});

// ---------- what is forwarded ----------

test("questions the copy can't answer exactly are forwarded", async () => {
  await forwards("get_version_history", {section: "15.305"});
  await forwards("search_cfr", {query: "x"});
  await forwards("get_cfr_content", {section: "15.305", date: "2026-10-01"});
  await forwards("get_cfr_content", {section: "15.305", raw_xml: true});
  await forwards("get_cfr_content", {section: "15.399"});
  await forwards("get_cfr_content", {chapter: "1"});
  await forwards("get_cfr_content", {part: "15", section: "15.305", subpart: "15.4"});
  await forwards("get_latest_date", {title_number: 13});
  await forwards("get_cfr_structure", {appendix: "appendix a to chapter 2", chapter: "2"});
  await forwards("find_far_definition", {term: "xyzzy plugh"});
  // Inputs that fail validation are answered here, even with raw_xml.
  assert.match(await errorText("get_cfr_content", {section: "15.305", raw_xml: true, page: 0}), /page must be >= 1\. Got 0\./);
  assert.match(await errorText("get_cfr_content", {title_number: 35, section: "1.1"}), /Cannot resolve a date for title 35: this title is marked 'reserved'/);
});

test("a forwarded request goes on exactly as sent; local answers are tagged d1", async () => {
  const {worker, sent} = recordingWorker();
  const body = JSON.stringify(toolCall("compare_versions", {section_id: "15.305", date_before: "2025-01-01", date_after: "2026-10-29"}));
  const response = await worker.fetch(post(body, {"Mcp-Session-Id": "x"}), env());
  assert.equal(await response.text(), '{"forwarded":true}');
  assert.equal(response.headers.get("X-1102tools-Backend"), "origin");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].body, body);
  assert.equal(sent[0].headers.get("Mcp-Session-Id"), "x");
  const local = await worker.fetch(post(toolCall("get_cfr_content", {section: "15.305"})), env());
  assert.equal(local.headers.get("X-1102tools-Backend"), "d1");
  assert.equal((await local.json() as any).result.structuredContent.section, "15.305");
  const other = await worker.fetch(post(toolCall("get_ancestry", {section: "15.305", date: "2026-10-28"})), env());
  assert.equal(await other.text(), '{"forwarded":true}');
  assert.equal(sent.length, 2);
});

test("a D1 failure or a gap in the copy forwards at once, logging only a category", async () => {
  const logged: string[] = [];
  const original = console.log;
  console.log = (line: string) => logged.push(line);
  try {
    let attempts = 0;
    const fail = () => { attempts++; throw new Error("D1_ERROR: secret-section"); };
    await forwards("get_cfr_content", {section: "secret-section"}, {prepare: fail, batch: fail});
    assert.equal(attempts, 1, "no retry: the Python server answers instead");
    const copy = new DatabaseSync(":memory:");
    copy.exec(readFileSync(join(ROOT, "deploy/ecfr/schema.sql"), "utf8"));
    await forwards("get_latest_date", {}, d1(copy));
  } finally {
    console.log = original;
  }
  assert.deepEqual(logged.map(line => JSON.parse(line).reason), ["d1"]);
  for (const line of logged) assert.ok(!line.includes("secret"));
});

test("staging sends forwarded requests to FORWARD_URL with the MCP headers only", async () => {
  const seen: {url: string; init: RequestInit}[] = [];
  const restore = mock.method(globalThis, "fetch", async (url: string, init: RequestInit) => {
    seen.push({url, init});
    return new Response('{"production":true}', {status: 200, headers: {"Content-Type": "application/json"}});
  });
  try {
    const body = new TextEncoder().encode(JSON.stringify(toolCall("search_cfr", {query: "audit"}))).buffer;
    const request = post("{}", {"MCP-Protocol-Version": "2025-06-18", "CF-Connecting-IP": "203.0.113.9", Cookie: "c=1"});
    const response = await toForwardUrl("https://ecfr.1102tools.com/mcp", request, body);
    assert.equal(await response.text(), '{"production":true}');
    assert.equal(response.headers.get("X-1102tools-Backend"), "forward_url");
    const headers = new Headers(seen[0].init.headers);
    assert.equal(seen[0].url, "https://ecfr.1102tools.com/mcp");
    assert.deepEqual([...headers.keys()].sort(), ["accept", "content-type", "mcp-protocol-version", "user-agent", "x-1102tools-monitor"]);
    assert.equal(seen[0].init.body, body);
  } finally {
    restore.mock.restore();
  }
});

// ---------- HTTP ----------

test("HTTP edge: health, docs, origin, rate limit, methods, body limits, message kinds", async () => {
  const {worker} = recordingWorker();
  const url = "https://ecfr.1102tools.com";
  const health = await worker.fetch(new Request(`${url}/health`), env());
  assert.deepEqual(await health.json(), {status: "ok", tools: 13, release_sha: "abc123", admission: {processing: 16, waiting: 32, total: 48, deadline_seconds: 55}});
  const unset = await worker.fetch(new Request(`${url}/health`), {...env(), RELEASE_SHA: undefined});
  assert.equal((await unset.json() as any).release_sha, "development");
  assert.equal((await worker.fetch(new Request(`${url}/privacy`), env())).status, 200);
  assert.equal((await worker.fetch(new Request(`${url}/`), env())).status, 200);
  assert.equal((await worker.fetch(new Request(`${url}/nope`), env())).status, 404);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized"}), env())).status, 202);
  assert.equal((await worker.fetch(post({}, {Origin: "https://evil.example"}), env())).status, 403);
  const limited = await worker.fetch(post(toolCall("get_latest_date", {}, 3)), env(false));
  assert.equal(limited.status, 200);
  assert.equal(limited.headers.get(TURNED_AWAY_HEADER), "1");
  assert.match((await limited.json() as any).result.content[0].text, /^You've reached the hosted eCFR limit of 20 calls per minute from your connection\. /);
  assert.equal((await worker.fetch(new Request(`${url}/mcp`), env())).status, 405);
  assert.equal((await worker.fetch(post("{"), env())).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(70000)), env())).status, 413);
  const response = await worker.fetch(post(toolCall("get_latest_date", {})), env());
  assert.deepEqual(Object.keys((await response.json() as any).result), ["content", "isError", "structuredContent"]);
});

const META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}};
const modern = (method: string, params: Record<string, unknown> = {}, headers: Record<string, string> = {}) =>
  post({jsonrpc: "2.0", id: 7, method, params: {...params, _meta: META}},
    {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, ...(typeof params.name === "string" ? {"Mcp-Name": params.name} : {}), ...headers});

test("2026-07-28 tool calls, forwards and listen streams", async () => {
  const {worker, sent} = recordingWorker();
  const stamp = `"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"ecfr","version":"${SERVER.version}"}}`;
  const result = JSON.parse(await (await worker.fetch(modern("tools/call", {name: "get_cfr_content", arguments: {section: "15.305"}}), env())).text());
  assert.deepEqual(Object.keys(result.result), ["content", "isError", "resultType", "structuredContent", "_meta"]);
  const error = await (await worker.fetch(modern("tools/call", {name: "get_cfr_content", arguments: {section: "15.305", page: 0}}), env())).text();
  assert.ok(error.endsWith(`"isError":true,"resultType":"complete",${stamp}}}`));
  const forwarded = await worker.fetch(modern("tools/call", {name: "get_corrections", arguments: {}}), env());
  assert.equal(await forwarded.text(), '{"forwarded":true}');
  assert.equal(sent[0].headers.get("Mcp-Name"), "get_corrections");
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

// ---------- Python helpers ----------

test("identifiers, dates and sizes are read the way the Python server reads them", () => {
  const section = (value: unknown) => coerceCfrStr(value, "section", {stripPrefixes: true, stripCites: true});
  assert.equal(section("  FAR 52.212–4(c)(2)(xviii) "), "52.212-4");
  assert.equal(section("48 C.F.R. §§ 15.305"), "15.305");
  assert.equal(section("DFARS Section 252.204-7012"), "252.204-7012");
  assert.equal(section("Subpart 15.3"), "15.3");
  assert.equal(section("FARx 1"), "FARx 1");
  assert.equal(section(15), "15");
  assert.equal(section("FAR"), null);
  assert.throws(() => section("1".repeat(121)), /section exceeds maximum length of 120 chars\. Got 121\./);
  assert.equal(checkTitle48Chapter(null, "252.204-7012"), "2");
  assert.equal(checkTitle48Chapter(null, "1852.215-84"), "18");
  assert.throws(() => checkTitle48Chapter("1", "552.238-81"), /552\.238-81 is in Title 48 chapter 5 \(GSAR \(Parts 500-599\)\), not chapter 1\./);
  assert.equal(validateDate(" 2026-10-29 ", "date"), "2026-10-29");
  assert.throws(() => validateDate("2026-02-30", "date"), /date='2026-02-30' is not a valid calendar date: day is out of range for month/);
  assert.throws(() => validateDate("0000-01-01", "date"), /year 0 is out of range/);
  assert.equal(pyInt(" ٥٢ "), 52);
  assert.equal(pyInt("1_000"), 1000);
  assert.equal(pyInt("1__0"), null);
  assert.equal(sizeOf({a: ["\u{1f600}", 1]}), 31);
  assert.equal(sizeOf(["x"], 2), 21);
});

// ---------- read sessions and the answer cache ----------

test("every read of a call goes through one first-unconstrained session", async () => {
  const constraints: string[] = [];
  const replicated = {prepare: () => { throw new Error("read outside the session"); }, batch: () => { throw new Error("read outside the session"); },
    withSession: (constraint: string) => { constraints.push(constraint); return db; }};
  assert.equal((await data("get_cfr_content", {section: "15.305"}, replicated)).section, "15.305");
  assert.deepEqual(constraints, ["first-unconstrained"]);
});

test("the answer cache gives the same bytes and is keyed to the copy's version", async () => {
  const {sqlite, db: local} = copy();
  const cache = memoryCache();
  const cached = async (name: string, args: Record<string, unknown>) => {
    const trace: {cache?: string} = {};
    const result = await callTool(name, args, env(true, local, {ANSWER_CACHE: cache}), trace as any);
    return {trace: trace.cache, text: dumps(result as any)};
  };
  const first = await cached("get_cfr_content", {section: "15.305"});
  const plain = dumps(await call("get_cfr_content", {section: "15.305"}, local) as any);
  assert.deepEqual([first.trace, first.text], ["miss", plain]);
  assert.equal(cache.store.size, 1);
  assert.equal([...cache.store.values()][0].control, "public, max-age=86400");
  assert.match([...cache.store.keys()][0], /^https:\/\/answer-cache\.ecfr\.1102tools\.com\/[0-9a-f]{64}$/);
  // The same validated arguments (defaults filled in) are the same question.
  assert.deepEqual(await cached("get_cfr_content", {section: "15.305", title_number: 48, page: 1}), {trace: "hit", text: plain});
  assert.equal((await cached("get_cfr_content", {section: "15.305", page: "1"})).trace, "hit");
  assert.equal((await cached("get_cfr_content", {section: "15.306"})).trace, "miss");
  // A load writes a new version: older entries are never used again.
  sqlite.exec("UPDATE meta SET value = 'next-load' WHERE key = 'version'");
  assert.deepEqual(await cached("get_cfr_content", {section: "15.305"}), {trace: "miss", text: plain});
  assert.equal((await cached("get_cfr_content", {section: "15.305"})).trace, "hit");
  assert.equal(cache.store.size, 3);
  // Every tool the copy answers caches its answers, byte for byte.
  for (const [name, args] of [["list_agencies", {}], ["get_latest_date", {}], ["get_cfr_structure", {part: "15"}], ["get_ancestry", {section: "15.305"}],
    ["list_sections_in_part", {part_number: "52", detail: true}], ["find_far_definition", {term: "surety"}], ["lookup_far_clause", {section_id: "2.101", page: 2}]] as const) {
    const miss = await cached(name, args);
    assert.deepEqual([miss.trace, await cached(name, args)], ["miss", {trace: "hit", text: miss.text}], name);
  }
  const keys = await Promise.all(["v1", "v2"].map(version => answerKey("get_latest_date", {title_number: 48}, version, "r")));
  assert.notEqual(keys[0].url, keys[1].url);
  assert.notEqual((await answerKey("get_latest_date", {title_number: 48}, "v1", "r2")).url, keys[0].url);
});

test("errors, forwarded calls, a copy without a version and answers read across a load are not cached", async () => {
  const {sqlite, db: local} = copy();
  const cache = memoryCache();
  const trace: {cache?: string} = {};
  const withCache = env(true, local, {ANSWER_CACHE: cache});
  assert.match((await callTool("get_cfr_content", {section: "15.305", page: "x"}, withCache, trace as any) as any).content[0].text, /1 validation error/);
  assert.equal(trace.cache, undefined, "arguments pydantic rejects never reach D1 or the cache");
  assert.match((await callTool("get_cfr_content", {section: "15.305", page: 0}, withCache) as any).content[0].text, /page must be >= 1/);
  assert.equal((await callTool("get_cfr_content", {section: "15.305", page: 9}, withCache) as any).isError, true);
  await assert.rejects(callTool("get_cfr_content", {section: "15.305", date: "2026-10-01"}, withCache), (e: unknown) => e instanceof Forward);
  await assert.rejects(callTool("get_cfr_content", {section: "15.399"}, withCache), (e: unknown) => e instanceof Forward);
  assert.equal(cache.store.size, 0);
  // A load lands between the version read and the answer's reads: the answer is not filed under the old version.
  const racing = {
    prepare: (sql: string) => {
      const statement = local.prepare(sql);
      return sql.includes("FROM meta") ? {...statement, all: async () => {
        const result = await statement.all();
        sqlite.exec("UPDATE meta SET value = 'mid-load' WHERE key = 'version'");
        return result;
      }} : statement;
    },
    batch: local.batch,
  };
  const raced: {cache?: string} = {};
  assert.equal((await callTool("get_cfr_content", {section: "15.305"}, env(true, racing, {ANSWER_CACHE: cache}), raced as any) as any).isError, false);
  assert.deepEqual([raced.cache, cache.store.size], ["miss", 0]);
  sqlite.exec("DELETE FROM meta WHERE key = 'version'");
  const none: {cache?: string} = {};
  assert.equal((await callTool("get_cfr_content", {section: "15.305"}, withCache, none as any) as any).isError, false);
  assert.deepEqual([none.cache, cache.store.size], [undefined, 0]);
});

test("a broken cache never breaks a call, and responses say hit or miss", async () => {
  const broken = {match: async () => { throw new Error("cache down"); }, put: async () => { throw new Error("cache down"); }};
  assert.equal((await callTool("get_latest_date", {}, env(true, db, {ANSWER_CACHE: broken})) as any).isError, false);
  const corrupt = {match: async () => new Response("{not json"), put: async () => {}};
  assert.equal((await callTool("get_latest_date", {}, env(true, db, {ANSWER_CACHE: corrupt})) as any).structuredContent.title, 48);
  const {worker} = recordingWorker();
  const cached = env(true, db, {ANSWER_CACHE: memoryCache()});
  const first = await worker.fetch(post(toolCall("get_cfr_content", {section: "15.305"})), cached);
  const second = await worker.fetch(post(toolCall("get_cfr_content", {section: "15.305"})), cached);
  assert.deepEqual([first.headers.get("X-1102tools-Cache"), second.headers.get("X-1102tools-Cache")], ["miss", "hit"]);
  assert.equal(second.headers.get("X-1102tools-Backend"), "d1");
  assert.equal(await first.text(), await second.text());
  const modernHit = await worker.fetch(modern("tools/call", {name: "get_cfr_content", arguments: {section: "15.305"}}), cached);
  assert.equal(modernHit.headers.get("X-1102tools-Cache"), "hit");
  assert.equal((await worker.fetch(post(toolCall("get_latest_date", {})), env())).headers.get("X-1102tools-Cache"), null);
});
