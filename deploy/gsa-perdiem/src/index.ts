import { publicDocs } from "./public-docs";
import { Container, getContainer } from "@cloudflare/containers";

export class GSAPerDiem extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2m";
  // The operator's api.data.gov key stays in Cloudflare secrets; users never supply or see it.
  envVars = {PERDIEM_API_KEY: this.env.PERDIEM_API_KEY ?? ""};
}

// Matches the container's max_request_body_size; MCP tool calls are small.
const MAX_BODY_BYTES = 65536;

function tooLarge(): Response {
  return new Response("Request body too large.", {status: 413});
}

async function readBounded(request: Request): Promise<ArrayBuffer | null> {
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
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
    if (url.pathname === "/mcp" && request.method !== "POST") {
      return new Response("Use POST for stateless MCP requests.", {status: 405, headers: {Allow: "POST"}});
    }
    if (url.pathname === "/health" && request.method !== "GET") return new Response(null, {status: 405});
    // Read the body at the edge, bounded, so slow or oversized uploads never
    // hold one of the single container's admission slots.
    let body: ArrayBuffer | null = null;
    if (request.method === "POST") {
      if (Number(request.headers.get("Content-Length") ?? "0") > MAX_BODY_BYTES) return tooLarge();
      body = await readBounded(request);
      if (body === null) return tooLarge();
    }
    try {
      const headers = new Headers(request.headers);
      headers.set("Host", "container.internal");
      headers.delete("Origin");
      headers.delete("Cookie");
      headers.delete("Authorization");
      headers.delete("Content-Length");
      const forwarded = new Request(`http://container.internal${url.pathname}`, {
        method: request.method, headers, body,
      });
      // A single named instance preserves process/file pacing across all users.
      return await getContainer(env.BACKEND, "public-gsa-perdiem").fetch(forwarded);
    } catch (error) {
      console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
      return Response.json({error: "GSA Per Diem service temporarily unavailable."}, {status: 503, headers: {"Retry-After": "15"}});
    }
  },
} satisfies ExportedHandler<Env>;
