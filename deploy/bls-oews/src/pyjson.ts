// Python-compatible formatting, so results match the Python server (mcp SDK
// 2.0.0) byte for byte: pydantic_core.to_json(indent=2) for tool text,
// repr()/str() for values echoed in messages, and format()/round() for wages.

/** A number Python holds as a float. Serialized with a fraction: 1000.0. */
export class PyFloat {
  readonly value: number;
  constructor(value: number) {
    this.value = value;
  }
}

export type Py = null | boolean | number | bigint | string | PyFloat | Py[] | Map<string, Py> | {[key: string]: Py | undefined};

const num = (x: number | PyFloat) => (x instanceof PyFloat ? x.value : x);

/** Python int str(): every digit, never an exponent. */
export function intStr(n: number | bigint): string {
  return typeof n === "bigint" || Math.abs(n) >= 1e21 ? BigInt(n).toString() : String(n);
}

/** Request JSON parsed the way Python's json module sees it: a number written
 * with a fraction or exponent stays a float (PyFloat, so 2.0 is not 2), and
 * an integer too large for a double keeps every digit (bigint). */
export function parseJson(text: string): unknown {
  const reviver = (_key: string, value: unknown, context?: {source?: string}) => {
    if (typeof value !== "number" || context?.source === undefined) return value;
    if (/[.eE]/.test(context.source)) return new PyFloat(value);
    return Number.isSafeInteger(value) ? value : BigInt(context.source);
  };
  return JSON.parse(text, reviver as (key: string, value: unknown) => unknown);
}

/** type(value).__name__ for a value parsed from JSON. */
export function pyType(value: unknown): string {
  if (value === null || value === undefined) return "NoneType";
  if (typeof value === "boolean") return "bool";
  if (typeof value === "bigint") return "int";
  if (value instanceof PyFloat) return "float";
  if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
  if (typeof value === "string") return "str";
  return Array.isArray(value) ? "list" : "dict";
}

function shortest(x: number): {sign: string; digits: string; exp: number} {
  // toExponential() without an argument gives the shortest round-trip digits.
  const [mantissa, exp] = Math.abs(x).toExponential().split("e");
  return {sign: x < 0 || Object.is(x, -0) ? "-" : "", digits: mantissa.replace(".", ""), exp: Number(exp)};
}

function fixedFromDigits(digits: string, exp: number): string {
  if (exp >= 0) return `${digits.slice(0, exp + 1).padEnd(exp + 1, "0")}.${digits.slice(exp + 1) || "0"}`;
  return `0.${"0".repeat(-exp - 1)}${digits}`;
}

/** Python float repr()/str(): 1.8, 2.0, 1e-05, 1e+16, nan, inf. */
export function floatRepr(value: number | PyFloat): string {
  const x = num(value);
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const {sign, digits, exp} = shortest(x);
  if (exp < -4 || exp >= 16) {
    const mantissa = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    return `${sign}${mantissa}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  return sign + fixedFromDigits(digits, exp);
}

/** A float as pydantic_core writes it in JSON (repr, except 1e-05 is 0.00001 and 1.5e-07 is 1.5e-7). */
function floatJson(x: number): string {
  if (Number.isNaN(x)) return "NaN";
  if (!Number.isFinite(x)) return x > 0 ? "Infinity" : "-Infinity";
  if (x !== 0 && Math.abs(x) < 1e-4) {
    const {sign, digits, exp} = shortest(x);
    if (exp === -5) return sign + fixedFromDigits(digits, exp);
    return `${sign}${digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits}e${exp}`;
  }
  return floatRepr(x);
}

/** format(x, f".{places}f"): correctly rounded, exact ties to even (JS toFixed rounds them up). */
export function fixed(value: number | PyFloat, places: number): string {
  const x = num(value);
  if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const sign = x < 0 || Object.is(x, -0) ? "-" : "";
  const exact = Math.abs(x).toFixed(Math.min(100, places + 60));
  const dot = exact.indexOf(".");
  if (!/^50*$/.test(exact.slice(dot + 1 + places))) return sign + Math.abs(x).toFixed(places);
  let kept = BigInt(exact.slice(0, dot) + exact.slice(dot + 1, dot + 1 + places));
  if (kept % 2n === 1n) kept += 1n;
  const digits = kept.toString().padStart(places + 1, "0");
  return sign + (places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits);
}

/** round(x, places) for a float. */
export const round = (x: number, places: number) => Number(fixed(x, places));

/** Thousands separators, as in f"{n:,}" and f"{x:,.2f}". */
export function group(text: string): string {
  const [whole, fraction] = text.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const grouped = whole.slice(sign.length).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return sign + grouped + (fraction === undefined ? "" : `.${fraction}`);
}

// str.isspace() characters, which str.strip() removes. JS trim() differs
// (it strips U+FEFF but not U+001C..U+001F or U+0085).
const PY_SPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0                　";

/** str.strip() with no arguments. */
export function strip(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && PY_SPACE.includes(text[start])) start++;
  while (end > start && PY_SPACE.includes(text[end - 1])) end--;
  return text.slice(start, end);
}

const UNPRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

function strRepr(text: string): string {
  const quote = text.includes("'") && !text.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if (ch === quote || ch === "\\") out += "\\" + ch;
    else if (ch === "\t") out += "\\t";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (code < 0x20 || code === 0x7f) out += "\\x" + code.toString(16).padStart(2, "0");
    else if (code < 0x7f || ch === " " || !UNPRINTABLE.test(ch)) out += ch;
    else if (code < 0x100) out += "\\x" + code.toString(16).padStart(2, "0");
    else if (code < 0x10000) out += "\\u" + code.toString(16).padStart(4, "0");
    else out += "\\U" + code.toString(16).padStart(8, "0");
  }
  return out + quote;
}

/** repr() of a value parsed from JSON: 'x', 51, 1.8, True, None, ['a'], {'k': 1}. */
export function repr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (value instanceof PyFloat) return floatRepr(value);
  if (typeof value === "bigint") return intStr(value);
  if (typeof value === "number") return Number.isInteger(value) ? intStr(value) : floatRepr(value);
  if (typeof value === "string") return strRepr(value);
  if (Array.isArray(value)) return `[${value.map(repr).join(", ")}]`;
  const entries = value instanceof Map ? [...value.entries()] : Object.entries(value as object);
  return `{${entries.map(([k, v]) => `${strRepr(k)}: ${repr(v)}`).join(", ")}}`;
}

/** str() of an argument value (a string stays as is). */
export const str = (value: unknown): string => (typeof value === "string" ? value : repr(value));

function write(value: Py | undefined, indent: number | undefined, pad: string): string {
  if (value === null || value === undefined) return "null";
  if (value instanceof PyFloat) return floatJson(value.value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "bigint") return intStr(value);
  if (typeof value === "number") return Number.isInteger(value) ? intStr(value) : floatJson(value);
  if (typeof value === "string") return JSON.stringify(value);
  const inner = indent === undefined ? "" : pad + " ".repeat(indent);
  const open = indent === undefined ? "" : "\n" + inner;
  const close = indent === undefined ? "" : "\n" + pad;
  const sep = indent === undefined ? "," : ",\n" + inner;
  const colon = indent === undefined ? ":" : ": ";
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return `[${open}${value.map(item => write(item, indent, inner)).join(sep)}${close}]`;
  }
  const entries = (value instanceof Map ? [...value.entries()] : Object.entries(value)).filter(([, v]) => v !== undefined);
  if (!entries.length) return "{}";
  return `{${open}${entries.map(([k, v]) => JSON.stringify(k) + colon + write(v, indent, inner)).join(sep)}${close}}`;
}

/** JSON as pydantic_core.to_json writes it (indent 2 for tool text; compact without indent). */
export const dumps = (value: Py, indent?: number) => write(value, indent, "");
