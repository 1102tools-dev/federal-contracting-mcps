// Tool argument validation as the Python server does it: the MCP SDK's
// pre_parse_json, then the pydantic argument model built from each tool's
// signature (lax mode, extra="forbid"). Failures carry pydantic's exact
// ValidationError text, which the SDK reports as the tool error.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {PyFloat, parseJson, pyType, repr} from "./pyjson.ts";

/** Deliberate tool errors (Python exceptions): "Error executing tool <name>: <message>". */
export class ToolError extends Error {}

type Schema = {type?: string; anyOf?: Schema[]; enum?: string[]; default?: unknown};
type Issue = {loc: string; type: string; msg: string; input: unknown};
type Result = {ok: true; value: unknown} | {ok: false; issue: Issue};

/** A Python int after validation: a number, or a bigint beyond 2**53. */
export type PyInt = number | bigint;

const PYDANTIC_DOCS = "https://errors.pydantic.dev/2.13/v/";
const I64 = 2 ** 63;
// Rust's char::is_whitespace, which pydantic_core strips before parsing an int.
const RUST_EDGES = /^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
const INT_TEXT = /^([+-]?)(\d(?:_?\d)*)(?:\.0+)?$/;
const utf8 = new TextEncoder();

const ok = (value: unknown): Result => ({ok: true, value});
const fail = (loc: string, type: string, msg: string, input: unknown): Result => ({ok: false, issue: {loc, type, msg, input}});
const exact = (value: bigint): PyInt => (value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value);

/** pydantic's lax int: bools, whole floats and integer strings convert. */
function laxInt(value: unknown, loc: string): Result {
  if (typeof value === "boolean") return ok(value ? 1 : 0);
  if (typeof value === "bigint" || (typeof value === "number" && Number.isInteger(value))) return ok(value);
  if (value instanceof PyFloat || typeof value === "number") {
    const f = value instanceof PyFloat ? value.value : value;
    if (!Number.isFinite(f)) return fail(loc, "finite_number", "Input should be a finite number", value);
    if (!Number.isInteger(f)) return fail(loc, "int_from_float", "Input should be a valid integer, got a number with a fractional part", value);
    if (Math.abs(f) >= I64) return fail(loc, "int_parsing_size", "Unable to parse input string as an integer, exceeded maximum size", value);
    return ok(f === 0 ? 0 : Number.isSafeInteger(f) ? f : BigInt(f));
  }
  if (typeof value === "string") {
    const text = value.replace(RUST_EDGES, "");
    if (utf8.encode(text).length > 4300) return fail(loc, "int_parsing_size", "Unable to parse input string as an integer, exceeded maximum size", value);
    const match = INT_TEXT.exec(text);
    if (!match) return fail(loc, "int_parsing", "Input should be a valid integer, unable to parse string as an integer", value);
    const parsed = BigInt(match[2].replaceAll("_", ""));
    return ok(exact(match[1] === "-" ? -parsed : parsed));
  }
  return fail(loc, "int_type", "Input should be a valid integer", value);
}

function validate(value: unknown, schema: Schema, loc: string): Result {
  if (schema.anyOf) {
    // Optional[X]: X that also takes None, reported under the field's own name.
    if (value === null) return ok(null);
    return validate(value, schema.anyOf.find(s => s.type !== "null")!, loc);
  }
  if (schema.enum) {
    if (typeof value === "string" && schema.enum.includes(value)) return ok(value);
    const quoted = schema.enum.map(e => `'${e}'`);
    return fail(loc, "literal_error", `Input should be ${quoted.slice(0, -1).join(", ")} or ${quoted.at(-1)}`, value);
  }
  if (schema.type === "string") return typeof value === "string" ? ok(value) : fail(loc, "string_type", "Input should be a valid string", value);
  if (schema.type === "integer") return laxInt(value, loc);
  throw new Error(`unsupported schema at ${loc}`);
}

/** pydantic's input_value: the repr, cut to 25 + 24 UTF-8 bytes when over 50. */
function inputValue(value: unknown): string {
  const text = repr(value);
  const bytes = utf8.encode(text);
  if (bytes.length <= 50) return text;
  const isStart = (i: number) => i >= bytes.length || (bytes[i] & 0xc0) !== 0x80;
  let head = 25;
  while (!isStart(head)) head--;
  let tail = bytes.length - 24;
  while (!isStart(tail)) tail++;
  const decode = (part: Uint8Array) => new TextDecoder().decode(part);
  return `${decode(bytes.slice(0, head))}...${decode(bytes.slice(tail))}`;
}

/** Validated keyword arguments, or ToolError with pydantic's message. Fields
 * are checked in the Python signature's order, which tools-contract.json keeps. */
export function validateArgs(name: string, args: Record<string, unknown>): Record<string, any> {
  const tool = CONTRACT.find(t => t.name === name)!;
  const properties = tool.inputSchema.properties as unknown as Record<string, Schema>;
  const required: string[] = (tool.inputSchema as {required?: string[]}).required ?? [];
  // pre_parse_json: for fields not annotated exactly `str` (a Literal is
  // not), a string that parses as JSON to a list, object or null replaces it.
  const input: Record<string, unknown> = {...args};
  for (const key of Object.keys(input)) {
    const value = input[key];
    const plainStr = properties[key]?.type === "string" && !properties[key].enum;
    if (!Object.hasOwn(properties, key) || plainStr || typeof value !== "string") continue;
    try {
      const parsed = parseJson(value);
      if (parsed === null || (typeof parsed === "object" && !(parsed instanceof PyFloat))) input[key] = parsed;
    } catch {
      // Not JSON; validate the string itself.
    }
  }
  const issues: Issue[] = [];
  const out: Record<string, any> = {};
  for (const key of Object.keys(properties)) {
    const schema = properties[key];
    if (!Object.hasOwn(input, key)) {
      if (required.includes(key)) issues.push({loc: key, type: "missing", msg: "Field required", input});
      else out[key] = schema.default;
      continue;
    }
    const result = validate(input[key], schema, key);
    if (result.ok) out[key] = result.value;
    else issues.push(result.issue);
  }
  for (const key of Object.keys(input)) {
    if (!Object.hasOwn(properties, key)) issues.push({loc: key, type: "extra_forbidden", msg: "Extra inputs are not permitted", input: input[key]});
  }
  if (issues.length) {
    throw new ToolError(`${issues.length} validation error${issues.length > 1 ? "s" : ""} for ${name}Arguments\n`
      + issues.map(i => `${i.loc}\n  ${i.msg} [type=${i.type}, input_value=${inputValue(i.input)}, input_type=${pyType(i.input)}]\n    For further information visit ${PYDANTIC_DOCS}${i.type}`).join("\n"));
  }
  return out;
}
