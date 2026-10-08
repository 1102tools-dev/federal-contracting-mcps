import {MAX_BODY_BYTES, readBounded, tooLarge} from "../../shared/edge.ts";
import {publicDocs} from "./public-docs.ts";
import {Snapshot, type Database} from "./data.ts";
import {dumps, loads} from "./py.ts";
import {TOOLS, callTool, type Context} from "./tools.ts";
import {DeadlineExceeded, Upstream, type CacheLike} from "./upstream.ts";

// Stateless MCP over streamable HTTP with JSON responses, served by this
// Worker: bundled GSA files from D1, live GSA Per Diem API calls with the
// operator's key. Answers match the gsa-perdiem-mcp Python server.

/** The gsa-perdiem-mcp package version this Worker answers as. */
export const SERVER_VERSION = "1.2.0";
const PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
// The container's admission deadline; work still running then gets its 504.
export const REQUEST_DEADLINE_MS = 55_000;

export interface WorkerEnv {
  DB: Database;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  PERDIEM_API_KEY?: string;
  RELEASE_SHA?: string;
}

/** Per-request dependencies; tests replace the clock, cache, and upstream fetch. */
export interface Runtime {
  now?: () => Date;
  cache?: CacheLike | null;
  fetch?: typeof fetch;
  upstream?: Partial<ConstructorParameters<typeof Upstream>[0]>;
  deadlineMs?: number;
}

type Message = {jsonrpc?: unknown; id?: unknown; method?: unknown; params?: any};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});
const rpcError = (id: unknown, code: number, message: string, data?: unknown) =>
  ({jsonrpc: "2.0", id: id ?? null, error: data === undefined ? {code, message} : {code, message, data}});

function context(env: WorkerEnv, runtime: Runtime): Context {
  const cache = runtime.cache !== undefined ? runtime.cache : (globalThis as any).caches?.default ?? null;
  return {
    snapshot: new Snapshot(env.DB),
    upstream: new Upstream({db: env.DB, key: env.PERDIEM_API_KEY, cache, fetch: runtime.fetch, ...runtime.upstream}),
    today: runtime.now ? runtime.now() : new Date(),
  };
}

function withDeadline<T>(work: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new DeadlineExceeded()), ms);
  });
  return Promise.race([work, deadline]).finally(() => clearTimeout(timer));
}

/** One JSON-RPC message; null for notifications. Throws DeadlineExceeded. */
export async function handleMessage(message: Message, env: WorkerEnv, runtime: Runtime = {}): Promise<object | null> {
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
          capabilities: {
            experimental: {},
            prompts: {listChanged: false},
            resources: {listChanged: false, subscribe: false},
            tools: {listChanged: false},
          },
          protocolVersion: PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0],
          serverInfo: {name: "gsa-perdiem", version: SERVER_VERSION},
        },
      };
    }
    case "ping":
      return {jsonrpc: "2.0", id, result: {}};
    case "tools/list":
      return {jsonrpc: "2.0", id, result: {tools: TOOLS}};
    case "prompts/list":
      return {jsonrpc: "2.0", id, result: {prompts: []}};
    case "resources/list":
      return {jsonrpc: "2.0", id, result: {resources: []}};
    case "resources/templates/list":
      return {jsonrpc: "2.0", id, result: {resourceTemplates: []}};
    case "tools/call": {
      const name = params?.name;
      const args = params?.arguments ?? {};
      if (typeof name !== "string" || typeof args !== "object" || Array.isArray(args)) {
        return rpcError(id, -32602, "Invalid request parameters");
      }
      const result = await withDeadline(callTool(context(env, runtime), name, args), runtime.deadlineMs ?? REQUEST_DEADLINE_MS);
      return {jsonrpc: "2.0", id, result};
    }
    default:
      return rpcError(id, -32601, "Method not found", method);
  }
}

/** Tool arguments with Python's int/float distinction kept (1.0 is a float). */
function withExactArguments(body: string, message: Message): Message {
  if (message.method !== "tools/call" || typeof message.params?.arguments !== "object" || message.params.arguments === null) return message;
  const exact = loads(body, {bigints: true});
  return {...message, params: {...message.params, arguments: exact.params.arguments}};
}

export async function serve(request: Request, env: WorkerEnv, runtime: Runtime = {}): Promise<Response> {
  const url = new URL(request.url);
  if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
  if (url.pathname !== "/mcp" && url.pathname !== "/health") {
    return new Response("GSA Per Diem MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
  }
  const origin = request.headers.get("Origin");
  if (origin && origin !== url.origin) return new Response("Origin not allowed", {status: 403});
  if (!await env.REQUEST_LIMITER.limit({key: request.headers.get("CF-Connecting-IP") || "unknown"}).then(r => r.success)) {
    return new Response("Request limit reached; retry later.", {status: 429, headers: {"Retry-After": "60"}});
  }
  if (url.pathname === "/health") {
    if (request.method !== "GET") return new Response(null, {status: 405});
    return json({status: "ok", tools: TOOLS.length, release_sha: env.RELEASE_SHA ?? null});
  }
  if (request.method !== "POST") return new Response("Use POST for stateless MCP requests.", {status: 405, headers: {Allow: "POST"}});
  if (Number(request.headers.get("Content-Length") ?? "0") > MAX_BODY_BYTES) return tooLarge();
  const raw = await readBounded(request);
  if (raw === null) return tooLarge();
  const body = new TextDecoder().decode(raw);
  let message: unknown;
  try {
    message = JSON.parse(body);
  } catch {
    return json(rpcError(null, -32700, "Parse error."), 400);
  }
  if (Array.isArray(message) || typeof message !== "object" || message === null) {
    return json(rpcError(null, -32600, "Send one JSON-RPC message per request."), 400);
  }
  let response: object | null;
  try {
    response = await handleMessage(withExactArguments(body, message as Message), env, runtime);
  } catch (error) {
    if (!(error instanceof DeadlineExceeded)) throw error;
    return json({error: error.message}, 504);
  }
  // dumps keeps Python's float text and dict key order in structuredContent.
  return response ? new Response(dumps(response, null), {headers: {"Content-Type": "application/json"}}) : new Response(null, {status: 202});
}
