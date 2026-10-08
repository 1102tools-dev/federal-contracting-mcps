// Tool argument validation as the Python server does it: the MCP SDK's
// pre_parse_json, then the pydantic argument model built from each tool's
// signature (lax mode, extra="forbid"). Failures carry pydantic's exact
// ValidationError text, which the SDK reports as the tool error.
import {PyFloat, isDict, loads, repr} from "./py.ts";

type Kind = "str" | "str?" | "int" | "int?" | "locations";
type Signature = [name: string, kind: Kind][];

// Parameters in Python signature order (server.py).
export const SIGNATURES: Record<string, Signature> = {
  get_data_status: [],
  lookup_city_perdiem: [["city", "str"], ["state", "str"], ["fiscal_year", "int?"], ["county", "str?"]],
  lookup_zip_perdiem: [["zip_code", "str"], ["fiscal_year", "int?"], ["county", "str?"]],
  lookup_state_rates: [["state", "str"], ["fiscal_year", "int?"]],
  get_mie_breakdown: [["fiscal_year", "int?"]],
  estimate_travel_cost: [
    ["city", "str"], ["state", "str"], ["num_nights", "int"], ["travel_month", "str?"],
    ["fiscal_year", "int?"], ["county", "str?"],
  ],
  compare_locations: [["locations", "locations"], ["fiscal_year", "int?"]],
};

/** A Python int after validation: a number, or a bigint beyond 2**53. */
export type PyInt = number | bigint;

const MESSAGES: Record<string, string> = {
  missing: "Field required",
  extra_forbidden: "Extra inputs are not permitted",
  string_type: "Input should be a valid string",
  int_type: "Input should be a valid integer",
  int_parsing: "Input should be a valid integer, unable to parse string as an integer",
  int_from_float: "Input should be a valid integer, got a number with a fractional part",
  int_parsing_size: "Unable to parse input string as an integer, exceeded maximum size",
  finite_number: "Input should be a finite number",
  list_type: "Input should be a valid list",
  dict_type: "Input should be a valid dictionary",
};

interface LineError {loc: (string | number)[]; type: string; input: unknown}

class Invalid extends Error {
  readonly type: string;
  constructor(type: string) {
    super(type);
    this.type = type;
  }
}

/** pydantic's ValidationError; its message is str(ValidationError). */
export class ArgumentError extends Error {}

function typeName(value: unknown): string {
  if (value === null || value === undefined) return "NoneType";
  if (typeof value === "boolean") return "bool";
  if (typeof value === "string") return "str";
  if (value instanceof PyFloat) return "float";
  if (typeof value === "number" || typeof value === "bigint") return "int";
  if (Array.isArray(value)) return "list";
  return "dict";
}

const utf8 = new TextEncoder();
const fromUtf8 = new TextDecoder();

// pydantic_core truncates input reprs longer than 50 bytes to the first 25
// and last 24 bytes, moved inward to character boundaries.
function inputRepr(value: unknown): string {
  const text = repr(value);
  const bytes = utf8.encode(text);
  if (bytes.length <= 50) return text;
  let head = 25;
  while (head > 0 && (bytes[head] & 0xc0) === 0x80) head--;
  let tail = bytes.length - 24;
  while (tail < bytes.length && (bytes[tail] & 0xc0) === 0x80) tail++;
  return fromUtf8.decode(bytes.subarray(0, head)) + "..." + fromUtf8.decode(bytes.subarray(tail));
}

function render(title: string, errors: LineError[]): string {
  const lines = [`${errors.length} validation error${errors.length === 1 ? "" : "s"} for ${title}`];
  for (const e of errors) {
    lines.push(e.loc.join("."));
    lines.push(`  ${MESSAGES[e.type]} [type=${e.type}, input_value=${inputRepr(e.input)}, input_type=${typeName(e.input)}]`);
    lines.push(`    For further information visit https://errors.pydantic.dev/2.13/v/${e.type}`);
  }
  return lines.join("\n");
}

// Rust's char::is_whitespace, which pydantic_core strips before parsing ints.
const RUST_EDGES = /^[\t\n\v\f\r \x85\xa0  -     　]+|[\t\n\v\f\r \x85\xa0  -     　]+$/g;
const INT_TEXT = /^([+-]?)(\d(?:_?\d)*)(?:\.0+)?$/;
const I64 = 2 ** 63;

function exactInt(value: bigint): PyInt {
  return value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value;
}

/** pydantic's lax int validation. */
function toInt(value: unknown): PyInt {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number" || typeof value === "bigint") return value;
  if (value instanceof PyFloat) {
    const v = value.value;
    if (!Number.isFinite(v)) throw new Invalid("finite_number");
    if (!Number.isInteger(v)) throw new Invalid("int_from_float");
    if (Math.abs(v) >= I64) throw new Invalid("int_parsing_size");
    return v === 0 ? 0 : v;
  }
  if (typeof value === "string") {
    const text = value.replace(RUST_EDGES, "");
    if (utf8.encode(text).length > 4300) throw new Invalid("int_parsing_size");
    const match = INT_TEXT.exec(text);
    if (!match) throw new Invalid("int_parsing");
    const parsed = BigInt(match[2].replaceAll("_", ""));
    return exactInt(match[1] === "-" ? -parsed : parsed);
  }
  throw new Invalid("int_type");
}

function toStr(value: unknown): string {
  if (typeof value !== "string") throw new Invalid("string_type");
  return value;
}

function preParse(kinds: Map<string, Kind>, args: Record<string, unknown>): Record<string, unknown> {
  const out = {...args};
  for (const [key, value] of Object.entries(args)) {
    // pre_parse_json skips fields annotated exactly `str`.
    if (!kinds.has(key) || kinds.get(key) === "str" || typeof value !== "string") continue;
    let parsed: unknown;
    try {
      parsed = loads(value, {bigints: true});
    } catch {
      continue;
    }
    if (typeof parsed === "string" || typeof parsed === "number" || typeof parsed === "bigint" ||
        typeof parsed === "boolean" || parsed instanceof PyFloat) continue;
    out[key] = parsed;
  }
  return out;
}

/** Validated keyword arguments, in signature order, or ArgumentError. */
export function validateArguments(tool: string, raw: Record<string, unknown>): Record<string, any> {
  const signature = SIGNATURES[tool];
  const kinds = new Map(signature);
  const args = preParse(kinds, raw);
  const errors: LineError[] = [];
  const out: Record<string, any> = {};
  for (const [name, kind] of signature) {
    if (!Object.hasOwn(args, name)) {
      if (kind === "str" || kind === "int" || kind === "locations") errors.push({loc: [name], type: "missing", input: args});
      else out[name] = null;
      continue;
    }
    const value = args[name];
    try {
      if (kind === "locations") {
        out[name] = validateLocations(name, value, errors);
      } else if (value === null && (kind === "str?" || kind === "int?")) {
        out[name] = null;
      } else {
        out[name] = kind.startsWith("str") ? toStr(value) : toInt(value);
      }
    } catch (error) {
      if (!(error instanceof Invalid)) throw error;
      errors.push({loc: [name], type: error.type, input: value});
    }
  }
  for (const [key, value] of Object.entries(args)) {
    if (!kinds.has(key)) errors.push({loc: [key], type: "extra_forbidden", input: value});
  }
  if (errors.length) throw new ArgumentError(render(`${tool}Arguments`, errors));
  return out;
}

function validateLocations(name: string, value: unknown, errors: LineError[]): Record<string, string>[] {
  if (!Array.isArray(value)) throw new Invalid("list_type");
  const out: Record<string, string>[] = [];
  value.forEach((item, i) => {
    if (!isDict(item)) {
      errors.push({loc: [name, i], type: "dict_type", input: item});
      return;
    }
    const entry: Record<string, string> = {};
    for (const [key, v] of Object.entries(item)) {
      if (typeof v === "string") entry[key] = v;
      else errors.push({loc: [name, i, key], type: "string_type", input: v});
    }
    out.push(entry);
  });
  return out;
}
