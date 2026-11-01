// get_cfr_structure, get_ancestry and list_sections_in_part over the copy of
// eCFR's structure trees. Each node keeps eCFR's JSON as sent (key order
// included); a filtered answer is eCFR's: the title-down chain, each ancestor
// with only the child on the path, then the whole subtree of the node asked for.
import {Forward, ToolError, validateArgs} from "./args.ts";
import {PAGE_CHARS, sizeOf} from "./assemble.ts";
import {
  MAX_ROWS, ancestorsStatement, belowStatement, checkDate, json, only, resolveDate, steps, targetStatement, titleEntry,
  titleStatement, truthy, type Database, type NodeRow, type Step, type Target,
} from "./data.ts";
import {group} from "./pyjson.ts";
import {checkCitedTitle, clamp, coerceCfrStr, validateChapter, validateDate, validateTitle} from "./validate.ts";

type Obj = Record<string, any>;

/** A node rebuilt from its row: eCFR's object with "children" filled in.
 * Below `levels` more levels the children are only counted (null placeholders). */
function build(key: string, rows: Map<string, NodeRow>, levels: number | null): Obj {
  const row = rows.get(key);
  if (!row) throw new Forward("missing_node");
  const node = json(row.structure);
  if (Object.hasOwn(node, "children")) {
    const keys: string[] = row.children ? json(row.children) : [];
    node.children = levels === 0 ? keys.map(() => null) : keys.map(k => build(k, rows, levels === null ? null : levels - 1));
  }
  return node;
}

/** eCFR's filtered answer: the chain from the title to the target, then its subtree. */
function chain(target: NodeRow, rows: Map<string, NodeRow>, levels: number | null): Obj {
  let node = build(target.key, rows, levels);
  const path = target.key ? target.key.split("/") : [];
  for (let i = path.length - 1; i >= 0; i--) {
    const parent = rows.get(path.slice(0, i).join("/"));
    if (!parent) throw new Forward("missing_ancestor");
    const above = json(parent.structure);
    above.children = [node];
    node = above;
  }
  return node;
}

const safeDict = (value: unknown): Obj => (value !== null && typeof value === "object" && !Array.isArray(value) ? value as Obj : {});
const asList = (value: unknown): unknown[] => (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]);
const without = (node: Obj, key: string) => Object.fromEntries(Object.entries(node).filter(([k]) => k !== key));

/** _trim_tree: keep depth levels of children; count what is cut. */
function trimTree(node: Obj, depth: number): Obj {
  const out = without(node, "children");
  const children = asList(node.children).map(safeDict);
  if (!children.length) return out;
  if (depth <= 0) {
    out.children_omitted = children.length;
    return out;
  }
  out.children = children.map(c => trimTree(c, depth - 1));
  return out;
}

/** _trim_below: trim depth levels below the first node of type anchor (or below node). */
function trimBelow(node: Obj, anchor: string | null, depth: number): Obj {
  if (anchor === null || node.type === anchor) return trimTree(node, depth);
  const children = asList(node.children).map(safeDict);
  const out = without(node, "children");
  if (children.length) out.children = children.map(c => trimBelow(c, anchor, depth));
  return out;
}

async function getCfrStructure(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("get_cfr_structure", raw);
  const title = validateTitle(a.title_number);
  let date = validateDate(a.date, "date");
  checkCitedTitle(a.part, title, "part");
  checkCitedTitle(a.subpart, title, "subpart");
  const chapter = validateChapter(a.chapter, title);
  const subchapter = coerceCfrStr(a.subchapter, "subchapter", {maxlen: 8});
  const part = coerceCfrStr(a.part, "part", {stripPrefixes: true});
  const subpart = coerceCfrStr(a.subpart, "subpart", {stripPrefixes: true});
  const appendix = coerceCfrStr(a.appendix, "appendix");
  const depth = a.depth === null ? null : clamp(a.depth, "depth", 1, 10);
  if (subchapter && !chapter && title === 48) {
    throw new ToolError("subchapter needs chapter in Title 48: every chapter has its own subchapter "
      + "A, B, ... (FAR subchapter A is chapter='1', DFARS subchapter A is chapter='2').");
  }

  // The node eCFR's filters name; an appendix is found by its exact name inside it.
  const filters = {chapter, subchapter, part, subpart};
  const named: Target = subpart ? {type: "subpart", identifier: subpart} : part ? {type: "part", identifier: part}
    : subchapter ? {type: "subchapter", identifier: subchapter} : chapter ? {type: "chapter", identifier: chapter} : null;
  const target: Target = appendix ? {type: "appendix", identifier: appendix} : named;
  // eCFR always answers from the title down; depth counts from the node asked for.
  const anchor = subpart ? "subpart" : part ? "part" : subchapter ? "subchapter" : chapter ? "chapter" : null;
  // Without depth the whole subtree decides the size; with it, only depth levels below the anchor matter.
  const levels = appendix ? null : depth;
  const statements = [titleStatement(db, title), targetStatement(db, title, target), belowStatement(db, title, target, {depth: levels})];
  if (target) statements.push(ancestorsStatement(db, title, target));
  const [titles, candidates, subtree, ancestors] = (await db.batch(statements)).map(r => r.results) as [any[], NodeRow[], NodeRow[], NodeRow[]?];

  const entry = titleEntry(titles);
  date ??= resolveDate(entry, title);
  checkDate(entry, date);
  // eCFR's structure endpoint ignores chapter when a part is the deepest filter (it answers with the
  // part's own chain); with a subpart, a chapter the part isn't in is a 404.
  const node = only(candidates, {...filters, chapter: part && !subpart ? null : chapter});
  if (subtree.length > MAX_ROWS) throw new Forward("too_big");
  const rows = new Map<string, NodeRow>([...subtree, ...(ancestors ?? []), node].map(r => [r.key, r]));

  let result: Obj = appendix ? build(node.key, rows, null) : chain(node, rows, levels);
  result.date = date;
  if (depth !== null) {
    result = trimBelow(result, anchor, depth);
  } else if (sizeOf(result) > PAGE_CHARS) {
    const full = sizeOf(result);
    let level = 6;
    let trimmed = result;
    for (; level >= 1; level--) {
      trimmed = trimBelow(result, anchor, level);
      if (sizeOf(trimmed) <= PAGE_CHARS || level === 1) break;
    }
    result = trimmed;
    result.note = `The full tree is about ${group(String(full))} characters, too long to send at once, so `
      + `levels below depth ${level} are left out (see children_omitted). Ask for a `
      + "part or subpart to see its sections.";
  }
  return result;
}

async function getAncestry(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("get_ancestry", raw);
  const title = validateTitle(a.title_number);
  let date = validateDate(a.date, "date");
  checkCitedTitle(a.section, title, "section");
  checkCitedTitle(a.part, title, "part");
  checkCitedTitle(a.subpart, title, "subpart");
  const part = coerceCfrStr(a.part, "part", {stripPrefixes: true});
  const section = coerceCfrStr(a.section, "section", {stripPrefixes: true, stripCites: true});
  const appendix = coerceCfrStr(a.appendix, "appendix");
  const subpart = coerceCfrStr(a.subpart, "subpart", {stripPrefixes: true});
  if (section && appendix) throw new Forward("two_targets");
  const target: Step | null = section ? {type: "section", identifier: section} : appendix ? {type: "appendix", identifier: appendix}
    : subpart ? {type: "subpart", identifier: subpart} : part ? {type: "part", identifier: part} : null;
  if (!target) throw new Forward("no_target");
  const [titles, candidates, path] = (await db.batch([titleStatement(db, title), targetStatement(db, title, target),
    ancestorsStatement(db, title, target)])).map(r => r.results) as [any[], NodeRow[], NodeRow[]];

  const entry = titleEntry(titles);
  date ??= resolveDate(entry, title);
  checkDate(entry, date);
  const node = only(candidates, {part, subpart});
  const keys = node.key.split("/").map((_, i, all) => all.slice(0, i + 1).join("/"));
  const byKey = new Map(path.map(r => [r.key, r]));
  const ancestors = ["", ...keys].map(key => {
    const row = byKey.get(key);
    if (!row) throw new Forward("missing_ancestor");
    return without(json(row.structure), "children");
  });
  return {ancestors, date};
}

async function listSectionsInPart(db: Database, raw: Record<string, unknown>) {
  const a = validateArgs("list_sections_in_part", raw);
  const title = validateTitle(a.title_number);
  checkCitedTitle(a.part_number, title, "part_number");
  checkCitedTitle(a.subpart, title, "subpart");
  const part = coerceCfrStr(a.part_number, "part_number", {stripPrefixes: true});
  if (!part) throw new ToolError("part_number is required. Pass something like '15' or '252'.");
  const chapter = validateChapter(a.chapter, title);
  const subpart = coerceCfrStr(a.subpart, "subpart", {stripPrefixes: true});
  let date = validateDate(a.date, "date");
  const page = clamp(a.page, "page", 1, 1000);
  const detail: boolean = a.detail;

  const target: Step = subpart ? {type: "subpart", identifier: subpart} : {type: "part", identifier: part};
  const [titles, candidates, subtree] = (await db.batch([titleStatement(db, title), targetStatement(db, title, target),
    belowStatement(db, title, target)])).map(r => r.results) as [any[], NodeRow[], NodeRow[]];
  const entry = titleEntry(titles);
  date ??= resolveDate(entry, title);
  checkDate(entry, date);
  // eCFR ignores chapter when the part is the deepest filter, and the check below says so, as the
  // Python server does; with a subpart, a chapter the part isn't in is a 404, left to the Python server.
  const node = only(candidates, subpart ? {chapter, part} : {part});
  if (subtree.length > MAX_ROWS) throw new Forward("too_big");
  const rows = new Map<string, NodeRow>([...subtree, node].map(r => [r.key, r]));

  // The walk sees the chain first, so the chapter is the one on the path.
  const foundChapter = steps(node.key).find(s => s.type === "chapter")?.identifier ?? null;
  const entries: Obj[] = [];
  const subparts: Obj[] = [];
  const walk = (key: string, current: Obj | null) => {
    const row = rows.get(key)!;
    const n = json(row.structure);
    if (n.type === "subpart") {
      current = {identifier: n.identifier ?? null, heading: n.label_description ?? null, section_count: 0};
      subparts.push(current);
    }
    if (n.type === "section" || n.type === "appendix") {
      const item: Obj = {identifier: n.identifier ?? null, heading: n.label_description ?? null};
      if (n.type === "appendix") item.type = "appendix";
      if (truthy(n.reserved)) item.reserved = true;
      if (detail) for (const k of ["label", "size", "received_on"]) item[k] = n[k] ?? null;
      entries.push(item);
      if (current !== null) {
        current.section_count += 1;
        if (!Object.hasOwn(current, "first_section")) current.first_section = item.identifier;
        current.last_section = item.identifier;
      }
      return;
    }
    for (const child of row.children ? json(row.children) as string[] : []) {
      if (!rows.has(child)) throw new Forward("missing_node");
      walk(child, current);
    }
  };
  walk(node.key, null);
  if (chapter && foundChapter !== null && foundChapter !== chapter) {
    throw new ToolError(`Part ${part} is in chapter ${foundChapter}, not chapter ${chapter}. Leave chapter out; the part number is enough.`);
  }
  const result: Obj = {
    title,
    chapter: foundChapter ?? chapter,
    part,
    date,
    section_count: entries.filter(e => e.type !== "appendix").length,
    appendix_count: entries.filter(e => e.type === "appendix").length,
  };
  if (subpart) result.subpart = subpart;
  if (subparts.length) result.subparts = subparts;
  result.sections = entries;
  if (sizeOf(result) <= PAGE_CHARS) {
    if (page !== 1) throw new ToolError(`This list fits on one page; page=${page} does not exist.`);
    return result;
  }
  // Too long to send at once: split the entries into pages.
  const budget = PAGE_CHARS - sizeOf({...result, sections: []}) - 600;
  const pages: Obj[][] = [[]];
  let used = 0;
  for (const item of entries) {
    const cost = sizeOf(item, 2) + 2;
    if (pages[pages.length - 1].length && used + cost > budget) {
      pages.push([]);
      used = 0;
    }
    pages[pages.length - 1].push(item);
    used += cost;
  }
  if (page > pages.length) throw new ToolError(`page=${page} does not exist; this list has ${pages.length} pages.`);
  const shown = pages[page - 1];
  result.sections = shown;
  result.page = page;
  result.total_pages = pages.length;
  result.page_note = `This list is too long to send at once, so it comes in ${pages.length} pages. `
    + `This is page ${page} of ${pages.length} (${shown[0].identifier} to ${shown[shown.length - 1].identifier}).`
    + (page < pages.length ? ` Call again with page=${page + 1} for the rest.` : "")
    + " subpart= lists one subpart.";
  return result;
}

export const STRUCTURE_HANDLERS = {
  get_cfr_structure: getCfrStructure,
  get_ancestry: getAncestry,
  list_sections_in_part: listSectionsInPart,
};
