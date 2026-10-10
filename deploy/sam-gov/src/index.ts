import {publicDocs} from "./public-docs.ts";
import {withToolCallLog, withinLimit} from "../../shared/edge.ts";
import {HANDLERS, TOOLS, ToolError, type Database} from "./tools.ts";

// Stateless MCP over streamable HTTP with JSON responses, served entirely by
// this Worker from D1. No container, no session state, no SAM.gov API key.

const SERVER_VERSION = "1.0.3";
const PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const MAX_BODY_BYTES = 65536;

export interface Env {
  DB: Database;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  AI_LIMITER?: {limit(options: {key: string}): Promise<{success: boolean}>};
  RELEASE_SHA?: string;
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

export async function handleMessage(message: Message, env: Env): Promise<object | null> {
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
      try {
        const data = await handler(env.DB, args);
        return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify(data)}], structuredContent: data}};
      } catch (error) {
        if (error instanceof ToolError) {
          return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: JSON.stringify({error: error.message})}], structuredContent: {error: error.message}, isError: true}};
        }
        console.log(JSON.stringify({event: "tool_failed", tool: name, reason: error instanceof Error ? error.message.slice(0, 200) : "unknown"}));
        const message = "SAM.gov opportunities data is temporarily unavailable. Try again shortly.";
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
  const response = await handleMessage(message as Message, env);
  return response ? json(response) : new Response(null, {status: 202});
}

export default {fetch: withToolCallLog("sam-gov", serve)} satisfies ExportedHandler<Env>;
