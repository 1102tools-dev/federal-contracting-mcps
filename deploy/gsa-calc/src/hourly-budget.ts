/** Durable hosted request budget. Current CALC+ tools each make at most one API call. */
export class HourlyBudget {
  private storage: Pick<DurableObjectStorage, "sql" | "transactionSync">;
  constructor(storage: Pick<DurableObjectStorage, "sql" | "transactionSync">) {
    this.storage = storage;
    storage.sql.exec("CREATE TABLE IF NOT EXISTS calc_hourly_attempts_v1 (id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL)");
    storage.sql.exec("CREATE TABLE IF NOT EXISTS calc_provider_cooldown_v1 (id INTEGER PRIMARY KEY CHECK (id = 1), until_ms INTEGER NOT NULL)");
  }
  observeCooldown(seconds: number, now = Date.now()) {
    const until = now + Math.ceil(seconds) * 1000;
    if (!Number.isFinite(seconds) || seconds < 0 || !Number.isSafeInteger(until)) throw new Error("Invalid provider cooldown");
    this.storage.sql.exec("INSERT INTO calc_provider_cooldown_v1 (id, until_ms) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET until_ms = MAX(until_ms, excluded.until_ms)", until);
  }
  reserve(now = Date.now()) {
    if (!Number.isSafeInteger(now) || now < 0) throw new Error("Invalid budget clock");
    return this.storage.transactionSync(() => {
      const sql = this.storage.sql;
      sql.exec("DELETE FROM calc_hourly_attempts_v1 WHERE started_ms <= ?", now - 3_600_000);
      const row = sql.exec<{count: number; oldest: number | null}>("SELECT COUNT(*) AS count, MIN(started_ms) AS oldest FROM calc_hourly_attempts_v1").one();
      const cooldown = sql.exec<{until_ms: number}>("SELECT COALESCE(MAX(until_ms), 0) AS until_ms FROM calc_provider_cooldown_v1").one().until_ms;
      if (cooldown > now) {
        return {allowed: false, remaining: Math.max(0, 500 - row.count), retryAfter: Math.ceil((cooldown-now)/1000), reason: "provider"};
      }
      if (row.count >= 500) {
        return {allowed: false, remaining: 0, retryAfter: Math.max(1, Math.ceil(((row.oldest ?? now) + 3_600_000 - now) / 1000)), reason: "hourly"};
      }
      sql.exec("INSERT INTO calc_hourly_attempts_v1 (started_ms) VALUES (?)", now);
      return {allowed: true, remaining: 499 - row.count, retryAfter: 0, reason: "allowed"};
    });
  }
}

export class BodyTimeoutError extends Error {}

/** Bound JSON inspection by size and time before counting/forwarding requests. */
export async function readBoundedBody(request: Request, timeoutMs = 10_000): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const read = async (): Promise<Uint8Array<ArrayBuffer> | null> => {
    const chunks: Uint8Array[] = [];
    let length = 0;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 65_536) return null;
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return bytes;
  };
  try {
    return await Promise.race([read(), new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new BodyTimeoutError("Request body timed out")), timeoutMs);
    })]);
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
