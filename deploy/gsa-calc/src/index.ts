import { HourlyBudget, readBoundedBody, BodyTimeoutError } from "./hourly-budget";
import { publicDocs } from "./public-docs";
import { Container, getContainer } from "@cloudflare/containers";

export class GSACalc extends Container {
  defaultPort = 8080;
  sleepAfter = "2m";
  private readonly hourlyBudget = new HourlyBudget(this.ctx.storage);

  override async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/mcp") return super.fetch(request);
    let bytes;
    try { bytes = await readBoundedBody(request); }
    catch (error) {
      if (error instanceof BodyTimeoutError) return new Response("Request body timed out", {status: 408});
      throw error;
    }
    if (bytes === null) return new Response("Request body too large", {status: 413});
    let body;
    try { body = JSON.parse(new TextDecoder().decode(bytes)); }
    catch { return new Response("Invalid JSON", {status: 400}); }
    let remaining: number | undefined;
    if (body && body.method === "tools/call") {
      const budget = this.hourlyBudget.reserve();
      if (!budget.allowed) {
        const detail = budget.reason === "provider" ? "GSA CALC+ provider cooldown is active." : "GSA CALC+ hosted safety budget of 500 tool requests per hour is exhausted.";
        return Response.json({jsonrpc: "2.0", id: body.id ?? null, result: {
          content: [{type: "text", text: `${detail} Retry after ${budget.retryAfter} seconds.`}], isError: true,
        }}, {headers: {"Retry-After": String(budget.retryAfter), "X-1102tools-Hourly-Remaining": String(budget.remaining), "Cache-Control": "no-store"}});
      }
      remaining = budget.remaining;
    }
    // Reserve durably before forwarding. Failed/invalid tool requests remain counted.
    const response = await super.fetch(new Request(request.url, {method: request.method, headers: request.headers, body: bytes}));
    const retryAfter = response.headers.get("X-1102tools-Provider-Retry-After");
    if (retryAfter !== null) this.hourlyBudget.observeCooldown(Number(retryAfter));
    if (remaining === undefined) return response;
    const headers = new Headers(response.headers);
    headers.set("X-1102tools-Hourly-Remaining", String(remaining));
    return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (publicDocs[url.pathname] && request.method === "GET") return new Response(publicDocs[url.pathname], {headers: {"Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff"}});
    if (url.pathname !== "/mcp" && url.pathname !== "/health") {
      return new Response("GSA CALC+ MCP by 1102tools. Connect at /mcp.", {status: url.pathname === "/" ? 200 : 404});
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
      return await getContainer(env.BACKEND, "public-gsa-calc").fetch(forwarded);
    } catch (error) {
      console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
      return Response.json({error: "GSA CALC+ service temporarily unavailable."}, {status: 503, headers: {"Retry-After": "15"}});
    }
  },
} satisfies ExportedHandler<Env>;
