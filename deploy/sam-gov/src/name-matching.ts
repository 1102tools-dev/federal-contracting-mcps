import {ToolError, type Database} from "./public-types.ts";

// Keep the SQL and JavaScript character transformations identical. SQLite lower()
// folds ASCII; query-specific Unicode case pairs below cover the compared letters.
const PUNCTUATION = `!"#$%'()*+,-./:;<=>?@[\\]^_\x60{|}~` + "‐‑‒–—―−‘’‚‛“”„‟«»‹›·•…，。、（）［］｛｝：；！？／＼";
const SPACES = "\t\n\r\v\f\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000";
const SUFFIXES = ["inc", "llc", "corp", "corporation", "co", "company", "ltd", "lp", "pllc", "the"];
const quote = (s: string) => "'" + s.replaceAll("'", "''") + "'";
export function nameWords(value: string): string[] {
  let s = value.toLowerCase().replaceAll("&", "and");
  for (const c of PUNCTUATION) s = s.replaceAll(c, "");
  for (const c of SPACES) s = s.replaceAll(c, " ");
  return s.split(/ +/).filter(w => w && !SUFFIXES.includes(w));
}
export function normalizedName(value: string): string {return nameWords(value).join("");}

export function compactSQL(column: string, query: string): string {
  const operations: ((value: string) => string)[] = [];
  const replace = (from: string, to: string) => operations.push(value => `replace(${value}, ${quote(from)}, ${quote(to)})`);
  for (const c of new Set(query.toLowerCase())) if (c.charCodeAt(0) > 127 && c.toUpperCase() !== c) replace(c.toUpperCase(), c);
  replace("&", "and");
  for (const c of PUNCTUATION) replace(c, "");
  for (const c of SPACES) replace(c, " ");
  operations.push(value => `(' ' || ${value} || ' ')`);
  for (const suffix of SUFFIXES) for (let n = 0; n < 7; n++) replace(` ${suffix} `, " ");
  replace(" ", "");
  // D1 limits each expression tree to depth 100. Small scalar stages keep
  // arbitrary input below that limit; LIMIT prevents flattening the stages.
  let stage = `SELECT lower(coalesce(${column}, '')) AS value LIMIT 1`;
  for (let i = 0; i < operations.length; i += 30) {
    let value = "value";
    for (const operation of operations.slice(i, i + 30)) value = operation(value);
    stage = `SELECT ${value} AS value FROM (${stage}) LIMIT 1`;
  }
  return `(SELECT value FROM (${stage}))`;
}

function globCharacters(value: string): string {
  return [...value].map(c => c.charCodeAt(0) > 127 && c.toUpperCase() !== c ? `[${c}${c.toUpperCase()}]` : c).join("*");
}
export function namePredicate(columns: string[], query: string) {
  const compact = normalizedName(query);
  if (!compact || nameWords(query).every(w => w === "and")) throw new ToolError("Name must contain a meaningful name beyond punctuation and company suffixes.");
  // Cheap subsequence prefilter preserves punctuation/spacing variants. Only
  // survivors pay for the full normalization; no new columns or indexes.
  const pattern = "*" + globCharacters([...compact].slice(0, 8).join("")) + "*";
  const values: unknown[] = [];
  const sql = columns.map(column => {
    values.push(pattern, compact);
    return `(lower(replace(coalesce(${column}, ''), '&', 'and')) GLOB ? AND instr(${compactSQL(column, query)}, ?) > 0)`;
  }).join(" OR ");
  return {sql: `(${sql})`, values};
}

function distance(a: string, b: string, limit: number): number {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  let previous = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const current = Array(b.length + 1).fill(limit + 1); current[0] = i;
    for (let j = Math.max(1, i - limit); j <= Math.min(b.length, i + limit); j++) {
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + Number(a[i - 1] !== b[j - 1]));
    }
    previous = current;
  }
  return previous[b.length];
}
export async function possibleNameMatches(db: Database, options: {
  table: "entities" | "exclusions"; kind: "entities" | "exclusions";
  columns: string[]; projection: string[]; where: string[]; values: unknown[];
  query: string; snapshot: Record<string, any>;
}) {
  const {table, kind, columns, projection, where, values, query, snapshot} = options;
  const key = normalizedName(query), words = nameWords(query);
  // Bounded candidate exploration, not a second exact/identity determination.
  const anchors = [...new Set([key.slice(0, 2), key.slice(-2), ...words.filter(w => w.length >= 3).map(w => w.slice(0, 3))])].filter(a => a.length >= 2);
  if (!anchors.length) return {possibleMatches: [], possibleMatchCandidatesTruncated: false, possibleMatchNote: "No close candidates found. No match is not a clearance; verify identifiers and current SAM.gov status."};
  const coarse = columns.flatMap(column => anchors.map(() => `instr(lower(replace(coalesce(${column}, ''), '&', 'and')), ?) > 0`)).join(" OR ");
  const prefix = [...key].slice(0, 3).join("");
  const priority = `max(${columns.map(column => `CASE WHEN lower(replace(coalesce(${column}, ''), '&', 'and')) GLOB ? THEN 1000 ELSE 0 END`).join(", ")}) + max(${columns.map(column => `CASE WHEN lower(replace(coalesce(${column}, ''), '&', 'and')) GLOB ? THEN 100 ELSE 0 END`).join(", ")})`;
  const params = [...values, ...columns.flatMap(() => anchors), ...columns.map(() => globCharacters([...key].slice(0, 8).join("")) + "*"), ...columns.map(() => globCharacters(prefix) + "*")];
  const fields = projection.map(c => `${quote(c)}, ${c}`).join(", ");
  const result = (await db.prepare(`WITH candidates AS (SELECT ${projection.join(", ")} FROM ${table} WHERE ${[...where, `(${coarse})`, `NOT EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='${kind}' AND state='applying')`].join(" AND ")}
    ORDER BY (${priority}) DESC, ${columns[0]} COLLATE NOCASE LIMIT 501)
    SELECT (SELECT json_group_array(json_object(${fields})) FROM candidates) AS candidates,
    EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='${kind}' AND state='applying') AS refreshing,
    s.* FROM extract_status s WHERE kind='${kind}'`).bind(...params).all<Record<string, any>>()).results[0];
  if (!result || result.refreshing || result.sha256 !== snapshot.sha256 || result.loaded_at !== snapshot.loaded_at) {
    throw new ToolError("SAM.gov name search is refreshing. Try again in about 10 minutes; confirm current status on SAM.gov.");
  }
  const candidates = JSON.parse(result.candidates) as Record<string, any>[];
  const limit = Math.min(6, Math.max(2, Math.ceil(key.length * 0.2)));
  const ranked = candidates.map(row => {
    const names = table === "entities" ? [row.legal_business_name, row.dba_name] : [row.name, [row.first_name, row.middle_name, row.last_name].filter(Boolean).join(" ")];
    let similarity = 0, matched_name = "";
    for (const raw of names) if (raw) {
      const candidate = normalizedName(raw);
      const d = distance(key, candidate, limit);
      let score = d <= limit ? 1 - d / Math.max(key.length, candidate.length) : 0;
      // A missing middle name or omitted business descriptor can be a useful
      // candidate, but never becomes a confirmed match.
      const meaningfulWords = [...new Set(words.filter(w => w.length > 2 && w !== "and"))];
      const candidateWords = [...new Set(nameWords(raw).filter(w => w.length > 2 && w !== "and"))];
      const overlap = meaningfulWords.filter(w => candidateWords.includes(w)).length;
      if (meaningfulWords.length >= 2 && overlap >= 2 && overlap / meaningfulWords.length >= 0.66) score = Math.max(score, 0.7 + 0.2 * overlap / Math.max(meaningfulWords.length, candidateWords.length));
      if (score > similarity) {similarity = score; matched_name = raw;}
    }
    return {label: "possible matches, not confirmed", matched_name, similarity: Math.round(similarity * 100) / 100,
      uei: row.uei ?? null, cage_code: row.cage_code ?? null, state: row.state ?? null, city: row.city ?? null, zip_code: row.zip_code ?? null, address_line_1: row.address_line_1 ?? null,
      ...(table === "exclusions" ? {exclusion_id: row.exclusion_id, classification: row.classification} : {entity_id: row.entity_id})};
  }).filter(row => row.similarity >= 0.65).sort((a, b) => b.similarity - a.similarity || a.matched_name.localeCompare(b.matched_name)).slice(0, 5);
  return {possibleMatches: ranked, possibleMatchNote: "Possible matches, not confirmed. Bounded close-name suggestions are not an exhaustive search or an identity, exclusion, registration or eligibility determination. Compare identifiers and addresses; confirm current status on SAM.gov.", possibleMatchCandidatesTruncated: ranked.length > 0 && candidates.length === 501};
}

// Trigram name index (separate sam-gov-name-index D1). It only narrows the
// rows that namePredicate then checks exactly, so results never change.
// Queries shorter than 3 characters, very broad queries, a missing index or an
// index built for another source generation all fall back to the full scan.
export const NAME_INDEX_MAX_CANDIDATES = 10000;
export type NameIndexCandidates = {ids: string; sha256: string; loadedAt: string};

export function trigramMatch(query: string): string | undefined {
  const key = [...normalizedName(query)];
  if (key.length < 3) return undefined;
  const grams = new Set<string>();
  for (let i = 0; i + 3 <= key.length; i++) grams.add(key.slice(i, i + 3).join(""));
  return [...grams].map(gram => `"${gram.replaceAll('"', '""')}"`).join(" AND ");
}

export async function nameIndexCandidates(indexDb: Database | undefined, kind: "entities" | "exclusions", query: string): Promise<NameIndexCandidates | undefined> {
  const match = trigramMatch(query);
  if (!indexDb || !match) return undefined;
  try {
    const row = (await indexDb.prepare(`SELECT s.source_sha AS sha256, s.source_loaded_at AS loaded_at,
      (SELECT json_group_array(rowid) FROM (SELECT rowid FROM ${kind}_name_index WHERE ${kind}_name_index MATCH ? LIMIT ?)) AS ids
      FROM name_index_status s WHERE s.kind = ?`).bind(match, NAME_INDEX_MAX_CANDIDATES + 1, kind).all<Record<string, any>>()).results[0];
    if (!row?.sha256) return undefined;
    const ids = JSON.parse(row.ids) as number[];
    if (ids.length > NAME_INDEX_MAX_CANDIDATES) return undefined;
    return {ids: JSON.stringify(ids), sha256: row.sha256, loadedAt: row.loaded_at};
  } catch {
    return undefined; // Index unavailable: the exact scan still answers.
  }
}

/** True when the index was built from the snapshot the search actually read. */
export const nameIndexMatches = (candidates: NameIndexCandidates | undefined, snapshot: Record<string, any> | undefined) =>
  !candidates || (snapshot?.sha256 === candidates.sha256 && snapshot?.loaded_at === candidates.loadedAt);
