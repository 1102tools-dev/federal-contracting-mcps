// The Python server's input checks (server.py, "Input validators"), with the
// same messages and order, so a bad argument gets the same answer here as
// from the container. Values arrive as pydantic left them (args.ts): strings,
// ints (number or bigint), floats (plain numbers) or null.
import {ToolError, type PyInt} from "./args.ts";
import {floatRepr, intStr, repr} from "./pyjson.ts";
import {cpLen, strip} from "./text.ts";

export const MAX_PAGE_SIZE = 500;
// price_reasonableness_check gives no high/low verdict below this many rates.
export const LOW_SAMPLE_MIN_RATES = 20;
export const EDUCATION_LEVELS: Record<string, string> = {
  AA: "Associate's",
  BA: "Bachelor's",
  HS: "High School",
  MA: "Master's",
  PHD: "Doctorate",
  TEC: "Technical/Vocational",
};
export const ORDERING_FIELDS = ["current_price", "labor_category", "vendor_name", "education_level", "min_years_experience",
  "next_year_price", "idv_piid", "business_size"];
// GSA CALC is backed by Elasticsearch with a 10,000-result window.
const ES_MAX_WINDOW = 10_000;

// Only these patterns trigger GSA CALC+'s firewall (live-verified in 0.2.1).
const WAF_PATTERNS: [RegExp, string][] = [
  [/\.\.\//u, "path traversal ('../')"],
  [/<[a-z/]/iu, "HTML angle brackets"],
  [/\x00/u, "null byte"],
];
const CONTROL_CHARS = /[\x00-\x1f\x7f]/;

export const fail = (message: string): never => {
  throw new ToolError(message);
};

/** str() of a validated number: a float prints as one (5.0), an int as digits. */
export const showFloat = (value: number) => floatRepr(value);
const showInt = (value: PyInt) => intStr(value);

export function validateNoControlChars(value: unknown, field: string): void {
  if (typeof value === "string" && CONTROL_CHARS.test(value)) {
    fail(`${field}=${repr(value)} contains control characters (null byte / newline / tab / CR / backspace). These typically come `
      + "from copy-paste artifacts and cause silent zero-result queries. Remove them and retry.");
  }
}

export function validateWafSafe(value: string | null, field: string): string | null {
  if (value === null) return null;
  for (const [pattern, description] of WAF_PATTERNS) {
    if (pattern.test(value)) {
      fail(`${field}=${repr(value)} contains characters that trigger GSA CALC+'s web application firewall (${description}). Remove the offending `
        + "characters and try again (empirically: quotes, SQL keywords, angle brackets, path traversal, semicolons all trigger 403/503).");
    }
  }
  return value;
}

/** _validate_finite for a float field (ints pass unchanged). */
export function validateFiniteFloat(value: number | null, field: string): number | null {
  if (value === null) return null;
  if (!Number.isFinite(value)) {
    fail(`${field} must be a finite number. Got ${floatRepr(value)}. NaN/Inf reach the API URL-encoded and return HTTP 406.`);
  }
  return value;
}

export function clampTextLen(value: string | null, field: string, maximum = 500): string | null {
  if (value === null) return null;
  const length = cpLen(value);
  if (length > maximum) fail(`${field} exceeds ${maximum} chars (${length}). Very long strings trigger HTTP 406 URI-too-long errors from GSA.`);
  return value;
}

/** _strip_or_none */
export function stripOrNone(value: string | null): string | null {
  if (value === null) return null;
  return strip(value) || null;
}

export function clamp(value: PyInt, field: string, lo: number, hi: number): number {
  if (value < lo) fail(`${field} must be >= ${lo}. Got ${showInt(value)}.`);
  if (value > hi) fail(`${field} exceeds maximum of ${hi}. Got ${showInt(value)}. Paginate instead.`);
  return Number(value);
}

export function validateEsWindow(page: number, pageSize: number): void {
  if (page * pageSize > ES_MAX_WINDOW) {
    fail(`page (${page}) * page_size (${pageSize}) = ${page * pageSize} exceeds GSA CALC+'s 10,000-result Elasticsearch window. Narrow your search `
      + "with filters (education_level, sin, price_range) to get under 10k results, or use suggest_contains() to find exact vendor/category names first.");
  }
}

export function validateOrdering(value: string | null): string {
  if (value === null) return "current_price";
  const s = strip(value);
  if (!s) return "current_price";
  if (!ORDERING_FIELDS.includes(s)) fail(`ordering=${repr(value)} is not a valid field. Valid: ${ORDERING_FIELDS.join(", ")}.`);
  return s;
}

export function validateSort(value: string | null): string {
  if (value === null) return "asc";
  const s = strip(value).toLowerCase();
  if (s !== "asc" && s !== "desc") fail(`sort must be 'asc' or 'desc'. Got ${repr(value)}.`);
  return s;
}

/** An education level, or several pipe-delimited for OR (e.g. 'BA|MA'). */
export function validateEducationLevel(value: string | null): string | null {
  if (value === null) return null;
  const s = strip(value);
  if (!s) return null;
  const parts = s.split("|").map(strip);
  for (const p of parts) {
    if (!p) fail(`education_level ${repr(value)} has an empty entry between pipes.`);
    if (!Object.hasOwn(EDUCATION_LEVELS, p)) {
      const valid = Object.keys(EDUCATION_LEVELS).sort().join(", ");
      fail(`education_level entry ${repr(p)} not valid. Valid codes: ${valid}. Pipe-delimit for OR (e.g. 'BA|MA').`);
    }
  }
  return parts.join("|");
}

/** Any worksite value is refused: the CALC+ v3 API silently ignores the filter. */
export function validateWorksite(value: string | null): void {
  if (value === null || !strip(value)) return;
  fail("worksite filtering is not supported by the CALC+ v3 API; the filter is silently ignored upstream (every value returns unfiltered "
    + "results). Remove the worksite argument. The underlying data does carry a worksite field (Customer_Facility, Contractor_Facility, "
    + "Virtual), so individual hit records still show it.");
}

/** SIN codes are alphanumeric (e.g., '54151S', '541330ENG'). */
export function validateSin(value: string | PyInt | null): string | null {
  if (value === null) return null;
  const s = strip(typeof value === "string" ? value : intStr(value));
  if (!s) return null;
  if (cpLen(s) > 20) fail(`sin=${repr(value)} exceeds 20 chars (${cpLen(s)}). Real SINs are <=10 chars (e.g. '54151S', '541330ENG').`);
  if (!/^[A-Za-z0-9]+$/.test(s)) fail(`sin=${repr(value)} must be alphanumeric (e.g. '54151S', '541330ENG'). No spaces or special characters.`);
  return s;
}

export function validateExperienceRange(emin: PyInt | null, emax: PyInt | null): [PyInt | null, PyInt | null] {
  if (emin !== null && emin < 0) fail(`experience_min must be >= 0. Got ${showInt(emin)}.`);
  if (emax !== null && emax < 0) fail(`experience_max must be >= 0. Got ${showInt(emax)}.`);
  if (emin !== null && emax !== null && emin > emax) fail(`experience_min (${showInt(emin)}) must be <= experience_max (${showInt(emax)}).`);
  return [emin, emax];
}

export function validatePriceRange(pmin: number | null, pmax: number | null): [number | null, number | null] {
  pmin = validateFiniteFloat(pmin, "price_min");
  pmax = validateFiniteFloat(pmax, "price_max");
  if (pmin !== null && pmin < 0) fail(`price_min must be >= 0. Got ${showFloat(pmin)}.`);
  if (pmax !== null && pmax <= 0) {
    // price_max=0 builds price_range:0,0, which matches nothing and returns a silent zero-result response.
    fail(`price_max must be > 0. Got ${showFloat(pmax)}. A zero or negative ceiling matches no rates and returns silent empty results.`);
  }
  if (pmin !== null && pmax !== null && pmin > pmax) fail(`price_min ($${showFloat(pmin)}) must be <= price_max ($${showFloat(pmax)}).`);
  return [pmin, pmax];
}
