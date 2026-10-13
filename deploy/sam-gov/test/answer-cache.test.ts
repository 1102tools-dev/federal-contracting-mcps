// The answer cache returns the stored answer for an identical question, never
// another question's answer, stores only successful answers, and never serves
// an answer from before the latest data load.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import worker, {answerKey, handleMessage, loadStamp} from "../src/index.ts";

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

function countingDb() {
  const db = {queries: 0, loadedAt: "2026-10-12T04:16:07Z", prepare: (sql: string) => ({bind: () => ({all: async () => {
    if (/key = 'loaded_at'/.test(sql)) return {results: [{value: JSON.stringify(db.loadedAt)}]};
    db.queries++;
    if (/load_status/.test(sql) && /SELECT key, value/.test(sql)) return {results: [{key: "file_date", value: JSON.stringify("2026-10-12")}, {key: "loaded_at", value: JSON.stringify("2026-10-12T04:16:07Z")}]};
    return {results: [{file_date_json: JSON.stringify("2026-10-12"), related_json: "[]", related_total: 0, notice_id: null}]};
  }})})};
  return db;
}

const call = (name: string, args: Record<string, unknown>, id = 1) => ({jsonrpc: "2.0", id, method: "tools/call", params: {name, arguments: args}});

test("identical questions hit the cache regardless of argument order; different ones miss", async () => {
  const cache = memoryCache(), db = countingDb();
  const env = {DB: db, ENTITY_DB: db, ANSWER_CACHE: cache, RELEASE_SHA: "r1"} as any;
  const first: any = await handleMessage(call("get_opportunity", {notice_id: "a".repeat(32)}), env);
  const used = db.queries;
  const trace: any = {};
  const second: any = await handleMessage(call("get_opportunity", {notice_id: "a".repeat(32)}, 2), env, trace);
  assert.equal(trace.cache, "hit");
  assert.equal(db.queries, used);
  assert.equal(second.id, 2);
  assert.deepEqual(second.result.structuredContent, first.result.structuredContent);
  const other: any = {};
  await handleMessage(call("get_opportunity", {notice_id: "b".repeat(32)}), env, other);
  assert.equal(other.cache, "miss");
});

test("the cache key ignores argument order but not values, tools or releases", async () => {
  const key = async (name: string, args: unknown, release = "r1") => (await answerKey(name, args, release)).url;
  const base = await key("search_opportunities", {keywords: "x", limit: 5, naics_codes: ["5415", "5416"]});
  assert.equal(await key("search_opportunities", {naics_codes: ["5415", "5416"], limit: 5, keywords: "x"}), base);
  for (const [name, args, release] of [
    ["search_opportunities", {keywords: "x", limit: 6, naics_codes: ["5415", "5416"]}, "r1"],
    ["search_opportunities", {keywords: "x", limit: 5, naics_codes: ["5416", "5415"]}, "r1"],
    ["summarize_opportunities", {keywords: "x", limit: 5, naics_codes: ["5415", "5416"]}, "r1"],
    ["search_opportunities", {keywords: "x", limit: 5, naics_codes: ["5415", "5416"]}, "r2"],
  ] as [string, unknown, string][]) assert.notEqual(await key(name, args, release), base);
  assert.match(base, /^https:\/\/answer-cache\.sam\.1102tools\.com\/[0-9a-f]{64}$/);
});

test("errors are not cached, a new release starts fresh, and cache lifetimes are bounded", async () => {
  const cache = memoryCache(), db = countingDb();
  const env = {DB: db, ENTITY_DB: db, ANSWER_CACHE: cache, RELEASE_SHA: "r1"} as any;
  const bad: any = await handleMessage(call("get_opportunity", {notice_id: "zz"}), env);
  assert.equal(bad.result.isError, true);
  assert.equal(cache.store.size, 0);
  await handleMessage(call("get_data_status", {}), env);
  assert.match([...cache.store.values()][0].control, /max-age=60$/);
  await handleMessage(call("get_opportunity", {notice_id: "c".repeat(32)}), env);
  assert.ok([...cache.store.values()].some(e => /max-age=86400$/.test(e.control)));
  const next: any = {};
  await handleMessage(call("get_data_status", {}), {...env, RELEASE_SHA: "r2"}, next);
  assert.equal(next.cache, "miss");
});

test("a broken cache never breaks a tool call, and the HTTP response says hit or miss", async () => {
  const db = countingDb();
  const broken = {match: async () => { throw new Error("cache down"); }, put: async () => { throw new Error("cache down"); }};
  const result: any = await handleMessage(call("get_data_status", {}), {DB: db, ENTITY_DB: db, ANSWER_CACHE: broken} as any);
  assert.equal(result.result.isError, undefined);
  const corrupt = {match: async () => new Response("not json"), put: async () => {}};
  const recovered: any = await handleMessage(call("get_data_status", {}), {DB: db, ENTITY_DB: db, ANSWER_CACHE: corrupt} as any);
  assert.equal(recovered.result.isError, undefined);
  const cache = memoryCache();
  const env = {DB: db, ENTITY_DB: db, ANSWER_CACHE: cache, REQUEST_LIMITER: {limit: async () => ({success: true})}} as any;
  const post = () => new Request("https://sam.1102tools.com/mcp", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(call("get_data_status", {}))});
  assert.equal((await worker.fetch(post(), env)).headers.get("X-1102tools-Cache"), "miss");
  assert.equal((await worker.fetch(post(), env)).headers.get("X-1102tools-Cache"), "hit");
});

test("a new opportunities load retires older answers at once", async () => {
  const cache = memoryCache(), db = countingDb();
  const env = {DB: db, ENTITY_DB: db, ANSWER_CACHE: cache, RELEASE_SHA: "r1"} as any;
  const ask = async () => { const trace: any = {}; await handleMessage(call("get_opportunity", {notice_id: "d".repeat(32)}), env, trace); return trace.cache; };
  assert.equal(await ask(), "miss");
  assert.equal(await ask(), "hit");
  db.loadedAt = "2026-10-13T04:16:07Z";
  assert.equal(await ask(), "miss");
  assert.equal(await ask(), "hit");
});

function publicDb() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  for (const kind of ["entities", "exclusions"]) sqlite.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)").run(kind, "file.zip", "2026-10-12", "https://sam.gov/public", "2026-10-12T10:00:00Z", 0, "sha-" + kind, 1, 1);
  const db = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => ({results: sqlite.prepare(sql).all(...values as any[]) as any[]})})})};
  return {db, sqlite};
}

test("entity and exclusion stamps change with either load and are withheld mid-refresh", async () => {
  const {db, sqlite} = publicDb();
  const first = await loadStamp("public", db as any);
  assert.ok(first);
  sqlite.exec("UPDATE extract_status SET database_bytes = 2");
  assert.equal(await loadStamp("public", db as any), first);
  sqlite.exec("UPDATE extract_status SET loaded_at = '2026-10-12T14:00:00Z', sha256 = 'sha-new' WHERE kind = 'exclusions'");
  const second = await loadStamp("public", db as any);
  assert.ok(second && second !== first);
  sqlite.exec("INSERT INTO public_refresh_runs VALUES ('exclusions','applying','target','parser','{}',0,100,10,'2026-10','now','now','owner','later')");
  assert.equal(await loadStamp("public", db as any), null);
  const empty = new DatabaseSync(":memory:");
  empty.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  assert.equal(await loadStamp("public", {prepare: (sql: string) => ({bind: () => ({all: async () => ({results: empty.prepare(sql).all() as any[]})})})} as any), null);
});

test("no stamp means no caching, and the tool still answers", async () => {
  const cache = memoryCache(), db = countingDb();
  const broken = {...db, prepare: (sql: string) => /key = 'loaded_at'/.test(sql) ? {bind: () => ({all: async () => { throw new Error("down"); }})} : db.prepare(sql)};
  const env = {DB: broken, ENTITY_DB: broken, ANSWER_CACHE: cache, RELEASE_SHA: "r1"} as any;
  const trace: any = {};
  const result: any = await handleMessage(call("get_opportunity", {notice_id: "e".repeat(32)}), env, trace);
  assert.equal(result.result.isError, undefined);
  assert.equal(trace.cache, undefined);
  assert.equal(cache.store.size, 0);
});
