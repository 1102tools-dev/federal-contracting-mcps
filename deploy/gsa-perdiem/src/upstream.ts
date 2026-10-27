// Live GSA Per Diem API calls with the operator's api.data.gov key, guarded
// like the package's hosted mode (server.py _get, _pacing.py): a 24-hour
// response cache, an hourly upstream budget below api.data.gov's 1,000
// requests/hour, spacing between calls, and the provider's 429 cooldown.
// Budget and spacing live in D1 so they hold across every Worker isolate.
import PACKAGE from "../../../servers/gsa-perdiem-mcp/server.json" with {type: "json"};
import type {Database} from "./data.ts";
import {PyFloat, dumps, loads, quote, quotePlus, squash, strip, pySlice} from "./py.ts";

export const BASE_URL = "https://api.gsa.gov/travel/perdiem/v2/rates";
/** The gsa-perdiem-mcp package version (server.json, bumped with pyproject.toml). */
export const PACKAGE_VERSION: string = PACKAGE.version;
export const USER_AGENT = `gsa-perdiem-mcp/${PACKAGE_VERSION}`;
export const HOURLY_UPSTREAM_CAP = 950;
export const REGISTERED_KEY_INTERVAL = 0.6;
// The container answered 504 after 55 seconds; a call that would wait for a
// slot longer than this (plus the 15-second request timeout) gets the busy answer now.
export const MAX_SLOT_WAIT = 40;
export const REQUEST_TIMEOUT_MS = 15_000;
export const RESPONSE_CACHE_SECONDS = 86_400;

/** A tool error whose message the user sees (MCPServer ToolError). */
export class ToolError extends Error {}

/** The request cannot finish within the hosted deadline: HTTP 504, as the container answered. */
export class DeadlineExceeded extends Error {
  constructor() { super("Request deadline exceeded while waiting or processing; retry later."); }
}

export const HOSTED_KEY_MISSING =
  "GSA Per Diem service credential is not configured. This is a server-side problem with the hosted service; " +
  "ZIP, state, and M&IE lookups for bundled fiscal years still work.";

export interface CacheLike {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
}

export interface UpstreamOptions {
  db: Database;
  key?: string;
  cache?: CacheLike | null;
  cacheOrigin?: string;
  fetch?: typeof fetch;
  clock?: () => number;            // milliseconds
  sleep?: (ms: number) => Promise<void>;
  hourlyCap?: number;
  interval?: number;               // seconds between upstream starts; 0 disables pacing
  maxWait?: number;
  cacheSeconds?: number;
}

// ---------- credential-safe text ----------

export function redact(text: string, key: string | null | undefined): string {
  if (!key) return text;
  let out = text;
  for (const variant of [...new Set([key, quote(key), quotePlus(key)])].sort((a, b) => b.length - a.length)) {
    out = out.split(variant).join("[REDACTED]");
  }
  return out;
}

function redactPayload(value: unknown, key: string): unknown {
  if (typeof value === "string") return redact(value, key);
  if (Array.isArray(value)) return value.map(v => redactPayload(v, key));
  if (value && typeof value === "object" && !(value instanceof PyFloat)) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactPayload(v, key)]));
  }
  return value;
}

const HTML_MARK = /<(?:!doctype|html)/i;
const TITLE = /<title[^>]*>([\s\S]*?)<\/title>/i;
const H1 = /<h1[^>]*>([\s\S]*?)<\/h1>/i;

export function cleanErrorBody(text: string | null, key?: string): string {
  if (text === null) return "(empty body)";
  text = redact(text, key);
  if (!HTML_MARK.test(text)) return pySlice(text, 400);
  const pieces: string[] = [];
  const title = TITLE.exec(text);
  if (title) pieces.push(squash(title[1]));
  const h1 = H1.exec(text);
  if (h1) {
    const h1Text = squash(h1[1]);
    if (h1Text && (!pieces.length || h1Text !== pieces[0])) pieces.push(h1Text);
  }
  return pieces.length ? pieces.join(" - ") : "upstream returned HTML page";
}

const SERVICE = "GSA Per Diem";

/** "about N minutes", rounded up, never less than one minute (_pacing.minutes_text). */
export function minutesText(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return minutes === 1 ? "about 1 minute" : `about ${minutes} minutes`;
}

/** The government's API is down, slow, or sent something unreadable (_pacing.government_unavailable_message). */
export function unavailableMessage(reason: string): string {
  return `The government's ${SERVICE} API isn't responding right now (${reason}). This is on the government's side; try again in a few minutes.`;
}

/** The government's API is limiting requests (_pacing.government_limited_message); the hosted key adds no fact. */
export function limitedMessage(retryAfterSeconds: number | null): string {
  const wait = retryAfterSeconds === null ? "Wait a few minutes before trying again." : `Try again in ${minutesText(retryAfterSeconds)}.`;
  return `The government's ${SERVICE} API is limiting requests right now. This is on the government's side. ${wait}`;
}

/** Plain user-facing text for an HTTP error. Never includes the response body. */
export function formatError(status: number): string {
  if (status === 403) {
    return "HTTP 403: the GSA Per Diem API rejected this service's credential. This is a server-side issue; " +
      "ZIP, state, and M&IE lookups for bundled fiscal years still work without it.";
  }
  if (status === 429) return limitedMessage(null);
  if (status === 404) {
    return "HTTP 404: Endpoint not found. If you passed a city with '..' or a slash, it may have been rejected " +
      "by the API router.";
  }
  return unavailableMessage(`error ${status}`);
}

// ---------- provider rate-limit headers (_pacing.py) ----------

const WANTED: Record<string, string> = {
  "retry-after": "retry_after", "x-ratelimit-limit": "limit", "x-ratelimit-remaining": "remaining",
  "x-ratelimit-reset": "reset", "ratelimit-limit": "limit", "ratelimit-remaining": "remaining", "ratelimit-reset": "reset",
};

function safeHeaders(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of headers) {
    const target = WANTED[name.toLowerCase()];
    if (target && !(target in out)) out[target] = pySlice(String(value), 200);
  }
  return out;
}

const PY_FLOAT = /^[+-]?(?:(?:\d(?:_?\d)*)?\.?\d(?:_?\d)*(?:[eE][+-]?\d(?:_?\d)*)?|\d(?:_?\d)*\.)$/;

/** Unix seconds when a Retry-After value ends, or null. */
export function retryAfterEpoch(value: string | undefined, now: number): number | null {
  if (value === undefined || !strip(value)) return null;
  const cleaned = strip(value);
  if (PY_FLOAT.test(cleaned)) {
    const seconds = Number(cleaned.replaceAll("_", ""));
    if (Number.isFinite(seconds) && seconds >= 0) return now + seconds;
  }
  const parsed = Date.parse(cleaned);
  return Number.isNaN(parsed) ? null : Math.max(now, parsed / 1000);
}

function networkReason(error: unknown): string {
  return error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError") ? "timed out" : "could not connect";
}

// ---------- the client ----------

export class Upstream {
  private db: Database;
  private key: string;
  private cache: CacheLike | null;
  private cacheOrigin: string;
  private fetcher: typeof fetch;
  private clock: () => number;
  private sleep: (ms: number) => Promise<void>;
  readonly hourlyCap: number;
  private interval: number;
  private maxWait: number;
  private cacheSeconds: number;

  constructor(options: UpstreamOptions) {
    this.db = options.db;
    this.key = strip(options.key ?? "");
    this.cache = options.cache ?? null;
    this.cacheOrigin = options.cacheOrigin ?? "https://gsa-perdiem.1102tools.com";
    this.fetcher = options.fetch ?? ((input, init) => fetch(input, init));
    this.clock = options.clock ?? Date.now;
    this.sleep = options.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
    this.hourlyCap = options.hourlyCap ?? HOURLY_UPSTREAM_CAP;
    this.interval = options.interval ?? REGISTERED_KEY_INTERVAL;
    this.maxWait = options.maxWait ?? MAX_SLOT_WAIT;
    this.cacheSeconds = options.cacheSeconds ?? RESPONSE_CACHE_SECONDS;
  }

  get keyConfigured(): boolean {
    return Boolean(this.key);
  }

  private cacheRequest(path: string): Request | null {
    return this.cache && this.cacheSeconds > 0 ? new Request(`${this.cacheOrigin}/__gsa-api-cache/v1/${path}`) : null;
  }

  /** Reserve one call in the rolling hour (minute buckets), or explain when to retry. */
  private async reserveHourly(): Promise<void> {
    const now = this.clock() / 1000;
    const minute = Math.floor(now / 60);
    const [reserved] = await this.db.batch<{calls: number}>([
      this.db.prepare(
        "INSERT INTO upstream_calls (minute, calls, first_at) SELECT ?1, 1, ?3 WHERE " +
        "(SELECT COALESCE(SUM(calls), 0) FROM upstream_calls WHERE minute > ?1 - 60) < ?2 " +
        "ON CONFLICT(minute) DO UPDATE SET calls = calls + 1 RETURNING calls",
      ).bind(minute, this.hourlyCap, now),
      this.db.prepare("DELETE FROM upstream_calls WHERE minute <= ?1 - 60").bind(minute),
    ]);
    if (reserved.results.length) return;
    // Seconds until the oldest call in the window ages out. Python's
    // int(x) + 1 on its nanosecond clock is ceil(x) in practice; this clock
    // has millisecond steps, where int(x) + 1 would overshoot by a second.
    const {results} = await this.db.prepare(
      "SELECT first_at FROM upstream_calls WHERE minute > ?1 - 60 ORDER BY minute LIMIT 1",
    ).bind(minute).all<{first_at: number}>();
    const oldest = results[0]?.first_at ?? now;
    const retry = Math.max(1, Math.ceil(oldest + 3600 - now));
    throw new ToolError(`The hosted ${SERVICE} server has used its hourly budget of ${this.hourlyCap} calls. Try again in ${minutesText(retry)}.`);
  }

  /** Claim the next start slot, at least `interval` after the previous one and after any provider cooldown. */
  private async waitForSlot(): Promise<void> {
    if (this.interval <= 0) return;
    const now = this.clock() / 1000;
    const {results} = await this.db.prepare(
      "INSERT INTO upstream_state (id, next_start, cooldown_until) VALUES (1, ?1 + ?2, 0) " +
      "ON CONFLICT(id) DO UPDATE SET next_start = MAX(next_start, ?1, cooldown_until) + ?2 " +
      "WHERE MAX(next_start, ?1, cooldown_until) - ?1 <= ?3 RETURNING next_start - ?2 AS start",
    ).bind(now, this.interval, this.maxWait).all<{start: number}>();
    if (!results.length) throw new DeadlineExceeded();
    const wait = results[0].start - now;
    if (wait > 0) await this.sleep(wait * 1000);
  }

  private async recordCooldown(until: number): Promise<void> {
    if (this.interval <= 0) return;
    await this.db.prepare(
      "INSERT INTO upstream_state (id, next_start, cooldown_until) VALUES (1, 0, ?1) " +
      "ON CONFLICT(id) DO UPDATE SET cooldown_until = MAX(cooldown_until, ?1)",
    ).bind(until).all();
  }

  /** GET a GSA Per Diem API path (after /rates/) and return its parsed, redacted JSON. */
  async get(path: string): Promise<any> {
    const cacheKey = this.cacheRequest(path);
    if (cacheKey) {
      // The cache only saves upstream calls; if it fails, ask GSA.
      const hit = await this.cache!.match(cacheKey).then(r => r?.text(), () => undefined);
      if (hit !== undefined) {
        try {
          return loads(hit);
        } catch {
          // A damaged entry is replaced below.
        }
      }
    }
    const key = this.key;
    if (!key) throw new ToolError(HOSTED_KEY_MISSING);
    await this.reserveHourly();
    await this.waitForSlot();
    // The key travels in api.data.gov's X-Api-Key header, never in the URL.
    let response: Response;
    let text: string;
    try {
      response = await this.fetcher(`${BASE_URL}/${path}`, {
        headers: {"User-Agent": USER_AGENT, "X-Api-Key": key},
        // httpx does not follow redirects; a 3xx is reported, not chased.
        redirect: "manual",
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      text = await response.text();
    } catch (error) {
      throw new ToolError(unavailableMessage(networkReason(error)));
    }
    if (response.status === 429) {
      const now = this.clock() / 1000;
      const until = retryAfterEpoch(safeHeaders(response.headers).retry_after, now);
      if (until !== null) await this.recordCooldown(until);
      throw new ToolError(limitedMessage(until === null ? null : until - now));
    }
    if (response.status >= 400) throw new ToolError(formatError(response.status));
    let payload: unknown;
    try {
      payload = loads(text);
    } catch {
      throw new ToolError(unavailableMessage("sent an unreadable response"));
    }
    payload = redactPayload(payload, key);
    // A null payload is never served from the container's cache either.
    if (cacheKey && payload !== null) {
      await this.cache!.put(cacheKey, new Response(dumps(payload, null, true), {
        headers: {"Content-Type": "application/json", "Cache-Control": `max-age=${this.cacheSeconds}`},
      })).catch(() => undefined);
    }
    return payload;
  }
}
