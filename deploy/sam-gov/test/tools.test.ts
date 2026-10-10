// Tool handlers and MCP edge behavior against a D1-shaped adapter over
// node:sqlite, using the same schema.sql the loader applies.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import worker, {handleMessage} from "../src/index.ts";
import {ftsQuery, getDataStatus, getOpportunity, searchOpportunities, summarizeOpportunities, TOOLS, ToolError} from "../src/tools.ts";

const NOW = new Date("2026-09-27T12:00:00Z");
const schema = readFileSync(new URL("../schema.sql", import.meta.url), "utf8");

function d1(sqlite: DatabaseSync) {
  return {
    prepare: (sql: string) => ({
      bind: (...values: unknown[]) => ({
        all: async () => ({results: sqlite.prepare(sql).all(...(values as any[])) as any[]}),
      }),
    }),
  };
}

const id = (n: number) => n.toString(16).padStart(32, "0");

function notice(n: number, fields: Record<string, unknown> = {}) {
  return {
    notice_id: id(n), title: `Notice ${n}`, solicitation_number: `SOL-${n}`, department: "DEPT OF DEFENSE",
    sub_tier: "DEPT OF THE ARMY", office: "W6QK ACC-APG", posted_at: "2026-09-01 10:00:00", posted_date: "2026-09-01",
    notice_type: "Solicitation", archive_date: "2026-12-31", set_aside_code: null, set_aside: null,
    response_deadline: "2026-10-15T14:00:00-04:00", response_deadline_utc: "2026-10-15T18:00:00Z",
    naics_code: "541512", psc_code: "D302", pop_state: null, office_state: "MD", description: "Routine services.", row_hash: `h${n}`,
    ...fields,
  };
}

const NOTICES = [
  notice(1, {title: "Zero trust network upgrade", description: "Implement zero trust architecture across bases.", set_aside_code: "SBA", set_aside: "Total Small Business Set-Aside (FAR 19.5)", pop_state: "MD"}),
  notice(2, {title: "Cloud migration", description: "Trust but verify. Zero-day patching and cloud hosting.", naics_code: "541519", notice_type: "Combined Synopsis/Solicitation", response_deadline: "2026-10-01T14:00:00-04:00", response_deadline_utc: "2026-10-01T18:00:00Z", posted_at: "2026-09-20 09:00:00", posted_date: "2026-09-20"}),
  notice(3, {title: "Past due solicitation", response_deadline: "2026-09-20T14:00:00-04:00", response_deadline_utc: "2026-09-20T18:00:00Z"}),
  notice(4, {title: "Bridge repair", department: "VETERANS AFFAIRS, DEPARTMENT OF", sub_tier: "VETERANS AFFAIRS, DEPARTMENT OF", office: "NETWORK CONTRACT OFFICE 5", naics_code: "237310", psc_code: "Y1LB", notice_type: "Sources Sought", description: "Repair of bridges.", set_aside_code: "SDVOSBC", set_aside: "Service-Disabled Veteran-Owned Small Business (SDVOSB) Set-Aside (FAR 19.14)", pop_state: "VA", posted_at: "2026-09-25 08:00:00", posted_date: "2026-09-25"}),
  notice(5, {title: "Award of network upgrade", solicitation_number: "SOL-1", notice_type: "Award Notice", response_deadline: null, response_deadline_utc: null, award_number: "W91-26-C-0001", award_amount: 1250000, awardee: "Acme Corp", posted_at: "2026-09-26 08:00:00", posted_date: "2026-09-26"}),
  notice(6, {title: "Archive date passed", archive_date: "2026-09-26"}),
  notice(7, {title: "Date-only deadline", response_deadline: "2026-09-27", response_deadline_utc: "2026-09-28T03:59:59Z", posted_date: "2026-08-15", posted_at: "2026-08-15 07:00:00"}),
  notice(8, {title: "Zero trust network upgrade", description: "Earlier version: zero trust.", solicitation_number: "sol-1", is_latest: 0, response_deadline: "2026-10-05T14:00:00-04:00", response_deadline_utc: "2026-10-05T18:00:00Z", posted_at: "2026-08-20 10:00:00", posted_date: "2026-08-20"}),
];

function database(loaded = true, rows: Record<string, unknown>[] = NOTICES) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(schema);
  for (const row of rows) {
    const columns = Object.keys(row);
    sqlite.prepare(`INSERT INTO opportunities (${columns.join(", ")}) VALUES (${columns.map(() => "?").join(", ")})`).run(...(Object.values(row) as any[]));
  }
  if (loaded) {
    const status = {file_date: "2026-09-26", loaded_at: "2026-09-26T10:20:00Z", notices: 7, added: 7, updated: 0, removed: 0, skipped_past_archive_date: 2, source_url: "https://sam.gov/x", by_notice_type: {Solicitation: 4}};
    for (const [key, value] of Object.entries(status)) sqlite.prepare("INSERT INTO load_status (key, value) VALUES (?, ?)").run(key, JSON.stringify(value));
  }
  return d1(sqlite);
}

const db = database();
const ids = (result: {results: {notice_id: string}[]}) => result.results.map(r => Number.parseInt(r.notice_id, 16));
const search = async (args: Record<string, unknown>) => searchOpportunities(db, args, NOW);

test("tool list is the four hosted tools, all read-only", () => {
  assert.deepEqual(TOOLS.map(t => t.name), ["search_opportunities", "get_opportunity", "summarize_opportunities", "get_data_status"]);
  for (const tool of TOOLS) assert.equal(tool.annotations.readOnlyHint, true);
});

test("tool metadata matches the reviewed contract", () => {
  const contract = JSON.parse(readFileSync(new URL("../tools-contract.json", import.meta.url), "utf8"));
  assert.deepEqual(JSON.parse(JSON.stringify(TOOLS)), contract, "Run npm run contract, review the diff, and commit it.");
});

test("default search hides past deadlines and archived notices, soonest deadline first", async () => {
  const result = await search({});
  assert.deepEqual(ids(result), [7, 2, 4, 1, 5]);
  assert.equal(result.total_matches, 5);
  assert.equal(result.data_as_of, "2026-09-26");
  assert.equal(result.results[0].link, `https://sam.gov/opp/${id(7)}/view`);
  assert.ok(result.notes[0].includes("include_past_deadlines"));
  assert.deepEqual(ids(await search({include_past_deadlines: true})), [3, 7, 2, 4, 1, 5]);
});

test("award notices and justifications are never dropped by the past-deadline filter", async () => {
  // GSA MAS award notices carry a placeholder deadline equal to the award day
  // (e.g. 2026-09-15T11:12:13-05:00); justifications have no real response deadline.
  const gsa = {department: "GENERAL SERVICES ADMINISTRATION", sub_tier: "FEDERAL ACQUISITION SERVICE", office: "GSA/FAS ADMIN SVCS ACQUISITION BR(2", solicitation_number: "47QSMD20R0001"};
  const rows = [
    ...NOTICES,
    notice(20, {...gsa, notice_type: "Award Notice", response_deadline: "2026-09-15T11:12:13-05:00", response_deadline_utc: "2026-09-15T16:12:13Z", award_number: "47QTCA26D0001", awardee: "Vendor A", award_amount: 475000, posted_date: "2026-09-15", posted_at: "2026-09-15 12:00:00"}),
    notice(21, {notice_type: "Justification", response_deadline: "2026-09-10T12:00:00-04:00", response_deadline_utc: "2026-09-10T16:00:00Z"}),
    notice(22, {notice_type: "Justification and Approval (J&A)", response_deadline: "2026-09-10T12:00:00-04:00", response_deadline_utc: "2026-09-10T16:00:00Z"}),
  ];
  const awards = database(true, rows);
  const found = await searchOpportunities(awards, {}, NOW);
  assert.deepEqual(ids(found).sort((a, b) => a - b), [1, 2, 4, 5, 7, 20, 21, 22], "past-deadline solicitation 3 stays out; award 20 and justifications 21, 22 stay in");
  const byAgency = await summarizeOpportunities(awards, {group_by: "agency", notice_types: ["Award Notice"]}, NOW);
  assert.deepEqual(byAgency.groups, [{value: "DEPT OF DEFENSE", count: 1}, {value: "GENERAL SERVICES ADMINISTRATION", count: 1}]);
  const description = (TOOLS[0].inputSchema.properties as any).include_past_deadlines.description;
  assert.match(description, /Award notices and justifications are always included/);
});

test("results say how many matches are award notices or justifications", async () => {
  const result = await search({naics_codes: ["5415"]});
  assert.equal(result.total_matches, 4);
  assert.ok(result.notes.some((n: string) => n.startsWith("1 of the 4 matches is an award notice or justification")), JSON.stringify(result.notes));
  const counts = await summarizeOpportunities(db, {group_by: "agency", naics_codes: ["5415"]}, NOW);
  assert.ok(counts.notes.some((n: string) => n.startsWith("1 of the 4 matches")));
  const typed = await search({naics_codes: ["5415"], notice_types: ["Solicitation"]});
  assert.ok(!typed.notes.some((n: string) => /take no responses/.test(n)), "no note once notice_types is set");
  const byType = await summarizeOpportunities(db, {group_by: "notice_type"}, NOW);
  assert.ok(!byType.notes.some((n: string) => /take no responses/.test(n)), "no note when grouped by notice type");
});

test("only the latest version of an amended notice is shown unless asked", async () => {
  assert.deepEqual(ids(await search({keywords: "\"zero trust\""})), [1]);
  const all = await search({keywords: "\"zero trust\"", include_earlier_versions: true});
  assert.deepEqual(ids(all), [8, 1]);
  assert.equal(all.results[0].superseded_by_newer_version, true);
  assert.equal(all.results[1].superseded_by_newer_version, undefined);
  const counts = await summarizeOpportunities(db, {group_by: "notice_type", include_earlier_versions: true}, NOW);
  assert.equal(counts.total_matches, 6);
});

test("keyword search matches words, stems, and quoted phrases in title or description", async () => {
  assert.deepEqual(ids(await search({keywords: "\"zero trust\""})), [1]);
  assert.deepEqual(ids(await search({keywords: "zero trust"})).sort(), [1, 2]);
  assert.deepEqual(ids(await search({keywords: "bridge"})), [4]);
  assert.deepEqual(ids(await search({keywords: "zero trust", sort: "relevance"})), [1, 2]);
  await assert.rejects(search({keywords: "NOT OR"}), /no searchable words/, "operators alone are ignored");
});

test("filters combine: type with slash, NAICS prefix, set-aside, agency, state, solicitation", async () => {
  assert.deepEqual(ids(await search({notice_types: ["combined synopsis/solicitation"]})), [2]);
  assert.deepEqual(ids(await search({naics_codes: ["5415"], notice_types: ["Solicitation", "Combined Synopsis/Solicitation"]})), [7, 2, 1]);
  assert.deepEqual(ids(await search({naics_codes: "237310,541519"})), [2, 4]);
  assert.deepEqual(ids(await search({psc_codes: ["y1"]})), [4]);
  assert.deepEqual(ids(await search({set_aside_codes: ["SBA", "SDVOSBC"]})), [4, 1]);
  assert.deepEqual(ids(await search({agency: "veterans"})), [4]);
  assert.deepEqual(ids(await search({agency: "army", place_of_performance_state: "md"})), [1]);
  assert.deepEqual(ids(await search({office_state: "md", notice_types: ["Sources Sought"]})), [4]);
  assert.deepEqual(ids(await search({solicitation_number: "sol-1"})), [1, 5]);
});

test("date ranges and sorting", async () => {
  assert.deepEqual(ids(await search({posted_from: "2026-09-20", posted_to: "2026-09-25"})), [2, 4]);
  assert.deepEqual(ids(await search({deadline_from: "2026-09-27", deadline_to: "2026-10-01"})), [7, 2]);
  assert.deepEqual(ids(await search({deadline_to: "2026-09-30", include_past_deadlines: true})), [3, 7]);
  assert.deepEqual(ids(await search({sort: "newest"})), [5, 4, 2, 1, 7]);
});

test("offset paging reports the next offset", async () => {
  const first = await search({limit: 2});
  assert.deepEqual([ids(first), first.next_offset], [[7, 2], 2]);
  const last = await search({limit: 2, offset: 4});
  assert.deepEqual([ids(last), last.next_offset], [[5], null]);
});

test("bad arguments raise clear tool errors", async () => {
  const cases: [Record<string, unknown>, RegExp][] = [
    [{posted_from: "2026-02-30"}, /real date/],
    [{deadline_to: "09/30/2026"}, /real date/],
    [{bogus: 1}, /Unknown argument: bogus/],
    [{sort: "relevance"}, /needs keywords/],
    [{sort: "oldest"}, /sort must be/],
    [{keywords: "!!!"}, /no searchable words/],
    [{naics_codes: ["54A"]}, /NAICS/],
    [{notice_types: ["RFP"]}, /notice type/],
    [{set_aside_codes: ["SMALL"]}, /set-aside/],
    [{limit: 500}, /limit must be/],
    [{include_past_deadlines: "yes"}, /true or false/],
    [{place_of_performance_state: "Maryland"}, /longer than 2|two-letter/],
  ];
  for (const [args, message] of cases) await assert.rejects(search(args), (e: Error) => e instanceof ToolError && message.test(e.message), JSON.stringify(args));
});

test("place-of-performance searches point to notices with an office in that state", async () => {
  const result = await search({place_of_performance_state: "MD"});
  assert.deepEqual(ids(result), [1]);
  assert.match(result.notes.at(-1), /^3 more matching notices leave the place of performance blank but have a contracting office in MD/);
  const counts = await summarizeOpportunities(db, {group_by: "office_state", place_of_performance_state: "MD"}, NOW);
  assert.deepEqual(counts.groups, [{value: "MD", count: 1}]);
  assert.match(counts.notes.at(-1), /^3 more/);
  assert.equal((await summarizeOpportunities(db, {group_by: "notice_type", place_of_performance_state: "VA"}, NOW)).notes.length, 1, "no hint when nothing more matches");
  assert.equal((await search({place_of_performance_state: "MD", office_state: "MD"})).notes.length, 1);
});

test("zero matches explain what to try", async () => {
  const result = await search({keywords: "submarine"});
  assert.equal(result.total_matches, 0);
  assert.ok(result.notes.some((n: string) => n.startsWith("No active notices matched")));
});

test("ftsQuery quotes every term so user text cannot inject FTS syntax", () => {
  assert.equal(ftsQuery("zero trust \"cloud migration\""), "\"zero\" \"trust\" \"cloud migration\"");
  assert.equal(ftsQuery("title:foo* OR (bar)"), "\"title foo\" \"bar\"");
  assert.equal(ftsQuery("AND"), undefined);
});

test("get_opportunity returns full details, related notices, and handles misses", async () => {
  const full = await getOpportunity(db, {notice_id: id(1).toUpperCase()}) as any;
  assert.equal(full.found, true);
  assert.equal(full.description, "Implement zero trust architecture across bases.");
  assert.deepEqual(full.set_aside, {code: "SBA", name: "Total Small Business Set-Aside (FAR 19.5)"});
  assert.equal(full.latest_version, true);
  assert.deepEqual(full.related_notices.map((r: any) => [Number.parseInt(r.notice_id, 16), r.latest_version]), [[5, true], [8, false]]);
  const old = await getOpportunity(db, {notice_id: id(8)}) as any;
  assert.equal(old.latest_version, false);
  assert.match(old.notes[0], /newer version/);
  const bySol = await getOpportunity(db, {solicitation_number: "SOL-1"}) as any;
  assert.equal(bySol.notice_id, id(5), "most recently posted latest version");
  assert.deepEqual(bySol.award, {number: "W91-26-C-0001", date: null, amount: 1250000, awardee: "Acme Corp"});
  const miss = await getOpportunity(db, {notice_id: "f".repeat(32)}) as any;
  assert.equal(miss.found, false);
  assert.equal(miss.link, `https://sam.gov/opp/${"f".repeat(32)}/view`);
  await assert.rejects(getOpportunity(db, {notice_id: "abc"}), /32-character/);
  await assert.rejects(getOpportunity(db, {}), /Pass notice_id or solicitation_number/);
  await assert.rejects(getOpportunity(db, {id: "x"}), /Unknown argument/);
});

test("get_opportunity says when the deadline has no time zone", async () => {
  // HC101326QA336: the file says 2026-10-12T16:00:00; sam.gov's API says America/Chicago.
  const disa = database(true, [notice(30, {office_state: "IL", response_deadline: "2026-10-12T16:00:00", response_deadline_utc: "2026-10-12T21:00:00Z"})]);
  const result = await getOpportunity(disa, {notice_id: id(30)}) as any;
  assert.ok(result.notes.some((n: string) => n.startsWith("SAM.gov's file gives this response deadline without a time zone")), JSON.stringify(result.notes));
  const withZone = await getOpportunity(db, {notice_id: id(1)}) as any;
  assert.ok(!withZone.notes.some((n: string) => /without a time zone/.test(n)));
});

test("summarize_opportunities groups with the search filters", async () => {
  const bySetAside = await summarizeOpportunities(db, {group_by: "set_aside", naics_codes: ["5415"]}, NOW);
  assert.equal(bySetAside.total_matches, 4);
  assert.deepEqual(bySetAside.groups, [{value: "(blank)", count: 3}, {value: "SBA", count: 1}]);
  const byMonth = await summarizeOpportunities(db, {group_by: "posted_month", top: 1, include_past_deadlines: true}, NOW);
  assert.deepEqual([byMonth.groups, byMonth.other_count, byMonth.distinct_values], [[{value: "2026-09", count: 5}], 1, 2]);
  await assert.rejects(summarizeOpportunities(db, {group_by: "vendor"}, NOW), /group_by must be one of/);
});

test("get_data_status reports freshness", async () => {
  const current = await getDataStatus(db, {}, NOW) as any;
  assert.deepEqual([current.status, current.file_age_days, current.active_notices, current.api_key_required], ["current", 1, 7, false]);
  assert.equal((await getDataStatus(db, {}, new Date("2026-10-01T12:00:00Z")) as any).status, "stale");
  assert.equal((await getDataStatus(database(false), {}, NOW) as any).status, "not_loaded");
  await assert.rejects(getDataStatus(db, {x: 1}, NOW), /Unknown argument/);
});

// ---------- MCP transport ----------

const env = (allow = true) => ({DB: db, REQUEST_LIMITER: {limit: async () => ({success: allow})}, RELEASE_SHA: "abc123"});
const post = (body: unknown, headers: Record<string, string> = {}) =>
  new Request("https://sam.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json", ...headers}, body: typeof body === "string" ? body : JSON.stringify(body)});

test("JSON-RPC methods, notifications, and tool errors", async () => {
  const init = await handleMessage({jsonrpc: "2.0", id: 1, method: "initialize", params: {protocolVersion: "2025-06-18"}}, env()) as any;
  assert.equal(init.result.protocolVersion, "2025-06-18");
  assert.equal(init.result.serverInfo.name, "sam-gov");
  assert.equal(await handleMessage({jsonrpc: "2.0", method: "notifications/initialized"}, env()), null);
  const list = await handleMessage({jsonrpc: "2.0", id: 2, method: "tools/list"}, env()) as any;
  assert.equal(list.result.tools.length, 4);
  const bad = await handleMessage({jsonrpc: "2.0", id: 3, method: "tools/call", params: {name: "search_opportunities", arguments: {sort: "relevance"}}}, env()) as any;
  assert.equal(bad.result.isError, true);
  assert.match(bad.result.structuredContent.error, /needs keywords/);
  const unknown = await handleMessage({jsonrpc: "2.0", id: 4, method: "tools/call", params: {name: "search_entities"}}, env()) as any;
  assert.equal(unknown.result.isError, true);
  const missing = await handleMessage({jsonrpc: "2.0", id: 5, method: "resources/list"}, env()) as any;
  assert.equal(missing.error.code, -32601);
  const broken = await handleMessage({jsonrpc: "2.0", id: 6, method: "tools/call", params: {name: "get_data_status", arguments: {}}}, {...env(), DB: {prepare: () => { throw new Error("D1 down"); }}} as any) as any;
  assert.match(broken.result.structuredContent.error, /temporarily unavailable/);
});

test("HTTP edge: health, docs, origin, rate limit, methods, body limits", async () => {
  const health = await worker.fetch(new Request("https://sam.1102tools.com/health"), env() as any);
  assert.deepEqual(await health.json(), {status: "ok", tools: 4, release_sha: "abc123"});
  assert.equal((await worker.fetch(new Request("https://sam.1102tools.com/privacy"), env() as any)).status, 200);
  assert.equal((await worker.fetch(new Request("https://sam.1102tools.com/nope"), env() as any)).status, 404);
  const call = await worker.fetch(post({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "search_opportunities", arguments: {keywords: "bridge"}}}), env() as any);
  assert.equal((await call.json() as any).result.structuredContent.total_matches, 1);
  assert.equal((await worker.fetch(post({jsonrpc: "2.0", method: "notifications/initialized"}), env() as any)).status, 202);
  assert.equal((await worker.fetch(post({}, {Origin: "https://evil.example"}), env() as any)).status, 403);
  assert.equal((await worker.fetch(post({}), env(false) as any)).status, 429);
  assert.equal((await worker.fetch(new Request("https://sam.1102tools.com/mcp"), env() as any)).status, 405);
  assert.equal((await worker.fetch(post("{"), env() as any)).status, 400);
  assert.equal((await worker.fetch(post([{jsonrpc: "2.0", id: 1, method: "ping"}]), env() as any)).status, 400);
  assert.equal((await worker.fetch(post("x".repeat(70000)), env() as any)).status, 413);
});
