// Python str behaviors the tools depend on: whitespace (str.isspace, which
// split() and strip() use), splitlines(), sorted(), and lengths and slices
// counted in code points, as Python's str counts them.

const WS = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WS_RUN = new RegExp(`[${WS}]+`);
const EDGES = new RegExp(`^[${WS}]+|[${WS}]+$`, "g");
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;
const SURROGATE = /[\ud800-\udfff]/;
const PAIR = /[\ud800-\udbff][\udc00-\udfff]/g;

/** str.strip() */
export const strip = (text: string) => text.replace(EDGES, "");

/** " ".join(text.split()) */
export const squash = (text: string) => strip(text).split(WS_RUN).filter(Boolean).join(" ");

/** str.splitlines() */
export function splitlines(text: string): string[] {
  if (!text) return [];
  const lines = text.split(LINE_BREAK);
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/** len(text) */
export const cpLen = (text: string) => (SURROGATE.test(text) ? text.length - (text.match(PAIR)?.length ?? 0) : text.length);

/** text[start:end] for 0 <= start <= end, in code points. */
export function cpSlice(text: string, start: number, end?: number): string {
  if (!SURROGATE.test(text)) return text.slice(start, end);
  return [...text].slice(start, end).join("");
}

/** sorted() of strings: by code point. */
export function pySorted(values: Iterable<string>): string[] {
  return [...values].sort((a, b) => {
    const x = [...a];
    const y = [...b];
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      const d = x[i].codePointAt(0)! - y[i].codePointAt(0)!;
      if (d) return d;
    }
    return x.length - y.length;
  });
}

/** re.escape for a JavaScript regular expression with the u flag. */
export const escapeRegex = (text: string) => text.replace(/[\\^$.*+?()[\]{}|/]/g, "\\$&");

/** Python's \w in a str pattern: letters, digits and numerals, underscore. */
export const WORD = "\\p{L}\\p{N}_";

/** Python's \s in a str pattern (str.isspace), as a character class body. */
export const SPACE = WS;

const DIGIT = /^\p{Nd}$/u;

/** The value of one decimal digit (\p{Nd}), any script. */
function digitValue(ch: string): number {
  const cp = ch.codePointAt(0)!;
  let zero = cp;
  while (DIGIT.test(String.fromCodePoint(zero - 1))) zero--;
  return (cp - zero) % 10;
}

/** int(text) for a str, or null where Python raises ValueError. */
export function pyInt(text: string): number | bigint | null {
  const match = /^([+-]?)(\p{Nd}(?:_?\p{Nd})*)$/u.exec(strip(text));
  if (!match) return null;
  let value = 0n;
  for (const ch of match[2]) if (ch !== "_") value = value * 10n + BigInt(digitValue(ch));
  if (match[1] === "-") value = -value;
  return value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : value;
}
