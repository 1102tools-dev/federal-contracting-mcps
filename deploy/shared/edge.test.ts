// Run: node --test deploy/shared/edge.test.ts
import assert from "node:assert/strict";
import {test} from "node:test";
import {fetchWithRetry, isContainerFailure, isOriginFailure, listenAtEdge, originFirst, resetOriginProbes} from "./edge.ts";

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
