import {Container} from "@cloudflare/containers";
import {withToolCallLog} from "../../shared/edge.ts";
import worker, {type Env} from "./worker.ts";

// Every request is answered by the Worker from D1 (src/worker.ts).

// The previous Python container backend. It stays configured so the cutover
// can be rolled back by redeploying the earlier Worker; nothing forwards to it.
export class AcquisitionGov extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "2m";
}

export default {fetch: withToolCallLog("acquisition-gov", worker.fetch)} satisfies ExportedHandler<Env>;
