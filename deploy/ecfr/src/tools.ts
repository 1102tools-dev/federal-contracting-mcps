// The hosted eCFR tools. Eight answer from the copy of the current eCFR in D1
// (schema.sql, filled by scripts/load_ecfr.py), mirroring the Python server
// (servers/ecfr-mcp/src/ecfr_mcp/server.py) step for step: the same
// validation order, messages and keys. The copy holds one date per title, so a
// question about any other date, raw XML, or anything the copy can't rebuild
// exactly throws Forward and the Python server answers it. The five tools that
// need eCFR's history or search are always forwarded (LIVE_TOOLS).
import CONTRACT from "../tools-contract.json" with {type: "json"};
import {Forward, ToolError, validateArgs} from "./args.ts";
import {paginate, parse, type Content} from "./assemble.ts";
import {
  belowStatement, checkDate, chunksStatement, contents, docStatement, joinDoc, json, only, resolveDate, targetStatement,
  titleEntry, titleStatement, truthy, type Database, type NodeRow, type Step,
} from "./data.ts";
import {cleanQuery, find} from "./definitions.ts";
import {repr, str, type Py} from "./pyjson.ts";
import {STRUCTURE_HANDLERS} from "./structure.ts";
import {cpLen, strip} from "./text.ts";
import {
  COMMON_FAR_SECTIONS, checkCitedTitle, checkTitle48Chapter, clamp, clampStrLen, coerceCfrStr, stripOrNone, validateChapter,
  validateDate, validateTitle,
} from "./validate.ts";

export {Forward, ToolError, type Database};

/** The reviewed tool definitions, sorted by name. */
export const TOOLS = [...CONTRACT].sort((a, b) => (a.name < b.name ? -1 : 1));

/** Tools that read eCFR's version history or search: always answered live. */
export const LIVE_TOOLS = new Set(["compare_versions", "get_version_history", "get_corrections", "find_recent_changes", "search_cfr"]);

// Content over this many bytes of XML (the structure's size) is left to the Python server.
const MAX_XML_BYTES = 4_000_000;

type Obj = Record<string, any>;
type Handler = (db: Database, args: Record<string, unknown>) => Promise<Py>;

// ---------- get_latest_date ----------

async function getLatestDate(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("get_latest_date", raw);
  const title = validateTitle(a.title_number);
  const [titles] = (await db.batch([titleStatement(db, title)])).map(r => r.results) as [{json: string}[]];
  const t = titleEntry(titles);
  const utd = t.up_to_date_as_of;
  if (typeof utd !== "string" || !strip(utd)) {
    throw new ToolError(`Title ${title} has no available content (reserved=${str(t.reserved ?? null)}). Reserved titles are placeholders `
      + "in the CFR numbering scheme without published regulations.");
  }
  return {
    title,
    name: t.name ?? null,
    up_to_date_as_of: utd,
    latest_amended_on: t.latest_amended_on ?? null,
    latest_issue_date: t.latest_issue_date ?? null,
    reserved: truthy(t.reserved ?? false),
  };
}

// ---------- get_cfr_content and lookup_far_clause ----------

/** The text of one node as parse() gives it, read in one batch. */
async function nodeText(db: Database, title: number, date: string | null, target: Step, filters: Record<string, string | null>) {
  const container = target.type !== "section" && target.type !== "appendix";
  const statements = [titleStatement(db, title), targetStatement(db, title, target, true), chunksStatement(db, title, target, container)];
  if (container) statements.push(belowStatement(db, title, target, {withContent: true}));
  const [titles, candidates, chunks, below] = (await db.batch(statements)).map(r => r.results) as [any[], NodeRow[], any[], NodeRow[]?];
  const entry = titleEntry(titles);
  date ??= resolveDate(entry, title);
  checkDate(entry, date);
  const node = only(candidates, filters);
  // A DIV parse() can't be rebuilt from (flag 1), or a scope too big to send through the Worker.
  if (node.flags! & 1) throw new Forward("flagged");
  if (Number(json(node.structure).size) > MAX_XML_BYTES) throw new Forward("too_big");
  const texts = contents([node, ...(below ?? [])], chunks);
  const contentOf = (key: string): Content => {
    const content = texts.get(key);
    if (!content) throw new Forward("no_content");
    return content;
  };
  return {date, parsed: parse(contentOf(node.key), node.meta ? json(node.meta) : null, date, contentOf)};
}

interface ContentArgs {
  title_number: number | bigint;
  date: string | null;
  part: unknown;
  subpart: unknown;
  section: unknown;
  chapter: unknown;
  appendix: unknown;
  raw_xml: boolean;
  page: number | bigint;
}

async function cfrContent(db: Database, a: ContentArgs) {
  const title = validateTitle(a.title_number);
  const date = validateDate(a.date, "date");
  checkCitedTitle(a.section, title, "section");
  checkCitedTitle(a.part, title, "part");
  checkCitedTitle(a.subpart, title, "subpart");
  const section = coerceCfrStr(a.section, "section", {stripPrefixes: true, stripCites: true});
  const part = coerceCfrStr(a.part, "part", {stripPrefixes: true});
  const subpart = coerceCfrStr(a.subpart, "subpart", {stripPrefixes: true});
  const chapter = validateChapter(a.chapter, title);
  const appendix = coerceCfrStr(a.appendix, "appendix");
  const page = clamp(a.page, "page", 1, 10_000);
  if (title === 48 && chapter && !appendix) checkTitle48Chapter(chapter, section || subpart || part);
  if (!(section || part || subpart || chapter || appendix)) {
    throw new ToolError("get_cfr_content requires at least one of: section, subpart, part, "
      + "chapter, appendix. Calling without any filter returns the entire title (often 20+ MB).");
  }
  // Raw XML, a whole chapter, or a section and an appendix at once: the Python server answers.
  if (a.raw_xml) throw new Forward("raw_xml");
  if (section && appendix) throw new Forward("two_targets");
  const target: Step | null = appendix ? {type: "appendix", identifier: appendix} : section ? {type: "section", identifier: section}
    : subpart ? {type: "subpart", identifier: subpart} : part ? {type: "part", identifier: part} : null;
  if (!target) throw new Forward("chapter_scope");

  const text = await nodeText(db, title, date, target, {chapter, part, subpart});
  const parsed = text.parsed;
  parsed.date = text.date;
  parsed.title = title;
  if (section) parsed.section = section;
  if (part) parsed.part = part;
  if (subpart) parsed.subpart = subpart;
  if (chapter) parsed.chapter = chapter;
  if (appendix) parsed.appendix = appendix;
  const narrower = Object.hasOwn(parsed, "sections")
    ? "To read one section instead, call get_cfr_content with section= set to an identifier from 'sections' (list_sections_in_part lists them all)."
    : section === "2.101" && title === 48 ? "For one FAR definition, find_far_definition returns just that term." : "";
  return paginate(parsed, page, narrower);
}

async function getCfrContent(db: Database, raw: Record<string, unknown>) {
  return await cfrContent(db, validateArgs("get_cfr_content", raw) as ContentArgs);
}

async function lookupFarClause(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("lookup_far_clause", raw);
  const section = coerceCfrStr(a.section_id, "section_id", {stripPrefixes: true, stripCites: true});
  if (!section) {
    throw new ToolError("section_id is required. Pass a section like '15.305', '52.212-4' or '252.204-7012'. "
      + `Common sections: ${COMMON_FAR_SECTIONS.slice(0, 5).join(", ")}.`);
  }
  const chapter = checkTitle48Chapter(validateChapter(a.chapter, 48), section);
  // The date resolves inside get_cfr_content's read, from the same titles row.
  const date = validateDate(a.date, "date");
  return await cfrContent(db, {title_number: 48, date, chapter, section, page: a.page, part: null, subpart: null, appendix: null, raw_xml: false});
}

// ---------- find_far_definition ----------

async function findFarDefinition(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("find_far_definition", raw);
  let term = stripOrNone(a.term);
  if (term === null) throw new ToolError("term is required and cannot be empty or whitespace-only.");
  if (cpLen(term) < 3) {
    throw new ToolError(`term must be at least 3 characters (got ${cpLen(term)}). Short terms match too broadly and return junk.`);
  }
  term = clampStrLen(term, "term", 100);
  const maxMatches = clamp(a.max_matches, "max_matches", 1, 100);
  const date = validateDate(a.date, "date");
  if (!cleanQuery(term)) throw new ToolError(`term=${repr(a.term)} has no words left to look up.`);

  const text = await nodeText(db, 48, date, {type: "section", identifier: "2.101"}, {});
  const paragraphs: string[] = text.parsed.paragraphs ?? [];
  const found = find(paragraphs, term);
  // Not defined in 2.101: the Python server searches the rest of the FAR and the DFARS live.
  if (!found.definitions.length) throw new Forward("defined_elsewhere");
  const room = Math.max(0, maxMatches - found.definitions.length);
  const matches = [...found.definitions, ...found.mentions.slice(0, room)];
  return {
    section: "2.101",
    date: text.date,
    search_term: term,
    definition_count: found.definitions.length,
    match_count: matches.length,
    total_matches: found.definitions.length + found.mentions.length,
    truncated: found.mentions.length > room,
    max_matches: maxMatches,
    matches,
    total_paragraphs: paragraphs.length,
    note: "Matches with kind='definition' come first and are complete: the defining "
      + "paragraph and every paragraph under it. kind='mention' entries are other "
      + "definitions that use the term.",
  } as Py;
}

// ---------- list_agencies ----------

// A reference can point at a subtitle, chapter, subchapter or part.
const REF_KEYS = ["title", "subtitle", "chapter", "subchapter", "part"];
const safeDict = (value: unknown): Obj => (value !== null && typeof value === "object" && !Array.isArray(value) ? value as Obj : {});
const asList = (value: unknown): unknown[] => (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]);

/** cfr_references from an agency and all of its descendants, first of each kept. */
function refsWithChildren(agency: Obj): Obj[] {
  const refs: Obj[] = [];
  const seen = new Set<string>();
  const walk = (a: Obj) => {
    for (const item of asList(a.cfr_references)) {
      const r = safeDict(item);
      const id = JSON.stringify(REF_KEYS.map(k => r[k] ?? null));
      if (seen.has(id)) continue;
      seen.add(id);
      refs.push(r);
    }
    for (const child of asList(a.children)) walk(safeDict(child));
  };
  walk(agency);
  return refs;
}

async function listAgencies(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("list_agencies", raw);
  const [pieces] = (await db.batch([docStatement(db, "agencies.json")])).map(r => r.results) as [{text: string}[]];
  const data = joinDoc(pieces);
  const agencies = asList(safeDict(data).agencies);
  if (!a.summary_only) return {agencies, count: agencies.length} as Py;
  const summarized = agencies.map(item => {
    const agency = safeDict(item);
    return {
      name: agency.name ?? null,
      short_name: agency.short_name ?? null,
      slug: agency.slug ?? null,
      cfr_references: refsWithChildren(agency).map(r =>
        Object.fromEntries(REF_KEYS.filter(k => (r[k] ?? null) !== null || k === "title" || k === "chapter").map(k => [k, r[k] ?? null]))),
      child_count: asList(agency.children).length,
    };
  });
  return {agencies: summarized, count: summarized.length, summary_only: true} as Py;
}

export const HANDLERS: Record<string, Handler> = {
  get_latest_date: getLatestDate,
  get_cfr_content: getCfrContent,
  lookup_far_clause: lookupFarClause,
  find_far_definition: findFarDefinition,
  list_agencies: listAgencies,
  ...STRUCTURE_HANDLERS,
} as Record<string, Handler>;
