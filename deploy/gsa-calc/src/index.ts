import {Container, getContainer} from "@cloudflare/containers";
import {explainCapacity, explainUnavailable, fetchWithRetry, originFirst, withToolCallLog} from "../../shared/edge.ts";
export {RateCounter} from "../../shared/rate-counter.ts";
import {toForwardUrl} from "./forward.ts";
import {BodyTimeoutError, HourlyBudget, budgetMessage, readBoundedBody} from "./hourly-budget.ts";
import {makeWorker, type Env} from "./worker.ts";

// The protocol and every tool call are answered by the Worker from the copy of
// GSA CALC+ in D1 (src/worker.ts). Only when the copy can't answer (a D1
// failure or an empty copy) does a call go to the Python server below: the
// Dell first, then this container, which keeps its shared hourly budget of
// GSA calls. The staging Worker (env.staging, no container) sends those to
// FORWARD_URL, production's /mcp.

export class GSACalc extends Container<Env> {
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
        return Response.json({jsonrpc: "2.0", id: body.id ?? null, result: {
          content: [{type: "text", text: budgetMessage(budget)}], isError: true,
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

/** A request the copy can't answer, sent as received: the Dell first, then the container. */
async function toBackend(request: Request, body: ArrayBuffer | null, env: Env): Promise<Response> {
  if (env.FORWARD_URL) return await toForwardUrl(env.FORWARD_URL, request, body);
  const url = new URL(request.url);
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
    const container = getContainer(env.BACKEND as DurableObjectNamespace<GSACalc>, "public-gsa-calc");
    // The Dell first (deploy/dell), then this container.
    const response = await originFirst(env, url.pathname, {method: request.method, headers, body},
      () => fetchWithRetry(() => container.fetch(forwarded())));
    const backend = response.headers.get("X-1102tools-Backend");
    const explained = explainCapacity(response, body, "GSA CALC+");
    if (backend && explained !== response) explained.headers.set("X-1102tools-Backend", backend);
    return explained;
  } catch {
    console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
    return explainUnavailable(body, "GSA CALC+");
  }
}

export default {fetch: withToolCallLog("gsa-calc", makeWorker(toBackend).fetch)} satisfies ExportedHandler<Env>;
