import {Container, getContainer} from "@cloudflare/containers";
import {explainCapacity, explainUnavailable, fetchWithRetry, originFirst, withToolCallLog} from "../../shared/edge.ts";
export {RateCounter} from "../../shared/rate-counter.ts";
import {toForwardUrl} from "./forward.ts";
import {makeWorker, type Env} from "./worker.ts";

// The protocol and most tool calls are answered by the Worker from D1
// (src/worker.ts); the rest go to the Python server below. The staging Worker
// (env.staging, no container) sends them to FORWARD_URL, production's /mcp.

export class ECFR extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2m";
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
    const container = getContainer(env.BACKEND as DurableObjectNamespace<ECFR>, "public-ecfr");
    // The Dell first (deploy/dell), then this container.
    const response = await originFirst(env, url.pathname, {method: request.method, headers, body},
      () => fetchWithRetry(() => container.fetch(forwarded())));
    const backend = response.headers.get("X-1102tools-Backend");
    const explained = explainCapacity(response, body, "eCFR");
    if (backend && explained !== response) explained.headers.set("X-1102tools-Backend", backend);
    return explained;
  } catch {
    console.log(JSON.stringify({event: "backend_unavailable", reason: "container_request_failed"}));
    return explainUnavailable(body, "eCFR");
  }
}

export default {fetch: withToolCallLog("ecfr", makeWorker(toBackend).fetch)} satisfies ExportedHandler<Env>;
