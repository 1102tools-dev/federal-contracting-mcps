// Local-only integration harness; not the production entrypoint.
import { DurableObject } from "cloudflare:workers";
import { HourlyBudget } from "../src/hourly-budget";
export class HourlyBudgetTest extends DurableObject {
  private budget = new HourlyBudget(this.ctx.storage);
  async fetch(request: Request) {
    const input = await request.json() as {now: number; cooldown?: number};
    if (input.cooldown !== undefined) this.budget.observeCooldown(input.cooldown, input.now);
    return Response.json(this.budget.reserve(input.now));
  }
}
export default {
  fetch(request: Request, env: { BUDGET: DurableObjectNamespace<HourlyBudgetTest> }) {
    return env.BUDGET.getByName("persisted-test").fetch(request);
  }
};
