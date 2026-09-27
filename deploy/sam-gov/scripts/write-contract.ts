// Rewrite tools-contract.json from TOOLS. Review the git diff before committing:
// published tool metadata changes may need directory review.
import {writeFileSync} from "node:fs";
import {TOOLS} from "../src/tools.ts";

writeFileSync(new URL("../tools-contract.json", import.meta.url), JSON.stringify(TOOLS, null, 2) + "\n");
console.log(`wrote ${TOOLS.length} tool definitions to tools-contract.json`);
