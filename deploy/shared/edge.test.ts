// Run: node --test deploy/shared/edge.test.ts
import assert from "node:assert/strict";
import {test} from "node:test";
import {clientApp, fetchWithRetry, isContainerFailure, isOriginFailure, listenAtEdge, logToolCall, originFirst, resetOriginProbes, isAiPlatform, toolName, withToolCallLog, withinLimit, rateLimited, explainCapacity, isAiPlatformLive, resetLiveRanges, OPENAI_RANGES_URL, metaKeys, chatgptUser} from "./edge.ts";

// Tests never reach openai.com: the live AI-platform list download fails unless a test mocks it.
const networkFetch = globalThis.fetch;
globalThis.fetch = (async (input: any, init?: any) => String(input?.url ?? input) === OPENAI_RANGES_URL
  ? new Response("offline in tests", {status: 503}) : networkFetch(input, init)) as typeof fetch;

const HEADERS = {
  "content-type": "application/json",
  "accept": "application/json, text/event-stream",
  "mcp-protocol-version": "2026-07-28",
  "mcp-method": "subscriptions/listen",
};
const META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}};
const FAST = {pingMs: 5, maxMs: 12};

function listenBody(notifications: unknown, extra: Record<string, unknown> = {}): ArrayBuffer {
  const message = {jsonrpc: "2.0", id: "abc", method: "subscriptions/listen", params: {notifications, _meta: META}, ...extra};
  return new TextEncoder().encode(JSON.stringify(message)).buffer as ArrayBuffer;
}

test("serves a listen stream with the SDK's acknowledgement, pings and graceful end", async () => {
  const notifications = {toolsListChanged: true, promptsListChanged: true, resourcesListChanged: true, resourceSubscriptions: ["x://y"]};
  const response = listenAtEdge(new Headers(HEADERS), listenBody(notifications), FAST);
  assert.ok(response);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  // Captured from the deployed bls-oews container for the same request.
  const ack = 'event: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/subscriptions/acknowledged","params":{"_meta":{"io.modelcontextprotocol/subscriptionId":"abc"},"notifications":{"toolsListChanged":true,"promptsListChanged":true,"resourcesListChanged":true,"resourceSubscriptions":["x://y"]}}}\r\n\r\n';
  const end = 'event: message\r\ndata: {"jsonrpc":"2.0","id":"abc","result":{"_meta":{"io.modelcontextprotocol/subscriptionId":"abc"},"resultType":"complete"}}\r\n\r\n';
  assert.equal(await response.text(), ack + ": ping\r\n\r\n".repeat(2) + end);
});

test("acknowledges only true flags and non-empty URI lists, like the SDK", async () => {
  const response = listenAtEdge(new Headers(HEADERS), listenBody({toolsListChanged: false, promptsListChanged: null, resourceSubscriptions: []}), FAST);
  assert.ok(response);
  assert.match(await response.text(), /"notifications":\{\}\}\}/);
});

test("stops writing when the client disconnects", async () => {
  const response = listenAtEdge(new Headers(HEADERS), listenBody({toolsListChanged: true}), {pingMs: 5, maxMs: 60_000});
  assert.ok(response?.body);
  const reader = response.body.getReader();
  await reader.read();
  await reader.cancel();
  await new Promise(resolve => setTimeout(resolve, 20));
});

test("forwards everything the container should answer itself", () => {
  const forwarded: Array<[Record<string, string>, ArrayBuffer | null]> = [
    [HEADERS, null],
    [{...HEADERS, "mcp-protocol-version": "2025-11-25"}, listenBody({})],
    [{...HEADERS, "mcp-method": "tools/call"}, listenBody({})],
    [{...HEADERS, "accept": "application/json"}, listenBody({})],
    [{...HEADERS, "accept": "text/event-stream"}, listenBody({})],
    [HEADERS, new TextEncoder().encode("not json").buffer as ArrayBuffer],
    [HEADERS, listenBody({}, {method: "tools/list"})],
    [HEADERS, listenBody({}, {id: null})],
    [HEADERS, listenBody({}, {id: 1.5})],
    [HEADERS, listenBody({}, {params: {notifications: {}}})],
    [HEADERS, listenBody({}, {params: {notifications: {}, _meta: {...META, "io.modelcontextprotocol/protocolVersion": "2025-11-25"}}})],
    [HEADERS, listenBody({toolsListChanged: "yes"})],
    [HEADERS, listenBody({resourceSubscriptions: [1]})],
    [HEADERS, listenBody({tools_list_changed: true})],
    [HEADERS, listenBody([])],
  ];
  for (const [headers, body] of forwarded) assert.equal(listenAtEdge(new Headers(headers), body, FAST), null, JSON.stringify(headers));
});

test("recognizes the Containers library's plain-text failures only", () => {
  assert.ok(isContainerFailure(new Response("Failed to start container: x", {status: 500})));
  assert.ok(isContainerFailure(new Response("There is no Container instance available at this time.", {status: 503})));
  assert.ok(!isContainerFailure(Response.json({error: "x"}, {status: 500})));
  assert.ok(!isContainerFailure(new Response("ok", {status: 200})));
  assert.ok(!isContainerFailure(new Response("busy", {status: 429})));
});

test("retries once after a container failure or a thrown proxy error", async () => {
  const replies = [new Response("Container suddenly disconnected, try again", {status: 500}), Response.json({ok: true})];
  let calls = 0;
  const first = await fetchWithRetry(async () => replies[calls++], 1);
  assert.equal(calls, 2);
  assert.equal(first.status, 200);

  calls = 0;
  const second = await fetchWithRetry(async () => {
    if (calls++ === 0) throw new Error("Network connection lost.");
    return Response.json({ok: true});
  }, 1);
  assert.equal(calls, 2);
  assert.equal(second.status, 200);

  calls = 0;
  const json500 = await fetchWithRetry(async () => { calls++; return Response.json({error: "x"}, {status: 500}); }, 1);
  assert.equal(calls, 1);
  assert.equal(json500.status, 500);

  calls = 0;
  const still = await fetchWithRetry(async () => { calls++; return new Response("Failed to start container", {status: 500}); }, 1);
  assert.equal(calls, 2);
  assert.equal(still.status, 500);
});

// --- originFirst -------------------------------------------------------------

const ORIGIN = {ORIGIN_URL: "https://x-origin.example", ORIGIN_SECRET: "s3cret"};
type Call = {url: string; headers: Headers; method: string};

function withFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({url, headers: new Headers(init.headers), method: init.method ?? "GET"});
    return handler(url, init);
  }) as typeof fetch;
  resetOriginProbes();
  return {calls, restore: () => { globalThis.fetch = original; }};
}

const json = (body: unknown, status = 200) => Response.json(body, {status});
const containerHeaders = () => new Headers({
  "Host": "container.internal", "Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.9",
  "X-Forwarded-For": "203.0.113.9", "True-Client-IP": "203.0.113.9", "CF-IPCountry": "US", "User-Agent": "Claude-User",
});
const init = () => ({method: "POST", headers: containerHeaders(), body: new TextEncoder().encode("{}").buffer as ArrayBuffer});

test("uses the origin when it is up, without client IP headers", async () => {
  const mock = withFetch(url => url.endsWith("/health") ? json({status: "ok"}) : json({result: "dell"}));
  try {
    let containerCalls = 0;
    const response = await originFirst(ORIGIN, "/mcp", init(), async () => { containerCalls++; return json({}); },
      {"X-Regulations-Key": "k"});
    assert.equal(response.headers.get("X-1102tools-Backend"), "origin");
    assert.deepEqual(await response.json(), {result: "dell"});
    assert.equal(containerCalls, 0);
    const call = mock.calls[1];
    assert.equal(call.url, "https://x-origin.example/mcp");
    assert.equal(call.headers.get("X-Origin-Auth"), "s3cret");
    assert.equal(call.headers.get("X-Regulations-Key"), "k");
    assert.equal(call.headers.get("Content-Type"), "application/json");
    for (const name of ["Host", "CF-Connecting-IP", "X-Forwarded-For", "True-Client-IP", "CF-IPCountry", "User-Agent"]) {
      assert.equal(call.headers.get(name), null, name);
    }
  } finally {
    mock.restore();
  }
});

test("falls back to the container when the probe fails, and caches that", async () => {
  const mock = withFetch(() => { throw new TypeError("network"); });
  try {
    for (let i = 0; i < 3; i++) {
      const response = await originFirst(ORIGIN, "/mcp", init(), async () => json({result: "container"}));
      assert.equal(response.headers.get("X-1102tools-Backend"), "container");
    }
    assert.equal(mock.calls.length, 1);
  } finally {
    mock.restore();
  }
});

test("falls back when the tunnel or gateway answers instead of the server, then skips the origin", async () => {
  const mock = withFetch(url => url.endsWith("/health") ? json({status: "ok"})
    : new Response("<html>Error 1033</html>", {status: 530, headers: {"Content-Type": "text/html"}}));
  try {
    let containerCalls = 0;
    const send = async () => { containerCalls++; return json({result: "container"}); };
    assert.equal((await originFirst(ORIGIN, "/mcp", init(), send)).headers.get("X-1102tools-Backend"), "container");
    assert.equal((await originFirst(ORIGIN, "/mcp", init(), send)).headers.get("X-1102tools-Backend"), "container");
    assert.equal(containerCalls, 2);
    assert.equal(mock.calls.length, 2);  // one probe, one origin call
  } finally {
    mock.restore();
  }
});

test("falls back when the origin call throws", async () => {
  const mock = withFetch(url => { if (url.endsWith("/health")) return json({status: "ok"}); throw new TypeError("reset"); });
  try {
    const response = await originFirst(ORIGIN, "/mcp", init(), async () => json({result: "container"}));
    assert.deepEqual(await response.json(), {result: "container"});
  } finally {
    mock.restore();
  }
});

test("returns the server's own JSON errors instead of falling back", async () => {
  const mock = withFetch(url => url.endsWith("/health") ? json({status: "ok"}) : json({error: "busy"}, 503));
  try {
    const response = await originFirst(ORIGIN, "/mcp", init(), async () => assert.fail("container used"));
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("X-1102tools-Backend"), "origin");
  } finally {
    mock.restore();
  }
});

test("goes straight to the container when no origin is configured", async () => {
  const mock = withFetch(() => assert.fail("origin used"));
  try {
    for (const env of [{}, {ORIGIN_URL: "https://x-origin.example"}]) {
      const response = await originFirst(env, "/mcp", init(), async () => json({}));
      assert.equal(response.headers.get("X-1102tools-Backend"), "container");
    }
  } finally {
    mock.restore();
  }
});

test("concurrent requests share one probe", async () => {
  const mock = withFetch(async url => {
    if (url.endsWith("/health")) await new Promise(resolve => setTimeout(resolve, 10));
    return json({status: "ok"});
  });
  try {
    await Promise.all(Array.from({length: 5}, () => originFirst(ORIGIN, "/mcp", init(), async () => json({}))));
    assert.equal(mock.calls.filter(call => call.url.endsWith("/health")).length, 1);
  } finally {
    mock.restore();
  }
});

test("treats only non-JSON gateway and tunnel answers as origin failures", () => {
  const text = (status: number) => new Response("x", {status, headers: {"Content-Type": "text/plain"}});
  for (const status of [403, 404, 502, 503, 504, 520, 530]) assert.ok(isOriginFailure(text(status)), String(status));
  for (const status of [200, 400, 405, 406, 413, 429]) assert.ok(!isOriginFailure(text(status)), String(status));
  assert.ok(!isOriginFailure(json({}, 503)));
});

test("skips a Dell that runs a different release than this Worker", async () => {
  const mock = withFetch(url => url.endsWith("/health") ? json({status: "ok", release_sha: "old"}) : assert.fail("origin used"));
  try {
    const response = await originFirst({...ORIGIN, RELEASE_SHA: "new"}, "/mcp", init(), async () => json({}));
    assert.equal(response.headers.get("X-1102tools-Backend"), "container");
  } finally {
    mock.restore();
  }
  const same = withFetch(url => url.endsWith("/health") ? json({status: "ok", release_sha: "new"}) : json({result: "dell"}));
  try {
    const response = await originFirst({...ORIGIN, RELEASE_SHA: "new"}, "/mcp", init(), async () => assert.fail("container used"));
    assert.equal(response.headers.get("X-1102tools-Backend"), "origin");
  } finally {
    same.restore();
  }
});

test("AI platform addresses get the higher per-address limit", async () => {
  // Anthropic's outbound range (Claude users) and one of OpenAI's ChatGPT connector ranges.
  for (const address of ["160.79.106.12", "160.79.104.0", "160.79.111.255", "104.210.139.200"]) assert.equal(isAiPlatform(address), true, address);
  for (const address of ["160.79.112.1", "160.79.103.255", "136.50.132.183", "2600:100c::1", "unknown", "1.2.3", "300.1.1.1"]) {
    assert.equal(isAiPlatform(address), false, address);
  }
  const used: string[] = [];
  const limiter = (name: string, success = true) => ({limit: async ({key}: {key: string}) => (used.push(`${name}:${key}`), {success})});
  const request = (ip: string) => new Request("https://x.1102tools.com/mcp", {method: "POST", headers: {"CF-Connecting-IP": ip}});
  const env = {REQUEST_LIMITER: limiter("normal"), AI_LIMITER: limiter("ai")};
  assert.equal(await withinLimit(request("160.79.106.12"), env), true);
  assert.equal(await withinLimit(request("136.50.132.183"), env), true);
  // A Worker without AI_LIMITER keeps the normal limit for everyone.
  assert.equal(await withinLimit(request("160.79.106.12"), {REQUEST_LIMITER: limiter("normal")}), true);
  assert.equal(await withinLimit(request("8.8.8.8"), {REQUEST_LIMITER: limiter("normal", false), AI_LIMITER: limiter("ai")}), false);
  assert.deepEqual(used, ["ai:160.79.106.12", "normal:136.50.132.183", "normal:160.79.106.12", "normal:8.8.8.8"]);
});

test("limits each ChatGPT user like one address, trusting the ID only from platform addresses", async () => {
  const used: string[] = [];
  const counts = new Map<string, number>();
  const limiter = (name: string, max: number) => ({limit: async ({key}: {key: string}) => {
    used.push(`${name}:${key.startsWith("chatgpt-user:") ? "user" : key}`);
    const n = (counts.get(`${name}:${key}`) ?? 0) + 1;
    counts.set(`${name}:${key}`, n);
    return {success: n <= max};
  }});
  const env = {REQUEST_LIMITER: limiter("normal", 2), AI_LIMITER: limiter("ai", 600)};
  const call = (ip: string, subject?: string) => new Request("https://x.1102tools.com/mcp", {method: "POST",
    headers: {"CF-Connecting-IP": ip},
    body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "search_awards", arguments: {}, ...(subject ? {_meta: {"openai/subject": subject}} : {})}})});
  const openai = "4.14.111.5";
  // One ChatGPT user gets the normal limit (2 here); another user on the same address is unaffected.
  assert.equal(await withinLimit(call(openai, "user-a"), env), true);
  assert.equal(await withinLimit(call(openai, "user-a"), env), true);
  const third = call(openai, "user-a");
  assert.equal(await withinLimit(third, env), false);
  assert.equal(await withinLimit(call(openai, "user-b"), env), true);
  // The request body is still readable by the handler afterwards.
  assert.equal(JSON.parse(await call(openai, "user-c").text()).params.name, "search_awards");
  // Over the per-user limit, the message names the limit instead of "at capacity".
  const message = await (await rateLimited(third, "USAspending", 20)).json() as {result: {content: {text: string}[]}};
  assert.match(message.result.content[0].text, /limit of 20 calls a minute per person/);
  // Platform calls without an ID keep the address limit only.
  used.length = 0;
  assert.equal(await withinLimit(call(openai), env), true);
  assert.deepEqual(used, [`ai:${openai}`]);
  // An ID from any other address is ignored: the address limit applies.
  used.length = 0;
  assert.equal(await withinLimit(call("8.8.8.8", "made-up"), env), true);
  assert.deepEqual(used, ["normal:8.8.8.8"]);
  // The ID is hashed, never used as is.
  const hashed = await chatgptUser(call(openai, "user-a"));
  assert.match(hashed ?? "", /^[0-9a-f]{64}$/);
  assert.equal(await chatgptUser(call(openai)), null);
  assert.equal(await chatgptUser(new Request("https://x.1102tools.com/mcp", {method: "POST", body: "not json"})), null);
});

test("logs the names of a call's _meta labels and never their values", () => {
  const body = (message: unknown) => new TextEncoder().encode(JSON.stringify(message)).buffer as ArrayBuffer;
  const meta = {"openai/subject": "v1/secret-user-id", "openai/session": "secret-chat", "openai/locale": "en-US", "bad key; drop": 1};
  const call = body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "search_awards", arguments: {}, _meta: meta}});
  assert.deepEqual(metaKeys(call), ["openai/locale", "openai/session", "openai/subject"]);
  assert.ok(!JSON.stringify(metaKeys(call)).includes("secret"));
  assert.deepEqual(metaKeys(body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "x"}})), []);
  assert.deepEqual(metaKeys(body({jsonrpc: "2.0", id: 1, method: "tools/list", params: {_meta: meta}})), []);
  const many = Object.fromEntries(Array.from({length: 20}, (_, i) => [`k${String(i).padStart(2, "0")}`, i]));
  assert.equal(metaKeys(body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "x", _meta: many}})).length, 12);
  assert.deepEqual(metaKeys(new TextEncoder().encode("not json").buffer as ArrayBuffer), []);
  assert.deepEqual(metaKeys(null), []);
});

test("logs the tool name of a tools/call and never its arguments", () => {
  const body = (message: unknown) => new TextEncoder().encode(JSON.stringify(message)).buffer as ArrayBuffer;
  const call = body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "keyword_search", arguments: {keyword: "secret words"}}});
  assert.equal(toolName(call), "keyword_search");
  assert.equal(toolName(body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {name: "Drop me; secret"}})), "other");
  assert.equal(toolName(body({jsonrpc: "2.0", id: 1, method: "tools/call", params: {}})), "other");
  assert.equal(toolName(body({jsonrpc: "2.0", id: 1, method: "tools/list"})), null);
  assert.equal(toolName(new TextEncoder().encode("not json").buffer as ArrayBuffer), null);
  assert.equal(toolName(null), null);

  const lines: string[] = [];
  const original = console.log;
  console.log = (line: string) => { lines.push(line); };
  try {
    const response = new Response("{}", {status: 200, headers: {"X-1102tools-Backend": "origin"}});
    logToolCall("gsa-calc", call, response, Date.now() - 5, "Claude-User");
    logToolCall("gsa-calc", body({jsonrpc: "2.0", id: 2, method: "tools/list"}), response, Date.now(), "Claude-User");
  } finally {
    console.log = original;
  }
  assert.equal(lines.length, 1);
  const line = JSON.parse(lines[0]);
  assert.deepEqual({...line, ms: 0}, {event: "tool_call", service: "gsa-calc", tool: "keyword_search", client: "claude", backend: "origin", cache: null, status: 200, ms: 0, meta: []});
  assert.ok(line.ms >= 0);
  assert.ok(!lines[0].includes("secret"));
});

test("labels the app from the User-Agent without keeping the string", () => {
  assert.equal(clientApp("Claude-User"), "claude");
  assert.equal(clientApp("openai-mcp/1.0.0"), "chatgpt");
  assert.equal(clientApp("Perplexity-MCP/1.0"), "perplexity");
  assert.equal(clientApp("claude-code/2.1.4 (cli)"), "claude-code");
  assert.equal(clientApp("openai-mcp/1.0.0 (Codex)"), "codex");
  assert.equal(clientApp("curl/8.7.1"), "1102tools");
  assert.equal(clientApp("1102tools-release-guard/1"), "1102tools");
  assert.equal(clientApp("tedix-mcp-scanner/1.0"), "scanner");
  assert.equal(clientApp("OldRexTech-govcon-tools/1.0"), "other");
  assert.equal(clientApp("Mozilla/5.0 (Macintosh)"), "other");
  assert.equal(clientApp(null), "other");
});

test("the D1 wrapper logs answered tools/call requests only", async () => {
  const lines: string[] = [];
  const original = console.log;
  console.log = (line: string) => { lines.push(line); };
  const post = (method: string, status: number) => withToolCallLog("sam-gov", async (request: Request) => {
    await request.text();
    return new Response("{}", {status, headers: {"X-1102tools-Cache": "hit"}});
  })(new Request("https://sam.1102tools.com/mcp", {
    method: "POST", headers: {"User-Agent": "openai-mcp/1.0.0"},
    body: JSON.stringify({jsonrpc: "2.0", id: 1, method, params: {name: "search_opportunities", arguments: {q: "secret words"}}}),
  }), {});
  try {
    assert.equal((await post("tools/call", 200)).status, 200);
    await post("tools/list", 200);
    await post("tools/call", 429);
  } finally {
    console.log = original;
  }
  assert.equal(lines.length, 1);
  assert.deepEqual({...JSON.parse(lines[0]), ms: 0}, {event: "tool_call", service: "sam-gov", tool: "search_opportunities", client: "chatgpt", backend: null, cache: "hit", status: 200, ms: 0, meta: []});
  assert.ok(!lines[0].includes("secret"));
});

test("an address over its limit gets a message the AI can relay", async () => {
  const call = (ip: string, body: unknown) => new Request("https://x.1102tools.com/mcp", {method: "POST",
    headers: {"CF-Connecting-IP": ip, "Content-Type": "application/json"}, body: JSON.stringify(body)});
  const tool = await rateLimited(call("8.8.8.8", {jsonrpc: "2.0", id: 7, method: "tools/call", params: {name: "x"}}), "USAspending", 20);
  assert.equal(tool.status, 200);
  assert.equal(tool.headers.get("Retry-After"), "60");
  const result = await tool.json() as any;
  assert.equal(result.id, 7);
  assert.equal(result.result.isError, true);
  assert.match(result.result.content[0].text, /limit of 20 calls a minute.*install it locally in the Claude or ChatGPT desktop app.*#local-or-hosted/);
  const other = await rateLimited(call("8.8.8.8", {jsonrpc: "2.0", id: 1, method: "tools/list"}), "eCFR", 20);
  assert.equal(other.status, 429);
  assert.match((await other.json() as any).error.message, /eCFR limit of 20 calls a minute/);
  const ai = await rateLimited(call("160.79.106.12", {jsonrpc: "2.0", id: 2, method: "tools/call"}), "GSA CALC+", 10);
  assert.match((await ai.json() as any).result.content[0].text, /USAspending|GSA CALC\+ server is at capacity right now.*Claude or ChatGPT desktop app/);
  const garbled = await rateLimited(new Request("https://x.1102tools.com/mcp", {method: "POST", body: "not json"}), "eCFR", 20);
  assert.equal(garbled.status, 429);
});

test("a busy or timed-out backend answer is reworded for the AI", async () => {
  const body = new TextEncoder().encode(JSON.stringify({jsonrpc: "2.0", id: 3, method: "tools/call", params: {name: "x"}})).buffer;
  const busy = explainCapacity(Response.json({error: "Server busy"}, {status: 429}), body, "eCFR");
  assert.equal(busy.status, 200);
  const result = await busy.json() as any;
  assert.equal(result.id, 3);
  assert.equal(result.result.isError, true);
  assert.match(result.result.content[0].text, /hosted eCFR server is at capacity.*Claude or ChatGPT desktop app.*#local-or-hosted/);
  const late = explainCapacity(Response.json({error: "deadline"}, {status: 504}), null, "eCFR");
  assert.equal(late.status, 504);
  assert.match((await late.json() as any).error.message, /at capacity/);
  const fine = Response.json({ok: true});
  assert.equal(explainCapacity(fine, body, "eCFR"), fine);
});

test("OpenAI's live connector list extends the built-in ranges, and failures keep the built-in list", async () => {
  const realFetch = globalThis.fetch;
  const prefixes = [{ipv4Prefix: "203.0.113.0/24"}, ...Array.from({length: 60}, (_, i) => ({ipv4Prefix: `198.51.${i}.0/24`}))];
  let calls = 0;
  try {
    resetLiveRanges();
    globalThis.fetch = (async (url: string) => (calls++, assert.equal(String(url), OPENAI_RANGES_URL), Response.json({prefixes}))) as any;
    assert.equal(await isAiPlatformLive("203.0.113.9"), true);
    assert.equal(await isAiPlatformLive("8.8.8.8"), false);
    assert.equal(await isAiPlatformLive("160.79.106.12"), true);
    assert.equal(calls, 1, "the list is fetched once, then reused");
    resetLiveRanges();
    globalThis.fetch = (async () => { throw new Error("offline"); }) as any;
    assert.equal(await isAiPlatformLive("203.0.113.9"), false);
    assert.equal(await isAiPlatformLive("160.79.106.12"), true, "built-in ranges still apply");
    resetLiveRanges();
    globalThis.fetch = (async () => Response.json({prefixes: [{ipv4Prefix: "203.0.113.0/24"}]})) as any;
    assert.equal(await isAiPlatformLive("203.0.113.9"), false, "a suspiciously short list is ignored");
  } finally {
    globalThis.fetch = realFetch;
    resetLiveRanges();
  }
});
