// Pieces both protocol eras share: the Worker environment, tools/call, and
// small JSON-RPC helpers.
import SERVER from "../../../servers/ecfr-mcp/server.json" with {type: "json"};
import {Forward, ToolError, validateArgs} from "./args.ts";
import {dumps, parseJson, type Py} from "./pyjson.ts";
import {HANDLERS, LIVE_TOOLS, type Database} from "./tools.ts";

// The package version (server.json is kept equal to pyproject.toml by
// scripts/validate_versions.py), reported as serverInfo.version.
export const SERVER_INFO = {name: "ecfr", version: SERVER.version as string};

// D1 read replication: a session lets reads go to the nearest replica. The
// loader is the only writer, and every read of one tool call shares the
// session, so they see one consistent copy. Test doubles without withSession
// use the database as is.
type ReplicatedDatabase = Database & {withSession?(constraint: "first-unconstrained"): Database};
export const readSession = (db: ReplicatedDatabase): Database => db.withSession?.("first-unconstrained") ?? db;

// Answer cache: Cloudflare's cache at the location that answered. Answers the
// Worker builds from D1 (never errors, never forwarded answers) are filed under
// a SHA-256 fingerprint of the release, the copy's version (meta 'version',
// which the loader changes with every write), the tool and its validated
// arguments, so a new load or release never serves an older answer, and kept
// at most a day. No version row, no caching.
type AnswerCache = {match(key: Request): Promise<Response | undefined>; put(key: Request, response: Response): Promise<void>};
const CACHE_SECONDS = 86400;
const VERSION_SQL = "SELECT value FROM meta WHERE key = 'version'";

/** Whether the answer came from the cache, for the tool-call log (X-1102tools-Cache). */
export interface Trace {
  cache?: "hit" | "miss";
}

export interface Env {
  DB: ReplicatedDatabase;
  REQUEST_LIMITER: {limit(options: {key: string}): Promise<{success: boolean}>};
  AI_LIMITER?: {limit(options: {key: string}): Promise<{success: boolean}>};
  // Exact per-minute tool-call tallies (deploy/shared/rate-counter.ts).
  RATE_COUNTER?: {idFromName(name: string): unknown; get(id: unknown): {fetch(input: string, init?: RequestInit): Promise<Response>}};
  // The Python server: the Dell origin first, then the ECFR container (src/index.ts).
  BACKEND?: unknown;
  ORIGIN_URL?: string;
  ORIGIN_SECRET?: string;
  RELEASE_SHA?: string;
  ANSWER_CACHE?: AnswerCache; // tests only; deployed Workers use caches.default
  // Staging only: forwarded requests go here (production's /mcp) instead of the Dell or container.
  FORWARD_URL?: string;
}

// A JSON object (parseJson turns floats into PyFloat objects, which are not).
export const isObject = (value: unknown): value is Record<string, any> =>
  typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype;

// A JSON-RPC id the SDK accepts: a string or an integer (not a bool or 1.0).
export const validId = (id: unknown) =>
  typeof id === "string" || typeof id === "bigint" || (typeof id === "number" && Number.isInteger(id));

// The SDK writes result keys in alphabetical order: content (text, type), isError, structuredContent.
const textResult = (text: string, isError: boolean) => ({content: [{text, type: "text"}], isError});

/** The cache key for one answer: a fingerprint, never the arguments themselves. */
export async function answerKey(name: string, args: Record<string, unknown>, version: string, release: string): Promise<Request> {
  const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable)
    : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(k => [k, stable((value as Record<string, unknown>)[k])]))
    : typeof value === "bigint" ? {int: value.toString()} : value;
  const text = JSON.stringify([release, version, name, stable(args)]);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
  return new Request(`https://answer-cache.ecfr.1102tools.com/${hex}`);
}

/** The database as a handler sees it, with the copy's version read in each of its batches. */
function versioned(db: Database): {db: Database; versions: (string | null)[]} {
  const versions: (string | null)[] = [];
  return {versions, db: {
    prepare: (sql: string) => db.prepare(sql),
    batch: (async (statements: any[]) => {
      const results = await db.batch([...statements, db.prepare(VERSION_SQL)]);
      versions.push((results.pop()!.results[0] as {value?: string} | undefined)?.value ?? null);
      return results;
    }) as Database["batch"],
  }};
}

const result = (text: string, data: Py) => ({content: [{text, type: "text"}], isError: false, structuredContent: data});

/** tools/call result, shaped like the Python SDK's CallToolResult. Throws
 * Forward when the Python server must answer: a live tool, a question the
 * copy can't answer exactly, or any failure reading it. */
export async function callTool(name: string, args: Record<string, unknown>, env: Env, trace: Trace = {}): Promise<{[key: string]: Py}> {
  if (LIVE_TOOLS.has(name)) throw new Forward("live");
  const handler = Object.hasOwn(HANDLERS, name) ? HANDLERS[name] : undefined;
  if (!handler) return textResult(`Unknown tool: ${name}`, true);
  const db = readSession(env.DB);
  const cache = env.ANSWER_CACHE ?? (globalThis as {caches?: {default?: AnswerCache}}).caches?.default;
  try {
    let key: Request | undefined;
    let version: string | null = null;
    if (cache) {
      // Invalid arguments are answered before anything is read.
      const validated = validateArgs(name, args);
      version = ((await db.prepare(VERSION_SQL).all<{value: string}>()).results[0]?.value) ?? null;
      if (version !== null) {
        key = await answerKey(name, validated, version, env.RELEASE_SHA || SERVER_INFO.version);
        const hit = await cache.match(key).catch(() => undefined);
        const text = hit && await hit.text().catch(() => undefined);
        let data: Py | undefined;
        try {
          if (text !== undefined) data = parseJson(text) as Py;
        } catch {
          // An unreadable entry is a miss.
        }
        if (text !== undefined && data !== undefined) {
          trace.cache = "hit";
          return result(text, data);
        }
        trace.cache = "miss";
      }
    }
    const seen = key ? versioned(db) : null;
    const data = await handler(seen?.db ?? db, args);
    const text = dumps(data, 2);
    // Stored only when every read saw the version the key names (no load in between).
    if (cache && key && seen!.versions.length && seen!.versions.every(v => v === version)) {
      await cache.put(key, new Response(text, {headers: {"Content-Type": "application/json", "Cache-Control": `public, max-age=${CACHE_SECONDS}`}})).catch(() => {});
    }
    return result(text, data);
  } catch (error) {
    if (error instanceof ToolError) return textResult(`Error executing tool ${name}: ${error.message}`, true);
    if (error instanceof Forward) throw error;
    // A D1 failure or a gap in the copy: the Python server answers instead.
    // A category only: error text can carry arguments or SQL.
    console.log(JSON.stringify({event: "tool_forwarded", tool: name, reason: failureReason(error)}));
    throw new Forward(failureReason(error));
  }
}

/** A loggable category for an unexpected tool failure. */
function failureReason(error: unknown): string {
  if (!(error instanceof Error)) return "unknown";
  if (/timed? ?out|timeout/i.test(error.message)) return "d1_timeout";
  if (/D1_/.test(error.message)) return "d1";
  return error.name.slice(0, 40) || "Error";
}

/** Accept header media ranges, as the SDK's check_accept_headers reads them. */
export function accepts(header: string | null): {json: boolean; sse: boolean} {
  const types = (header ?? "").split(",").map(part => part.trim().split(";")[0].trim().toLowerCase());
  const any = types.includes("*/*");
  return {json: any || types.includes("application/json") || types.includes("application/*"),
    sse: any || types.includes("text/event-stream") || types.includes("text/*")};
}
