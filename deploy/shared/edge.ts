// Edge handling shared by the container-backed hosted Workers.

// Matches the container's max_request_body_size; MCP tool calls are small.
export const MAX_BODY_BYTES = 65536;

export function tooLarge(): Response {
  return new Response("Request body too large.", {status: 413});
}

export async function readBounded(request: Request): Promise<ArrayBuffer | null> {
  const reader = request.body?.getReader();
  if (!reader) return new ArrayBuffer(0);
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
  const out = new Uint8Array(new ArrayBuffer(size));
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out.buffer;
}

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

// --- subscriptions/listen (MCP 2026-07-28) ---------------------------------
//
// Claude opens a long-lived listen stream beside its tool calls. These servers
// never change their tool, prompt or resource lists while running, so the
// stream only ever carries its acknowledgement and keepalives. In the
// container each stream held one of the 16 admission slots and kept the
// container awake until the 55-second deadline cut it, after which the client
// re-listened and refetched. Serve it here instead, with the same frames the
// MCP SDK sends, and end it gracefully after LISTEN_MAX_MS.

const LISTEN_VERSION = "2026-07-28";
const PROTOCOL_META = "io.modelcontextprotocol/protocolVersion";
const CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities";
const SUBSCRIPTION_META = "io.modelcontextprotocol/subscriptionId";
const FLAGS = ["toolsListChanged", "promptsListChanged", "resourcesListChanged"] as const;
export const LISTEN_PING_MS = 15_000;
export const LISTEN_MAX_MS = 30 * 60_000;

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache, no-transform",
  "X-Accel-Buffering": "no",
};

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);

function accepts(accept: string, types: string[]): boolean {
  return accept.split(",").some(part => types.includes(part.split(";")[0].trim().toLowerCase()));
}

// The subset the SDK acknowledges: true flags and a non-empty URI list.
// Returns null for anything the SDK would validate differently, so the
// container answers it exactly as before.
function honoredFilter(requested: Json): Json | null {
  const honored: Json = {};
  for (const [key, value] of Object.entries(requested)) {
    if ((FLAGS as readonly string[]).includes(key)) {
      if (value !== null && typeof value !== "boolean") return null;
      if (value) honored[key] = true;
    } else if (key === "resourceSubscriptions") {
      if (value === null) continue;
      if (!Array.isArray(value) || !value.every(uri => typeof uri === "string")) return null;
      if (value.length) honored[key] = [...value];
    } else {
      return null;
    }
  }
  return honored;
}

function frame(message: Json): Uint8Array {
  return new TextEncoder().encode(`event: message\r\ndata: ${JSON.stringify(message)}\r\n\r\n`);
}

const PING = new TextEncoder().encode(": ping\r\n\r\n");

/** An edge-served listen stream, or null to forward the request unchanged. */
export function listenAtEdge(
  headers: Headers,
  body: ArrayBuffer | null,
  timing: {pingMs: number; maxMs: number} = {pingMs: LISTEN_PING_MS, maxMs: LISTEN_MAX_MS},
): Response | null {
  if (body === null) return null;
  if (headers.get("mcp-protocol-version") !== LISTEN_VERSION) return null;
  if (headers.get("mcp-method") !== "subscriptions/listen") return null;
  const accept = headers.get("accept") ?? "";
  if (!accepts(accept, ["application/json", "application/*", "*/*"])) return null;
  if (!accepts(accept, ["text/event-stream", "text/*", "*/*"])) return null;

  let message: unknown;
  try {
    message = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return null;
  }
  if (!isObject(message) || message.jsonrpc !== "2.0" || message.method !== "subscriptions/listen") return null;
  const id = message.id;
  if (typeof id !== "string" && !Number.isSafeInteger(id)) return null;
  const params = message.params;
  if (!isObject(params) || !isObject(params.notifications) || !isObject(params._meta)) return null;
  if (params._meta[PROTOCOL_META] !== LISTEN_VERSION || !isObject(params._meta[CAPABILITIES_META])) return null;
  const honored = honoredFilter(params.notifications);
  if (honored === null) return null;

  const meta = {[SUBSCRIPTION_META]: id};
  const {readable, writable} = new TransformStream<Uint8Array, Uint8Array>();
  const writer = writable.getWriter();
  (async () => {
    try {
      await writer.write(frame({jsonrpc: "2.0", method: "notifications/subscriptions/acknowledged",
        params: {_meta: meta, notifications: honored}}));
      for (let waited = timing.pingMs; waited <= timing.maxMs; waited += timing.pingMs) {
        await sleep(timing.pingMs);
        await writer.write(PING);
      }
      await writer.write(frame({jsonrpc: "2.0", id, result: {_meta: meta, resultType: "complete"}}));
      await writer.close();
    } catch {
      // The client closed the stream.
    }
  })();
  return new Response(readable, {headers: SSE_HEADERS});
}

// --- container start races --------------------------------------------------
//
// When the container is starting, stopping or restarting, the Containers
// library answers with a plain-text 500/503 ("Failed to start container",
// "Container suddenly disconnected, try again", "There is no Container
// instance available"). The MCP server itself always answers JSON. Every tool
// is read-only, so one retry after a short pause is safe.

export const RETRY_PAUSE_MS = 2000;

export function isContainerFailure(response: Response): boolean {
  if (response.status !== 500 && response.status !== 503) return false;
  return !(response.headers.get("Content-Type") ?? "").toLowerCase().includes("json");
}

export async function fetchWithRetry(send: () => Promise<Response>, pauseMs = RETRY_PAUSE_MS): Promise<Response> {
  let response: Response;
  try {
    response = await send();
  } catch {
    await sleep(pauseMs);
    return await send();
  }
  if (!isContainerFailure(response)) return response;
  await response.body?.cancel();
  await sleep(pauseMs);
  return await send();
}

// --- Dell origin, container fallback ----------------------------------------
//
// USAspending, eCFR, Federal Register, GSA CALC+ and Regulations.gov also run
// on James's Dell behind a Cloudflare Tunnel (deploy/dell). The Worker tries
// it first and falls back to the container, which then only wakes when the
// Dell is unreachable. Tool responses are JSON, so their headers arrive only
// when the tool finishes; a short header timeout would cut slow calls. A
// cheap /health probe with a short timeout decides instead, cached per
// isolate. Every tool is read-only, so retrying on the container is safe.
// The Dell counts as up only when it runs this Worker's RELEASE_SHA, so after
// a release the new container serves until the Dell's updater catches up.

export interface OriginEnv {
  ORIGIN_URL?: string;
  ORIGIN_SECRET?: string;
  RELEASE_SHA?: string;
}

export const ORIGIN_PROBE_MS = 5000;
export const ORIGIN_PROBE_TTL_MS = 30_000;
// Just past the server's 55-second admission deadline.
export const ORIGIN_DEADLINE_MS = 58_000;

// The Dell never sees who is calling.
const CLIENT_HEADERS = [
  "cf-connecting-ip", "cf-connecting-ipv6", "cf-pseudo-ipv4", "true-client-ip", "x-forwarded-for",
  "x-real-ip", "forwarded", "cf-ipcountry", "cf-ipcity", "cf-ipcontinent", "cf-iplatitude",
  "cf-iplongitude", "cf-postal-code", "cf-region", "cf-region-code", "cf-metro-code", "cf-timezone",
  "cf-ray", "cf-visitor", "cf-worker", "cdn-loop", "user-agent", "referer", "host",
];

const probes = new Map<string, {checked: number; up: Promise<boolean>}>();

export function resetOriginProbes(): void {
  probes.clear();
}

function markOrigin(base: string, up: boolean, now = Date.now()): void {
  probes.set(base, {checked: now, up: Promise.resolve(up)});
}

export function originUp(base: string, releaseSha?: string, now = Date.now(), probeMs = ORIGIN_PROBE_MS): Promise<boolean> {
  const cached = probes.get(base);
  if (cached && now - cached.checked < ORIGIN_PROBE_TTL_MS) return cached.up;
  // Concurrent requests share one probe.
  const up = (async () => {
    try {
      const response = await fetch(`${base}/health`, {signal: AbortSignal.timeout(probeMs)});
      if (!response.ok || !isJson(response)) {
        await response.body?.cancel();
        return false;
      }
      const health = await response.json() as {status?: string; release_sha?: string};
      return health.status === "ok" && (!releaseSha || health.release_sha === releaseSha);
    } catch {
      return false;
    }
  })();
  probes.set(base, {checked: now, up});
  return up;
}

function isJson(response: Response): boolean {
  return (response.headers.get("Content-Type") ?? "").toLowerCase().includes("json");
}

// Answers from the tunnel, gateway or Cloudflare rather than the MCP server:
// HTML or text 403 (secret mismatch), 404 (unknown host), 502-504 (server or
// gateway down) and 52x (tunnel down). The MCP server answers JSON.
export function isOriginFailure(response: Response): boolean {
  if (isJson(response)) return false;
  return [403, 404, 502, 503, 504].includes(response.status) || response.status >= 520;
}

function tagged(response: Response, backend: string): Response {
  const out = new Response(response.body, response);
  out.headers.set("X-1102tools-Backend", backend);
  return out;
}

/**
 * Sends the request to the Dell origin when it is configured and up, else to
 * `container`. `headers` are the container-bound headers; client-identifying
 * ones are removed for the origin. `extra` adds origin-only headers.
 */
export async function originFirst(
  env: OriginEnv,
  path: string,
  init: {method: string; headers: Headers; body: ArrayBuffer | null},
  container: () => Promise<Response>,
  extra: Record<string, string> = {},
): Promise<Response> {
  const base = env.ORIGIN_URL?.replace(/\/+$/, "");
  let reason = "not_configured";
  if (base && env.ORIGIN_SECRET) {
    reason = "probe_failed";
    if (await originUp(base, env.RELEASE_SHA)) {
      const headers = new Headers(init.headers);
      for (const name of CLIENT_HEADERS) headers.delete(name);
      for (const [name, value] of Object.entries(extra)) if (value) headers.set(name, value);
      headers.set("X-Origin-Auth", env.ORIGIN_SECRET);
      try {
        const response = await fetch(`${base}${path}`, {
          method: init.method, headers, body: init.body, signal: AbortSignal.timeout(ORIGIN_DEADLINE_MS),
        });
        if (!isOriginFailure(response)) {
          console.log(JSON.stringify({event: "backend", backend: "origin", status: response.status}));
          return tagged(response, "origin");
        }
        reason = `origin_${response.status}`;
        await response.body?.cancel();
      } catch (error) {
        reason = error instanceof Error && error.name === "TimeoutError" ? "origin_timeout" : "origin_unreachable";
      }
      markOrigin(base, false);
    }
  }
  const response = await container();
  console.log(JSON.stringify({event: "backend", backend: "container", reason, status: response.status}));
  return tagged(response, "container");
}

// --- Tool-call log ------------------------------------------------------------
//
// One line per tools/call so Workers Logs can count which tools people use.
// It names the tool only, never its arguments: they can hold what people
// typed. A name that isn't a plain tool identifier logs as "other".

const TOOL_NAME = /^[a-z][a-z0-9_]{0,63}$/;

/** The tools/call tool name in a request body, or null for anything else. */
export function toolName(body: ArrayBuffer | null): string | null {
  if (!body) return null;
  let message: unknown;
  try {
    message = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return null;
  }
  if (!isObject(message) || message.method !== "tools/call") return null;
  const name = isObject(message.params) ? message.params.name : undefined;
  return typeof name === "string" && TOOL_NAME.test(name) ? name : "other";
}

/** Which app sent a request, as a platform label; the User-Agent itself is never logged. */
export function clientApp(userAgent: string | null): string {
  const ua = (userAgent ?? "").toLowerCase();
  if (ua.includes("claude-user")) return "claude";
  if (ua.startsWith("openai-mcp")) return "chatgpt";
  if (ua.includes("perplexity")) return "perplexity";
  if (ua.includes("claude-code")) return "claude-code";
  return "other";
}

export function logToolCall(service: string, body: ArrayBuffer | null, response: Response, started: number, userAgent: string | null): void {
  const tool = toolName(body);
  if (tool === null) return;
  console.log(JSON.stringify({
    event: "tool_call", service, tool, client: clientApp(userAgent), backend: response.headers.get("X-1102tools-Backend"),
    status: response.status, ms: Date.now() - started,
  }));
}

// Requests turned away before the server sees them; the container-backed
// Workers return these before logToolCall runs, so the wrapper skips them too.
const TURNED_AWAY = new Set([403, 413, 429]);

/** Logs each tools/call a Worker answers itself (the D1 services), the same
 * way the container-backed Workers log the calls they forward. */
export function withToolCallLog<E>(service: string, handler: (request: Request, env: E) => Promise<Response>) {
  return async (request: Request, env: E): Promise<Response> => {
    if (request.method !== "POST") return handler(request, env);
    // The body is read once here and handed on; a tee'd clone would stall the
    // handler's cancel of an oversized body.
    const body = await readBounded(request);
    if (body === null) return tooLarge();
    const started = Date.now();
    const response = await handler(new Request(request, {body}), env);
    if (!TURNED_AWAY.has(response.status)) logToolCall(service, body, response, started, request.headers.get("User-Agent"));
    return response;
  };
}

// --- Per-address request limits ---------------------------------------------
//
// Every caller gets REQUEST_LIMITER's limit (120 a minute per address). AI
// platforms funnel all their users through a few addresses: every Claude
// user arrives from Anthropic's outbound range, every ChatGPT user from
// OpenAI's connector ranges. Calls from those published ranges use
// AI_LIMITER (600 a minute per address) when the Worker has it, so one
// platform address isn't capped like one person. The ranges below come from
// the companies' own allowlists; refresh them with
// scripts/refresh_ai_platform_ranges.py. An address they miss keeps the
// normal limit.

export interface Limiter {
  limit(options: {key: string}): Promise<{success: boolean}>;
}

// BEGIN AI_PLATFORM_RANGES (scripts/refresh_ai_platform_ranges.py)
// Anthropic 160.79.104.0/21; OpenAI ChatGPT connectors (283 ranges), fetched 2026-10-08.
const AI_PLATFORM_RANGES = [
  "160.79.104.0/21", "3.12.200.18/32", "3.140.2.201/32", "4.7.10.112/30", "4.7.11.196/30", "4.14.111.0/28",
  "4.17.25.128/29", "4.19.160.0/28", "4.38.166.228/30", "4.53.139.144/28", "4.151.71.176/28", "4.151.119.48/28",
  "4.151.200.38/32", "4.155.146.196/32", "4.185.216.109/32", "4.189.118.208/28", "4.197.64.0/28", "4.197.64.48/28",
  "4.197.115.112/28", "4.197.172.116/32", "4.201.232.64/28", "4.205.128.176/28", "4.217.235.100/32", "4.218.24.64/28",
  "4.226.200.16/28", "4.226.226.32/28", "4.245.198.13/32", "8.244.149.100/30", "9.129.0.0/17", "9.160.96.16/28",
  "9.160.128.16/28", "9.160.128.64/28", "9.205.8.48/28", "9.205.8.64/28", "9.205.128.32/28", "9.205.128.48/28",
  "9.234.96.192/28", "9.234.97.96/28", "12.12.47.194/32", "12.12.56.24/29", "12.12.56.32/29", "12.12.56.224/28",
  "12.12.56.240/28", "12.77.42.78/32", "12.79.34.30/32", "12.79.201.188/30", "12.79.202.152/30", "12.79.202.156/30",
  "12.79.202.228/30", "12.79.202.232/30", "12.79.225.144/30", "12.105.90.64/27", "12.108.172.96/28", "12.117.245.68/30",
  "12.129.184.64/26", "12.162.186.200/29", "13.65.138.112/28", "13.67.72.16/28", "13.71.2.208/28", "13.71.25.29/32",
  "13.76.32.208/28", "13.76.116.80/28", "13.83.237.176/28", "13.223.161.115/32", "13.237.176.161/32", "13.238.110.96/32",
  "15.168.252.168/32", "18.218.234.253/32", "20.44.100.224/28", "20.45.178.144/28", "20.55.229.144/28", "20.57.199.192/28",
  "20.63.221.64/28", "20.74.221.21/32", "20.78.130.48/28", "20.98.18.80/28", "20.102.212.144/28", "20.125.40.252/32",
  "20.125.112.224/28", "20.162.96.163/32", "20.168.7.192/28", "20.169.78.48/28", "20.169.78.64/28", "20.169.86.224/28",
  "20.170.184.16/28", "20.170.184.32/28", "20.170.184.48/28", "20.170.184.64/28", "20.170.184.80/28", "20.171.137.175/32",
  "20.172.29.32/28", "20.184.36.134/32", "20.206.101.192/28", "20.212.62.208/28", "20.215.187.208/28", "20.215.219.208/28",
  "20.219.161.192/28", "20.219.184.96/28", "20.227.140.32/28", "20.228.106.176/28", "20.235.87.224/28", "20.241.32.36/32",
  "20.249.63.208/28", "20.250.136.64/28", "20.254.201.208/28", "23.98.186.64/28", "23.98.186.96/28", "23.101.217.176/28",
  "23.102.141.32/28", "24.82.185.0/29", "40.88.27.77/32", "40.118.236.137/32", "40.119.36.240/28", "40.122.118.93/32",
  "40.122.118.119/32", "40.122.118.202/32", "40.124.161.0/28", "43.202.230.227/32", "44.221.134.118/32", "44.249.227.138/32",
  "45.147.211.96/29", "48.218.181.198/32", "48.221.40.176/28", "48.221.184.80/28", "48.221.184.96/28", "50.145.17.208/30",
  "50.145.17.212/30", "50.145.17.216/29", "50.145.17.224/29", "50.151.105.128/30", "50.151.105.136/29", "50.213.205.80/29",
  "50.235.235.72/29", "51.4.112.173/32", "51.57.0.96/28", "51.59.24.64/28", "51.59.24.80/28", "51.59.48.80/28",
  "52.2.184.223/32", "52.6.94.121/32", "52.17.188.55/32", "52.43.161.225/32", "52.119.123.85/32", "52.143.181.161/32",
  "52.148.129.32/28", "52.165.212.48/28", "52.172.129.160/28", "52.173.221.16/28", "52.173.234.16/28", "52.173.234.80/28",
  "52.190.137.16/28", "52.190.137.144/28", "52.190.139.48/28", "52.190.142.64/28", "52.190.251.112/28", "52.208.217.159/32",
  "52.231.30.48/28", "52.231.39.144/28", "52.242.132.224/28", "52.242.132.240/28", "52.255.109.80/28", "52.255.109.96/28",
  "52.255.109.144/28", "52.255.111.0/28", "54.180.197.31/32", "54.227.131.66/32", "56.155.71.179/32", "57.133.92.112/31",
  "57.154.174.112/28", "57.154.187.32/28", "61.105.58.228/30", "62.96.221.184/29", "64.71.12.112/28", "64.124.21.196/32",
  "64.124.191.96/28", "66.193.99.66/32", "67.207.103.240/28", "68.154.28.96/28", "68.220.57.64/28", "70.153.32.16/28",
  "70.153.32.32/28", "70.156.152.96/28", "72.146.20.246/32", "74.7.35.48/28", "74.7.35.112/28", "74.7.36.64/28",
  "74.7.36.80/28", "74.7.36.96/28", "74.161.200.96/28", "74.224.217.64/28", "74.226.253.160/28", "74.248.37.160/28",
  "74.248.148.7/32", "76.77.188.112/29", "77.75.96.48/29", "79.244.198.212/30", "80.169.53.32/28", "85.211.128.16/28",
  "85.211.128.32/28", "98.87.72.221/32", "100.31.168.162/32", "102.37.57.54/32", "104.192.219.204/30", "104.208.184.192/28",
  "104.210.139.192/28", "104.210.139.224/28", "108.179.20.6/31", "112.220.228.112/29", "115.42.241.224/29", "128.177.85.168/30",
  "128.177.174.162/32", "130.33.24.99/32", "132.196.82.48/28", "134.33.102.192/28", "134.138.52.16/28", "134.138.52.64/28",
  "134.138.57.64/28", "134.138.57.80/28", "134.149.233.80/28", "135.13.64.240/28", "135.116.136.160/28", "135.220.40.201/32",
  "135.220.73.208/28", "135.220.208.92/32", "135.234.27.89/32", "135.237.133.48/28", "137.135.191.176/28", "145.132.136.96/28",
  "148.76.185.192/27", "148.109.10.28/30", "148.109.36.240/28", "149.97.160.16/28", "152.44.170.32/29", "159.180.234.92/30",
  "172.162.248.64/28", "172.167.32.228/32", "172.167.161.96/32", "172.170.1.80/28", "172.170.225.0/28", "172.170.241.80/28",
  "172.171.234.186/32", "172.172.206.48/28", "172.175.152.224/28", "172.177.53.240/28", "172.183.143.224/28", "172.191.70.179/32",
  "172.191.238.68/32", "172.192.112.208/28", "172.198.58.176/28", "172.198.79.112/28", "172.199.137.80/28", "172.203.39.49/32",
  "172.204.96.80/28", "172.206.38.240/28", "172.207.1.32/28", "172.207.173.200/32", "172.214.226.198/32", "172.215.215.32/28",
  "173.195.76.0/26", "180.222.194.124/30", "184.73.124.134/32", "191.232.238.96/28", "191.233.251.27/32", "191.234.167.144/28",
  "191.237.249.64/28", "194.46.223.16/28", "195.171.64.176/28", "199.47.142.0/23", "199.241.201.152/29", "203.125.229.136/29",
  "203.149.223.128/29", "208.52.97.112/29", "208.69.43.136/29", "208.80.35.32/27", "208.184.8.84/30", "208.184.8.104/29",
  "209.247.142.56/30", "209.247.151.176/28", "209.249.37.128/26", "209.249.246.178/31", "213.122.44.84/31", "216.64.170.234/32",
  "217.111.182.45/32", "217.111.242.24/29",
];
// END AI_PLATFORM_RANGES

function ipv4(address: string): number | null {
  const parts = address.split(".");
  if (parts.length !== 4) return null;
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part) || Number(part) > 255) return null;
    value = value * 256 + Number(part);
  }
  return value;
}

const PARSED_RANGES = AI_PLATFORM_RANGES.map(range => {
  const [base, bits] = range.split("/");
  const size = 2 ** (32 - Number(bits));
  const start = Math.floor(ipv4(base)! / size) * size;
  return [start, start + size] as const;
});

/** True for an IPv4 address inside a published Anthropic or OpenAI range. */
export function isAiPlatform(address: string): boolean {
  const value = ipv4(address);
  return value !== null && PARSED_RANGES.some(([start, end]) => value >= start && value < end);
}

/** Whether this request is within its address's per-minute limit. */
export async function withinLimit(request: Request, env: {REQUEST_LIMITER: Limiter; AI_LIMITER?: Limiter}): Promise<boolean> {
  const key = request.headers.get("CF-Connecting-IP") || "unknown";
  const limiter = env.AI_LIMITER && isAiPlatform(key) ? env.AI_LIMITER : env.REQUEST_LIMITER;
  return (await limiter.limit({key})).success;
}
