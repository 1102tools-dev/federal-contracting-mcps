// Tool argument validation as the Python server does it: the MCP SDK's
// pre_parse_json, then the pydantic argument model built from each tool's
// signature (lax mode, extra="forbid", smart unions). Failures carry
// pydantic's exact ValidationError text, which the SDK reports as the tool error.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {PyFloat, parseJson, pyType, repr} from "./pyjson.ts";

/** Deliberate tool errors (Python exceptions): "Error executing tool <name>: <message>". */
export class ToolError extends Error {}

/** Not answerable from the copy: the Worker sends the original request to the Python server. */
export class Forward extends Error {}

type Schema = {type?: string; anyOf?: Schema[]; default?: unknown};
type Issue = {loc: string; type: string; msg: string; input: unknown};
type Result = {ok: true; value: unknown} | {ok: false; issues: Issue[]};

/** A Python int after validation: a number, or a bigint beyond 2**53. */
export type PyInt = number | bigint;

// Each tool's parameters in its Python signature's order (pydantic reports
// errors in that order; tools-contract.json lists some differently).
const SIGNATURES: Record<string, string[]> = {
  get_latest_date: ["title_number"],
  get_cfr_content: ["title_number", "date", "part", "subpart", "section", "chapter", "appendix", "raw_xml", "page"],
  get_cfr_structure: ["title_number", "date", "chapter", "subchapter", "part", "subpart", "appendix", "depth"],
  get_ancestry: ["title_number", "date", "part", "section", "appendix", "subpart"],
  list_agencies: ["summary_only"],
  lookup_far_clause: ["section_id", "chapter", "date", "page"],
  list_sections_in_part: ["part_number", "chapter", "title_number", "date", "subpart", "detail", "page"],
  find_far_definition: ["term", "date", "max_matches"],
};

const PYDANTIC_DOCS = "https://errors.pydantic.dev/2.13/v/";
const I64 = 2 ** 63;
// Rust's char::is_whitespace, which pydantic_core strips before parsing an int.
const RUST_EDGES = /^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
const INT_TEXT = /^([+-]?)(\d(?:_?\d)*)(?:\.0+)?$/;
const TRUE_TEXT = new Set(["1", "on", "t", "true", "y", "yes"]);
const FALSE_TEXT = new Set(["0", "off", "f", "false", "n", "no"]);
const SHORT: Record<string, string> = {string: "str", integer: "int", boolean: "bool"};
const utf8 = new TextEncoder();

const ok = (value: unknown): Result => ({ok: true, value});
const fail = (loc: string, type: string, msg: string, input: unknown): Result => ({ok: false, issues: [{loc, type, msg, input}]});
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

/** pydantic's lax bool: 0/1, whole 0.0/1.0, and yes/no style strings (any case). */
function laxBool(value: unknown, loc: string): Result {
  const unsure = () => fail(loc, "bool_parsing", "Input should be a valid boolean, unable to interpret input", value);
  if (typeof value === "boolean") return ok(value);
  if (typeof value === "string") {
    const text = value.toLowerCase();
    return TRUE_TEXT.has(text) ? ok(true) : FALSE_TEXT.has(text) ? ok(false) : unsure();
  }
  if (typeof value === "bigint") return unsure();
  if (typeof value === "number" || value instanceof PyFloat) {
    const f = value instanceof PyFloat ? value.value : value;
    if (!Number.isInteger(f)) return fail(loc, "bool_type", "Input should be a valid boolean", value);
    return f === 0 ? ok(false) : f === 1 ? ok(true) : unsure();
  }
  return fail(loc, "bool_type", "Input should be a valid boolean", value);
}

function validate(value: unknown, schema: Schema, loc: string): Result {
  if (schema.anyOf) {
    // Optional[...] takes None; the rest is reported under the field's own
    // name when one type is left, else as a smart union (key.str, key.int).
    if (value === null && schema.anyOf.some(s => s.type === "null")) return ok(null);
    const members = schema.anyOf.filter(s => s.type !== "null");
    if (members.length === 1) return validate(value, members[0], loc);
    // str | int: an exact type wins, then lax int (bools and whole floats).
    if (typeof value === "string") return ok(value);
    const issues: Issue[] = [];
    for (const member of members) {
      const result = validate(value, member, `${loc}.${SHORT[member.type!]}`);
      if (result.ok) return result;
      issues.push(...result.issues);
    }
    return {ok: false, issues};
  }
  if (schema.type === "string") return typeof value === "string" ? ok(value) : fail(loc, "string_type", "Input should be a valid string", value);
  if (schema.type === "integer") return laxInt(value, loc);
  if (schema.type === "boolean") return laxBool(value, loc);
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

/** Validated keyword arguments, or ToolError with pydantic's message. */
export function validateArgs(name: string, args: Record<string, unknown>): Record<string, any> {
  const tool = CONTRACT.find(t => t.name === name)!;
  const properties = tool.inputSchema.properties as unknown as Record<string, Schema>;
  const required: string[] = (tool.inputSchema as {required?: string[]}).required ?? [];
  // pre_parse_json: for fields not annotated exactly `str`, a string that
  // parses as JSON to a list, object or null replaces it.
  const input: Record<string, unknown> = {...args};
  for (const key of Object.keys(input)) {
    const value = input[key];
    const plainStr = properties[key]?.type === "string";
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
  for (const key of SIGNATURES[name]) {
    const schema = properties[key];
    if (!Object.hasOwn(input, key)) {
      if (required.includes(key)) issues.push({loc: key, type: "missing", msg: "Field required", input});
      else out[key] = schema.default;
      continue;
    }
    const result = validate(input[key], schema, key);
    if (result.ok) out[key] = result.value;
    else issues.push(...result.issues);
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
