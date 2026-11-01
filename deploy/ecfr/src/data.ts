// Reading the copy of the eCFR in D1 (schema.sql, written by scripts/load_ecfr.py).
// Every tool reads what it needs in one batch: the title's row from eCFR's
// titles.json, the node the filters name (by type and identifier), and its
// ancestors or descendants. Anything missing or inconsistent means the copy
// can't answer exactly, so the Worker forwards the request (Forward).
import {Forward, ToolError} from "./args.ts";
import type {Content} from "./assemble.ts";
import {parseJson} from "./pyjson.ts";
import {strip} from "./text.ts";

type Row = Record<string, any>;
export interface Statement {
  bind(...values: unknown[]): Statement;
  all<T = Row>(): Promise<{results: T[]}>;
}
export interface Database {
  prepare(sql: string): Statement;
  batch<T = Row>(statements: Statement[]): Promise<{results: T[]}[]>;
}

/** A nodes row (the columns a query asked for). */
export interface NodeRow {
  key: string;
  type: string;
  identifier: string | null;
  structure: string;
  children: string | null;
  content?: string | null;
  chunks?: number;
  meta?: string | null;
  flags?: number;
}

/** One step of a node's path: chapter 1, part 15, ... */
export interface Step {
  type: string;
  identifier: string;
}

/** The node a filter names, or null for the title itself. */
export type Target = Step | null;

const STRUCTURE_COLUMNS = ["key", "type", "identifier", "structure", "children"];
const ALL_COLUMNS = [...STRUCTURE_COLUMNS, "content", "chunks", "meta", "flags"];
const columns = (alias: string, withContent: boolean) => (withContent ? ALL_COLUMNS : STRUCTURE_COLUMNS).map(c => `${alias}.${c}`).join(", ");
// Larger trees than this are left to the Python server (a whole big title).
export const MAX_ROWS = 6000;

/** A node key's steps from the title down ('' is the title). */
export function steps(key: string): Step[] {
  if (!key) return [];
  return key.split("/").map(step => {
    const colon = step.indexOf(":");
    return {type: step.slice(0, colon), identifier: step.slice(colon + 1).replace(/%2F|%25/g, m => (m === "%2F" ? "/" : "%"))};
  });
}

/** The keys of a node's ancestors, the title ('') first. */
export function ancestorKeys(key: string): string[] {
  const parts = key ? key.split("/") : [];
  return parts.map((_, i) => parts.slice(0, i).join("/"));
}

/** Whether every given filter (type -> identifier) names a level on the node's path. */
export function onPath(key: string, filters: Record<string, string | null>): boolean {
  const path = steps(key);
  return Object.entries(filters).every(([type, identifier]) =>
    identifier === null || path.some(s => s.type === type && s.identifier === identifier));
}

const where = (target: Target) => (target ? "t.title = ?1 AND t.type = ?2 AND t.identifier = ?3" : "t.title = ?1 AND t.key = ''");
const below = (target: Target) => (target ? "d.key > t.key || '/' AND d.key < t.key || '0'" : "d.key > ''");
const params = (title: number, target: Target) => (target ? [title, target.type, target.identifier] : [title]);
// A key's depth below the title: one per step.
const LEVEL = (column: string) => `(CASE WHEN ${column} = '' THEN 0 ELSE length(${column}) - length(replace(${column}, '/', '')) + 1 END)`;

export const titleStatement = (db: Database, title: number) => db.prepare("SELECT json FROM titles WHERE number = ?1").bind(title);

/** The node(s) the filter names; with content when asked. */
export const targetStatement = (db: Database, title: number, target: Target, withContent = false) =>
  db.prepare(`SELECT ${columns("t", withContent)} FROM nodes t WHERE ${where(target)}`).bind(...params(title, target));

/** Every node below the target, at most `depth` levels down (all when null). */
export const belowStatement = (db: Database, title: number, target: Target, {withContent = false, depth = null as number | null} = {}) =>
  db.prepare(`SELECT ${columns("d", withContent)} FROM nodes t JOIN nodes d ON d.title = t.title AND ${below(target)}
    WHERE ${where(target)}${depth === null ? "" : ` AND ${LEVEL("d.key")} <= ${LEVEL("t.key")} + ${Math.trunc(depth)}`}
    LIMIT ${MAX_ROWS + 1}`).bind(...params(title, target));

/** The chunked text (nodes.chunks > 0) of the target and, with `descendants`, of the nodes below it.
 * The key range from the target up to its key + '0' holds it, its descendants and a few siblings. */
export const chunksStatement = (db: Database, title: number, target: Step, descendants: boolean) =>
  db.prepare(`SELECT c.key, c.seq, c.text FROM nodes t JOIN chunks c ON c.title = t.title AND ${descendants
    ? "c.key >= t.key AND c.key < t.key || '0' AND (c.key = t.key OR c.key > t.key || '/')" : "c.key = t.key"}
    WHERE ${where(target)} ORDER BY c.key, c.seq`).bind(...params(title, target));

/** The target's ancestors, the title first: each parent key is the key up to its last '/'. */
export const ancestorsStatement = (db: Database, title: number, target: Step) =>
  db.prepare(`WITH RECURSIVE up(key) AS (
      SELECT t.key FROM nodes t WHERE ${where(target)}
      UNION
      SELECT CASE WHEN instr(key, '/') = 0 THEN '' ELSE substr(rtrim(key, replace(key, '/', '')), 1, length(rtrim(key, replace(key, '/', ''))) - 1) END
      FROM up WHERE key != ''
    )
    SELECT ${columns("n", false)} FROM up JOIN nodes n ON n.title = ?1 AND n.key = up.key`).bind(...params(title, target));

/** Whole documents kept in docs (agencies.json), joined from their pieces. */
export const docStatement = (db: Database, name: string) => db.prepare("SELECT text FROM docs WHERE name = ?1 ORDER BY seq").bind(name);

export function joinDoc(rows: {text: string}[]): unknown {
  if (!rows.length) throw new Forward("no_doc");
  return parseJson(rows.map(r => r.text).join(""));
}

/** A JSON column, parsed as Python reads it (floats stay floats). */
export const json = (text: string) => parseJson(text) as any;

/** Each node's content, with chunked content joined in order. */
export function contents(rows: NodeRow[], chunks: {key: string; seq: number; text: string}[]): Map<string, Content> {
  const pieces = new Map<string, string[]>();
  for (const chunk of chunks) {
    const list = pieces.get(chunk.key) ?? [];
    if (chunk.seq !== list.length) throw new Forward("chunk_gap");
    list.push(chunk.text);
    pieces.set(chunk.key, list);
  }
  const out = new Map<string, Content>();
  for (const row of rows) {
    let text = row.content ?? null;
    if (row.chunks) {
      const list = pieces.get(row.key);
      if (!list || list.length !== row.chunks) throw new Forward("chunk_gap");
      text = list.join("");
    }
    if (text !== null) out.set(row.key, json(text));
  }
  return out;
}

/** Python truthiness for a JSON value. */
export const truthy = (value: unknown) =>
  !(value === null || value === undefined || value === false || value === 0 || value === "" || (Array.isArray(value) && !value.length)
    || (typeof value === "object" && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype && !Object.keys(value as object).length));

/** eCFR's titles.json entry for the title; the copy has every title, so a gap forwards. */
export function titleEntry(rows: {json: string}[]): Record<string, any> {
  if (!rows.length) throw new Forward("no_title");
  return json(rows[0].json);
}

/** _resolve_date: the title's up_to_date_as_of, which is also the copy's date for it. */
export function resolveDate(entry: Record<string, any>, title: number): string {
  const utd = entry.up_to_date_as_of;
  if (typeof utd !== "string" || !strip(utd)) {
    const reason = truthy(entry.reserved) ? "this title is marked 'reserved'" : "the API did not return up_to_date_as_of";
    throw new ToolError(`Cannot resolve a date for title ${title}: ${reason}. Reserved or un-issued titles have no published content.`);
  }
  return utd;
}

/** The copy answers only for its own date; any other date is asked live. */
export function checkDate(entry: Record<string, any>, date: string): void {
  if (date !== entry.up_to_date_as_of) throw new Forward("date");
}

/** The one candidate whose path matches every other filter; anything else forwards. */
export function only<T extends {key: string}>(candidates: T[], filters: Record<string, string | null>): T {
  const matching = candidates.filter(c => onPath(c.key, filters));
  if (matching.length !== 1) throw new Forward(matching.length ? "ambiguous" : "not_found");
  return matching[0];
}
