// Pieces both protocol eras share: the Worker environment, tools/call, and
// small JSON-RPC helpers.
import SERVER from "../../../servers/acquisition-gov-mcp/server.json" with {type: "json"};
import {dumps, type Py} from "./pyjson.ts";
import {HANDLERS, ToolError, type Database} from "./tools.ts";

// The package version (server.json is kept equal to pyproject.toml by
// scripts/validate_versions.py), reported as serverInfo.version.
export const SERVER_INFO = {name: "acquisition-gov", version: SERVER.version as string};

export interface Env {
  DB: Database;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  AI_LIMITER?: {limit(options: {key: string}): Promise<{success: boolean}>};
  RELEASE_SHA?: string;
}

// A JSON object (parseJson turns floats into PyFloat objects, which are not).
export const isObject = (value: unknown): value is Record<string, any> =>
  typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype;

// A JSON-RPC id the SDK accepts: a string or an integer (not a bool or 1.0).
export const validId = (id: unknown) =>
  typeof id === "string" || typeof id === "bigint" || (typeof id === "number" && Number.isInteger(id));

// The SDK writes result keys in alphabetical order: content (text, type), isError, structuredContent.
const textResult = (text: string, isError: boolean) => ({content: [{text, type: "text"}], isError});

/** tools/call result, shaped like the Python SDK's CallToolResult. */
export async function callTool(name: string, args: Record<string, unknown>, env: Env): Promise<{[key: string]: Py}> {
  const handler = Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
  if (!handler) return textResult(`Unknown tool: ${name}`, true);
  try {
    const data = await handler(env.DB, args);
    return {content: [{text: dumps(data, 2), type: "text"}], isError: false, structuredContent: data};
  } catch (error) {
    if (error instanceof ToolError) return textResult(`Error executing tool ${name}: ${error.message}`, true);
    console.log(JSON.stringify({event: "tool_failed", tool: name, reason: error instanceof Error ? error.message.slice(0, 200) : "unknown"}));
    return textResult(`Error executing tool ${name}: Acquisition.gov data is temporarily unavailable. Try again shortly.`, true);
  }
}

/** Accept header media ranges, as the SDK's check_accept_headers reads them. */
export function accepts(header: string | null): {json: boolean; sse: boolean} {
  const types = (header ?? "").split(",").map(part => part.trim().split(";")[0].trim().toLowerCase());
  const any = types.includes("*/*");
  return {json: any || types.includes("application/json") || types.includes("application/*"),
    sse: any || types.includes("text/event-stream") || types.includes("text/*")};
}
