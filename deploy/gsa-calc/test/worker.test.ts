// The Worker over a small copy built from GSA's recorded answers
// (test/fixture-db.ts), read through a D1-shaped adapter. Tool-by-tool parity
// with the Python server is scripts/parity.py; this covers the contract, the
// tools' answers and D1 use, what is forwarded and how, failures, the caps,
// the HTTP edge, staging's FORWARD_URL, the answer cache and the Python helpers.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {mock, test} from "node:test";
import {TURNED_AWAY_HEADER} from "../../shared/edge.ts";
import {MinuteCounter} from "../../shared/rate-counter.ts";
import {Forward} from "../src/args.ts";
import {toForwardUrl} from "../src/forward.ts";
import {dumps} from "../src/pyjson.ts";
import {answerKey} from "../src/rpc.ts";
import {TOOLS, buildQueryString, containsWholeWord, quotePlus} from "../src/tools.ts";
import {callTool, handleMessage, makeWorker} from "../src/worker.ts";
import {d1} from "./d1.ts";
import {SCHEMA, buildDatabase, fixtureAnswers, fixtureDatabase, fixtureRecords} from "./fixture-db.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const SERVER = JSON.parse(read("../../../servers/gsa-calc-mcp/server.json"));
const ANSWERS = Object.fromEntries(fixtureAnswers().map(a => [a.name, a]));

const db = d1(fixtureDatabase());
/** A private copy of the fixture database, so tests can change it. */
function copy() {
  const local = buildDatabase(fixtureRecords());
  return {sqlite: local, db: d1(local)};
}
function emptyCopy() {
  const empty = new DatabaseSync(":memory:");
  empty.exec(SCHEMA);
  return d1(empty);
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
  ({DB, REQUEST_LIMITER: {limit: async () => ({success: allow})}, RELEASE_SHA: "abc123", EMULATOR_TOOK: 4, ...extra}) as any;
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
  new Request("https://gsa-calc.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers}, body: typeof body === "string" ? body : JSON.stringify(body)});
const toolCall = (name: string, args: Record<string, unknown>, id = 1) => ({jsonrpc: "2.0", id, method: "tools/call", params: {name, arguments: args}});

/** A Worker whose forwarded requests are recorded and answered with a marker. */
function recordingWorker() {
  const sent: {body: string | null; headers: Headers; url: string}[] = [];
  const worker = makeWorker(async (request, body) => {
    sent.push({body: body && new TextDecoder().decode(body), headers: request.headers, url: request.url});
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
  assert.equal(TOOLS.length, 8);
});

test("initialize matches the Python server", async () => {
  const init = await handleMessage({jsonrpc: "2.0", id: 1, method: "initialize", params: {protocolVersion: "2025-11-25", capabilities: {}, clientInfo: {name: "t", version: "1"}}}, env());
  assert.equal(dumps(init), `{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-11-25","serverInfo":{"name":"gsa-calc","version":"${SERVER.version}"}}}`);
  const unknown = await handleMessage({jsonrpc: "2.0", id: 2, method: "tools/call", params: {name: "nope", arguments: {}}}, env()) as any;
  assert.equal(dumps(unknown.result), `{"content":[{"text":"Unknown tool: nope","type":"text"}],"isError":true}`);
});

// ---------- answers from the copy ----------

test("every tool answers from the copy", async () => {
  const keyword = await data("keyword_search", {keyword: "Registered Nurse I", education_level: "BA", experience_min: 1, page_size: 10});
  assert.equal(keyword.hits.hits[0]._index, "ceilingrates-2026-10-10_02-00-02");
  assert.deepEqual([keyword._stats.total_rates, keyword._stats.education_breakdown.get("BA")], [keyword.hits.total.value, keyword.hits.total.value]);
  const exact = await data("exact_search", {field: "labor_category", value: "Registered Nurse I", education_level: "BA", experience_min: 1, page_size: 6});
  assert.deepEqual(exact.hits.hits.map((h: any) => h._id), ["1710487800", "1703111483", "1761260883"]);
  const colon = await data("exact_search", {field: "labor_category", value: "Engineer 1: Sr. Naval Architect Sr. Marine Engineer Sr. Ocean Engineer"});
  assert.match(colon._exact_match_note, /^GSA exact-field search truncates colon-containing values/);
  const suggest = await data("suggest_contains", {field: "vendor_name", term: "proxy"});
  assert.deepEqual(suggest.suggestions[0], {value: "PROXY PERSONNEL LLC", count: 6, count_is_approximate: false});
  const browse = await data("filtered_browse", {sin: "541330EMI", page_size: 3});
  assert.equal(browse.hits.hits.length, 3);
  const igce = await data("igce_benchmark", {labor_category: "Ocean Engineer I"});
  assert.deepEqual([igce.total_rates, igce.population_scope.exact_title_population_verified], [1, true]);
  const low = await data("price_reasonableness_check", {labor_category: "Ocean Engineer I", proposed_rate: 72});
  assert.equal(low.status, "LOW_SAMPLE");
  const mixed = await data("price_reasonableness_check", {labor_category: "Registered Nurse I", education_level: "BA", experience_min: 1, proposed_rate: 60});
  assert.equal(mixed.status, "MIXED_LABOR_TITLES");
  const none = await data("price_reasonableness_check", {labor_category: "zzqq", proposed_rate: 60});
  assert.equal(dumps(none), '{"status":"NO_DATA","proposed_rate":60.0,"message":"No comparable ceiling rates found for \'zzqq\' with the given filters."}');
  const card = await data("vendor_rate_card", {vendor_name: "proxy personnel", page_size: 4});
  assert.deepEqual([card.vendor, card.returned, card.has_more, card.next_page], ["PROXY PERSONNEL LLC", 4, true, 2]);
  const acronym = await data("vendor_rate_card", {vendor_name: "PACT, INC."});
  assert.match(acronym.error, /^No vendor found matching 'PACT, INC\.'/);
  const retired = await data("sin_analysis", {sin_code: 541512});
  assert.equal(retired.total_rates, 0);
  assert.match(retired._note, /^0 records for this SIN/);
});

test("one D1 round trip per GSA call; validation errors never reach D1", async () => {
  const trips = async (name: string, args: Record<string, unknown>) => {
    const start = db.log.length;
    await call(name, args);
    const statements = db.log.slice(start);
    for (const s of statements) assert.ok(s.values.length <= 100, "D1 allows 100 bound parameters");
    return new Set(statements.map(s => s.batch)).size;
  };
  assert.equal(await trips("keyword_search", {keyword: "nurse"}), 1);
  assert.equal(await trips("exact_search", {field: "vendor_name", value: "PROXY PERSONNEL LLC"}), 1);
  assert.equal(await trips("suggest_contains", {field: "labor_category", term: "nurse"}), 1);
  assert.equal(await trips("filtered_browse", {education_level: "BA|MA|PHD", sin: "541611", price_min: 10, experience_max: 30}), 1);
  assert.equal(await trips("price_reasonableness_check", {labor_category: "nurse", proposed_rate: 70}), 1);
  assert.equal(await trips("vendor_rate_card", {vendor_name: "proxy"}), 2);
  assert.equal(await trips("sin_analysis", {sin_code: "54151S"}), 1);
  assert.equal(await trips("keyword_search", {keyword: "nurse", page: 0}), 0);
  assert.equal(await trips("keyword_search", {keyword: "nurse", price_min: "nan"}), 0);
});

test("the Python server's messages, in its order", async () => {
  assert.equal(await errorText("keyword_search", {keyword: "  "}), "Error executing tool keyword_search: keyword cannot be empty. For unfiltered browsing use filtered_browse() instead.");
  assert.match(await errorText("keyword_search", {keyword: "x", page: 0, price_min: -1}), /page must be >= 1\. Got 0\.$/);
  assert.match(await errorText("keyword_search", {keyword: "x", price_min: 200, price_max: 100}), /price_min \(\$200\.0\) must be <= price_max \(\$100\.0\)\.$/);
  assert.match(await errorText("keyword_search", {keyword: "x", sin: true}), /^Error executing tool keyword_search: 1 validation error for keyword_searchArguments\nsin\n  Value error, Expected a string or int, not a boolean\. Got True\./);
  assert.match(await errorText("keyword_search", {keyword: "x", business_size: "L"}), /business_size\n  Input should be 'S' or 'O' \[type=literal_error, input_value='L', input_type=str\]/);
  assert.match(await errorText("keyword_search", {keyword: "x", price_min: "abc"}), /Input should be a valid number, unable to parse string as a number \[type=float_parsing/);
  assert.match(await errorText("keyword_search", {keyword: "x", education_level: "BA||MA"}), /education_level 'BA\|\|MA' has an empty entry between pipes\.$/);
  assert.match(await errorText("filtered_browse", {}), /^Error executing tool filtered_browse: filtered_browse requires at least one filter\./);
  assert.match(await errorText("keyword_search", {keyword: "a\tb"}), /keyword='a\\tb' contains control characters/);
  assert.match(await errorText("keyword_search", {keyword: "<script>"}), /\(HTML angle brackets\)/);
  assert.match(await errorText("keyword_search", {keyword: "x", page: 21, page_size: 500}), /page \(21\) \* page_size \(500\) = 10500 exceeds/);
  assert.match(await errorText("price_reasonableness_check", {labor_category: "x", proposed_rate: 0}), /proposed_rate must be > 0\. Got 0\.0\.$/);
  assert.match(await errorText("exact_search", {field: "vendor_name", value: "A: B"}), /GSA cannot verify the complete exact vendor_name population for 'A: B'/);
});

// ---------- what is forwarded ----------

test("an empty copy or a D1 failure forwards at once, logging only a category", async () => {
  const logged: string[] = [];
  const original = console.log;
  console.log = (line: string) => logged.push(line);
  try {
    let attempts = 0;
    const fail = () => { attempts++; throw new Error("D1_ERROR: secret-keyword"); };
    await assert.rejects(call("keyword_search", {keyword: "secret-keyword"}, {prepare: fail, batch: fail}), (e: unknown) => e instanceof Forward);
    assert.equal(attempts, 1, "no retry: the Python server answers instead");
    await assert.rejects(call("sin_analysis", {sin_code: "54151S"}, emptyCopy()), (e: unknown) => e instanceof Forward);
  } finally {
    console.log = original;
  }
  // An empty copy is a deliberate Forward (not logged); a D1 error is logged by category.
  assert.deepEqual(logged.map(line => JSON.parse(line).reason), ["d1"]);
  for (const line of logged) assert.ok(!line.includes("secret"));
  // Validation still answers here with an empty copy.
  assert.equal((await call("sin_analysis", {sin_code: "!"}, emptyCopy())).isError, true);
});

test("a forwarded request goes on exactly as sent; local answers are tagged d1", async () => {
  const {worker, sent} = recordingWorker();
  const body = JSON.stringify(toolCall("keyword_search", {keyword: "nurse"}));
  const response = await worker.fetch(post(body, {"Mcp-Session-Id": "x"}), env(true, emptyCopy()));
  assert.equal(await response.text(), '{"forwarded":true}');
  assert.equal(response.headers.get("X-1102tools-Backend"), "origin");
  assert.deepEqual([sent.length, sent[0].body, sent[0].headers.get("Mcp-Session-Id")], [1, body, "x"]);
  const local = await worker.fetch(post(toolCall("keyword_search", {keyword: "nurse", page_size: 1})), env());
  assert.equal(local.headers.get("X-1102tools-Backend"), "d1");
  assert.equal((await local.json() as any).result.structuredContent.took, 4);
});

test("every call counts toward 120 a minute; calls sent to the Dell also toward 10", async () => {
  const counter = new MinuteCounter();
  const RATE_COUNTER = {
    idFromName: (name: string) => name,
    get: () => ({fetch: async (_url: string, init?: RequestInit) => {
      const {key, limit} = JSON.parse(String(init?.body));
      return new Response(null, {status: counter.hit(key, limit, 60_000 * 5 + 1) ? 204 : 429});
    }}),
  };
  const {worker, sent} = recordingWorker();
  const from = (body: unknown) => post(body, {"CF-Connecting-IP": "8.8.8.8"});
  const down = env(true, emptyCopy(), {RATE_COUNTER});
  for (let i = 0; i < 10; i++) assert.equal(await (await worker.fetch(from(toolCall("sin_analysis", {sin_code: "54151S"})), down)).text(), '{"forwarded":true}');
  const over = await worker.fetch(from(toolCall("sin_analysis", {sin_code: "54151S"}, 7)), down);
  const text = (await over.json() as any).result.content[0].text;
  assert.match(text, /^You've reached the hosted GSA CALC\+ limit of 10 calls per minute from your connection for lookups sent to GSA CALC\+ live while 1102tools' copy is unavailable\./);
  assert.equal(over.headers.get(TURNED_AWAY_HEADER), "1");
  assert.equal(sent.length, 10);
  // The copy still answers: those calls only count toward 120 (11 used so far).
  const up = env(true, db, {RATE_COUNTER});
  for (let i = 0; i < 109; i++) assert.equal((await worker.fetch(from(toolCall("sin_analysis", {sin_code: "!"})), up)).headers.get("X-1102tools-Backend"), "d1");
  const capped = await worker.fetch(from(toolCall("sin_analysis", {sin_code: "54151S"})), up);
  assert.match((await capped.json() as any).result.content[0].text, /limit of 120 calls per minute from your connection/);
  const other = await worker.fetch(post(toolCall("sin_analysis", {sin_code: "54151S"}), {"CF-Connecting-IP": "8.8.4.4"}), up);
  assert.equal(other.headers.get("X-1102tools-Backend"), "d1");
});

test("staging sends forwarded requests to FORWARD_URL with the MCP headers only", async () => {
  const seen: {url: string; init: RequestInit}[] = [];
  const restore = mock.method(globalThis, "fetch", async (url: string, init: RequestInit) => {
    seen.push({url, init});
    return new Response('{"production":true}', {status: 200, headers: {"Content-Type": "application/json"}});
  });
  try {
    const body = new TextEncoder().encode(JSON.stringify(toolCall("sin_analysis", {sin_code: "611430"}))).buffer;
    const request = post("{}", {"MCP-Protocol-Version": "2025-06-18", "CF-Connecting-IP": "203.0.113.9", Cookie: "c=1"});
    const response = await toForwardUrl("https://gsa-calc.1102tools.com/mcp", request, body);
    assert.equal(await response.text(), '{"production":true}');
    assert.equal(response.headers.get("X-1102tools-Backend"), "forward_url");
    const headers = new Headers(seen[0].init.headers);
    assert.equal(seen[0].url, "https://gsa-calc.1102tools.com/mcp");
    assert.deepEqual([...headers.keys()].sort(), ["accept", "content-type", "mcp-protocol-version", "user-agent", "x-1102tools-monitor"]);
    assert.equal(headers.get("user-agent"), "1102tools-gsa-calc-staging");
    assert.equal(seen[0].init.body, body);
  } finally {
    restore.mock.restore();
  }
});

// ---------- HTTP ----------

test("HTTP edge: health, docs, origin, rate limit, methods, body limits, message kinds", async () => {
  const {worker, sent} = recordingWorker();
  const url = "https://gsa-calc.1102tools.com";
  const health = await worker.fetch(new Request(`${url}/health`), env());
  assert.deepEqual(await health.json(), {status: "ok", tools: 8, release_sha: "abc123", admission: {processing: 16, waiting: 32, total: 48, deadline_seconds: 55}});
  // Production (a container, no FORWARD_URL) asks the Dell, as check_hosted_health.py expects.
  const production = await worker.fetch(new Request(`${url}/health`), env(true, db, {BACKEND: {}}));
  assert.deepEqual([await production.text(), production.headers.get("X-1102tools-Backend"), sent.at(-1)!.url], ['{"forwarded":true}', "origin", `${url}/health`]);
  const staging = await worker.fetch(new Request(`${url}/health`), env(true, db, {BACKEND: {}, FORWARD_URL: "https://x"}));
  assert.equal((await staging.json() as any).status, "ok");
  const unset = await worker.fetch(new Request(`${url}/health`), {...env(), RELEASE_SHA: undefined});
  assert.equal((await unset.json() as any).release_sha, "development");
  for (const path of ["/privacy", "/terms", "/support", "/"]) assert.equal((await worker.fetch(new Request(`${url}${path}`), env())).status, 200, path);
  assert.equal((await worker.fetch(new Request(`${url}/nope`), env())).status, 404);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized"}), env())).status, 202);
  assert.equal((await worker.fetch(post({}, {Origin: "https://evil.example"}), env())).status, 403);
  const limited = await worker.fetch(post(toolCall("sin_analysis", {sin_code: "54151S"}, 3)), env(false));
  assert.equal(limited.headers.get(TURNED_AWAY_HEADER), "1");
  assert.match((await limited.json() as any).result.content[0].text, /^You've reached the hosted GSA CALC\+ limit of 120 calls per minute from your connection\. /);
  assert.equal((await worker.fetch(new Request(`${url}/mcp`), env())).status, 405);
  assert.equal((await worker.fetch(post("{"), env())).status, 400);
  assert.equal((await worker.fetch(post('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"keyword_search","arguments":{"keyword":"\\ud800"}}}'), env())).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(70000)), env())).status, 413);
  const response = await worker.fetch(post(toolCall("sin_analysis", {sin_code: "54151S"})), env());
  assert.deepEqual(Object.keys((await response.json() as any).result), ["content", "isError", "structuredContent"]);
});

const META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}};
const modern = (method: string, params: Record<string, unknown> = {}, headers: Record<string, string> = {}) =>
  post({jsonrpc: "2.0", id: 7, method, params: {...params, _meta: META}},
    {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, ...(typeof params.name === "string" ? {"Mcp-Name": params.name} : {}), ...headers});

test("2026-07-28 tool calls, forwards and listen streams", async () => {
  const {worker, sent} = recordingWorker();
  const stamp = `"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"gsa-calc","version":"${SERVER.version}"}}`;
  const result = JSON.parse(await (await worker.fetch(modern("tools/call", {name: "sin_analysis", arguments: {sin_code: "54151S"}}), env())).text());
  assert.deepEqual(Object.keys(result.result), ["content", "isError", "resultType", "structuredContent", "_meta"]);
  const error = await (await worker.fetch(modern("tools/call", {name: "sin_analysis", arguments: {sin_code: ""}}), env())).text();
  assert.ok(error.endsWith(`"isError":true,"resultType":"complete",${stamp}}}`));
  const forwarded = await worker.fetch(modern("tools/call", {name: "igce_benchmark", arguments: {labor_category: "x"}}), env(true, emptyCopy()));
  assert.equal(await forwarded.text(), '{"forwarded":true}');
  assert.equal(sent[0].headers.get("Mcp-Name"), "igce_benchmark");
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

// ---------- read sessions and the answer cache ----------

test("every read of a call goes through one first-unconstrained session", async () => {
  const constraints: string[] = [];
  const replicated = {prepare: () => { throw new Error("read outside the session"); }, batch: () => { throw new Error("read outside the session"); },
    withSession: (constraint: string) => { constraints.push(constraint); return db; }};
  assert.equal((await data("vendor_rate_card", {vendor_name: "proxy"}, replicated)).vendor, "PROXY PERSONNEL LLC");
  assert.deepEqual(constraints, ["first-unconstrained"]);
});

test("the answer cache gives the same bytes and is keyed to the night", async () => {
  const {sqlite: local, db: copyDb} = copy();
  const cache = memoryCache();
  const cached = async (name: string, args: Record<string, unknown>) => {
    const trace: {cache?: string} = {};
    const result = await callTool(name, args, env(true, copyDb, {ANSWER_CACHE: cache}), trace as any);
    return {trace: trace.cache, text: dumps(result as any)};
  };
  const first = await cached("keyword_search", {keyword: "nurse", page_size: 3});
  const plain = dumps(await call("keyword_search", {keyword: "nurse", page_size: 3}, copyDb) as any);
  assert.deepEqual([first.trace, first.text], ["miss", plain]);
  assert.equal([...cache.store.values()][0].control, "public, max-age=86400");
  assert.match([...cache.store.keys()][0], /^https:\/\/answer-cache\.gsa-calc\.1102tools\.com\/[0-9a-f]{64}$/);
  // The same validated arguments (defaults filled in) are the same question.
  assert.deepEqual(await cached("keyword_search", {keyword: "nurse", page_size: "3", page: 1, sort: "asc"}), {trace: "hit", text: plain});
  assert.equal((await cached("keyword_search", {keyword: "nurse", page_size: 4})).trace, "miss");
  // A new night switches the version: older entries are never used again.
  local.exec("UPDATE meta SET value = 'ceilingrates-2026-10-11_02-00-02' WHERE key = 'version'");
  const next = await cached("keyword_search", {keyword: "nurse", page_size: 3});
  assert.equal(next.trace, "miss");
  assert.match(next.text, /ceilingrates-2026-10-11_02-00-02/);
  for (const [name, args] of [["suggest_contains", {field: "vendor_name", term: "proxy"}], ["vendor_rate_card", {vendor_name: "proxy"}],
    ["price_reasonableness_check", {labor_category: "nurse", proposed_rate: 70}], ["sin_analysis", {sin_code: "54151S"}]] as const) {
    const miss = await cached(name, args);
    assert.deepEqual([miss.trace, await cached(name, args)], ["miss", {trace: "hit", text: miss.text}], name);
  }
  // NaN, Infinity and -0 floats get keys of their own (JSON.stringify writes them as null and 0).
  const keys = await Promise.all([NaN, Infinity, null, 0, -0].map(v => answerKey("keyword_search", {price_min: v}, "v", "r")));
  assert.equal(new Set(keys.map(k => k.url)).size, 5);
  assert.match((await cached("keyword_search", {keyword: "nurse", page_size: 3, price_min: "nan"})).text, /price_min must be a finite number/);
});

test("errors, forwarded calls and a copy without a version are not cached", async () => {
  const {sqlite: local, db: copyDb} = copy();
  const cache = memoryCache();
  const withCache = env(true, copyDb, {ANSWER_CACHE: cache});
  const trace: {cache?: string} = {};
  assert.match((await callTool("keyword_search", {keyword: "x", page: "x"}, withCache, trace as any) as any).content[0].text, /1 validation error/);
  assert.equal(trace.cache, undefined, "arguments pydantic rejects never reach D1 or the cache");
  assert.equal((await callTool("keyword_search", {keyword: "x", page: 0}, withCache) as any).isError, true);
  await assert.rejects(callTool("keyword_search", {keyword: "x"}, env(true, emptyCopy(), {ANSWER_CACHE: cache})), (e: unknown) => e instanceof Forward);
  assert.equal(cache.store.size, 0);
  local.exec("DELETE FROM meta WHERE key = 'version'");
  await assert.rejects(callTool("keyword_search", {keyword: "x"}, withCache), (e: unknown) => e instanceof Forward);
  assert.equal(cache.store.size, 0);
});

test("a broken cache never breaks a call, and responses say hit or miss", async () => {
  const broken = {match: async () => { throw new Error("cache down"); }, put: async () => { throw new Error("cache down"); }};
  assert.equal((await callTool("sin_analysis", {sin_code: "54151S"}, env(true, db, {ANSWER_CACHE: broken})) as any).isError, false);
  const corrupt = {match: async () => new Response("{not json"), put: async () => {}};
  assert.equal((await callTool("sin_analysis", {sin_code: "54151S"}, env(true, db, {ANSWER_CACHE: corrupt})) as any).structuredContent.sin, "54151S");
  const {worker} = recordingWorker();
  const cached = env(true, db, {ANSWER_CACHE: memoryCache()});
  const first = await worker.fetch(post(toolCall("sin_analysis", {sin_code: "54151S"})), cached);
  const second = await worker.fetch(post(toolCall("sin_analysis", {sin_code: "54151S"})), cached);
  assert.deepEqual([first.headers.get("X-1102tools-Cache"), second.headers.get("X-1102tools-Cache")], ["miss", "hit"]);
  assert.equal(await first.text(), await second.text());
  const modernHit = await worker.fetch(modern("tools/call", {name: "sin_analysis", arguments: {sin_code: "54151S"}}), cached);
  assert.equal(modernHit.headers.get("X-1102tools-Cache"), "hit");
});

// ---------- Python helpers ----------

test("query strings, quote_plus and whole-word matching as Python writes them", () => {
  assert.equal(quotePlus("Engineer 1: Sr. ~a/b+c&d"), "Engineer+1%3A+Sr.+~a%2Fb%2Bc%26d");
  assert.equal(quotePlus("Café \u{1f600}"), "Caf%C3%A9+%F0%9F%98%80");
  assert.throws(() => quotePlus("ab\ud800"), /'utf-8' codec can't encode character '\\ud800' in position 2: surrogates not allowed/);
  assert.throws(() => quotePlus("\udc00\udc01x"), /characters in position 0-1: surrogates not allowed/);
  assert.equal(buildQueryString({keyword: "Registered Nurse I", filters: ["education_level:BA|MA", "experience_range:3,999"], page: 1, page_size: 10}),
    ANSWERS.no_exact_grade.query);
  assert.equal(buildQueryString({search_field: "labor_category", search_value: "Registered Nurse I", filters: ["education_level:BA", "experience_range:1,999"], page_size: 6}),
    ANSWERS.exact_grade.query);
  assert.equal(buildQueryString({suggest_field: "vendor_name", suggest_term: "booz allen", exclude: "1|2"}),
    "suggest-contains=vendor_name:booz+allen&page=1&page_size=100&ordering=current_price&sort=asc&exclude=1%7C2");
  assert.throws(() => buildQueryString({keyword: "a", search_field: "vendor_name", search_value: "b"}), /Only one search mode allowed per query/);
  assert.equal(containsWholeWord("SAICAM CORPORATION, INC.", "SAIC"), false);
  assert.equal(containsWholeWord("APOGEE-SAIC CAPABILITIES", "saic"), true);
  assert.equal(containsWholeWord("REEL IMPACT, INC.", "PACT, INC."), false);
});
