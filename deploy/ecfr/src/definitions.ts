// ecfr_mcp/_definitions.py's find(): a term's definition blocks in FAR 2.101
// and the other paragraphs that mention it. Only the found case is ported:
// with no definition the Python server searches the rest of the FAR live, so
// the Worker forwards those questions.
import {SPACE, WORD, cpLen, escapeRegex, strip} from "./text.ts";

const S = `[${SPACE}]`;
const B = `(?![${WORD}])`;

// The italic names at the start of a definition: "*A* or *B* means", "*A, B,* or *C*".
const LEAD = /^\*([^*]+)\*/;
const MORE_NAMES = new RegExp(`^${S}*(?:,|or|,${S}*or)${S}*\\*([^*]+)\\*`, "u");
const TRAILING_ACRONYM = new RegExp(`^${S}*\\(([A-Z][A-Za-z&']{1,10})\\)`, "u");
const PAREN_ACRONYM = new RegExp(`${S}*\\(([A-Z][A-Za-z&'.]{1,12}?)(?:'s)?\\)${S}*`, "u");
const SEE = /\(see [\u201c"]([^\u201d"]+)[\u201d"]\)|has the same meaning as \*([^*]+)\*/giu;
// Common acronyms 2.101 never spells out next to the term.
const ACRONYMS: Record<string, string> = {
  SAT: "simplified acquisition threshold",
  MPT: "micro-purchase threshold",
  UEI: "unique entity identifier",
};
const ALIASES: [string, string][] = [
  ["commercial off-the-shelf", "commercially available off-the-shelf item"],
  ["commercial off-the-shelf item", "commercially available off-the-shelf item"],
];
const QUERY_NOISE = new RegExp(`^(?:what${S}+is${S}+|define${S}+|definition${S}+of${S}+|the${S}+definition${S}+of${S}+|the${S}+term${S}+|the${S}+|an?${S}+)+`, "iu");
const QUERY_TAIL = new RegExp(`(?:${S}+(?:means|is${S}+defined${S}+as|meaning))+${S}*[\u2014\u2013:-]*${S}*$`, "iu");
// An explicitly introduced list of types can define names without italic leads.
const TYPES = new RegExp(`(?<![${WORD}])types${B}.*(?<![${WORD}])are as follows:${S}*$`, "iu");
const TYPE_LEAD = new RegExp(`^\\((\\p{Nd}+)\\)${S}+(?:An?${S}+)?([A-Za-z][A-Za-z '-]*?)${S}+(?:is|means)${S}`, "iu");
const NUMBERED = new RegExp(`^\\((\\p{Nd}+)\\)${S}`, "u");

/** str.strip(chars) / str.rstrip(chars). */
function stripChars(text: string, chars: string, left = true): string {
  const list = [...text];
  let start = 0;
  let end = list.length;
  while (left && start < end && chars.includes(list[start])) start++;
  while (end > start && chars.includes(list[end - 1])) end--;
  return list.slice(start, end).join("");
}

/** Compare names without punctuation, case, spacing or possessive suffixes. */
export function key(text: string): string {
  return text.toLowerCase().replace(new RegExp(`['\u2019]s${B}`, "gu"), "").replace(/[^a-z0-9&]/g, "");
}

/** 'commercial services' -> 'commercial service'; 'supplies' -> 'supply'. */
export function singular(text: string): string {
  const words = text.replace(new RegExp(`${S}+$`, "u"), "").split(" ");
  let last = words[words.length - 1];
  const low = last.toLowerCase();
  if (cpLen(low) > 4 && low.endsWith("ies")) last = last.slice(0, -3) + "y";
  else if (cpLen(low) > 4 && /(?:ches|shes|sses|xes)$/.test(low)) last = last.slice(0, -2);
  else if (cpLen(low) > 3 && low.endsWith("s") && !low.endsWith("ss")) last = last.slice(0, -1);
  words[words.length - 1] = last;
  return words.join(" ");
}

export function cleanQuery(term: string): string {
  let text = stripChars(strip(term), "\u201c\u201d\"'\u2018\u2019?.:;");
  text = text.replace(QUERY_NOISE, "");
  text = text.replace(QUERY_TAIL, "");
  return stripChars(strip(text), "\u201c\u201d\"'\u2018\u2019,");
}

/** The names a definition goes by, and its acronyms. */
function names(lead: string): [string[], string[]] {
  const out: string[] = [];
  const m = LEAD.exec(lead);
  if (!m) return [out, []];
  const raw = [m[1]];
  let rest = lead.slice(m[0].length);
  for (;;) {
    const more = MORE_NAMES.exec(rest);
    if (!more) break;
    raw.push(more[1]);
    rest = rest.slice(more[0].length);
  }
  const acronyms: string[] = [];
  const trailing = TRAILING_ACRONYM.exec(rest);
  if (trailing) acronyms.push(trailing[1]);
  for (const name of raw) {
    // "In writing, writing," names two; trailing punctuation and dashes go.
    for (let part of name.split(new RegExp(`,${S}+(?=[a-z])`, "u"))) {
      part = strip(stripChars(strip(part), ",.\u2014-\u2013 ", false));
      if (part && !out.includes(part)) out.push(part);
    }
  }
  for (const name of [...out]) {
    const acr = PAREN_ACRONYM.exec(name);
    if (!acr) continue;
    const acronym = stripChars(acr[1], ".", false);
    acronyms.push(acronym);
    const before = strip(name.slice(0, acr.index));
    const after = strip(name.slice(acr.index + acr[0].length));
    for (const variant of [strip(`${before} ${after}`), strip(`${acronym} ${after}`)]) {
      if (variant && !out.includes(variant)) out.push(variant);
    }
  }
  return [out, [...new Set(acronyms)]];
}

interface Block {
  term: string;
  names: string[];
  acronyms: string[];
  start: number;
  end: number;
  keys: Set<string>;
}

/** Definition blocks of 2.101: lead paragraph plus the paragraphs under it. */
function indexDefinitions(paragraphs: string[]): Block[] {
  const blocks: Block[] = [];
  paragraphs.forEach((p, i) => {
    if (LEAD.test(p)) {
      const [found, acronyms] = names(p);
      blocks.push({term: found.length ? found[0] : [...p].slice(0, 60).join(""), names: found, acronyms, start: i, end: i + 1, keys: new Set()});
    } else if (blocks.length) {
      blocks[blocks.length - 1].end = i + 1;
    }
  });
  // Each explicit subtype is also indexed through the next sibling.
  const subtypes: Block[] = [];
  for (const block of blocks) {
    if (!TYPES.test(paragraphs[block.start])) continue;
    for (let i = block.start + 1; i < block.end; i++) {
      const lead = TYPE_LEAD.exec(paragraphs[i]);
      if (!lead) continue;
      let end = block.end;
      for (let j = i + 1; j < block.end; j++) {
        if (NUMBERED.test(paragraphs[j])) {
          end = j;
          break;
        }
      }
      subtypes.push({term: lead[2], names: [lead[2]], acronyms: [], start: i, end, keys: new Set()});
    }
  }
  blocks.push(...subtypes);
  for (const block of blocks) {
    for (const name of block.names) {
      block.keys.add(key(name));
      block.keys.add(key(singular(name)));
    }
  }
  return blocks;
}

function phrasePattern(text: string): RegExp {
  const words = strip(text).split(new RegExp(`[${SPACE}\\-\u2013\u2014]+`, "u")).filter(Boolean).map(escapeRegex);
  return new RegExp(`(?<![A-Za-z0-9])${words.join(`[${SPACE}\\-\u2013\u2014]*`)}(?:s|es)?(?![A-Za-z0-9])`, "iu");
}

const WORDS = /[a-z0-9&]+/g;
const intersects = (a: Set<string>, b: Iterable<string>) => [...b].some(x => a.has(x));

/** Definition blocks for term (best first) and the other paragraphs that mention it. */
export function find(paragraphs: string[], term: string) {
  const query = cleanQuery(term);
  const blocks = indexDefinitions(paragraphs);
  const wanted = [key(query), key(singular(query))];
  const how = new Map<number, string>();
  blocks.forEach((block, n) => {
    if (!intersects(block.keys, wanted)) return;
    const primary = block.names.length ? block.names[0] : "";
    how.set(n, intersects(new Set([key(primary), key(singular(primary))]), wanted) ? "name" : "other name");
  });
  const upper = query.replace(/[^A-Za-z0-9&]/g, "").toUpperCase();
  if (!how.size) {
    blocks.forEach((block, n) => {
      if (block.acronyms.some(a => a.toUpperCase() === upper || a.toUpperCase() + "S" === upper) && !how.has(n)) how.set(n, "acronym");
    });
  }
  if (!how.size && Object.hasOwn(ACRONYMS, upper)) {
    const expanded = ACRONYMS[upper];
    blocks.forEach((block, n) => {
      if (block.keys.has(key(expanded))) how.set(n, `acronym ${upper}`);
    });
  }
  if (!how.size) {
    const alias = ALIASES.find(([name]) => wanted.includes(key(singular(name))))?.[1];
    if (alias) blocks.forEach((block, n) => {
      if (block.keys.has(key(alias))) how.set(n, "common name");
    });
  }
  if (!how.size) {
    // Omitted trailing words count only when the whole-word prefix names exactly one definition.
    const words = query.toLowerCase().match(WORDS) ?? [];
    const prefixes = new Set<number>();
    if (words.length >= 2) {
      blocks.forEach((block, n) => {
        for (const name of block.names) {
          const nameWords = name.toLowerCase().match(WORDS) ?? [];
          if (nameWords.length > words.length && words.every((w, i) => nameWords[i] === w)) prefixes.add(n);
        }
      });
    }
    if (prefixes.size === 1) how.set([...prefixes][0], "unique name prefix");
  }
  const rank: Record<string, number> = {"name": 0, "other name": 1};
  const found = [...how.keys()].sort((a, b) =>
    (rank[how.get(a)!] ?? 2) - (rank[how.get(b)!] ?? 2) || cpLen(blocks[a].term) - cpLen(blocks[b].term));
  // Cross-references ("Procurement (see \u201cacquisition\u201d)") bring the target along.
  for (const n of [...found]) {
    const block = blocks[n];
    for (const see of paragraphs[block.start].matchAll(SEE)) {
      const name = see[1] || see[2];
      const targets = [key(singular(name)), key(name)];
      blocks.forEach((other, m) => {
        if (!how.has(m) && intersects(other.keys, targets)) {
          how.set(m, `referred to by ${block.term}`);
          found.push(m);
        }
      });
    }
  }
  const definitions = [];
  const covered = new Set<number>();
  for (const n of found) {
    const block = blocks[n];
    for (let i = block.start; i < block.end; i++) covered.add(i);
    definitions.push({
      kind: "definition",
      term: block.term,
      matched_by: how.get(n)!,
      paragraph_index: block.start,
      context: paragraphs.slice(block.start, block.end),
    });
  }
  const pattern = phrasePattern(singular(query));
  const owner = new Map<number, string>();
  for (const block of blocks) for (let i = block.start; i < block.end; i++) owner.set(i, block.term);
  const mentions = [];
  for (let i = 0; i < paragraphs.length; i++) {
    if (covered.has(i)) continue;
    if (!pattern.test(paragraphs[i].replaceAll("*", ""))) continue;
    const mention: Record<string, unknown> = {kind: "mention", paragraph_index: i, context: [paragraphs[i]]};
    if (owner.has(i)) mention.term = owner.get(i);
    mentions.push(mention);
  }
  return {query, definitions, mentions};
}
