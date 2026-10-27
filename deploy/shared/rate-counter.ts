// No imports: this file is loaded by every Worker and by node's test runner.

/** One minute's tallies; the RateCounter Durable Object wraps this. */
export class MinuteCounter {
  #minute = -1;
  #counts = new Map<string, number>();

  /** Count one call for `key`; true while the tally is within `limit`. */
  hit(key: string, limit: number, now = Date.now()): boolean {
    const minute = Math.floor(now / 60_000);
    if (minute !== this.#minute) {
      this.#counts.clear();
      this.#minute = minute;
    }
    const count = (this.#counts.get(key) ?? 0) + 1;
    this.#counts.set(key, count);
    return count <= limit;
  }
}

/** Exact per-minute tool-call tallies for one shard of callers (see edge.ts).
 * Tallies live in memory only and reset every minute; nothing is stored. */
export class RateCounter {
  #counter = new MinuteCounter();

  async fetch(request: Request): Promise<Response> {
    const {key, limit} = await request.json() as {key?: unknown; limit?: unknown};
    if (typeof key !== "string" || typeof limit !== "number") return new Response(null, {status: 400});
    return new Response(null, {status: this.#counter.hit(key, limit) ? 204 : 429});
  }
}
