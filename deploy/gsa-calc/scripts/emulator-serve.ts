// "GSA in a box" over HTTP, for the Python server: GET /?<query string> is
// answered by emulate() over a local SQLite copy (scripts/load_gsa_calc.py
// build, or test/fixture-db.ts), as GSA's API would answer it: 200 with the
// JSON body (Python's json.dumps formatting, so json.loads gives the same
// values the Worker's tools see), or GSA's error status and text.
//
//   node scripts/emulator-serve.ts <d1.sqlite> [--port N] [--took MS]
//
// Prints "listening <port>" once ready. --took fixes `took` (default: measured),
// so the Python server's answers can match the Worker's byte for byte.
import {createServer} from "node:http";
import {DatabaseSync} from "node:sqlite";
import {emulate} from "../src/emulator.ts";
import {dumpsPython} from "../src/pyjson.ts";
import {d1} from "../test/d1.ts";

const [database, ...rest] = process.argv.slice(2);
const option = (name: string) => {
  const i = rest.indexOf(name);
  return i >= 0 ? rest[i + 1] : undefined;
};
if (!database) throw new Error("usage: node scripts/emulator-serve.ts <d1.sqlite> [--port N] [--took MS]");
const db = d1(new DatabaseSync(database, {readOnly: true}));
const took = option("--took") === undefined ? undefined : Number(option("--took"));

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  try {
    const answer = await emulate(db, url.search.slice(1), {took});
    if ("body" in answer) {
      response.writeHead(200, {"Content-Type": "application/json"});
      response.end(dumpsPython(answer.body));
    } else {
      response.writeHead(answer.status, {"Content-Type": "application/json"});
      response.end(answer.text);
    }
  } catch (error) {
    // An empty copy (Forward) or a query the emulator can't run: a 500, which the Python server reports as GSA being down.
    response.writeHead(500, {"Content-Type": "text/plain"});
    response.end(`emulator: ${error instanceof Error ? error.message : String(error)}`);
  }
});
server.listen(Number(option("--port") ?? 0), "127.0.0.1", () => {
  const address = server.address();
  console.log(`listening ${typeof address === "object" && address ? address.port : ""}`);
});
