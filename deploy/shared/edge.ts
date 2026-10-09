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
