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
