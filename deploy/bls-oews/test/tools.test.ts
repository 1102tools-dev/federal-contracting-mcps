// Tool handlers, Python-compatible output, and MCP/HTTP edge behavior against
// a D1-shaped adapter over node:sqlite, using the schema.sql the loader
// applies and a few real cells from the bundled May 2025 release.
// Whole-release parity with the Python server is scripts/parity.py.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {mock, test} from "node:test";
import worker, {callTool, handleMessage} from "../src/worker.ts";
import {dumps, fixed, floatRepr, parseJson, PyFloat, repr, strip} from "../src/pyjson.ts";
import {TOOLS, validateArgs} from "../src/tools.ts";
import {d1} from "./d1.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const schema = read("../schema.sql");
// The package's manifest, pinned to the release the fixture cells come from.
const bundled = JSON.parse(read("../../../servers/bls-oews-mcp/src/bls_oews_mcp/data/manifest.json"));
const manifest = {...bundled, data_year: "2025", release: {...bundled.release, year: "2025", description: "May 2025"}};
const SERVER = JSON.parse(read("../../../servers/bls-oews-mcp/server.json"));
const FOOTNOTES = {
  "4": "Wages for some occupations that do not generally work year-round, full time, are reported either as hourly wages or annual salaries depending on how they are typically paid.",
  "5": "This wage is equal to or greater than $115.00 per hour or $239,200 per year.",
  "8": "Estimate not released.",
};
// [key, v01..v17, {fNN: footnote code}] as loaded from the bundled release.
const CELLS: [string, (string | null)[], Record<string, string>][] = [
  ["OEUN0000000000000151252", ["1687890", "0.6", "71.20", "148100", "0.4", "39.64", "50.58", "65.38", "82.68", "103.21", "82460", "105210", "135980", "171980", "214670", null, null], {}],
  ["OEUM0047900000000151252", ["69060", "3.2", "73.61", "153100", "1.0", "46.37", "59.48", "74.49", "84.73", "102.72", "96450", "123720", "154930", "176230", "213660", "22.020", "2.03"], {}],
  ["OEUS5100000000000151252", ["88280", "3.0", "70.36", "146340", "1.0", "40.07", "51.25", "65.61", "82.26", "101.89", "83350", "106600", "136460", "171090", "211930", "21.484", "1.98"], {}],
  ["OEUN0000000000000252021", ["1388390", "0.8", "-", "72650", "0.4", "-", "-", "-", "-", "-", "47960", "57710", "63970", "81450", "104340", null, null],
    {f03: "4", f06: "4", f07: "4", f08: "4", f09: "4", f10: "4"}],
  ["OEUM0010540000000291215", ["50", "12.9", "-", "-", "5.6", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "1.003", "1.45"],
    {f03: "5", f04: "5", f06: "5", f07: "5", f08: "5", f09: "5", f10: "5", f11: "5", f12: "5", f13: "5", f14: "5", f15: "5"}],
  // 2026-10-10 content test repros, as BLS publishes them in oe.data.0.Current.
  ["OEUM0047260000000151232", ["2430", "6.3", "29.96", "62310", "1.7", "19.01", "23.33", "28.68", "36.05", "44.55", "39530", "48520", "59650", "74980", "92660", "3.185", "0.69"], {}],
  ["OEUM0017820000000151242", ["110", "19.5", "56.78", "118110", "9.4", "27.29", "40.80", "56.81", "77.08", "80.56", "56770", "84850", "118170", "160330", "167570", "0.357", "0.79"], {}],
  ["OEUM0047900000000291214", ["770", "27.9", "-", "-", "4.5", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "0.247", "1.17"],
    {f03: "5", f04: "5", f06: "5", f07: "5", f08: "5", f09: "5", f10: "5", f11: "5", f12: "5", f13: "5", f14: "5", f15: "5"}],
  ["OEUM0014740000000151212", ["70", "14.1", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "0.712", "0.58"],
    {f03: "8", f04: "8", f05: "8", f06: "8", f07: "8", f08: "8", f09: "8", f10: "8", f11: "8", f12: "8", f13: "8", f14: "8", f15: "8"}],
  ["OEUS2400000000000151212", ["8650", "9.9", "72.09", "149940", "3.7", "38.04", "51.34", "67.14", "88.10", "104.12", "79130", "106790", "139640", "183260", "216570", "3.131", "2.55"], {}],
];
const OCCUPATIONS = [["151252", "Software Developers"], ["252021", "Elementary School Teachers, Except Special Education"], ["291215", "Family Medicine Physicians"],
  ["151232", "Computer User Support Specialists"], ["151242", "Database Administrators"], ["291214", "Emergency Medicine Physicians"], ["151212", "Information Security Analysts"]];
const AREAS = [["0000000", "National"], ["0047900", "Washington-Arlington-Alexandria, DC-VA-MD-WV"], ["5100000", "Virginia"], ["0010540", "Albany, OR"], ["7800000", "Virgin Islands"],
  ["0047260", "Virginia Beach-Chesapeake-Norfolk, VA-NC"], ["0017820", "Colorado Springs, CO"], ["0014740", "Bremerton-Silverdale-Port Orchard, WA"], ["2400000", "Maryland"]];

function addVersion(sqlite: DatabaseSync, version: number, adjust = (value: string | null) => value) {
  sqlite.prepare("INSERT INTO release (version, database_sha256, manifest, footnotes, loaded_at) VALUES (?, ?, ?, ?, ?)")
    .run(version, manifest.database_sha256, JSON.stringify(manifest), JSON.stringify(FOOTNOTES), "2026-10-08T00:00:00Z");
  const columns = Array.from({length: 17}, (_, i) => String(i + 1).padStart(2, "0"));
  const insert = sqlite.prepare(`INSERT INTO cell (version, key, ${columns.map(c => `v${c}`).join(", ")}, ${columns.map(c => `f${c}`).join(", ")}) VALUES (${Array(36).fill("?").join(", ")})`);
  for (const [key, values, notes] of CELLS) insert.run(version, key, ...values.map(adjust), ...columns.map(c => notes[`f${c}`] ?? null));
  for (const [code, name] of OCCUPATIONS) sqlite.prepare("INSERT INTO occupation (version, code, name) VALUES (?, ?, ?)").run(version, code, name);
  for (const [code, name] of AREAS) sqlite.prepare("INSERT INTO area (version, code, name) VALUES (?, ?, ?)").run(version, code, name);
}

function database({active = true} = {}) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(schema);
  addVersion(sqlite, 1);
  if (active) sqlite.exec("INSERT INTO active_release (id, version) VALUES (1, 1)");
  return {sqlite, db: d1(sqlite)};
}

const {db} = database();
const env = (allow = true, DB: unknown = db) => ({DB, REQUEST_LIMITER: {limit: async () => ({success: allow})}, RELEASE_SHA: "abc123"}) as any;
const call = async (name: string, args: Record<string, unknown>, DB: unknown = db) => await callTool(name, args, env(true, DB)) as any;
const data = async (name: string, args: Record<string, unknown>) => {
  const result = await call(name, args);
  assert.equal(result.isError, false, result.content[0].text);
  return JSON.parse(result.content[0].text);
};
const errorText = async (name: string, args: Record<string, unknown>) => {
  const result = await call(name, args);
  assert.equal(result.isError, true);
  assert.equal(result.structuredContent, undefined);
  return result.content[0].text as string;
};
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://bls-oews.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers}, body: typeof body === "string" ? body : JSON.stringify(body)});

// ---------- contract and protocol ----------

test("tools/list is the reviewed contract, verbatim", async () => {
  assert.deepEqual(TOOLS, JSON.parse(read("../tools-contract.json")));
  const list = await handleMessage({jsonrpc: "2.0", id: 1, method: "tools/list"}, env()) as any;
  assert.equal(JSON.stringify(list.result.tools), JSON.stringify(JSON.parse(read("../tools-contract.json"))));
  assert.equal(TOOLS.length, 8);
});

test("initialize matches the Python server", async () => {
  const init = await handleMessage({jsonrpc: "2.0", id: 1, method: "initialize", params: {protocolVersion: "2025-06-18", capabilities: {}, clientInfo: {name: "t", version: "1"}}}, env());
  assert.equal(dumps(init), `{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"listChanged":false,"subscribe":false},"tools":{"listChanged":false}},"protocolVersion":"2025-06-18","serverInfo":{"name":"bls-oews","version":"${SERVER.version}"}}}`);
  const future = await handleMessage({jsonrpc: "2.0", id: 2, method: "initialize", params: {protocolVersion: "2099-01-01", capabilities: {}, clientInfo: {name: "t", version: "1"}}}, env()) as any;
  assert.equal(future.result.protocolVersion, "2025-11-25");
  const bad = await handleMessage({jsonrpc: "2.0", id: 3, method: "initialize", params: {protocolVersion: "2025-06-18", capabilities: {}, clientInfo: {name: "t"}}}, env()) as any;
  assert.deepEqual(bad.error, {code: -32602, message: "Invalid request parameters", data: ""});
});

test("other methods answer like the Python SDK", async () => {
  const ask = async (method: string, params?: unknown) => await handleMessage({jsonrpc: "2.0", id: 9, method, params}, env()) as any;
  assert.deepEqual((await ask("prompts/list")).result, {prompts: []});
  assert.deepEqual((await ask("resources/list")).result, {resources: []});
  assert.deepEqual((await ask("resources/templates/list")).result, {resourceTemplates: []});
  assert.deepEqual((await ask("ping")).result, {});
  assert.deepEqual((await ask("resources/read", {uri: "x://y"})).error, {code: -32602, message: "Unknown resource: x://y", data: {uri: "x://y"}});
  assert.deepEqual((await ask("prompts/get", {name: "p"})).error, {code: 0, message: "Unknown prompt: p", data: undefined});
  assert.deepEqual((await ask("tools/frob")).error, {code: -32601, message: "Method not found", data: "tools/frob"});
  const unknown = await ask("tools/call", {name: "nope", arguments: {}});
  assert.equal(dumps(unknown.result), `{"content":[{"text":"Unknown tool: nope","type":"text"}],"isError":true}`);
});

// ---------- tool results ----------

test("get_wage_data formats every datatype like the Python server", async () => {
  const all = Array.from({length: 17}, (_, i) => String(i + 1).padStart(2, "0"));
  const result = await call("get_wage_data", {occ_code: "15-1252", scope: "metro", area_code: "47900", datatypes: all});
  const wages = result.structuredContent.get("wages");
  const formatted = Object.fromEntries([...wages].map(([label, value]: [string, Map<string, unknown>]) => [label, value.get("formatted")]));
  assert.deepEqual(formatted, {
    "Employment": "69,060", "Employment RSE (%)": "3.2%", "Hourly Mean Wage": "$73.61/hr", "Annual Mean Wage": "$153,100",
    "Mean Wage RSE (%)": "1.0%", "Hourly 10th Percentile": "$46.37/hr", "Hourly 25th Percentile": "$59.48/hr", "Hourly Median": "$74.49/hr",
    "Hourly 75th Percentile": "$84.73/hr", "Hourly 90th Percentile": "$102.72/hr", "Annual 10th Percentile": "$96,450",
    "Annual 25th Percentile": "$123,720", "Annual Median": "$154,930", "Annual 75th Percentile": "$176,230", "Annual 90th Percentile": "$213,660",
    "Employment per 1,000 Jobs": "22.02", "Location Quotient": "2.03",
  });
  // The text is pydantic_core.to_json(indent=2): floats keep ".0", ints do not.
  const text: string = result.content[0].text;
  assert.equal(text, dumps(result.structuredContent, 2));
  assert.match(text, /"raw": "1\.0",\n {6}"formatted": "1\.0%",\n {6}"numeric": 1\.0,/);
  assert.match(text, /"raw": "153100",\n {6}"formatted": "\$153,100",\n {6}"numeric": 153100,/);
  assert.match(text, /"numeric": 22\.02,/);
  assert.equal(result.structuredContent.get("area_name"), "Washington-Arlington-Alexandria, DC-VA-MD-WV");
  assert.equal(result.structuredContent.get("data_year"), "2025");
});

test("unpublished cells carry the BLS footnote; no-data results say why", async () => {
  const teachers = await data("get_wage_data", {occ_code: "252021", datatypes: ["03", "04"]});
  assert.deepEqual(teachers.wages["Hourly Mean Wage"], {raw: "-", formatted: `[Not published] ${FOOTNOTES["4"]}`, numeric: null, suppressed: true});
  assert.equal(teachers.wages["Annual Mean Wage"].numeric, 72650);
  const physicians = await data("get_wage_data", {occ_code: "291215", scope: "metro", area_code: 10540, datatypes: ["15"]});
  assert.equal(physicians.wages["Annual 90th Percentile"].formatted, `[Not published] ${FOOTNOTES["5"]}`);
  assert.equal(physicians.no_data, true);
  assert.match(physicians.no_data_reason, /BLS publishes no estimate for this occupation/);
  const unknownSoc = await data("get_wage_data", {occ_code: "999999"});
  assert.match(unknownSoc.no_data_reason, /occ_code=999999 is not an occupation in the May 2025 OEWS release/);
  assert.equal(unknownSoc.data_year, null);
  assert.deepEqual(unknownSoc.wages["Annual Mean Wage"], {raw: null, formatted: "No data", numeric: null, suppressed: true});
  const unknownArea = await data("get_wage_data", {occ_code: "151252", scope: "metro", area_code: "99999"});
  assert.match(unknownArea.no_data_reason, /area_code='99999' is not an OEWS area/);
  const national = await data("get_wage_data", {occ_code: "151252", area_code: 51});
  assert.equal(national._note, "area_code=51 was ignored because scope='national'. Use scope='state' or scope='metro' for geographic breakdowns.");
});

test("compare tools keep the caller's labels, in order, and collapse duplicates", async () => {
  const metros = await call("compare_metros", {occ_code: "151252", metro_codes: [" 47900", "0047900", "99999"]});
  assert.deepEqual([...metros.structuredContent.get("metros").keys()], ["47900", "99999"]);
  assert.match(metros.content[0].text, /"_note": "Inputs \['0047900'\] normalized to the same series/);
  const occupations = await data("compare_occupations", {occ_codes: ["151252", "", "15-1252", "252021"], scope: "state", area_code: "51", datatype: "17"});
  assert.deepEqual(Object.keys(occupations.occupations), ["151252 (Software Developers)", "252021 (Elementary School Teachers, Except Special Education)"]);
  assert.equal(occupations.occupations["151252 (Software Developers)"].formatted, "1.98");
});

test("list_common_metros keeps Python's key order for numeric-looking codes", async () => {
  const result = await call("list_common_metros", {});
  assert.ok(result.content[0].text.startsWith('{\n  "metros": {\n    "0047900": "Washington DC",\n    "0042660": "Seattle",'));
});

test("igce_wage_benchmark: Python float formatting and annual-only warning", async () => {
  const ints = await data("igce_wage_benchmark", {occ_code: "151252", burden_low: 2, burden_high: "2.5"});
  assert.equal(ints.burden_range, "2.0x - 2.5x");
  assert.deepEqual(ints.benchmarks["Annual Mean Wage"], {
    annual: "$148,100", hourly_base: "$71.20", hourly_burdened_low: "$142.40", hourly_burdened_high: "$178.00", numeric_annual: 148100, numeric_hourly: 71.2,
  });
  assert.match((await call("igce_wage_benchmark", {occ_code: "151252", burden_low: 2})).content[0].text, /"numeric_hourly": 71\.2\n/);
  const teachers = await data("igce_wage_benchmark", {occ_code: "25-2021"});
  assert.equal(teachers.annual_only, true);
  assert.match(teachers._hourly_warning, /does not generally work a 2080-hour year/);
  const unknown = await data("igce_wage_benchmark", {occ_code: "999999"});
  assert.equal(unknown.occ_title, "999999");
  assert.match(unknown._title_warning, /occ_code='999999' is not an occupation/);
  assert.equal(await errorText("igce_wage_benchmark", {occ_code: "151252", burden_low: 2.5, burden_high: 2}),
    "Error executing tool igce_wage_benchmark: burden_low (2.5) must be <= burden_high (2.0).");
});

test("detect_latest_year, get_data_status, and list_common_soc_codes cite the release", async () => {
  const latest = await data("detect_latest_year", {});
  assert.deepEqual([latest.latest_year, latest.default_year, latest.newer_data_available], ["2025", "2025", false]);
  const status = await data("get_data_status", {});
  assert.equal(status.status, "bundled");
  assert.equal(status.api_key_required, false);
  assert.deepEqual(Object.keys(status.sources), Object.keys(manifest.sources).sort());
  assert.equal(status.source.kind, "bundled_bls_oews_files");
  const socs = await data("list_common_soc_codes", {});
  assert.equal(socs.soc_codes["151252"], "Software Developers");
});

// ---------- validation ----------

test("argument errors use pydantic's text, fields in signature order", async () => {
  const text = await errorText("get_wage_data", {scope: "county", datatypes: [4], extra: 1.0});
  assert.equal(text, [
    "Error executing tool get_wage_data: 4 validation errors for get_wage_dataArguments",
    "occ_code", "  Field required [type=missing, input_value={'scope': 'county', 'datatypes': [4], 'extra': 1}, input_type=dict]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/missing",
    "scope", "  Input should be 'national', 'state' or 'metro' [type=literal_error, input_value='county', input_type=str]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/literal_error",
    "datatypes.0", "  Input should be a valid string [type=string_type, input_value=4, input_type=int]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/string_type",
    "extra", "  Extra inputs are not permitted [type=extra_forbidden, input_value=1, input_type=int]",
    "    For further information visit https://errors.pydantic.dev/2.13/v/extra_forbidden",
  ].join("\n"));
  // Union[str, int]: both branches reported; floats from the request stay floats.
  const union = await errorText("compare_metros", parseJson('{"occ_code": 1.5, "metro_codes": "x", "zz": "' + "é".repeat(30) + '"}') as any);
  assert.match(union, /occ_code\.str\n {2}Input should be a valid string \[type=string_type, input_value=1\.5, input_type=float\]/);
  assert.match(union, /occ_code\.int\n {2}Input should be a valid integer, got a number with a fractional part \[type=int_from_float/);
  assert.match(union, /metro_codes\n {2}Input should be a valid list \[type=list_type, input_value='x', input_type=str\]/);
  assert.match(union, /input_value='éééééééééééé\.\.\.ééééééééééé', input_type=str/);
  // pre_parse_json, lax coercions, and pydantic's float parsing.
  assert.deepEqual(validateArgs("get_wage_data", {occ_code: true, datatypes: '["04"]', year: "null"}),
    {occ_code: 1, scope: "national", area_code: null, industry: "000000", datatypes: ["04"], year: null});
  const burdens = validateArgs("igce_wage_benchmark", {occ_code: 151252.0, burden_low: "1_5e-1", burden_high: "\u2003inf "});
  assert.deepEqual([burdens.burden_low.value, burdens.burden_high.value], [1.5, Infinity]);
  assert.throws(() => validateArgs("igce_wage_benchmark", {occ_code: "1", burden_low: " 1_0 "}), /float_parsing/);
  assert.equal(await errorText("get_wage_data", {occ_code: "151252", year: "2024"}),
    "Error executing tool get_wage_data: year=2024 is before the current OEWS release. This server answers from the current release only (May 2025, data year 2025). For historical OEWS data, download from bls.gov/oes/tables.htm. Omit the year argument to get current data.");
  assert.equal(await errorText("get_wage_data", {occ_code: "１５１２５２"}),
    "Error executing tool get_wage_data: occ_code='１５１２５２' must be a SOC code like '15-1252' or '151252' (6 ASCII digits, optional single dash after the first 2). No letters, whitespace, or Unicode digits.");
});

// ---------- D1 use ----------

test("one D1 round trip per call, two when a year is passed", async () => {
  const trips = async (name: string, args: Record<string, unknown>) => {
    const start = db.log.length;
    await call(name, args);
    const statements = db.log.slice(start);
    for (const s of statements) assert.ok(s.values.length <= 100, "D1 allows 100 bound parameters");
    return new Set(statements.map(s => s.batch)).size;
  };
  assert.equal(await trips("get_wage_data", {occ_code: "151252"}), 1);
  assert.equal(await trips("get_wage_data", {occ_code: "151252", year: 2025}), 2);
  assert.equal(await trips("compare_metros", {occ_code: "151252", metro_codes: Array.from({length: 50}, (_, i) => 10000 + i)}), 1);
  assert.equal(await trips("igce_wage_benchmark", {occ_code: "151252"}), 1);
  assert.equal(await trips("get_wage_data", {occ_code: "bad"}), 0);
});

test("readers see only the active release; a switch is atomic", async () => {
  const {sqlite: other, db: otherDb} = database();
  addVersion(other, 2, value => (value === "148100" ? "150000" : value));
  const mean = async () => (await callTool("get_wage_data", {occ_code: "151252", datatypes: ["04"]}, env(true, otherDb)) as any)
    .structuredContent.get("wages").get("Annual Mean Wage").get("numeric");
  assert.equal(await mean(), 148100);
  other.exec("UPDATE active_release SET version = 2 WHERE id = 1");
  assert.equal(await mean(), 150000);
});

test("missing data or a D1 failure is a generic tool error without arguments in logs", async () => {
  const logged: string[] = [];
  const original = console.log;
  console.log = (line: string) => logged.push(line);
  try {
    const empty = database({active: false}).db;
    assert.equal((await call("get_data_status", {}, empty)).content[0].text,
      "Error executing tool get_data_status: BLS OEWS data is temporarily unavailable. Try again shortly.");
    const broken = {prepare: () => { throw new Error("D1 down"); }, batch: () => { throw new Error("D1 down"); }};
    const result = await call("get_wage_data", {occ_code: "151252"}, broken);
    assert.deepEqual([result.isError, result.structuredContent], [true, undefined]);
    assert.match(result.content[0].text, /temporarily unavailable/);
  } finally {
    console.log = original;
  }
  assert.equal(logged.length, 2);
  for (const line of logged) {
    assert.equal(JSON.parse(line).event, "tool_failed");
    assert.ok(!line.includes("151252"));
  }
});

// ---------- HTTP ----------

test("HTTP edge: health, docs, origin, rate limit, methods, body limits, message kinds", async () => {
  const health = await worker.fetch(new Request("https://bls-oews.1102tools.com/health"), env());
  assert.deepEqual(await health.json(), {status: "ok", tools: 8, release_sha: "abc123", admission: {processing: 16, waiting: 32, total: 48, deadline_seconds: 55}});
  const unset = await worker.fetch(new Request("https://bls-oews.1102tools.com/health"), {...env(), RELEASE_SHA: undefined});
  assert.equal((await unset.json() as any).release_sha, "development");
  assert.equal((await worker.fetch(new Request("https://bls-oews.1102tools.com/privacy"), env())).status, 200);
  assert.equal((await worker.fetch(new Request("https://bls-oews.1102tools.com/nope"), env())).status, 404);
  const response = await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "list_common_metros", arguments: {}}}), env());
  const body = await response.text();
  assert.ok(body.includes('"structuredContent":{"metros":{"0047900":"Washington DC","0042660":"Seattle"'), "numeric-looking keys keep their order");
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized"}), env())).status, 202);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", id: 1.5, method: "ping"}), env())).status, 202);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", id: 1, result: {}}), env())).status, 202);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "ping", params: []}), env())).status, 400);
  assert.equal((await worker.fetch(post({}, {Origin: "https://evil.example"}), env())).status, 403);
  assert.equal((await worker.fetch(post({}), env(false))).status, 429);
  assert.equal((await worker.fetch(new Request("https://bls-oews.1102tools.com/mcp"), env())).status, 405);
  assert.equal((await worker.fetch(post("{"), env())).status, 400);
  assert.equal((await worker.fetch(post([{jsonrpc: "2.0", id: 1, method: "ping"}]), env())).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(70000)), env())).status, 413);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "ping"}, {"Content-Type": "text/plain"}), env())).status, 400);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "ping"}, {Accept: "text/event-stream"}), env())).status, 406);
});

// ---------- MCP 2026-07-28 ----------

const META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}};
const modern = (method: string, params: Record<string, unknown> = {}, headers: Record<string, string> = {}) =>
  post({jsonrpc: "2.0", id: 7, method, params: {...params, _meta: META}},
    {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, ...(typeof params.name === "string" ? {"Mcp-Name": params.name} : {}), ...headers});

test("2026-07-28 requests get the SDK's envelope: discover, decorated results, json.dumps text", async () => {
  const stamp = `"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"bls-oews","version":"${SERVER.version}"}}`;
  const discover = await worker.fetch(modern("server/discover"), env());
  assert.equal(await discover.text(), `{"jsonrpc":"2.0","id":7,"result":{"cacheScope":"private","capabilities":{"prompts":{"listChanged":true},"resources":{"listChanged":true,"subscribe":true},"tools":{"listChanged":true}},"resultType":"complete","supportedVersions":["2026-07-28"],"ttlMs":0,${stamp}}}`);
  const list = JSON.parse(await (await worker.fetch(modern("tools/list"), env())).text());
  assert.deepEqual(Object.keys(list.result), ["cacheScope", "resultType", "tools", "ttlMs", "_meta"]);
  const call = await worker.fetch(modern("tools/call", {name: "get_wage_data", arguments: {occ_code: "é"}}), env());
  const text = await call.text();
  assert.ok(text.includes("occ_code='\\u00e9' must be a SOC code"), "non-ASCII is escaped like json.dumps");
  assert.ok(text.endsWith(`"isError":true,"resultType":"complete",${stamp}}}`));
  const ok = JSON.parse(await (await worker.fetch(modern("tools/call", {name: "list_common_metros", arguments: {}}), env())).text());
  assert.deepEqual(Object.keys(ok.result), ["content", "isError", "resultType", "structuredContent", "_meta"]);
});

test("2026-07-28 validation ladder, statuses, and methods outside the 2026 surface", async () => {
  const answer = async (request: Request) => {
    const response = await worker.fetch(request, env());
    return [response.status, (await response.json() as any).error] as const;
  };
  assert.deepEqual(await answer(modern("tools/call", {name: "get_data_status"}, {"Mcp-Name": "other"})),
    [400, {code: -32020, message: "mcp-name header does not match the request body's 'name' parameter"}]);
  assert.deepEqual(await answer(modern("tools/list", {}, {"Mcp-Method": "tools/call"})),
    [400, {code: -32020, message: "mcp-method header does not match the request body's method"}]);
  assert.deepEqual(await answer(post({jsonrpc: "2.0", id: 1, method: "tools/list", params: {_meta: {...META, "io.modelcontextprotocol/protocolVersion": "2027-01-01"}}},
    {"MCP-Protocol-Version": "2027-01-01", "Mcp-Method": "tools/list"})),
    [400, {code: -32022, message: "Unsupported protocol version", data: {supported: ["2026-07-28"], requested: "2027-01-01"}}]);
  assert.deepEqual(await answer(post({jsonrpc: "2.0", id: 1, method: "tools/list"}, {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"})),
    [400, {code: -32602, message: "params._meta must be an object carrying the required 'io.modelcontextprotocol/protocolVersion' and 'io.modelcontextprotocol/clientCapabilities' envelope keys"}]);
  assert.deepEqual(await answer(modern("ping")), [404, {code: -32601, message: "Method not found", data: "ping"}]);
  assert.deepEqual(await answer(modern("tools/call", {arguments: {}})), [400, {code: -32602, message: "Invalid request parameters", data: ""}]);
  assert.deepEqual(await answer(modern("prompts/get", {name: "p"})), [200, {code: -32603, message: "Internal server error"}]);
  const base64 = await worker.fetch(modern("tools/call", {name: "list_common_metros", arguments: {}}, {"Mcp-Name": "=?base64?bGlzdF9jb21tb25fbWV0cm9z?="}), env());
  assert.equal(base64.status, 200);
  const notification = await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized", params: {_meta: META}}, {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "notifications/initialized"}), env());
  assert.deepEqual([notification.status, await notification.text()], [400, '{"jsonrpc":"2.0","error":{"code":-32600,"message":"Body must be a single JSON-RPC request object"},"id":null}']);
});

test("2026-07-28 listen streams open at the edge with the SDK's acknowledgement", async () => {
  // Fake timers, so the stream's 15-second keepalive does not hold the test open.
  mock.timers.enable({apis: ["setTimeout"]});
  try {
    const response = await worker.fetch(modern("subscriptions/listen", {notifications: {toolsListChanged: true}}), env());
    assert.equal(response.headers.get("Content-Type"), "text/event-stream");
    const reader = response.body!.getReader();
    const first = new TextDecoder().decode((await reader.read()).value);
    assert.match(first, /^event: message\r\ndata: \{"jsonrpc":"2.0","method":"notifications\/subscriptions\/acknowledged"/);
    await new Promise(resolve => setImmediate(resolve)); // the stream is now waiting on its (fake) keepalive timer
    await reader.cancel();
  } finally {
    mock.timers.reset();
  }
  const jsonOnly = await worker.fetch(modern("subscriptions/listen", {notifications: {}}, {Accept: "application/json"}), env());
  assert.equal(jsonOnly.status, 406);
});

// ---------- 2026-10-10 content test (BLS-1 to BLS-9) ----------

test("BLS-1: the IGCE names the wage month beside the burdened rates", async () => {
  const igce = await data("igce_wage_benchmark", {occ_code: "15-1232", scope: "metro", area_code: "47260"});
  assert.equal(igce.wage_period, "May 2025");
  assert.match(igce._escalation_note, /^May 2025 wages; escalate to the period of performance/);
  const keys = Object.keys(igce);
  assert.ok(keys.indexOf("wage_period") < keys.indexOf("benchmarks") && keys.indexOf("benchmarks") < keys.indexOf("_escalation_note"));
  // The month comes from the release in D1, not from the code.
  const {sqlite, db: later} = database();
  sqlite.prepare("UPDATE release SET manifest = ?").run(JSON.stringify({...manifest, release: {...manifest.release, description: "May 2031"}}));
  const next = JSON.parse((await call("igce_wage_benchmark", {occ_code: "151252"}, later)).content[0].text);
  assert.equal(next.wage_period, "May 2031");
  assert.match(next._escalation_note, /^May 2031 wages; escalate/);
});

test("BLS-7: IGCE hourly figures are BLS's published hourly wages", async () => {
  // BLS dt06 = 19.01; annual 39,530 / 2080 gave 19.00.
  const tenth = (await data("igce_wage_benchmark", {occ_code: "15-1232", scope: "metro", area_code: "47260"})).benchmarks["Annual 10th Percentile"];
  assert.deepEqual([tenth.annual, tenth.hourly_base, tenth.numeric_hourly, tenth.hourly_burdened_low], ["$39,530", "$19.01", 19.01, "$34.22"]);
  // Annual-only occupations still fall back to annual / 2080 (63,970 / 2080 = 30.75).
  const teachers = await data("igce_wage_benchmark", {occ_code: "25-2021"});
  assert.equal(teachers.benchmarks["Annual Median"].hourly_base, "$30.75");
});

test("BLS-3: the IGCE carries the 25th and 75th percentiles", async () => {
  const bench = (await data("igce_wage_benchmark", {occ_code: "15-1242", scope: "metro", area_code: "17820"})).benchmarks;
  assert.deepEqual(Object.keys(bench), ["Annual Mean Wage", "Annual 10th Percentile", "Annual 25th Percentile", "Annual Median", "Annual 75th Percentile", "Annual 90th Percentile"]);
  assert.deepEqual([bench["Annual 25th Percentile"].annual, bench["Annual 25th Percentile"].hourly_base], ["$84,850", "$40.80"]);
  assert.deepEqual([bench["Annual 75th Percentile"].annual, bench["Annual 75th Percentile"].hourly_base], ["$160,330", "$77.08"]);
});

test("BLS-2: the IGCE shows the sample behind the benchmark", async () => {
  const thin = await data("igce_wage_benchmark", {occ_code: "15-1242", scope: "metro", area_code: "17820"});
  assert.deepEqual(thin.reliability, {employment: "110", employment_rse: "19.5%", mean_wage_rse: "9.4%"});
  assert.match(thin._reliability_warning, /employment RSE 19\.5%/);
  assert.doesNotMatch(thin._reliability_warning, /mean wage RSE/);
  const solid = await data("igce_wage_benchmark", {occ_code: "15-1252", scope: "metro", area_code: "47900"});
  assert.deepEqual(solid.reliability, {employment: "69,060", employment_rse: "3.2%", mean_wage_rse: "1.0%"});
  assert.equal(solid._reliability_warning, undefined);
  // Employment alone does not make a wageless cell look benchmarked.
  const topCoded = await data("igce_wage_benchmark", {occ_code: "29-1214", scope: "metro", area_code: "47900"});
  assert.equal(topCoded.no_data, true);
  assert.equal(topCoded.reliability.employment, "770");
});

// ---------- Python formatting helpers ----------

test("pyjson matches Python's repr, format, round, and strip", () => {
  assert.deepEqual([1.8, 2, 1e-5, 1e16, 0.1 + 0.2, -0].map(x => floatRepr(x)), ["1.8", "2.0", "1e-05", "1e+16", "0.30000000000000004", "-0.0"]);
  assert.deepEqual([1e-5, 1.5e-7, 1e16, 2].map(x => dumps(new PyFloat(x))), ["0.00001", "1.5e-7", "1e+16", "2.0"]);
  assert.deepEqual([[0.125, 2], [0.375, 2], [2.675, 2], [2.5, 0], [1e21, 1]].map(([x, p]) => fixed(x, p)), ["0.12", "0.38", "2.67", "2", "1000000000000000000000.0"]);
  assert.equal(repr("it's"), `"it's"`);
  assert.equal(repr(`a'b"c\n`), `'a\\'b"c\\n'`);
  assert.equal(repr({k: [1, new PyFloat(2), true, null]}), "{'k': [1, 2.0, True, None]}");
  assert.equal(strip("\x1c 51\u3000"), "51");
  assert.equal(strip("51\ufeff"), "51\ufeff");
  const parsed = parseJson('{"a": 2.0, "b": 2, "c": 123456789012345678901234567890}') as any;
  assert.ok(parsed.a instanceof PyFloat);
  assert.equal(parsed.b, 2);
  assert.equal(parsed.c, 123456789012345678901234567890n);
});
