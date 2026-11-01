// What ecfr_mcp/_xml_text.py's parse() and paginate() return, rebuilt from
// the copy: each DIV's text was parsed at load time with the package itself
// (nodes.content, see PORT_PROGRESS.md "Content format"), so this only puts
// the pieces together the way parse() does for a section, appendix, subpart
// or part, and splits long answers into the same pages.
import {Forward, ToolError} from "./args.ts";
import {group} from "./pyjson.ts";
import {cpLen, pyInt} from "./text.ts";

export const ECFR_SITE = "https://www.ecfr.gov";
export const PAGE_CHARS = 64_000;
export const TABLE_NOTE = "Tables are in 'tables'. Each has 'table' (its number, matching the "
  + "[See table N] marker in the paragraphs), an optional 'caption', and "
  + "'rows' (lists of cell strings). [fn N] marks a footnote reference.";

/** One DIV's parsed text (nodes.content). */
export interface Content {
  n: string;
  kind: string;
  unit: Record<string, any>;
  label?: string;
  divs?: string[];
  images: number;
  pending: number;
  unparsed: number;
}

type Obj = Record<string, any>;

const UNIT_KEYS = ["heading", "paragraphs", "citations", "tables", "notes", "examples", "images", "pending_amendments", "editorial_notes"];
const PLURALS: Record<string, string> = {
  title: "titles", subtitle: "subtitles", chapter: "chapters", subchapter: "subchapters", part: "parts",
  subpart: "subparts", subject_group: "subject_groups", division: "divisions",
};

/** _Unit.as_dict(always=...): the stored unit with the always-present keys filled in, in order. */
function asDict(unit: Obj, always: string[]): Obj {
  const out: Obj = {};
  for (const key of UNIT_KEYS) {
    if (Object.hasOwn(unit, key)) out[key] = unit[key];
    else if (always.includes(key)) out[key] = key === "heading" ? "" : [];
  }
  if (Object.hasOwn(unit, "authority")) out.authority = unit.authority;
  if (Object.hasOwn(unit, "source")) out.source = unit.source;
  return out;
}

/** _metadata(): eCFR's hierarchy_metadata with the date filled in and a url. */
export function metadata(meta: Obj | null, date: string): Obj | null {
  if (meta === null || typeof meta !== "object" || Array.isArray(meta)) return null;
  const out = {...meta};
  if (typeof out.path === "string" && out.path.includes("_SUBSTITUTE_DATE_")) {
    out.path = out.path.replaceAll("/on/_SUBSTITUTE_DATE_/", `/on/${date}/`);
  }
  if (typeof out.path === "string" && out.path.startsWith("/")) out.url = ECFR_SITE + out.path;
  return Object.keys(out).length ? out : null;
}

/** _warnings(units): pending amendments, images, unparsed tables. */
function warnings(units: Content[]): string[] {
  const out: string[] = [];
  const pending = units.filter(u => u.pending);
  if (pending.length) {
    if (units.length === 1) {
      out.push("eCFR links an amendment to this text that was published in the "
        + "Federal Register and may not be in effect yet (see "
        + "pending_amendments). Check that document before relying on "
        + "this text.");
    } else {
      const names = pending.slice(0, 10).map(u => u.n || "?").join(", ");
      const more = pending.length > 10 ? ` and ${pending.length - 10} more` : "";
      out.push(`${pending.length} section(s) have a published amendment that may `
        + `not be in effect yet (${names}${more}; see each section's `
        + "pending_amendments).");
    }
  }
  const images = units.reduce((sum, u) => sum + u.images, 0);
  if (images) {
    out.push(`This text includes ${images} image(s), such as formulas, forms or `
      + "figures, that can't be shown as text; each is marked [Image: <link>] "
      + "where it appears.");
  }
  const unparsed = units.reduce((sum, u) => sum + u.unparsed, 0);
  if (unparsed) {
    out.push(`${unparsed} table(s) contained content that could not be parsed `
      + "into rows and were omitted. Use raw_xml=True to inspect.");
  }
  return out;
}

/**
 * parse() of eCFR's XML for one node: a section or appendix alone, or a
 * grouping level (part, subpart) with one object per section. `contentOf`
 * reads a descendant DIV's content by its key.
 */
export function parse(root: Content, meta: Obj | null, date: string, contentOf: (key: string) => Content): Obj {
  let result: Obj;
  let units: Content[];
  if (root.kind === "section" || root.kind === "appendix") {
    result = asDict(root.unit, ["heading", "paragraphs", "citations"]);
    units = [root];
  } else {
    // _parse_container: sections get the levels they sit in as context.
    units = [root];
    const sections: Obj[] = [];
    const groups = new Map<string, Obj[]>();
    const visit = (div: Content, context: Obj) => {
      for (const key of div.divs ?? []) {
        const child = contentOf(key);
        units.push(child);
        if (child.kind === "section" || child.kind === "appendix") {
          sections.push({[child.kind]: child.n, ...context, ...asDict(child.unit, ["heading", "paragraphs"])});
          continue;
        }
        const kind = child.kind;
        const record: Obj = kind === "subject_group" ? {...context} : {[kind]: child.n, ...context};
        if (!groups.has(kind)) groups.set(kind, []);
        groups.get(kind)!.push(record);
        const inner = {...context};
        inner[kind] = kind === "subject_group" ? child.label ?? "" : child.n;
        visit(child, inner);
        Object.assign(record, asDict(child.unit, ["heading"]));
      }
    };
    visit(root, {});
    // parse() reads a DIV with no section below it as one block of text.
    if (!sections.length) throw new Forward("no_sections");
    result = asDict(root.unit, ["heading"]);
    for (const [kind, records] of groups) result[PLURALS[kind]] = records;
    result.section_count = sections.length;
    result.sections = sections;
  }
  const hierarchy = metadata(meta, date);
  if (hierarchy) result.hierarchy_metadata = [hierarchy];
  if (result.tables?.length || (result.sections ?? []).some((s: Obj) => s.tables?.length)) result.table_note = TABLE_NOTE;
  const warned = warnings(units);
  if (warned.length) result.warning = warned.join(" ");
  return result;
}

// ---------------------------------------------------------------------------
// Pages for answers too large for one tool reply (_xml_text.paginate)
// ---------------------------------------------------------------------------

/** size_of(): characters value takes as JSON indented two spaces, nested depth levels deep. */
export function sizeOf(value: unknown, depth = 0): number {
  const text = JSON.stringify(value, null, 2);
  let lines = 1;
  for (let i = text.indexOf("\n"); i !== -1; i = text.indexOf("\n", i + 1)) lines++;
  return cpLen(text) + lines * 2 * depth;
}

const MARKER = /^\[See (table|note|example) (\p{Nd}+)(?::.*)?\]$/u;
const HEADER_KEYS = ["section", "appendix", "title", "subtitle", "chapter", "subchapter", "part",
  "subpart", "subject_group", "heading", "pending_amendments", "authority", "source"];
const TRAILER_KEYS = ["citations", "images", "editorial_notes"];
const CONTENT_KEYS = ["paragraphs", "tables", "notes", "examples"];
const GROUP_LISTS: Record<string, string> = Object.fromEntries(Object.entries(PLURALS).map(([k, v]) => [v, k]));
const pick = (unit: Obj, keys: string[]) => Object.fromEntries(keys.filter(k => Object.hasOwn(unit, k)).map(k => [k, unit[k]]));

type Atom = [kind: string, value: any];

function tablePieces(table: Obj, limit: number): Obj[] {
  if (sizeOf(table) <= limit * 0.8) return [table];
  const rows: unknown[] = table.rows ?? [];
  const head = Object.fromEntries(Object.entries(table).filter(([k]) => k !== "rows" && k !== "notes"));
  const pieces: Obj[] = [];
  let chunk: unknown[] = [];
  let chunkSize = 0;
  const budget = Math.trunc(limit * 0.6);
  for (const row of rows) {
    const rowSize = sizeOf(row, 6) + 1;
    if (chunk.length && chunkSize + rowSize > budget) {
      pieces.push({...head, rows: chunk});
      chunk = [];
      chunkSize = 0;
    }
    chunk.push(row);
    chunkSize += rowSize;
  }
  if (chunk.length) pieces.push({...head, rows: chunk});
  let first = 1;
  pieces.forEach((piece, i) => {
    if (i) {
      piece.continued = true;
      piece.header_row = rows[0];
      piece.first_row = first;
    }
    first += piece.rows.length;
  });
  if (table.notes?.length) pieces[pieces.length - 1].notes = table.notes;
  return pieces;
}

/** _atoms(): a unit's content in reading order, in pieces small enough to pack. */
function atoms(unit: Obj, limit: number): Atom[] {
  const out: Atom[] = [["start", null]];
  const used = new Set<string>();
  const place = (kind: string, number: number) => {
    const entry = (unit[kind + "s"] ?? []).find((x: Obj) => x[kind] === number);
    if (entry === undefined || used.has(`${kind} ${number}`)) return;
    used.add(`${kind} ${number}`);
    if (kind === "table") {
      for (const piece of tablePieces(entry, limit)) out.push(["tables", piece]);
      return;
    }
    out.push([kind + "s", entry]);
    for (const p of entry.paragraphs ?? []) {
      const m = MARKER.exec(p);
      if (m && m[1] === "table") place("table", Number(pyInt(m[2])));
    }
  };
  for (const p of unit.paragraphs ?? []) {
    out.push(["paragraphs", p]);
    const m = MARKER.exec(p);
    if (m) place(m[1], Number(pyInt(m[2])));
  }
  for (const kind of ["table", "note", "example"]) {
    for (const entry of unit[kind + "s"] ?? []) place(kind, entry[kind]);
  }
  // Citations and editorial notes ride with the unit's last piece; count them there.
  const trailer = pick(unit, TRAILER_KEYS);
  out.push(["end", Object.keys(trailer).length ? trailer : null]);
  return out;
}

/** _identity(): where a part/subpart/... record sits, in the same terms sections use. */
function identity(record: Obj, singular: string): string {
  const ident: [string, unknown][] = Object.entries(record).filter(([k]) => Object.hasOwn(PLURALS, k) && k !== "subject_group");
  if (singular === "subject_group") ident.push(["subject_group", record.heading ?? ""]);
  ident.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify(ident);
}

/** _Plan: where every piece of an oversized answer goes, worked out once. */
class Plan {
  totalSize: number;
  multi: boolean;
  units: Obj[];
  frame: Obj;
  groups: [plural: string, ident: string, record: Obj][] = [];
  unitGroups: number[][] = [];
  orphans: number[];
  pages: [index: number, kind: string, value: any][][] = [];
  firstPageOf = new Map<number, number>();
  lastPageOf = new Map<number, number>();

  constructor(result: Obj, limit: number) {
    this.totalSize = sizeOf(result);
    this.multi = Object.hasOwn(result, "sections");
    this.units = this.multi ? result.sections : [result];
    if (this.multi) {
      this.frame = Object.fromEntries(Object.entries(result).filter(([k]) => k !== "sections" && !Object.hasOwn(GROUP_LISTS, k)));
      for (const [plural, singular] of Object.entries(GROUP_LISTS)) {
        for (const record of result[plural] ?? []) this.groups.push([plural, identity(record, singular), record]);
      }
    } else {
      this.frame = Object.fromEntries(Object.entries(result).filter(([k]) =>
        !CONTENT_KEYS.includes(k) && !HEADER_KEYS.includes(k) && !TRAILER_KEYS.includes(k)));
    }
    const byIdentity = new Map<string, number>();
    this.groups.forEach(([, ident], i) => byIdentity.set(ident, i));
    for (const unit of this.units) {
      // Each level above the section, outermost first, is one record.
      const chain: [string, unknown][] = [];
      const wanted: number[] = [];
      for (const level of Object.keys(PLURALS)) {
        if (!Object.hasOwn(unit, level)) continue;
        chain.push([level, unit[level]]);
        const sorted = [...chain].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
        const found = byIdentity.get(JSON.stringify(sorted));
        if (found !== undefined) wanted.push(found);
      }
      this.unitGroups.push(wanted.sort((a, b) => a - b));
    }
    const groupSizes = this.groups.map(([, , record]) => sizeOf(record, 2) + 2);
    // A level with no sections of its own (a reserved subpart) goes on page 1.
    const attached = new Set(this.unitGroups.flat());
    this.orphans = this.groups.map((_, g) => g).filter(g => !attached.has(g));
    const headers = this.units.map(u => pick(u, HEADER_KEYS));
    // Inside a page, an item sits two levels down (key, list); a section's
    // items sit two more down (sections list, section).
    const depth = this.multi ? 4 : 2;
    const headerSizes = headers.map(h => sizeOf(h, depth - 1) + 60);

    const frameSize = sizeOf(this.frame) + 700; // room for the page note
    let current: [number, string, any][] = [];
    let currentSize = frameSize + this.orphans.reduce((sum, g) => sum + groupSizes[g], 0);
    let openUnit: number | null = null;
    let onPage = new Set<number>();
    const openingCost = (index: number) =>
      headerSizes[index] + this.unitGroups[index].filter(g => !onPage.has(g)).reduce((sum, g) => sum + groupSizes[g], 0);

    this.units.forEach((unit, index) => {
      for (const [kind, value] of atoms(unit, limit)) {
        const body = value !== null ? sizeOf(value, depth) + 2 : 0;
        let cost = body + (index !== openUnit ? openingCost(index) : 0);
        if (current.length && currentSize + cost > limit) {
          this.pages.push(current);
          current = [];
          currentSize = frameSize;
          onPage = new Set();
          cost = body + openingCost(index);
        }
        if (index !== openUnit || !current.length) for (const g of this.unitGroups[index]) onPage.add(g);
        current.push([index, kind, value]);
        currentSize += cost;
        openUnit = index;
      }
    });
    if (current.length) this.pages.push(current);
    this.pages.forEach((pageAtoms, i) => {
      for (const [index] of pageAtoms) {
        if (!this.firstPageOf.has(index)) this.firstPageOf.set(index, i + 1);
        this.lastPageOf.set(index, i + 1);
      }
    });
  }

  page(page: number, narrower: string): Obj {
    const total = this.pages.length;
    if (page > total) throw new ToolError(`page=${page} does not exist; this answer has ${total} pages.`);
    const pieces: Obj[] = [];
    const byUnit = new Map<number, Obj>();
    for (const [index, kind, value] of this.pages[page - 1]) {
      let piece = byUnit.get(index);
      if (piece === undefined) {
        piece = pick(this.units[index], HEADER_KEYS);
        if (this.firstPageOf.get(index)! < page) piece.continued_from_previous_page = true;
        piece.paragraphs = [];
        byUnit.set(index, piece);
        pieces.push(piece);
      }
      if (kind !== "start" && kind !== "end") (piece[kind] ??= []).push(value);
    }
    for (const [index, piece] of byUnit) {
      if (this.lastPageOf.get(index)! > page) piece.continues_on_next_page = true;
      else Object.assign(piece, pick(this.units[index], TRAILER_KEYS));
    }
    const out: Obj = {...this.frame};
    if (this.multi) {
      const wanted = new Set<number>();
      for (const index of byUnit.keys()) for (const g of this.unitGroups[index]) wanted.add(g);
      if (page === 1) for (const g of this.orphans) wanted.add(g);
      for (const g of [...wanted].sort((a, b) => a - b)) {
        const [plural, , record] = this.groups[g];
        (out[plural] ??= []).push(record);
      }
      out.sections = pieces;
    } else {
      Object.assign(out, pieces[0] ?? {});
    }
    out.page = page;
    out.total_pages = total;
    out.page_note = `This answer is about ${group(String(this.totalSize))} characters, too long to send at once, `
      + `so it comes in ${total} pages. This is page ${page} of ${total}.`
      + (page < total ? ` Call again with page=${page + 1} for the next part.` : " This is the last page.")
      + (narrower ? ` ${narrower}` : "");
    return out;
  }
}

/** paginate(): page `page` (1-based) of result, or result itself when it fits. */
export function paginate(result: Obj, page: number, narrower = "", limit = PAGE_CHARS): Obj {
  if (sizeOf(result) <= limit) {
    if (page !== 1) throw new ToolError(`This answer fits on one page; page=${page} does not exist. Use page=1.`);
    return result;
  }
  return new Plan(result, limit).page(page, narrower);
}
