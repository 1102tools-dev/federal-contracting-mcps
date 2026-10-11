const REPOSITORY = "https://api.github.com/repos/1102tools-dev/federal-contracting-mcps";
const ACTIVE_STATUSES = ["queued", "in_progress", "requested", "waiting", "pending"];
const WORKFLOWS: Record<string, string> = {
  "15 */2 * * *": "sam-opportunities-load.yml",
  "15 */4 * * *": "sam-public-load.yml",
  "10 10 * * *": "sam-public-load.yml",
  "10 11 * * *": "sam-public-load.yml",
  "40 9 * * *": "acquisition-gov-load.yml",
  "7,37 * * * *": "hosted-health.yml",
};

export function workflowsForCron(cron: string): string[] {
  const workflow = WORKFLOWS[cron];
  return workflow ? [workflow] : [];
}

type LogEntry = {workflow: string; status: number};

// Only workflow names and HTTP status codes enter logs. A zero status means
// there was no HTTP response (missing credential, transport or parse failure).
export async function dispatchLoads(
  cron: string,
  token: string | undefined,
  request: typeof fetch = fetch,
  log: (entry: LogEntry) => void = entry => console.log(JSON.stringify(entry)),
): Promise<void> {
  for (const workflow of workflowsForCron(cron)) {
    if (!token) { log({workflow, status: 0}); continue; }
    const headers = {
      Authorization: `Bearer ${token}`,
      "User-Agent": "1102tools-scheduler",
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    };
    try {
      let active = false;
      for (const status of ACTIVE_STATUSES) {
        const response = await request(`${REPOSITORY}/actions/workflows/${workflow}/runs?status=${status}&per_page=1`,
          {headers, signal: AbortSignal.timeout(10_000)});
        log({workflow, status: response.status});
        if (!response.ok) { active = true; break; }
        const result = await response.json() as {total_count?: unknown};
        if (!Number.isSafeInteger(result.total_count) || (result.total_count as number) < 0) {
          log({workflow, status: 0});
          active = true;
          break;
        }
        if ((result.total_count as number) > 0) { active = true; break; }
      }
      // Fail closed when an active run exists or its status cannot be checked.
      if (active) continue;
      const response = await request(`${REPOSITORY}/actions/workflows/${workflow}/dispatches`, {
        method: "POST", headers: {...headers, "Content-Type": "application/json"},
        body: JSON.stringify({ref: "main"}), signal: AbortSignal.timeout(10_000),
      });
      log({workflow, status: response.status});
    } catch {
      log({workflow, status: 0});
    }
  }
}

export default {
  scheduled(controller: ScheduledController, env: {GITHUB_DISPATCH_TOKEN?: string}, ctx: ExecutionContext): void {
    ctx.waitUntil(dispatchLoads(controller.cron, env.GITHUB_DISPATCH_TOKEN));
  },
} satisfies ExportedHandler<{GITHUB_DISPATCH_TOKEN?: string}>;
