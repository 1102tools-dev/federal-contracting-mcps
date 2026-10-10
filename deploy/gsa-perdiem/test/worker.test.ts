// Worker behavior against the real bundled data, loaded into node:sqlite by
// scripts/load_gsa_perdiem.py exactly as production D1 is loaded. Output
// parity with the Python server is checked separately (parity/run.ts).
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {REQUEST_DEADLINE_MS, SERVER_VERSION, handleMessage, serve, type Runtime} from "../src/mcp.ts";
import {loads, dumps, repr, round2, float} from "../src/py.ts";
import {TOOLS} from "../src/tools.ts";
import {BASE_URL, MAX_SLOT_WAIT, USER_AGENT, Upstream, type CacheLike} from "../src/upstream.ts";
import {ROOT, d1, loadedDatabaseFile} from "./d1.ts";

const DB_FILE = loadedDatabaseFile();
const KEY = "test key+/=";
const TODAY = new Date("2026-10-08T12:00:00Z");
const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");

class MemoryCache implements CacheLike {
  entries = new Map<string, string>();
  async match(request: Request) {
    const hit = this.entries.get(request.url);
    return hit === undefined ? undefined : new Response(hit);
  }
  async put(request: Request, response: Response) {
    this.entries.set(request.url, await response.text());
  }
}

interface Seen {url: string; headers: Headers}

function gsa(responses: Record<string, {status?: number; body: unknown; headers?: Record<string, string>}>, seen: Seen[] = []) {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    seen.push({url, headers: new Headers(init?.headers)});
    const fixture = responses[url.slice(BASE_URL.length + 1)];
    if (!fixture) return new Response("missing", {status: 404});
    const body = typeof fixture.body === "string" ? fixture.body : JSON.stringify(fixture.body);
    return new Response(body, {status: fixture.status ?? 200, headers: fixture.headers ?? {"content-type": "application/json"}});
  }) as typeof fetch;
}

function setup(options: {db?: ReturnType<typeof d1>; key?: string; runtime?: Runtime} = {}) {
  const db = options.db ?? d1(new DatabaseSync(DB_FILE));
  db.sqlite.exec("DELETE FROM upstream_calls; UPDATE upstream_state SET next_start = 0, cooldown_until = 0;");
  const env = {DB: db, REQUEST_LIMITER: {limit: async () => ({success: true})}, PERDIEM_API_KEY: options.key ?? KEY, RELEASE_SHA: "abc123"};
  const runtime: Runtime = {now: () => TODAY, cache: new MemoryCache(), fetch: gsa({}), upstream: {interval: 0}, ...options.runtime};
  const call = async (name: string, args: Record<string, unknown> = {}) => {
    const response: any = await handleMessage({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name, arguments: args}}, env, runtime);
    return response.result as {content: {text: string}[]; structuredContent?: any; isError: boolean};
  };
  return {db, env, runtime, call};
}

const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://gsa-perdiem.1102tools.com/mcp", {
    method: "POST", body: typeof body === "string" ? body : JSON.stringify(body),
    headers: {"Content-Type": "application/json", ...headers},
  });

const CITY = (city: string, entries: unknown[]) => ({
  body: {rates: [{rate: entries, state: "VA", year: 2027}]},
  path: `city/${encodeURIComponent(city)}/state/VA/year/2027`,
});
const rate = (city: string, county: string, meals: number, value: number) => ({
  city, county, meals, months: {month: ["Jan", "Feb", "Mar"].map((short, i) => ({short, value, number: i + 1}))},
});

test("malformed ZIP+4 is rejected instead of looking up its valid prefix", async () => {
  const {call} = setup();
  for (const zip_code of ["12345-garbage", "12345-1234-extra", "12345-", "12345-123", "１２３４５"]) {
    const r = await call("lookup_zip_perdiem", {zip_code, fiscal_year: 2027});
    assert.equal(r.isError, true);
    assert.match(r.content[0].text, /5-digit US ZIP/);
  }
  assert.equal((await call("lookup_zip_perdiem", {zip_code: "20120-1234", fiscal_year: 2027})).isError, false);
});

test("city-limit rates do not silently ignore a conflicting county", async () => {
  const {call} = setup();
  for (const [city, state, county] of [["Cambridge", "MA", "Essex"], ["Santa Monica", "CA", "San Diego"], ["Sedona", "AZ", "Maricopa"]]) {
    const args = {city, state, county, fiscal_year: 2027};
    const r = (await call("lookup_city_perdiem", args)).structuredContent;
    assert.equal(r.status, "invalid_county");
    assert.equal(r.mie_daily, undefined);
    assert.match(r.note, /city or locality/);
    assert.equal((await call("estimate_travel_cost", {...args, num_nights: 2, travel_month: "Oct"})).structuredContent.grand_total, undefined);
  }
});

test("split-month guidance adds lodging and computes M&IE once per trip", async () => {
  const {call} = setup();
  const estimate = async (num_nights: number, travel_month: string) =>
    JSON.parse((await call("estimate_travel_cost", {city: "Washington", state: "DC", county: "District of Columbia", fiscal_year: 2027, num_nights, travel_month})).content[0].text);
  const a = await estimate(2, "Oct"), b = await estimate(2, "Nov"), all = await estimate(4, "Oct");
  assert.equal(a.status, "resolved", JSON.stringify(a));
  assert.equal(a.mie_total + b.mie_total - all.mie_total, 46);
  assert.equal(all.mie_total, 414);
  assert.match(a.rate_month_note, /lodging_total.*once for the entire trip.*Do not add.*grand_total/);
});

test("comparison rows retain their GSA data source", async () => {
  const {call} = setup();
  const r = (await call("compare_locations", {fiscal_year: 2027, locations: [
    {city: "Cambridge", state: "MA", county: "Middlesex"},
    {city: "Cambridge", state: "MA", county: "Essex"},
  ]})).structuredContent;
  assert.deepEqual(r.locations.map((row: any) => row.status), ["resolved", "invalid_county"]);
  for (const row of r.locations) {
    assert.equal(row.source.kind, "bundled_gsa_files");
    assert.equal(row.source.fiscal_year, 2027);
    assert.match(row.source.rate_file, /gsa.gov/);
  }
});

test("published estimate description separates monthly lodging from trip M&IE", async () => {
  const {env, runtime} = setup();
  const out: any = await handleMessage({jsonrpc: "2.0", id: 1, method: "tools/list"}, env, runtime);
  const description = out.result.tools.find((tool: any) => tool.name === "estimate_travel_cost").description;
  assert.match(description, /add only each month's lodging_total/);
  assert.match(description, /Calculate M&IE once across the actual trip days/);
  assert.match(description, /Do not add[\s\S]*grand_total/);
  assert.doesNotMatch(description, /month's nights separately and add them/);
  const status = out.result.tools.find((tool: any) => tool.name === "get_data_status").description;
  assert.match(status, /supplied county for a bundled year also need no key or network call/);
});

test("tools/list serves exactly the reviewed contract, in the Python server's order", () => {
  const contract = JSON.parse(readFileSync(new URL("../tools-contract.json", import.meta.url), "utf8"));
  const byName = (list: {name: string}[]) => [...list].sort((a, b) => (a.name < b.name ? -1 : 1));
  assert.deepEqual(byName(TOOLS), contract);
  assert.deepEqual(TOOLS.map(t => t.name), [
    "get_data_status", "lookup_city_perdiem", "lookup_zip_perdiem", "lookup_state_rates",
    "get_mie_breakdown", "estimate_travel_cost", "compare_locations",
  ]);
});

test("server version and User-Agent follow the Python package version", () => {
  const version = /^version = "([^"]+)"/m.exec(readFileSync(`${ROOT}servers/gsa-perdiem-mcp/pyproject.toml`, "utf8"))![1];
  assert.equal(SERVER_VERSION, version);
  assert.equal(USER_AGENT, `gsa-perdiem-mcp/${version}`);
});

test("initialize matches the live Python server", async () => {
  const {env} = setup();
  const init: any = await handleMessage({jsonrpc: "2.0", id: 7, method: "initialize", params: {protocolVersion: "2025-06-18"}}, env);
  assert.deepEqual(init, {
    jsonrpc: "2.0", id: 7,
    result: {
      capabilities: {experimental: {}, prompts: {listChanged: false}, resources: {listChanged: false, subscribe: false}, tools: {listChanged: false}},
      protocolVersion: "2025-06-18",
      serverInfo: {name: "gsa-perdiem", version: SERVER_VERSION},
    },
  });
  const fallback: any = await handleMessage({jsonrpc: "2.0", id: 8, method: "initialize", params: {protocolVersion: "2026-07-28"}}, env);
  assert.equal(fallback.result.protocolVersion, "2025-11-25");
  assert.equal(fallback.result.instructions, undefined);
  const discover: any = await handleMessage({jsonrpc: "2.0", id: 9, method: "server/discover"}, env);
  assert.equal(discover.error.code, -32601, "2026-07-28 clients fall back to initialize");
});

test("HTTP edge: health, docs, methods, origin, limits, parse errors, notifications", async () => {
  const {env} = setup();
  const health = await serve(new Request("https://gsa-perdiem.1102tools.com/health"), env);
  assert.deepEqual(await health.json(), {status: "ok", tools: 7, release_sha: "abc123", admission: {processing: 16, waiting: 32, total: 48, deadline_seconds: 55}});
  assert.equal((await serve(new Request("https://gsa-perdiem.1102tools.com/health", {method: "POST"}), env)).status, 405);
  const unreleased = await serve(new Request("https://gsa-perdiem.1102tools.com/health"), {...env, RELEASE_SHA: undefined});
  assert.equal(((await unreleased.json()) as any).release_sha, "development");
  const privacy = await serve(new Request("https://gsa-perdiem.1102tools.com/privacy"), env);
  assert.match(await privacy.text(), /privacy notice/);
  assert.equal((await serve(new Request("https://gsa-perdiem.1102tools.com/"), env)).status, 200);
  assert.equal((await serve(new Request("https://gsa-perdiem.1102tools.com/nope"), env)).status, 404);
  assert.equal((await serve(new Request("https://gsa-perdiem.1102tools.com/mcp"), env)).status, 405);
  assert.equal((await serve(post({jsonrpc: "2.0", id: 1, method: "ping"}, {Origin: "https://evil.example"}), env)).status, 403);
  assert.equal((await serve(post("{"), env)).status, 400);
  assert.equal((await serve(post([{jsonrpc: "2.0", id: 1, method: "ping"}]), env)).status, 400);
  assert.equal((await serve(post("x".repeat(70_000)), env)).status, 413);
  assert.equal((await serve(post({jsonrpc: "2.0", method: "notifications/initialized"}), env)).status, 202);
  const limited = {...env, REQUEST_LIMITER: {limit: async () => ({success: false})}};
  assert.equal((await serve(post({jsonrpc: "2.0", id: 1, method: "ping"}), limited)).status, 429);
});

test("tool results: indented text with Python floats, compact structuredContent on the wire", async () => {
  const {env, runtime} = setup();
  const response = await serve(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "lookup_zip_perdiem", arguments: {zip_code: "02138"}}}), env, runtime);
  const raw = await response.text();
  assert.match(raw, /"mie_first_last_day":69\.0/, "floats keep .0 in structuredContent too");
  const result = JSON.parse(raw).result;
  assert.equal(result.isError, false);
  assert.equal(result.structuredContent.matched_city, "Boston / Cambridge");
  assert.match(result.content[0].text, /^\{\n  "zip_code": "02138",\n/);
  assert.match(result.content[0].text, /\n  "mie_first_last_day": 69\.0,\n/);
  assert.equal(result.structuredContent.source.kind, "bundled_gsa_files");
});

test("bundled lookups never call the GSA API or need the key", async () => {
  const seen: Seen[] = [];
  const {call} = setup({key: "", runtime: {fetch: gsa({}, seen)}});
  assert.equal((await call("lookup_zip_perdiem", {zip_code: "22201"})).structuredContent.status, "resolved");
  assert.equal((await call("lookup_state_rates", {state: "VA", fiscal_year: 2021})).structuredContent.nsa_count > 0, true);
  assert.equal(dumps((await call("get_mie_breakdown")).structuredContent.tiers[0].total), "68.0");
  assert.equal((await call("lookup_city_perdiem", {city: "Arlington", state: "VA", county: "Arlington"})).structuredContent.status, "resolved");
  assert.equal((await call("get_data_status")).structuredContent.live_lookup_access, "hosted_key_missing");
  const city = await call("lookup_city_perdiem", {city: "McLean", state: "VA"});
  assert.equal(city.isError, true);
  assert.match(city.content[0].text, /service credential is not configured/);
  assert.equal(seen.length, 0);
});

test("live lookups send the key only in X-Api-Key, cache for a day, and never echo the key", async () => {
  const seen: Seen[] = [];
  const cache = new MemoryCache();
  const city = CITY("Echo Town", [rate(`Echo ${KEY}`, `county ${encodeURIComponent(KEY)}`, 74, 150)]);
  const {call} = setup({runtime: {fetch: gsa({[city.path]: {body: city.body}}, seen), cache}});
  const first = await call("lookup_city_perdiem", {city: "Echo Town", state: "VA"});
  const second = await call("lookup_city_perdiem", {city: "Echo  Town", state: "VA"});
  assert.equal(seen.length, 1, "second call answered from the cache");
  assert.equal(seen[0].url.includes(encodeURIComponent(KEY)) || seen[0].url.includes(KEY), false);
  assert.equal(seen[0].headers.get("x-api-key"), KEY);
  assert.equal(seen[0].headers.get("user-agent"), USER_AGENT);
  assert.equal(first.content[0].text, second.content[0].text);
  for (const text of [first.content[0].text, ...cache.entries.values(), ...cache.entries.keys()]) {
    assert.equal(text.includes(KEY) || text.includes(encodeURIComponent(KEY)), false);
  }
  assert.match(first.content[0].text, /Echo \[REDACTED\]/);
});

test("a failing cache never fails a lookup", async () => {
  const broken: CacheLike = {match: async () => { throw new Error("cache down"); }, put: async () => { throw new Error("cache down"); }};
  const city = CITY("Boise", [rate("Boise", "Ada", 86, 150)]);
  const {call} = setup({runtime: {cache: broken, fetch: gsa({[city.path]: {body: city.body}})}});
  const result = await call("lookup_city_perdiem", {city: "Boise", state: "VA"});
  assert.equal(result.isError, false);
  assert.equal(result.structuredContent.match_type, "exact");
});

test("upstream errors are redacted and reported as tool errors", async () => {
  const path = CITY("Broken", []).path;
  const {call} = setup({runtime: {fetch: gsa({[path]: {status: 500, body: `oops ${KEY}`, headers: {"content-type": "text/plain"}}})}});
  const result = await call("lookup_city_perdiem", {city: "Broken", state: "VA"});
  assert.equal(result.isError, true);
  assert.equal(result.content[0].text.includes(KEY), false);
  assert.match(result.content[0].text, /^Error executing tool lookup_city_perdiem: HTTP 500: .*Response: oops \[REDACTED\]$/);
});

test("pacing spaces upstream starts across isolates and honors Retry-After", async () => {
  const db = d1(new DatabaseSync(DB_FILE));
  setup({db});
  let now = 1_000_000_000_000;
  const waits: number[] = [];
  const responses: Record<string, any> = {
    a: {body: {}}, b: {body: {}},
    limited: {status: 429, body: "{}", headers: {"retry-after": "30", "x-ratelimit-remaining": "0"}},
    c: {body: {}},
  };
  const make = () => new Upstream({
    db, key: KEY, fetch: gsa(responses), clock: () => now, sleep: async ms => { waits.push(ms); now += ms; },
  });
  await make().get("a");
  await make().get("b");
  assert.deepEqual(waits.map(Math.round), [600], "a second isolate waits out the 0.6 s spacing");
  await assert.rejects(make().get("limited"), /Retry-After='30'.*Rate-limit diagnostics: \{'remaining': '0'\}/);
  waits.length = 0;
  await make().get("c");
  assert.ok(waits[0] > 29_000 && waits[0] <= 30_001, `waited ${waits[0]} ms for the provider cooldown`);
});

test("a wait beyond the deadline answers 504, as the container did", async () => {
  const db = d1(new DatabaseSync(DB_FILE));
  const now = Date.now();
  const path = CITY("Boise", []).path;
  const {env} = setup({db});
  db.sqlite.prepare("UPDATE upstream_state SET cooldown_until = ?").run(now / 1000 + MAX_SLOT_WAIT + 5);
  const response = await serve(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "lookup_city_perdiem", arguments: {city: "Boise", state: "VA"}}}), env,
    {now: () => TODAY, cache: null, fetch: gsa({[path]: {body: {}}})});
  assert.equal(response.status, 504);
  assert.deepEqual(await response.json(), {error: "Request deadline exceeded while waiting or processing; retry later."});
});

test("a request still running at the deadline gets the 504", async () => {
  const {env} = setup();
  const hang = (() => new Promise<Response>(() => {})) as typeof fetch;
  const response = await serve(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "lookup_city_perdiem", arguments: {city: "Boise", state: "VA"}}}), env,
    {now: () => TODAY, cache: null, fetch: hang, upstream: {interval: 0}, deadlineMs: 50});
  assert.equal(response.status, 504);
  assert.equal(REQUEST_DEADLINE_MS, 55_000);
});

test("the hourly budget is shared through D1", async () => {
  const db = d1(new DatabaseSync(DB_FILE));
  setup({db});
  const make = () => new Upstream({db, key: KEY, fetch: gsa({a: {body: {}}, b: {body: {}}, c: {body: {}}}), interval: 0, hourlyCap: 2});
  await make().get("a");
  await make().get("b");
  await assert.rejects(make().get("c"), /budget \(2 upstream calls\) is used up\. Retry in about 3600 seconds\./);
});

test("without a loaded release every tool reports the data as temporarily unavailable", async () => {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(schema);
  const {call} = setup({db: d1(sqlite)});
  for (const [name, args] of [["get_data_status", {}], ["lookup_zip_perdiem", {zip_code: "22201"}], ["lookup_city_perdiem", {city: "A", state: "VA"}]] as const) {
    const result = await call(name, args);
    assert.equal(result.isError, true);
    assert.equal(result.content[0].text, `Error executing tool ${name}: GSA Per Diem data is temporarily unavailable. Try again shortly.`);
  }
});

test("D1 work per call stays small", async () => {
  const {db, call} = setup();
  const count = async (name: string, args: Record<string, unknown>) => {
    const before = db.reads;
    await call(name, args);
    return db.reads - before;
  };
  assert.ok(await count("lookup_zip_perdiem", {zip_code: "22201"}) <= 2);
  assert.ok(await count("lookup_state_rates", {state: "VA"}) <= 1);
  assert.ok(await count("lookup_city_perdiem", {city: "Cambridge", state: "MA", county: "Middlesex"}) <= 3);
  const rows = db.sqlite.prepare("SELECT length(data) AS n FROM years").all() as {n: number}[];
  assert.ok(rows.every(r => r.n < 100_000), "one year row stays far below D1's 2 MB row limit");
});

test("argument errors carry pydantic's text", async () => {
  const {call} = setup();
  const result = await call("lookup_zip_perdiem", {zip_code: "22201", fiscal_year: "x".repeat(60), extra: 1});
  assert.equal(result.content[0].text, [
    "Error executing tool lookup_zip_perdiem: 2 validation errors for lookup_zip_perdiemArguments",
    "fiscal_year",
    "  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='xxxxxxxxxxxxxxxxxxxxxxxx...xxxxxxxxxxxxxxxxxxxxxxx', input_type=str]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/int_parsing",
    "extra",
    "  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden",
  ].join("\n"));
  const unknown = await call("nope");
  assert.deepEqual(unknown, {content: [{type: "text", text: "Unknown tool: nope"}], isError: true});
});

test("Python number and text helpers", () => {
  assert.equal(round2(0.125).value, 0.12);
  assert.equal(round2(0.375).value, 0.38);
  assert.equal(round2(2.675).value, 2.67, "2.675 is below the tie in binary");
  assert.equal(round2(51.0).value, 51);
  assert.equal(dumps({a: float(51), b: float(1e16), c: float(1e-5), d: [], e: {}}), '{\n  "a": 51.0,\n  "b": 1e+16,\n  "c": 0.00001,\n  "d": [],\n  "e": {}\n}');
  assert.equal(repr(["it's", 'say "x"', "tab\t", 1.5, float(2), null, true]), `["it's", 'say "x"', 'tab\\t', 1.5, 2.0, None, True]`);
  assert.equal(repr(float(1e-5)), "1e-05");
  const parsed = loads('{"a": 1.0, "b": 2, "c": 99999999999999999999}', {bigints: true});
  assert.equal(dumps(parsed, null), '{"a":1.0,"b":2,"c":99999999999999999999}');
});

// P2-1 (content test 2026-10-10): real GSA responses captured 2026-10-10.
// GSA did not recognize Milton, OH and returned every Ohio rate area; "milton"
// is inside "Hamilton" but is not that rate area.
const REAL_CITY = (file: string) => readFileSync(`${ROOT}servers/gsa-perdiem-mcp/tests/fixtures/gsa_city/${file}`, "utf8");

test("a town whose name is inside an NSA name does not get that NSA's rate", async () => {
  const {call} = setup({runtime: {fetch: gsa({
    "city/Milton/state/OH/year/2027": {body: REAL_CITY("city_Milton_state_OH_year_2027.json")},
    "city/Gardiner/state/MT/year/2027": {body: REAL_CITY("city_Gardiner_state_MT_year_2027.json")},
  })}});
  const milton = (await call("lookup_city_perdiem", {city: "Milton", state: "OH", fiscal_year: 2027})).structuredContent;
  assert.equal(milton.status, "unresolved");
  assert.equal(milton.matched_city, undefined);
  assert.equal(milton.census_suggestion.destination, "Standard Rate");
  assert.equal(milton.census_suggestion.lodging_range, "$113/night");
  assert.equal(milton.census_suggestion.mie_daily, 68);
  const row = (await call("compare_locations", {locations: [{city: "Milton", state: "OH"}], fiscal_year: 2027})).structuredContent.locations[0];
  assert.equal(row.status, "unresolved");
  const gardiner = (await call("lookup_city_perdiem", {city: "Gardiner", state: "MT", fiscal_year: 2027})).structuredContent;
  assert.equal(gardiner.matched_city, "Big Sky / West Yellowstone/Gardiner");
  assert.equal(gardiner.match_type, "composite");
});

test("composite names match whole slash-separated parts only", async () => {
  const cases: [string, string, boolean][] = [
    ["Milton", "Hamilton", false],
    ["Overland", "Kansas City / Overland Park", false],
    ["Park", "Kansas City / Overland Park", false],
    ["Fayette", "Lafayette / West Lafayette", false],
    ["Anton", "San Antonio", false],
    ["Columbia", "District of Columbia", false],
    ["Bedford", "Plymouth / Taunton / New Bedford", false],
    ["Overland Park", "Kansas City / Overland Park", true],
    ["west  lafayette", "Lafayette / West Lafayette", true],
    ["St Petersburg", "Tampa / St. Petersburg", true],
    ["Whitefish", "Kalispell/Whitefish", true],
  ];
  for (const [query, name, match] of cases) {
    const path = `city/${encodeURIComponent(query.replace(/\s+/g, " "))}/state/WY/year/2027`;
    const body = {rates: [{rate: [rate(name, "Somewhere", 80, 150)], state: "WY", year: 2027}]};
    const {call} = setup({runtime: {fetch: gsa({[path]: {body}})}});
    const out = (await call("lookup_city_perdiem", {city: query, state: "WY", fiscal_year: 2027})).structuredContent;
    assert.equal(out.match_type === "composite", match, `${query} vs ${name}: ${out.status} ${out.match_type}`);
  }
});

test("a ZIP answer chosen by county keeps the supplied county (P3-4)", async () => {
  // GSA's FY2027 ZIP file lists 20120 under Fairfax County, VA (District of Columbia) and Loudoun County, VA.
  const {call} = setup();
  const out = (await call("lookup_zip_perdiem", {zip_code: "20120", county: "Fairfax", fiscal_year: 2027})).structuredContent;
  assert.equal(out.status, "resolved");
  assert.equal(out.matched_city, "District of Columbia");
  assert.equal(out.county_supplied, "Fairfax");
  assert.notEqual(out.county, "Fairfax");
  assert.match(out.county, /Fairfax/);
});

test("trip estimates say every night uses one month, flag long stays, and cite the current FTR section (P3-1, P3-6)", async () => {
  const {call} = setup();
  const sf = (await call("estimate_travel_cost", {city: "San Francisco", state: "CA", county: "San Francisco", num_nights: 4, travel_month: "Sep", fiscal_year: 2026})).structuredContent;
  assert.equal(sf.rate_month, "Sep");
  assert.match(sf.rate_month_note, /All 4 nights.*each month/);
  const one = (await call("estimate_travel_cost", {city: "San Francisco", state: "CA", county: "San Francisco", num_nights: 1, travel_month: "Sep", fiscal_year: 2026})).structuredContent;
  assert.equal(one.rate_month_note, undefined);
  const long = (await call("estimate_travel_cost", {city: "San Antonio", state: "TX", county: "Bexar", num_nights: 30, fiscal_year: 2027})).structuredContent;
  assert.equal(long.travel_days, 31);
  assert.match(long.long_term_note, /301-11\.22/);
  const short = (await call("estimate_travel_cost", {city: "San Antonio", state: "TX", county: "Bexar", num_nights: 29, fiscal_year: 2027})).structuredContent;
  assert.equal(short.long_term_note, undefined);
  const tools: {name: string; description: string}[] = JSON.parse(readFileSync(new URL("../tools-contract.json", import.meta.url), "utf8"));
  const description = tools.find(t => t.name === "estimate_travel_cost")?.description ?? "";
  assert.match(description, /301-11\.20\b/);
  assert.doesNotMatch(description, /301-11\.101/);
});

test("the M&IE table explains why its file is named FY 2025 (P3-5)", async () => {
  const {call} = setup();
  const fy2027 = (await call("get_mie_breakdown", {fiscal_year: 2027})).structuredContent;
  assert.equal(fy2027.source.mie_file_covers, "FY2025-present");
  assert.match(fy2027.mie_note, /FY2025.*FY2027/);
  assert.equal((await call("get_mie_breakdown", {fiscal_year: 2025})).structuredContent.mie_note, undefined);
});

test("state lists show season months for seasonal areas (P3-2)", async () => {
  // GSA FY2027 rate file: Virginia Beach $129 Oct-May, $212 Jun-Aug, $129 Sep; Richmond is flat.
  const {call} = setup();
  const rows = JSON.parse((await call("lookup_state_rates", {state: "VA", fiscal_year: 2027})).content[0].text).rates;
  const vb = rows.find((r: any) => r.city === "Virginia Beach").lodging_by_month;
  assert.deepEqual([vb.Oct, vb.May, vb.Jun, vb.Jul, vb.Aug, vb.Sep], [129, 129, 212, 212, 212, 129]);
  const richmond = rows.find((r: any) => r.city === "Richmond");
  assert.equal(richmond.seasonal, false);
  assert.equal(richmond.lodging_by_month, undefined);
});

test("White Sands valid accented/plain county completes lookup, ZIP, estimate and comparison", async () => {
  const {call} = setup();
  for (const county of ["Doña Ana", "Dona Ana", "Doña Ana County", "Dona Ana County"]) {
    const args = {city: "White Sands Missile Range", state: "NM", county, fiscal_year: 2027};
    const lookup = (await call("lookup_city_perdiem", args)).structuredContent;
    assert.equal(lookup.status, "resolved");
    assert.equal(lookup.is_standard_rate, true);
    assert.equal(lookup.mie_daily, 68);
    const trip = (await call("estimate_travel_cost", {...args, num_nights: 2, travel_month: "May"})).structuredContent;
    assert.equal(trip.lodging_total, 226);
    assert.equal(trip.mie_total.value, 170);
    assert.equal(trip.grand_total.value, 396);
    const zip = (await call("lookup_zip_perdiem", {zip_code: "88002", county, fiscal_year: 2027})).structuredContent;
    assert.equal(zip.status, "resolved");
    assert.equal(zip.mie_daily, 68);
    const comparison = (await call("compare_locations", {locations: [{city: args.city, state: args.state, county}], fiscal_year: 2027})).structuredContent;
    assert.equal(comparison.locations[0].status, "resolved");
    assert.equal(comparison.locations[0].max_daily_total, 181);
  }
});
