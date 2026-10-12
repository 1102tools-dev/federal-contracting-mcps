// The answer cache returns the stored answer for an identical question, never
// another question's answer, and stores only successful answers.
import assert from "node:assert/strict";
import {test} from "node:test";
import worker, {answerKey, handleMessage} from "../src/index.ts";

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
  const db = {queries: 0, prepare: (sql: string) => ({bind: () => ({all: async () => {
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
  assert.ok([...cache.store.values()].some(e => /max-age=300$/.test(e.control)));
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
