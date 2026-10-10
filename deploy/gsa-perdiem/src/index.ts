import {Container} from "@cloudflare/containers";
import {withToolCallLog} from "../../shared/edge.ts";
import {serve} from "./mcp.ts";

// The container that served this service before the D1 port. Kept exported
// (with its Durable Object binding and migration) so the cutover can be
// reversed; the fetch handler below never forwards to it.
export class GSAPerDiem extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2m";
  // The operator's api.data.gov key stays in Cloudflare secrets; users never supply or see it.
  envVars = {PERDIEM_API_KEY: this.env.PERDIEM_API_KEY ?? ""};
}

export default {fetch: withToolCallLog("gsa-perdiem", (request: Request, env: Env) => serve(request, env))} satisfies ExportedHandler<Env>;

