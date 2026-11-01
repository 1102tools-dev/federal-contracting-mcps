// The staging Worker (env.staging) has no container: what the copy can't
// answer goes to FORWARD_URL, production's /mcp, so live tools and forwarded
// questions come back from today's production server.
import {ORIGIN_DEADLINE_MS, explainUnavailable} from "../../shared/edge.ts";

// Headers a forwarded MCP request keeps when it goes to FORWARD_URL.
const MCP_HEADERS = ["accept", "content-type", "mcp-protocol-version", "mcp-method", "mcp-name"];

/** Staging (FORWARD_URL set): what the copy can't answer goes to the production server as sent. */
export async function toForwardUrl(forwardUrl: string, request: Request, body: ArrayBuffer | null): Promise<Response> {
  const headers = new Headers();
  for (const name of MCP_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  // Production counts these as 1102tools' own checks, apart from real users.
  headers.set("User-Agent", "1102tools-ecfr-staging");
  headers.set("X-1102tools-Monitor", "1");
  try {
    const response = await fetch(forwardUrl, {method: request.method, headers, body, signal: AbortSignal.timeout(ORIGIN_DEADLINE_MS)});
    const out = new Response(response.body, response);
    out.headers.set("X-1102tools-Backend", "forward_url");
    return out;
  } catch {
    console.log(JSON.stringify({event: "backend_unavailable", reason: "forward_url_failed"}));
    return explainUnavailable(body, "eCFR");
  }
}
