import { publicDocs } from "./public-docs";
import { Container, getContainer } from "@cloudflare/containers";
import { MAX_BODY_BYTES, fetchWithRetry, listenAtEdge, originFirst, readBounded, tooLarge, withinLimit } from "../../shared/edge";

export class RegulationsGov extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2m";
  // The operator's api.data.gov key stays in Cloudflare secrets; users never supply or see it.
  envVars = {REGULATIONS_GOV_API_KEY: this.env.REGULATIONS_GOV_API_KEY ?? ""};
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
    if (url.pathname !== "/mcp" && url.pathname !== "/health") {
      return new Response("Regulations.gov MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
    }
    const origin = request.headers.get("Origin");
    if (origin && origin !== url.origin) return new Response("Origin not allowed", {status: 403});
    if (!await withinLimit(request, env)) {
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
    const listen = listenAtEdge(request.headers, body);
    if (listen) return listen;
    try {
      const headers = new Headers(request.headers);
      headers.set("Host", "container.internal");
      headers.delete("Origin");
      headers.delete("Cookie");
      headers.delete("Authorization");
      headers.delete("Content-Length");
      const forwarded = () => new Request(`http://container.internal${url.pathname}`, {
        method: request.method, headers, body,
      });
      // A single named instance preserves process/file pacing across all users.
      const backend = getContainer(env.BACKEND, "public-regulations-gov");
      // The Dell first (deploy/dell), then this container.
      return await originFirst(env, url.pathname, {method: request.method, headers, body},
        () => fetchWithRetry(() => backend.fetch(forwarded())), {"X-Regulations-Key": env.REGULATIONS_GOV_API_KEY ?? ""});
    } catch (error) {
      console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
      return Response.json({error: "Regulations.gov service temporarily unavailable."}, {status: 503, headers: {"Retry-After": "15"}});
    }
  },
} satisfies ExportedHandler<Env>;
