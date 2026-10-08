import {MAX_BODY_BYTES, listenAtEdge, readBounded, tooLarge} from "../../shared/edge.ts";
import {handleModern} from "./modern.ts";
import {publicDocs} from "./public-docs.ts";
import {dumps, parseJson, type Py} from "./pyjson.ts";
import {SERVER_INFO, accepts, callTool, isObject, validId, type Env} from "./rpc.ts";
import {TOOLS} from "./tools.ts";

export {callTool, type Env};

// Stateless MCP over streamable HTTP with JSON responses, served entirely by
// this Worker from D1. No container, no session state. Answers match the
// Python server (bls-oews-mcp) the container ran, in both protocol eras:
// initialize-handshake versions here, 2026-07-28 in modern.ts.

const HANDSHAKE_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
const CAPABILITIES = {
  experimental: {},
  prompts: {listChanged: false},
  resources: {listChanged: false, subscribe: false},
  tools: {listChanged: false},
};
// scripts/verify_hosted_release.py checks /health for the container's
// admission limits; a Worker has no queue, so the values are fixed.
const ADMISSION = {processing: 16, waiting: 32, total: 48, deadline_seconds: 55};

type Message = {jsonrpc?: unknown; id?: unknown; method?: unknown; params?: any; result?: unknown; error?: unknown};

const json = (body: Py, status = 200) =>
  new Response(dumps(body), {status, headers: {"Content-Type": "application/json"}});
const rpcError = (id: unknown, code: number, message: string, data?: Py) =>
  ({jsonrpc: "2.0", id: (id ?? null) as Py, error: {code, message, data}});

/** How the SDK classifies one message: a request it answers, a notification
 * or client response it accepts silently, or an invalid message (HTTP 400). */
export function classify(message: Message): "request" | "accepted" | "invalid" {
  if (message.jsonrpc !== "2.0") return "invalid";
  if (typeof message.method === "string") {
    if (message.params !== undefined && message.params !== null && !isObject(message.params)) return "invalid";
    // A message whose id is missing or unusable is read as a notification.
    return validId(message.id) ? "request" : "accepted";
  }
  if (validId(message.id) && (isObject(message.result) || isObject(message.error))) return "accepted";
  return "invalid";
}

/** The response to one request (classify() returned "request"). */
export async function handleMessage(message: Message, env: Env): Promise<Py> {
  const {id, method, params} = message;
  const result = (value: Py) => ({jsonrpc: "2.0", id: id as Py, result: value});
  const invalid = () => rpcError(id, -32602, "Invalid request parameters", "");
  switch (method) {
    case "initialize": {
      const client = params?.clientInfo;
      if (!isObject(params) || typeof params.protocolVersion !== "string" || !isObject(params.capabilities)
        || !isObject(client) || typeof client.name !== "string" || typeof client.version !== "string") return invalid();
      const requested = params.protocolVersion;
      return result({
        capabilities: CAPABILITIES,
        protocolVersion: HANDSHAKE_VERSIONS.includes(requested) ? requested : HANDSHAKE_VERSIONS[0],
        serverInfo: {...SERVER_INFO},
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
      // The SDK lets this ValueError through as error code 0.
      return isObject(params) && typeof params.name === "string" ? rpcError(id, 0, `Unknown prompt: ${params.name}`) : invalid();
    case "tools/call": {
      const args = params?.arguments ?? {};
      if (!isObject(params) || typeof params.name !== "string" || !isObject(args)) return invalid();
      return result(await callTool(params.name, args, env));
    }
    default:
      return rpcError(id, -32601, "Method not found", method as string);
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
    if (Number(request.headers.get("Content-Length") ?? "0") > MAX_BODY_BYTES) return tooLarge();
    const body = await readBounded(request);
    if (body === null) return tooLarge();
    // Long-lived 2026-07-28 listen streams, as the Worker served them before.
    const listen = listenAtEdge(request.headers, body);
    if (listen) return listen;
    if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/json")) {
      return new Response("Invalid Content-Type header", {status: 400});
    }
    // Like the SDK: any protocol-version header that is not a handshake version is the 2026-07-28 path.
    const version = request.headers.get("MCP-Protocol-Version");
    if (version !== null && !HANDSHAKE_VERSIONS.includes(version)) return handleModern(request, body, env);
    if (!accepts(request.headers.get("Accept")).json) {
      return json(rpcError(null, -32600, "Not Acceptable: Client must accept application/json"), 406);
    }
    if (!(request.headers.get("Content-Type") ?? "").split(";")[0].split(",").some(part => part.trim() === "application/json")) {
      return json(rpcError(null, -32600, "Unsupported Media Type: Content-Type must be application/json"), 415);
    }
    let message: unknown;
    try {
      message = parseJson(new TextDecoder("utf-8", {fatal: true}).decode(body));
    } catch {
      return json(rpcError(null, -32700, "Parse error: the body is not valid JSON."), 400);
    }
    // Invalid messages get the SDK's status and code, without its pydantic dump.
    if (!isObject(message)) return json(rpcError(null, -32602, "Validation error: send one JSON-RPC message (an object) per request."), 400);
    const kind = classify(message);
    if (kind === "invalid") return json(rpcError(null, -32602, "Validation error: not a valid JSON-RPC request, notification, or response."), 400);
    if (kind === "accepted") return new Response(null, {status: 202});
    return json(await handleMessage(message, env));
  },
} satisfies ExportedHandler<Env>;
