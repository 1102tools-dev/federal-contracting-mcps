// Run: node --test deploy/shared/edge.test.ts
import assert from "node:assert/strict";
import {test} from "node:test";
import {fetchWithRetry, isContainerFailure, listenAtEdge} from "./edge.ts";

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
