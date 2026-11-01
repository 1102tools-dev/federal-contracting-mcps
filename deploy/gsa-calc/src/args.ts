// Tool argument validation as the Python server does it: the MCP SDK's
// pre_parse_json, then the pydantic argument model built from each tool's
// signature (lax mode, extra="forbid", smart unions, Literal enums, and the
// BeforeValidator that refuses booleans for SIN arguments). Failures carry
// pydantic's exact ValidationError text, which the SDK reports as the tool error.
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {PyFloat, parseJson, pyType, repr} from "./pyjson.ts";

/** Deliberate tool errors (Python exceptions): "Error executing tool <name>: <message>". */
export class ToolError extends Error {}

/** Not answerable from the copy: the Worker sends the original request to the Python server. */
export class Forward extends Error {}

type Schema = {type?: string; enum?: string[]; anyOf?: Schema[]; default?: unknown};
type Issue = {loc: string; type: string; msg: string; input: unknown};
type Result = {ok: true; value: unknown} | {ok: false; issues: Issue[]};

/** A Python int after validation: a number, or a bigint beyond 2**53. */
export type PyInt = number | bigint;

// Each tool's parameters in its Python signature's order (pydantic reports
// errors in that order; tools-contract.json lists them alphabetically).
const FILTERS = ["education_level", "experience_min", "experience_max", "price_min", "price_max", "business_size"];
const SIGNATURES: Record<string, string[]> = {
  keyword_search: ["keyword", ...FILTERS, "security_clearance", "sin", "worksite", "page", "page_size", "ordering", "sort", "exclude"],
  exact_search: ["field", "value", ...FILTERS, "page", "page_size", "ordering", "sort"],
  suggest_contains: ["field", "term"],
  filtered_browse: [...FILTERS, "security_clearance", "sin", "worksite", "page", "page_size", "ordering", "sort"],
  igce_benchmark: ["labor_category", "education_level", "experience_min", "experience_max", "business_size", "sin", "security_clearance"],
  price_reasonableness_check: ["labor_category", "proposed_rate", "education_level", "experience_min", "experience_max", "business_size", "sin", "security_clearance"],
  vendor_rate_card: ["vendor_name", "page", "page_size", "ordering", "sort"],
  sin_analysis: ["sin_code", "page_size"],
};
// Fields annotated with BeforeValidator(_reject_bool_pre) (SinInput and sin_code).
const REJECT_BOOL = new Set(["sin", "sin_code"]);
const REJECT_BOOL_MESSAGE = (value: boolean) =>
  `Value error, Expected a string or int, not a boolean. Got ${value ? "True" : "False"}. This usually means the caller passed the wrong argument type.`;

const PYDANTIC_DOCS = "https://errors.pydantic.dev/2.13/v/";
const I64 = 2 ** 63;
// Rust's char::is_whitespace, which pydantic_core strips before parsing a number.
const RUST_EDGES = /^[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
const INT_TEXT = /^([+-]?)(\d(?:_?\d)*)(?:\.0+)?$/;
// Rust's f64 FromStr grammar, which pydantic_core uses for strings.
const FLOAT_TEXT = /^[+-]?(?:inf|infinity|nan|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)$/i;
const SHORT: Record<string, string> = {string: "str", integer: "int", boolean: "bool", number: "float"};
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

/** Rust's f64 parse of a string, or null where it fails. */
function rustFloat(text: string): number | null {
  if (!FLOAT_TEXT.test(text)) return null;
  const body = text.replace(/^[+-]/, "").toLowerCase();
  if (body === "nan") return NaN;
  if (body === "inf" || body === "infinity") return text.startsWith("-") ? -Infinity : Infinity;
  return Number(text);
}

/** pydantic's lax float (a validated float is a plain number; the tools format it as one). Strings
 * parse after trimming, else with underscores removed (none leading, trailing or doubled). */
function laxFloat(value: unknown, loc: string): Result {
  if (typeof value === "boolean") return ok(value ? 1 : 0);
  if (value instanceof PyFloat) return ok(value.value);
  if (typeof value === "number") return ok(value);
  if (typeof value === "bigint") return ok(Number(value));
  if (typeof value === "string") {
    let parsed = rustFloat(value.replace(RUST_EDGES, ""));
    if (parsed === null && !value.startsWith("_") && !value.endsWith("_") && !value.includes("__")) parsed = rustFloat(value.replaceAll("_", ""));
    return parsed === null ? fail(loc, "float_parsing", "Input should be a valid number, unable to parse string as a number", value) : ok(parsed);
  }
  return fail(loc, "float_type", "Input should be a valid number", value);
}

/** Literal[...]: one of the listed strings. */
function literal(value: unknown, choices: string[], loc: string): Result {
  if (typeof value === "string" && choices.includes(value)) return ok(value);
  const quoted = choices.map(c => `'${c}'`);
  const expected = quoted.length > 1 ? `${quoted.slice(0, -1).join(", ")} or ${quoted.at(-1)}` : quoted[0];
  return fail(loc, "literal_error", `Input should be ${expected}`, value);
}

function validate(value: unknown, schema: Schema, loc: string): Result {
  if (schema.anyOf) {
    // Optional[...] takes None; the rest is reported under the field's own
    // name when one type is left, else as a smart union (key.str, key.int).
    if (value === null && schema.anyOf.some(s => s.type === "null")) return ok(null);
    const members = schema.anyOf.filter(s => s.type !== "null");
    if (members.length === 1) return validate(value, members[0], loc);
    // str | int: an exact type wins, then lax int (whole floats).
    if (typeof value === "string") return ok(value);
    const issues: Issue[] = [];
    for (const member of members) {
      const result = validate(value, member, `${loc}.${SHORT[member.type!]}`);
      if (result.ok) return result;
      issues.push(...result.issues);
    }
    return {ok: false, issues};
  }
  if (schema.enum) return literal(value, schema.enum, loc);
  if (schema.type === "string") return typeof value === "string" ? ok(value) : fail(loc, "string_type", "Input should be a valid string", value);
  if (schema.type === "integer") return laxInt(value, loc);
  if (schema.type === "number") return laxFloat(value, loc);
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
  // pre_parse_json: for fields not annotated exactly `str` (Literal and
  // Optional fields included), a string that parses as JSON to a list,
  // object or null replaces it.
  const input: Record<string, unknown> = {...args};
  for (const key of Object.keys(input)) {
    const value = input[key];
    const schema = properties[key];
    const plainStr = schema?.type === "string" && !schema.enum;
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
    if (REJECT_BOOL.has(key) && typeof input[key] === "boolean") {
      issues.push({loc: key, type: "value_error", msg: REJECT_BOOL_MESSAGE(input[key] as boolean), input: input[key]});
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
