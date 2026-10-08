import SERVER from "../../../servers/bls-oews-mcp/server.json" with {type: "json"};
import {publicDocs} from "./public-docs.ts";
import {dumps, type Py} from "./pyjson.ts";
import {HANDLERS, TOOLS, ToolError, type Database} from "./tools.ts";

// Stateless MCP over streamable HTTP with JSON responses, served entirely by
// this Worker from D1. No container, no session state. Answers match the
// Python server (bls-oews-mcp) the container ran: the same initialize
// result, tool list, tool results, and error text.

// The package version (server.json is kept equal to pyproject.toml by
// scripts/validate_versions.py), reported as serverInfo.version.
const SERVER_VERSION: string = SERVER.version;
const PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const MAX_BODY_BYTES = 65536;
const CAPABILITIES = {
  experimental: {},
  prompts: {listChanged: false},
  resources: {listChanged: false, subscribe: false},
  tools: {listChanged: false},
};
// scripts/verify_hosted_release.py checks /health for the container's
// admission limits; a Worker has no queue, so the values are fixed.
const ADMISSION = {processing: 16, waiting: 32, total: 48, deadline_seconds: 55};

export interface Env {
  DB: Database;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  RELEASE_SHA?: string;
}

type Message = {jsonrpc?: unknown; id?: unknown; method?: unknown; params?: any};

const json = (body: Py, status = 200) =>
  new Response(dumps(body), {status, headers: {"Content-Type": "application/json"}});
const rpcError = (id: unknown, code: number, message: string, data?: Py) =>
  ({jsonrpc: "2.0", id: (id ?? null) as Py, error: {code, message, data}});
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const textResult = (text: string, isError: boolean) => ({content: [{type: "text", text}], isError});

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

/** tools/call result, shaped like the Python SDK's CallToolResult. */
export async function callTool(name: string, args: Record<string, unknown>, env: Env): Promise<Py> {
  const handler = Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
  if (!handler) return textResult(`Unknown tool: ${name}`, true);
  try {
    const data = await handler(env.DB, args);
    return {content: [{type: "text", text: dumps(data, 2)}], structuredContent: data, isError: false};
  } catch (error) {
    if (error instanceof ToolError) return textResult(`Error executing tool ${name}: ${error.message}`, true);
    console.log(JSON.stringify({event: "tool_failed", tool: name, reason: error instanceof Error ? error.message.slice(0, 200) : "unknown"}));
    return textResult(`Error executing tool ${name}: BLS OEWS data is temporarily unavailable. Try again shortly.`, true);
  }
}

export async function handleMessage(message: Message, env: Env): Promise<Py | null> {
  const {id, method, params} = message;
  if (message.jsonrpc !== "2.0" || typeof method !== "string") return rpcError(id, -32600, "Invalid JSON-RPC request.");
  // Notifications (no id) get no response body.
  if (id === undefined) return null;
  const result = (value: Py) => ({jsonrpc: "2.0", id: id as Py, result: value});
  const invalid = () => rpcError(id, -32602, "Invalid request parameters", "");
  switch (method) {
    case "initialize": {
      if (!isObject(params) || typeof params.protocolVersion !== "string" || !isObject(params.capabilities) || !isObject(params.clientInfo)) return invalid();
      const requested = params.protocolVersion;
      return result({
        capabilities: CAPABILITIES,
        protocolVersion: PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0],
        serverInfo: {name: "bls-oews", version: SERVER_VERSION},
      });
    }
    case "ping":
      return result({});
    case "tools/list":
      return result({tools: TOOLS as Py});
    // Advertised (empty) like the Python server's capabilities.
    case "prompts/list":
      return result({prompts: []});
    case "resources/list":
      return result({resources: []});
    case "resources/templates/list":
      return result({resourceTemplates: []});
    case "resources/read":
      return isObject(params) && typeof params.uri === "string" ? rpcError(id, -32602, `Unknown resource: ${params.uri}`, {uri: params.uri}) : invalid();
    case "prompts/get":
      return isObject(params) && typeof params.name === "string" ? rpcError(id, -32602, `Unknown prompt: ${params.name}`) : invalid();
    case "tools/call": {
      const args = params?.arguments ?? {};
      if (!isObject(params) || typeof params.name !== "string" || !isObject(args)) return invalid();
      return result(await callTool(params.name, args, env));
    }
    default:
      return rpcError(id, -32601, "Method not found", method);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
    if (url.pathname !== "/mcp" && url.pathname !== "/health") {
      return new Response("BLS OEWS MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
    }
    const origin = request.headers.get("Origin");
    if (origin && origin !== url.origin) return new Response("Origin not allowed", {status: 403});
    if (!await env.REQUEST_LIMITER.limit({key: request.headers.get("CF-Connecting-IP") || "unknown"}).then(r => r.success)) {
      return new Response("Request limit reached; retry later.", {status: 429, headers: {"Retry-After": "60"}});
    }
    if (url.pathname === "/health") {
      if (request.method !== "GET") return new Response(null, {status: 405});
      return json({status: "ok", tools: TOOLS.length, release_sha: env.RELEASE_SHA ?? null, admission: ADMISSION});
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
    if (!isObject(message)) return json(rpcError(null, -32600, "Send one JSON-RPC message per request."), 400);
    const response = await handleMessage(message as Message, env);
    return response ? json(response) : new Response(null, {status: 202});
  },
} satisfies ExportedHandler<Env>;
