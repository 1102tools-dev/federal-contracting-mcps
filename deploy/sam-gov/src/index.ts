import {publicDocs} from "./public-docs.ts";
import {withToolCallLog, withinLimit} from "../../shared/edge.ts";
import {HANDLERS, TOOLS, ToolError, type Database} from "./tools.ts";

// Stateless MCP over streamable HTTP with JSON responses, served entirely by
// this Worker from D1. No container, no session state, no SAM.gov API key.

const SERVER_VERSION = "1.1.13";
const PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const MAX_BODY_BYTES = 65536;

// D1 read replication: a session lets reads go to the nearest replica.
// Writes come only from the GitHub load jobs, so replica lag of a few seconds
// after a load is fine. Test doubles without withSession use the database as is.
type ReplicatedDatabase = Database & {withSession?(constraint: "first-unconstrained"): Database};

const readSession = (db: ReplicatedDatabase): Database => db.withSession?.("first-unconstrained") ?? db;

// Answer cache: Cloudflare's per-location cache. Identical questions skip D1,
// which absorbs bursts such as scheduled agents asking for today's notices.
// Entries are filed under a SHA-256 fingerprint of the tool, its arguments, the
// release and the load stamp of the data the tool reads; only successful
// answers are stored. A new load changes the stamp, so older answers are never
// served again. Data status keeps a short fixed lifetime.
const CACHE_SECONDS: Record<string, number> = {
  get_data_status: 60,
  search_opportunities: 86400,
  get_opportunity: 86400,
  summarize_opportunities: 86400,
  search_entities: 86400,
  search_exclusions: 86400,
};
const LOAD_KEYED: Record<string, "opportunities" | "public"> = {
  search_opportunities: "opportunities",
  get_opportunity: "opportunities",
  summarize_opportunities: "opportunities",
  search_entities: "public",
  search_exclusions: "public",
};
type AnswerCache = {match(key: Request): Promise<Response | undefined>; put(key: Request, response: Response): Promise<void>};

// Both loaders write these stamps after their data, so a stamp never names a
// load that is still being written. Read in the same session as the answer,
// which is then at least as new as the stamp. Null (not loaded, mid-refresh or
// unreadable) means no caching for this call.
export async function loadStamp(kind: "opportunities" | "public", db: Database): Promise<string | null> {
  if (kind === "opportunities") {
    const {results} = await db.prepare("SELECT value FROM load_status WHERE key = 'loaded_at'").bind().all<{value: string}>();
    return results.length ? results[0].value : null;
  }
  const {results} = await db.prepare(`SELECT s.kind, s.sha256, s.loaded_at,
    EXISTS(SELECT 1 FROM public_refresh_runs r WHERE r.kind = s.kind AND r.state = 'applying') AS refreshing
    FROM extract_status s ORDER BY s.kind`).bind().all<{kind: string; sha256: string; loaded_at: string; refreshing: number}>();
  if (!results.length || results.some(r => r.refreshing)) return null;
  return JSON.stringify(results.map(r => [r.kind, r.sha256, r.loaded_at]));
}

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k => [k, stable((value as Record<string, unknown>)[k])]));
  return value;
}

export async function answerKey(name: string, args: unknown, release: string, stamp = ""): Promise<Request> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([release, stamp, name, stable(args)])));
  const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
  return new Request(`https://answer-cache.sam.1102tools.com/${hex}`);
}

export interface Env {
  DB: ReplicatedDatabase;
  ENTITY_DB: ReplicatedDatabase;
  // Trigram name index kept out of ENTITY_DB: D1 cannot export databases with
  // virtual tables, and the public loader exports ENTITY_DB to rehearse costs.
  NAME_INDEX_DB?: ReplicatedDatabase;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  AI_LIMITER?: {limit(options: {key: string}): Promise<{success: boolean}>};
  RELEASE_SHA?: string;
  ANSWER_CACHE?: AnswerCache; // tests only; production uses caches.default
}

type Message = {jsonrpc?: unknown; id?: unknown; method?: unknown; params?: any};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
const rpcError = (id: unknown, code: number, message: string) => ({jsonrpc: "2.0", id: id ?? null, error: {code, message}});

async function readBounded(request: Request): Promise<string | null> {
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(out);
}

export async function handleMessage(message: Message, env: Env, trace: {cache?: "hit" | "miss"} = {}): Promise<object | null> {
  const {id, method, params} = message;
  if (message.jsonrpc !== "2.0" || typeof method !== "string") return rpcError(id, -32600, "Invalid JSON-RPC request.");
  // Notifications (no id) get no response body.
  if (id === undefined) return null;
  switch (method) {
    case "initialize": {
      const requested = params?.protocolVersion;
      return {
        jsonrpc: "2.0", id,
        result: {
          protocolVersion: PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0],
          capabilities: {tools: {listChanged: false}},
          serverInfo: {name: "sam-gov", version: SERVER_VERSION},
        },
      };
    }
    case "ping":
      return {jsonrpc: "2.0", id, result: {}};
    case "tools/list":
      return {jsonrpc: "2.0", id, result: {tools: TOOLS}};
    case "tools/call": {
      const name = params?.name;
      const args = params?.arguments ?? {};
      const handler = typeof name === "string" && Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
      if (!handler) return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: `Unknown tool: ${name}`}], isError: true}};
      if (typeof args !== "object" || Array.isArray(args)) {
        return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: "arguments must be an object."}], isError: true}};
      }
      const db = readSession(env.DB), entityDb = env.ENTITY_DB && readSession(env.ENTITY_DB);
      const toolDb = name === "search_entities" || name === "search_exclusions" ? entityDb : db;
      const ttl = CACHE_SECONDS[name];
      const cache = ttl ? env.ANSWER_CACHE ?? (globalThis as {caches?: {default?: AnswerCache}}).caches?.default : undefined;
      const keyed = LOAD_KEYED[name];
      const stamp = cache && keyed ? await loadStamp(keyed, toolDb).catch(() => null) : "";
      const key = cache && stamp !== null ? await answerKey(name, args, env.RELEASE_SHA ?? SERVER_VERSION, stamp) : undefined;
      if (cache && key) {
        const hit = await cache.match(key).catch(() => undefined);
        const data = hit && await hit.json().catch(() => undefined);
        if (data !== undefined) {
          trace.cache = "hit";
          return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify(data)}], structuredContent: data}};
        }
        trace.cache = "miss";
      }
      try {
        const nameIndexDb = env.NAME_INDEX_DB && readSession(env.NAME_INDEX_DB);
        const data = await handler(toolDb, args, entityDb, nameIndexDb);
        if (cache && key) {
          const body = JSON.stringify(data);
          await cache.put(key, new Response(body, {headers: {"Content-Type": "application/json", "Cache-Control": `public, max-age=${ttl}`}})).catch(() => {});
        }
        return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify(data)}], structuredContent: data}};
      } catch (error) {
        if (error instanceof ToolError) {
          return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify({error: error.message})}], structuredContent: {error: error.message}, isError: true}};
        }
        // Error type only: messages can echo request text.
        console.log(JSON.stringify({event: "tool_failed", tool: name, error: error instanceof Error ? error.name : "unknown"}));
        const message = "SAM.gov data is temporarily unavailable. Try again shortly.";
        return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify({error: message})}], structuredContent: {error: message}, isError: true}};
      }
    }
    default:
      return rpcError(id, -32601, `Method not found: ${method}`);
  }
}

async function serve(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
  if (url.pathname !== "/mcp" && url.pathname !== "/health") {
    return new Response("SAM.gov MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
  }
  const origin = request.headers.get("Origin");
  if (origin && origin !== url.origin) return new Response("Origin not allowed", {status: 403});
  if (!await withinLimit(request, env)) {
    return new Response("Request limit reached; retry later.", {status: 429, headers: {"Retry-After": "60"}});
  }
  if (url.pathname === "/health") {
    if (request.method !== "GET") return new Response(null, {status: 405});
    return json({status: "ok", tools: TOOLS.length, release_sha: env.RELEASE_SHA ?? null});
  }
  if (request.method !== "POST") return new Response("Use POST for stateless MCP requests.", {status: 405, headers: {Allow: "POST"}});
  if (Number(request.headers.get("Content-Length") ?? "0") > MAX_BODY_BYTES) return new Response("Request body too large.", {status: 413});
  const body = await readBounded(request);
  if (body === null) return new Response("Request body too large.", {status: 413});
  let message: unknown;
  try {
    message = JSON.parse(body);
  } catch {
    return json(rpcError(null, -32700, "Parse error."), 400);
  }
  if (Array.isArray(message) || typeof message !== "object" || message === null) {
    return json(rpcError(null, -32600, "Send one JSON-RPC message per request."), 400);
  }
  const trace: {cache?: "hit" | "miss"} = {};
  const response = await handleMessage(message as Message, env, trace);
  if (!response) return new Response(null, {status: 202});
  const out = json(response);
  if (trace.cache) out.headers.set("X-1102tools-Cache", trace.cache);
  return out;
}

export default {fetch: withToolCallLog("sam-gov", serve)} satisfies ExportedHandler<Env>;
