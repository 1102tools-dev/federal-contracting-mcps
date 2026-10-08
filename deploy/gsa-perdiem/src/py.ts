// Python behaviors the hosted results depend on, so this Worker answers
// byte for byte like the gsa-perdiem-mcp package it replaces: float values,
// the MCP SDK's indented JSON text, repr() in messages, Python whitespace and
// word characters, urllib.parse.quote, and str.title.

/** A Python float. Plain numbers are Python ints; 51.0 must print as 51.0. */
export class PyFloat {
  readonly value: number;
  constructor(value: number) {
    this.value = value;
  }
}

export const float = (value: number) => new PyFloat(value);
export const num = (value: unknown): number =>
  value instanceof PyFloat ? value.value : typeof value === "bigint" ? Number(value) : (value as number);
export const isFloat = (value: unknown): value is PyFloat => value instanceof PyFloat;
/** A Python dict: a plain object, never a list, None, or a float. */
export const isDict = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value) && !(value instanceof PyFloat) && !(value instanceof Map);

/** Python arithmetic: int op int stays int; a float on either side gives a float. */
export const add = (a: unknown, b: unknown) => wrap(num(a) + num(b), a, b);
export const mul = (a: unknown, b: unknown) => wrap(num(a) * num(b), a, b);
const wrap = (value: number, a: unknown, b: unknown) => (isFloat(a) || isFloat(b) ? float(value) : value);

/** Python's float formatting: pydantic_core JSON (json = true) or repr()/str(). */
function floatText(value: number, json: boolean): string {
  if (Number.isNaN(value)) return json ? "null" : "nan";
  if (!Number.isFinite(value)) return json ? "null" : value > 0 ? "inf" : "-inf";
  if (value === 0) return Object.is(value, -0) ? "-0.0" : "0.0";
  const [mantissa, exponentText] = value.toExponential().split("e");
  const exponent = Number(exponentText);
  if (exponent >= 16) return `${mantissa}e+${json ? exponent : String(exponent).padStart(2, "0")}`;
  if (!json && exponent < -4) return `${mantissa}e-${String(-exponent).padStart(2, "0")}`;
  const text = String(value);
  return Number.isInteger(value) ? text + ".0" : text;
}

/** str() / repr() of a Python number. */
export function numStr(value: unknown): string {
  if (value instanceof PyFloat) return floatText(value.value, false);
  if (typeof value === "bigint") return String(value);
  return Number.isInteger(value) ? String(value) : floatText(value as number, false);
}

/**
 * pydantic_core.to_json(value, indent=2), which the SDK uses for the text
 * content; with indent null, the same value as compact JSON. Maps are dicts
 * whose key order must survive (JavaScript objects move integer-like keys).
 */
export function dumps(value: unknown, indent: string | null = ""): string {
  if (value === null || value === undefined) return "null";
  if (value instanceof PyFloat) return floatText(value.value, true);
  if (typeof value === "bigint") return String(value);
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : floatText(value, true);
  if (typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  const inner = indent === null ? null : indent + "  ";
  const open = inner === null ? "" : "\n" + inner;
  const sep = inner === null ? "," : ",\n" + inner;
  const close = inner === null ? "" : "\n" + indent;
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return "[" + open + value.map(v => dumps(v, inner)).join(sep) + close + "]";
  }
  const entries = (value instanceof Map ? [...value.entries()] : Object.entries(value as object))
    .filter(([, v]) => v !== undefined);
  if (!entries.length) return "{}";
  const colon = inner === null ? ":" : ": ";
  return "{" + open + entries.map(([k, v]) => JSON.stringify(String(k)) + colon + dumps(v, inner)).join(sep) + close + "}";
}

/** The same value as plain JSON data. */
export function plain(value: unknown): unknown {
  if (value instanceof PyFloat) return value.value;
  if (typeof value === "bigint") return Number(value);
  if (Array.isArray(value)) return value.map(plain);
  if (value instanceof Map) return plain(Object.fromEntries(value));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) if (v !== undefined) out[k] = plain(v);
    return out;
  }
  return value;
}

/**
 * JSON.parse that keeps Python's int/float distinction (1.0 stays a float).
 * With bigints, integers beyond 2**53 stay exact, as Python ints do.
 */
export function loads(text: string, options: {bigints?: boolean} = {}): any {
  return (JSON.parse as any)(text, (_key: string, value: unknown, context?: {source?: string}) => {
    if (typeof value !== "number" || !context?.source) return value;
    if (/[.eE]/.test(context.source)) return new PyFloat(value);
    if (options.bigints && !Number.isSafeInteger(value)) return BigInt(context.source);
    return value;
  });
}

/** Python's round(x, 2): the double nearest the decimal rounded half to even. */
export function round2(value: number): PyFloat {
  if (!Number.isFinite(value) || Math.abs(value) >= 1e15) return float(value);
  const [whole, fraction] = Math.abs(value).toFixed(100).split(".");
  let scaled = BigInt(whole + fraction.slice(0, 2));
  const rest = fraction.slice(2).replace(/0+$/, "");
  if (rest > "5" || (rest === "5" && scaled % 2n === 1n)) scaled += 1n;
  const rounded = Number(scaled) / 100;
  return float(value < 0 || Object.is(value, -0) ? -rounded : rounded);
}

/** Python's sort order for strings: by code point. */
export function cmp(a: string, b: string): number {
  const x = [...a];
  const y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
    if (d) return d;
  }
  return x.length - y.length;
}

// Python's str.isspace() set, which \s and strip() use.
const WS = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
export const WS_RUN = new RegExp(`[${WS}]+`, "g");
const EDGES = new RegExp(`^[${WS}]+|[${WS}]+$`, "g");
export const strip = (s: string) => s.replace(EDGES, "");
/** re.sub(r"\s+", " ", s).strip() */
export const squash = (s: string) => strip(s.replace(WS_RUN, " "));
/** Python's \w: letters, digits and numerals, underscore. */
export const WORD = "[\\p{L}\\p{N}_]";

/** Length in code points, as Python's len(). */
export const pyLen = (s: string) => [...s].length;
export const pySlice = (s: string, end: number) => [...s].slice(0, end).join("");

const PRINTABLE_EXCLUDED = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

function reprString(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const code = ch.codePointAt(0)!;
    if (ch === "\\") out += "\\\\";
    else if (ch === quote) out += "\\" + ch;
    else if (ch === "\t") out += "\\t";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (code < 0x20 || code === 0x7f) out += "\\x" + code.toString(16).padStart(2, "0");
    else if (code < 0x7f || ch === " " || !PRINTABLE_EXCLUDED.test(ch)) out += ch;
    else if (code <= 0xff) out += "\\x" + code.toString(16).padStart(2, "0");
    else if (code <= 0xffff) out += "\\u" + code.toString(16).padStart(4, "0");
    else out += "\\U" + code.toString(16).padStart(8, "0");
  }
  return out + quote;
}

/** repr() of a JSON-shaped value. */
export function repr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (value instanceof PyFloat || typeof value === "number" || typeof value === "bigint") return numStr(value);
  if (typeof value === "string") return reprString(value);
  if (Array.isArray(value)) return "[" + value.map(repr).join(", ") + "]";
  if (value instanceof Map) return "{" + [...value].map(([k, v]) => repr(k) + ": " + repr(v)).join(", ") + "}";
  return "{" + Object.entries(value as object).map(([k, v]) => repr(k) + ": " + repr(v)).join(", ") + "}";
}

/** urllib.parse.quote(s, safe=""). */
export function quote(s: string): string {
  return encodeURIComponent(s).replace(/[!'()*]/g, c => "%" + c.charCodeAt(0).toString(16).toUpperCase());
}

/** urllib.parse.quote_plus(s). */
export const quotePlus = (s: string) => quote(s).replace(/%20/g, "+");

const CASED = /[\p{Lu}\p{Ll}\p{Lt}]/u;

/** str.title(). */
export function title(s: string): string {
  let out = "";
  let previousCased = false;
  for (const ch of s) {
    out += previousCased ? ch.toLowerCase() : ch.toUpperCase();
    previousCased = CASED.test(ch);
  }
  return out;
}
