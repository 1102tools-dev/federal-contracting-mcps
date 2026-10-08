// Python behaviors the hosted results depend on, so this Worker answers
// byte for byte like the gsa-perdiem-mcp package it replaces: float values,
// the MCP SDK's indented JSON text, repr() in messages, Python whitespace and
// word characters, urllib.parse.quote, and str.title.

/** A Python float. Plain numbers are Python ints; 51.0 must print as 51.0. */
export class PyFloat {
  constructor(readonly value: number) {}
}

export const float = (value: number) => new PyFloat(value);
export const num = (value: number | PyFloat) => (value instanceof PyFloat ? value.value : value);

// Shortest round-trip digits, as Python and pydantic_core print floats. The
// values here are dollar amounts; exponent forms only matter for huge input.
function floatRepr(value: number): string {
  if (Math.abs(value) >= 1e16) return value.toExponential();
  if (Number.isInteger(value)) return (Object.is(value, -0) ? "-0" : String(value)) + ".0";
  return String(value);
}

/** pydantic_core.to_json(value, indent=2), which the SDK uses for the text content. */
export function dumps(value: unknown, indent = ""): string {
  if (value === null || value === undefined) return "null";
  if (value instanceof PyFloat) return floatRepr(value.value);
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : floatRepr(value);
  if (typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  const inner = indent + "  ";
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return "[\n" + value.map(v => inner + dumps(v, inner)).join(",\n") + "\n" + indent + "]";
  }
  const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== undefined);
  if (!entries.length) return "{}";
  return "{\n" + entries.map(([k, v]) => inner + JSON.stringify(k) + ": " + dumps(v, inner)).join(",\n") + "\n" + indent + "}";
}

/** The same value as plain JSON data (structuredContent). */
export function plain(value: unknown): unknown {
  if (value instanceof PyFloat) return value.value;
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) if (v !== undefined) out[k] = plain(v);
    return out;
  }
  return value;
}

/** JSON.parse that keeps Python's int/float distinction (1.0 stays a float). */
export function loads(text: string): any {
  return (JSON.parse as any)(text, (_key: string, value: unknown, context?: {source?: string}) =>
    typeof value === "number" && context?.source && /[.eE]/.test(context.source) ? new PyFloat(value) : value);
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
  if (value instanceof PyFloat) return floatRepr(value.value);
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : floatRepr(value);
  if (typeof value === "string") return reprString(value);
  if (Array.isArray(value)) return "[" + value.map(repr).join(", ") + "]";
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
