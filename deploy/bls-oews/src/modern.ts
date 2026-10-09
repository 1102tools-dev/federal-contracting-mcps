// MCP 2026-07-28 (the per-request envelope, no initialize handshake), as the
// Python SDK's single-exchange HTTP path serves it (mcp/server/
// _streamable_http_modern.py): the same validation ladder, error codes, HTTP
// statuses, result decorations and json.dumps formatting. Long-lived
// subscriptions/listen streams are served by deploy/shared/edge.ts first.
import {dumpsPython, parseJson, type Py} from "./pyjson.ts";
import {SERVER_INFO, accepts, callTool, isObject, validId, type Env} from "./rpc.ts";
import {TOOLS} from "./tools.ts";

export const MODERN_VERSION = "2026-07-28";
const PROTOCOL_KEY = "io.modelcontextprotocol/protocolVersion";
const CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities";
const CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo";
const SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo";

const PARSE_ERROR = -32700;
const INVALID_REQUEST = -32600;
const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;
const INTERNAL_ERROR = -32603;
const HEADER_MISMATCH = -32020;
const UNSUPPORTED_PROTOCOL_VERSION = -32022;
// mcp.shared.inbound.ERROR_CODE_HTTP_STATUS; other codes are HTTP 200.
const HTTP_STATUS: Record<number, number> = {
  [PARSE_ERROR]: 400, [INVALID_REQUEST]: 400, [INVALID_PARAMS]: 400, [HEADER_MISMATCH]: 400,
  [UNSUPPORTED_PROTOCOL_VERSION]: 400, [METHOD_NOT_FOUND]: 404,
};
// Client methods the 2026-07-28 surface defines (others, such as ping and
// initialize, are Method not found), and the ones this server has handlers for.
const SURFACE = new Set(["completion/complete", "prompts/get", "prompts/list", "resources/list", "resources/read",
  "resources/templates/list", "server/discover", "subscriptions/listen", "tools/call", "tools/list"]);
const NAME_PARAM: Record<string, string> = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"};
const DISCOVER_CAPABILITIES = {
  prompts: {listChanged: true}, resources: {listChanged: true, subscribe: true}, tools: {listChanged: true},
};

class RpcError extends Error {
  readonly code: number;
  readonly data?: Py;
  constructor(code: number, message: string, data?: Py) {
    super(message);
    this.code = code;
    this.data = data;
  }
}
const invalidParams = () => new RpcError(INVALID_PARAMS, "Invalid request parameters", "");

function respond(body: Py, status = 200): Response {
  return new Response(dumpsPython(body), {status, headers: {"Content-Type": "application/json"}});
}

function errorResponse(id: Py, error: RpcError): Response {
  const detail: Record<string, Py> = {code: error.code, message: error.message};
  if (error.data !== undefined && error.data !== null) detail.data = error.data;
  // An unparseable id is written last, as null (the SDK adds it after dumping).
  const body = id === null ? {jsonrpc: "2.0", error: detail, id: null} : {jsonrpc: "2.0", id, error: detail};
  return respond(body, HTTP_STATUS[error.code] ?? 200);
}

/** A 2026-era result: keys in the SDK's order (alphabetical) and the serverInfo stamp last. */
function decorate(result: Record<string, Py>): Record<string, Py> {
  const out: Record<string, Py> = {};
  for (const key of Object.keys(result).sort()) out[key] = result[key];
  out._meta = {[SERVER_INFO_KEY]: {...SERVER_INFO}};
  return out;
}
const cached = (result: Record<string, Py>) => decorate({cacheScope: "private", resultType: "complete", ttlMs: 0, ...result});

/** decode_header_value: a header value, or the payload of its =?base64?...?= sentinel. */
function decodeHeader(value: string | null): string | null {
  if (value === null) return null;
  const match = /^=\?base64\?(.*)\?=$/s.exec(value);
  if (!match) return value;
  const payload = match[1];
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(payload) || payload.length % 4) return null;
  try {
    const bytes = Uint8Array.from(atob(payload), ch => ch.charCodeAt(0));
    if (btoa(String.fromCharCode(...bytes)) !== payload) return null;
    return new TextDecoder("utf-8", {fatal: true}).decode(bytes);
  } catch {
    return null;
  }
}

/** classify_inbound_request: the envelope and routing-header rungs. */
function ladder(message: Record<string, any>, headers: Headers): RpcError | null {
  const meta = isObject(message.params) ? message.params._meta : undefined;
  if (!isObject(meta)) {
    return new RpcError(INVALID_PARAMS, `params._meta must be an object carrying the required '${PROTOCOL_KEY}' and '${CAPABILITIES_KEY}' envelope keys`);
  }
  const missing = [PROTOCOL_KEY, CAPABILITIES_KEY].filter(key => !Object.hasOwn(meta, key));
  if (missing.length) return new RpcError(INVALID_PARAMS, `params._meta is missing the required envelope key(s): ${missing.join(", ")}`);
  const version = meta[PROTOCOL_KEY];
  if (headers.get("mcp-protocol-version") !== version) {
    return new RpcError(HEADER_MISMATCH, "mcp-protocol-version header does not match the request envelope's protocol version");
  }
  if (headers.get("mcp-method") !== message.method) {
    return new RpcError(HEADER_MISMATCH, "mcp-method header does not match the request body's method");
  }
  const nameKey = NAME_PARAM[message.method];
  const named = nameKey ? message.params[nameKey] : undefined;
  if (named !== undefined && named !== null && decodeHeader(headers.get("mcp-name")) !== named) {
    return new RpcError(HEADER_MISMATCH, `mcp-name header does not match the request body's '${nameKey}' parameter`);
  }
  if (version !== MODERN_VERSION) {
    return new RpcError(UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version", {supported: [MODERN_VERSION], requested: version});
  }
  return null;
}

const optionalString = (value: unknown) => value === undefined || value === null || typeof value === "string";
const optionalObject = (value: unknown) => value === undefined || value === null || isObject(value);

/** The per-method params check (validate_client_request), for the shapes real clients send. */
function checkParams(method: string, params: Record<string, any>) {
  const meta = params._meta;
  const caps = meta[CAPABILITIES_KEY];
  const info = meta[CLIENT_INFO_KEY];
  const capsOk = isObject(caps) && Object.entries(caps).every(([key, value]) =>
    !["roots", "sampling", "elicitation", "experimental", "tasks", "extensions"].includes(key) || optionalObject(value));
  const infoOk = info === undefined || info === null || (isObject(info) && typeof info.name === "string" && typeof info.version === "string");
  if (!capsOk || !infoOk) throw invalidParams();
  const ok = (() => {
    switch (method) {
      case "tools/list": case "prompts/list": case "resources/list": case "resources/templates/list":
        return optionalString(params.cursor);
      case "tools/call":
        return typeof params.name === "string" && optionalObject(params.arguments);
      case "resources/read":
        return typeof params.uri === "string";
      case "prompts/get":
        return typeof params.name === "string" && optionalObject(params.arguments);
      case "subscriptions/listen":
        return isObject(params.notifications);
      case "completion/complete":
        return isObject(params.ref) && isObject(params.argument);
      default:
        return true;
    }
  })();
  if (!ok) throw invalidParams();
}

async function dispatch(method: string, params: Record<string, any>, env: Env): Promise<Record<string, Py>> {
  if (!SURFACE.has(method)) throw new RpcError(METHOD_NOT_FOUND, "Method not found", method);
  checkParams(method, params);
  switch (method) {
    case "server/discover":
      return cached({capabilities: DISCOVER_CAPABILITIES, supportedVersions: [MODERN_VERSION]});
    case "tools/list":
      return cached({tools: TOOLS as Py});
    case "prompts/list":
      return cached({prompts: []});
    case "resources/list":
      return cached({resources: []});
    case "resources/templates/list":
      return cached({resourceTemplates: []});
    case "tools/call":
      return decorate({...await callTool(params.name, params.arguments ?? {}, env), resultType: "complete"});
    case "resources/read":
      throw new RpcError(INVALID_PARAMS, `Unknown resource: ${params.uri}`, {uri: params.uri});
    case "prompts/get":
      // The SDK maps this unhandled ValueError to a generic internal error.
      throw new RpcError(INTERNAL_ERROR, "Internal server error");
    case "subscriptions/listen":
      // Valid listen requests were streamed by listenAtEdge; it declines
      // filters it cannot acknowledge exactly like the SDK (non-boolean flags,
      // unknown keys), and those get the SDK's invalid-params answer here.
      throw invalidParams();
    default:
      throw new RpcError(METHOD_NOT_FOUND, "Method not found", method);
  }
}

/** One 2026-07-28 POST: everything after the edge checks and the listen stream. */
export async function handleModern(request: Request, body: ArrayBuffer, env: Env): Promise<Response> {
  const accept = accepts(request.headers.get("Accept"));
  if (!accept.json) return new Response(null, {status: 406});
  let message: unknown;
  try {
    message = parseJson(new TextDecoder("utf-8", {fatal: true}).decode(body));
  } catch {
    return errorResponse(null, new RpcError(PARSE_ERROR, "Parse error"));
  }
  if (!isObject(message) || message.jsonrpc !== "2.0" || !validId(message.id) || typeof message.method !== "string"
    || !(message.params === undefined || message.params === null || isObject(message.params))) {
    return errorResponse(null, new RpcError(INVALID_REQUEST, "Body must be a single JSON-RPC request object"));
  }
  const id = message.id as Py;
  if (message.method === "subscriptions/listen" && !accept.sse) return new Response(null, {status: 406});
  const rejection = ladder(message, request.headers);
  if (rejection) return errorResponse(id, rejection);
  try {
    return respond({jsonrpc: "2.0", id, result: await dispatch(message.method, message.params, env)});
  } catch (error) {
    if (error instanceof RpcError) return errorResponse(id, error);
    throw error;
  }
}
