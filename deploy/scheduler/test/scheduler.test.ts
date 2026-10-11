import assert from "node:assert/strict";
import {test} from "node:test";
import worker, {dispatchLoads, workflowsForCron} from "../src/index.ts";

const crons: Record<string, string> = {
  "15 */2 * * *": "sam-opportunities-load.yml",
  "15 */4 * * *": "sam-public-load.yml",
  "10 10 * * *": "sam-public-load.yml",
  "10 11 * * *": "sam-public-load.yml",
  "40 9 * * *": "acquisition-gov-load.yml",
  "7,37 * * * *": "hosted-health.yml",
};
const token = "test-only-secret-never-log";
const empty = () => Response.json({total_count: 0});

for (const [cron, workflow] of Object.entries(crons)) {
  test(`${cron} dispatches ${workflow} on main with required headers`, async () => {
    const calls: {url: string; init: RequestInit | undefined}[] = [];
    const logs: unknown[] = [];
    await dispatchLoads(cron, token, (async (url, init) => {
      calls.push({url: String(url), init});
      return init?.method === "POST" ? new Response(null, {status: 204}) : empty();
    }) as typeof fetch, entry => logs.push(entry));
    assert.equal(calls.length, 6);
    const post = calls.at(-1)!;
    assert.equal(post.url, `https://api.github.com/repos/1102tools-dev/federal-contracting-mcps/actions/workflows/${workflow}/dispatches`);
    assert.equal(post.init?.body, '{"ref":"main"}');
    const headers = new Headers(post.init?.headers);
    assert.equal(headers.get("Authorization"), `Bearer ${token}`);
    assert.equal(headers.get("User-Agent"), "1102tools-scheduler");
    assert.equal(headers.get("Content-Type"), "application/json");
    assert.deepEqual(logs.at(-1), {workflow, status: 204});
    assert.ok(!JSON.stringify(logs).includes(token));
  });
}

for (const active of ["queued", "in_progress", "requested", "waiting", "pending"]) {
  test(`does not dispatch when ${active} exists`, async () => {
    let posts = 0;
    await dispatchLoads("15 */2 * * *", token, (async (url, init) => {
      if (init?.method === "POST") posts++;
      return Response.json({total_count: new URL(String(url)).searchParams.get("status") === active ? 1 : 0});
    }) as typeof fetch, () => {});
    assert.equal(posts, 0);
  });
}

for (const response of [() => new Response(token, {status: 403}), () => Response.json({}),
  () => Response.json({total_count: -1}), () => Response.json({total_count: 0.5}),
  () => Response.json({total_count: "0"}), () => new Response(token)]) {
  test("failed or malformed status check fails closed without sensitive logs", async () => {
    let calls = 0;
    const logs: unknown[] = [];
    await dispatchLoads("15 */2 * * *", token, (async () => {calls++; return response();}) as typeof fetch, entry => logs.push(entry));
    assert.equal(calls, 1);
    assert.ok(!JSON.stringify(logs).includes(token));
    assert.ok(logs.every(entry => Object.keys(entry as object).sort().join() === "status,workflow"));
  });
}

test("failed POST logs HTTP status but never response body", async () => {
  const logs: unknown[] = [];
  await dispatchLoads("40 9 * * *", token, (async (_url, init) =>
    init?.method === "POST" ? new Response(token, {status: 500}) : empty()) as typeof fetch, entry => logs.push(entry));
  assert.deepEqual(logs.at(-1), {workflow: "acquisition-gov-load.yml", status: 500});
  assert.ok(!JSON.stringify(logs).includes(token));
});

test("transport failure redacts exception text", async () => {
  const logs: unknown[] = [];
  await dispatchLoads("40 9 * * *", token, (async () => {throw new Error(token);}) as typeof fetch, entry => logs.push(entry));
  assert.deepEqual(logs, [{workflow: "acquisition-gov-load.yml", status: 0}]);
});

test("missing secret never makes a request", async () => {
  await dispatchLoads("40 9 * * *", undefined, (async () => {assert.fail("request");}) as typeof fetch, () => {});
});

test("unknown cron has no dispatch and Worker has no fetch handler", () => {
  assert.deepEqual(workflowsForCron("* * * * *"), []);
  assert.equal("fetch" in worker, false);
});

test("scheduled handler registers work with waitUntil", async () => {
  let promise: Promise<unknown> | undefined;
  worker.scheduled({cron: "unknown"} as ScheduledController, {}, {
    waitUntil(value: Promise<unknown>) {promise = value;},
  } as ExecutionContext);
  assert.ok(promise instanceof Promise);
  await promise;
});
