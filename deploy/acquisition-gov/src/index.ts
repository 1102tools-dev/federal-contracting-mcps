import { publicDocs } from "./public-docs";
import { Container, getContainer } from "@cloudflare/containers";

export class AcquisitionGov extends Container {
  defaultPort = 8080;
  sleepAfter = "2m";
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
    if (url.pathname !== "/mcp" && url.pathname !== "/health") {
      return new Response("Acquisition.gov MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
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
    try {
      const headers = new Headers(request.headers);
      headers.set("Host", "container.internal");
      headers.delete("Origin");
      headers.delete("Cookie");
      headers.delete("Authorization");
      const forwarded = new Request(`http://container.internal${url.pathname}`, {
        method: request.method, headers, body: request.body,
      });
      // A single named instance preserves process/file pacing across all users.
      return await getContainer(env.BACKEND, "public-acquisition-gov").fetch(forwarded);
    } catch (error) {
      console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
      return Response.json({error: "Acquisition.gov service temporarily unavailable."}, {status: 503, headers: {"Retry-After": "15"}});
    }
  },
} satisfies ExportedHandler<Env>;
