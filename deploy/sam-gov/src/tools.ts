// The four hosted SAM.gov tools. Every answer comes from the D1 mirror of
// SAM.gov's public contract opportunities file (see schema.sql and
// scripts/load_sam_opportunities.py); no SAM.gov API key is used.

export interface Database {
  prepare(sql: string): {bind(...values: unknown[]): {all<T = Record<string, unknown>>(): Promise<{results: T[]}>}};
}

type Row = Record<string, any>;
type Args = Record<string, unknown>;

export class ToolError extends Error {}

export const NOTICE_TYPES = [
  "Solicitation", "Combined Synopsis/Solicitation", "Presolicitation", "Sources Sought",
  "Special Notice", "Award Notice", "Justification", "Justification and Approval (J&A)",
  "Modification/Amendment/Cancel", "Consolidate/(Substantially) Bundle", "Sale of Surplus Property",
];

/** Notice types nobody responds to; never dropped by the past-deadline filter. */
const NO_RESPONSE_TYPES = ["Award Notice", "Justification", "Justification and Approval (J&A)"];

export const SET_ASIDE_CODES = [
  "SBA", "SBP", "8A", "8AN", "HZC", "HZS", "SDVOSBC", "SDVOSBS", "WOSB", "WOSBSS", "EDWOSB",
  "EDWOSBSS", "VSA", "VSS", "ISBEE", "IEE", "BICiv", "LAS", "ESB", "NONE",
];

const GROUPS: Record<string, string> = {
  agency: "department",
  sub_tier: "sub_tier",
  office: "office",
  naics: "naics_code",
  psc: "psc_code",
  set_aside: "set_aside_code",
  notice_type: "notice_type",
  place_of_performance_state: "pop_state",
  office_state: "office_state",
  posted_month: "substr(posted_date, 1, 7)",
};

const SOURCE = "SAM.gov public Contract Opportunities file (ContractOpportunitiesFullCSV.csv)";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const NOTICE_ID = /^[0-9a-f]{32}$/i;

const READ_ONLY = {readOnlyHint: true, destructiveHint: false, openWorldHint: false};
const dateField = (description: string) => ({type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$", description});
const codeList = (description: string) => ({type: "array", items: {type: "string"}, maxItems: 20, description});

const FILTERS = {
  keywords: {type: "string", maxLength: 300, description: "Words that must all appear in the title or full description. Put exact phrases in double quotes, e.g. zero trust \"cloud migration\". Word endings are matched loosely (bridge matches bridges)."},
  notice_types: {type: "array", items: {type: "string", enum: NOTICE_TYPES}, description: "Current notice types to include. Omit for all types."},
  naics_codes: codeList("NAICS codes or prefixes (2 to 6 digits); a prefix such as 5415 matches every code under it."),
  psc_codes: codeList("Product and service codes or prefixes, e.g. D3 or R425."),
  set_aside_codes: {type: "array", items: {type: "string", enum: SET_ASIDE_CODES}, description: "SAM.gov set-aside codes, e.g. SBA (total small business), 8A, SDVOSBC, WOSB, HZC. NONE means the notice says no set-aside was used."},
  agency: {type: "string", maxLength: 200, description: "Text matched against the department, sub-tier, and office names, e.g. Army, Veterans Affairs, NSWC Dahlgren. Field activities post under their own office names, so a command name matches only its headquarters office (NAVSEA matches NAVSEA HQ, not NSWC or NUWC offices)."},
  place_of_performance_state: {type: "string", pattern: "^[A-Za-z]{2}$", description: "Two-letter state code for the place of performance. Most notices leave the place of performance blank, so results also report how many more notices have a contracting office in that state (see office_state)."},
  office_state: {type: "string", pattern: "^[A-Za-z]{2}$", description: "Two-letter state code of the contracting office. Filled in on nearly every notice, but an office's state is not always where the work happens."},
  solicitation_number: {type: "string", maxLength: 100, description: "Exact solicitation number."},
  posted_from: dateField("Earliest posted date, YYYY-MM-DD."),
  posted_to: dateField("Latest posted date, YYYY-MM-DD."),
  deadline_from: dateField("Earliest response deadline date, YYYY-MM-DD, in the deadline's own time zone."),
  deadline_to: dateField("Latest response deadline date, YYYY-MM-DD."),
  include_past_deadlines: {type: "boolean", default: false, description: "Include notices whose response deadline has already passed. SAM.gov keeps notices active for a while after the deadline; by default they are left out. Award notices and justifications are always included, even when they list a past deadline, and so are notices with no deadline."},
  include_earlier_versions: {type: "boolean", default: false, description: "Include earlier versions of amended notices. SAM.gov's file lists every version of a notice as its own row; by default only the latest version of each is included."},
};

export const TOOLS = [
  {
    name: "search_opportunities",
    description: "Search active SAM.gov contract opportunity notices: solicitations, combined synopses, presolicitations, sources sought, special notices, award notices, and justifications.\n\nAll filters combine. Keyword search covers titles and full descriptions. By default, only the latest version of each amended notice is included, notices whose response deadline has passed are left out, and results are sorted by soonest deadline, with notices that have no deadline last. Returns up to 100 notices per call with the total match count; use offset to page. Use get_opportunity for a notice's full description and contacts.\n\nData is SAM.gov's public daily file of active notices, not live SAM.gov. Archived notices and attachments are not included.",
    inputSchema: {
      type: "object",
      properties: {
        ...FILTERS,
        sort: {type: "string", enum: ["deadline", "newest", "relevance"], default: "deadline", description: "deadline: soonest response deadline first. newest: most recently posted first. relevance: best keyword match first (needs keywords)."},
        limit: {type: "integer", minimum: 1, maximum: 100, default: 25},
        offset: {type: "integer", minimum: 0, maximum: 10000, default: 0},
      },
      additionalProperties: false,
    },
    annotations: {title: "Search Opportunities", ...READ_ONLY},
  },
  {
    name: "get_opportunity",
    description: "Get one SAM.gov notice in full: description, response deadline, set-aside, NAICS and PSC codes, place of performance, contracting office, points of contact, award details for award notices, and the public sam.gov link. Also lists other active notices with the same solicitation number, such as earlier versions, amendments, or awards (with awardee and amount).\n\nPass the 32-character notice ID from search results, or a solicitation number (returns its most recently posted current notice, preferring the solicitation over award notices and justifications). Attachments are not retrieved; open the sam.gov link for them.",
    inputSchema: {
      type: "object",
      properties: {
        notice_id: {type: "string", pattern: "^[0-9a-fA-F]{32}$", description: "32-character SAM.gov notice ID."},
        solicitation_number: {type: "string", maxLength: 100, description: "Solicitation number, used when notice_id is not given."},
      },
      additionalProperties: false,
    },
    annotations: {title: "Get Opportunity", ...READ_ONLY},
  },
  {
    name: "summarize_opportunities",
    description: "Count active SAM.gov notices grouped by agency, sub-tier, office, NAICS, PSC, set-aside, notice type, place-of-performance state, contracting office state, or posted month. Accepts the same filters as search_opportunities, e.g. counts of open solicitations under one NAICS by set-aside, or which agencies posted the most sources sought notices this quarter.\n\nCounts cover active notices in SAM.gov's public daily file only, not archived or historical notices.",
    inputSchema: {
      type: "object",
      properties: {
        group_by: {type: "string", enum: Object.keys(GROUPS), description: "Field to group counts by."},
        ...FILTERS,
        top: {type: "integer", minimum: 1, maximum: 100, default: 25, description: "Number of groups to return, largest first. For posted_month, the most recent months, in month order."},
      },
      required: ["group_by"],
      additionalProperties: false,
    },
    annotations: {title: "Summarize Opportunities", ...READ_ONLY},
  },
  {
    name: "get_data_status",
    description: "Report the date of the SAM.gov file behind every answer, when it was loaded, how many active notices it holds by type, and what changed in the last nightly load. Use it to judge how current results are.",
    inputSchema: {type: "object", properties: {}, additionalProperties: false},
    annotations: {title: "Get Data Status", ...READ_ONLY},
  },
];

// ---------- argument helpers ----------

function str(args: Args, key: string, max = 300): string | undefined {
  const value = args[key];
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string") throw new ToolError(`${key} must be a string.`);
  const trimmed = value.trim();
  if (trimmed.length > max) throw new ToolError(`${key} is longer than ${max} characters.`);
  return trimmed || undefined;
}

function date(args: Args, key: string): string | undefined {
  const value = str(args, key, 10);
  if (value === undefined) return undefined;
  const parsed = new Date(value + "T00:00:00Z");
  if (!DATE.test(value) || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new ToolError(`${key} must be a real date in YYYY-MM-DD form.`);
  }
  return value;
}

function int(args: Args, key: string, fallback: number, min: number, max: number): number {
  const value = args[key];
  if (value === undefined || value === null) return fallback;
  const n = typeof value === "string" && /^\d+$/.test(value) ? Number(value) : value;
  if (typeof n !== "number" || !Number.isInteger(n) || n < min || n > max) {
    throw new ToolError(`${key} must be a whole number from ${min} to ${max}.`);
  }
  return n;
}

function list(args: Args, key: string, pattern: RegExp, hint: string, allowed?: string[]): string[] {
  let value = args[key];
  if (value === undefined || value === null || value === "") return [];
  if (typeof value === "string") value = value.split(",");
  if (!Array.isArray(value)) throw new ToolError(`${key} must be a list.`);
  if (value.length > 20) throw new ToolError(`${key} accepts at most 20 values.`);
  return value.map(item => {
    const text = String(item).trim();
    const match = allowed?.find(a => a.toLowerCase() === text.toLowerCase()) ?? text;
    if (allowed ? !allowed.includes(match) : !pattern.test(match)) throw new ToolError(`${key}: ${JSON.stringify(text)} is not ${hint}.`);
    return allowed ? match : match.toUpperCase();
  });
}

function bool(args: Args, key: string): boolean {
  const value = args[key];
  if (value === undefined || value === null) return false;
  if (typeof value === "boolean") return value;
  if (value === "true" || value === "false") return value === "true";
  throw new ToolError(`${key} must be true or false.`);
}

function unknownKeys(args: Args, allowed: string[]) {
  const extra = Object.keys(args).filter(k => !allowed.includes(k));
  if (extra.length) throw new ToolError(`Unknown argument${extra.length > 1 ? "s" : ""}: ${extra.join(", ")}. Allowed: ${allowed.join(", ")}.`);
}

/** Turn user keywords into an FTS5 query: every word and quoted phrase must match. */
export function ftsQuery(keywords: string): string | undefined {
  const terms: string[] = [];
  for (const [, phrase, word] of keywords.matchAll(/"([^"]*)"|(\S+)/g)) {
    const text = (phrase ?? word).replace(/[^\p{L}\p{N}\s]+/gu, " ").trim();
    if (!text || (!phrase && /^(AND|OR|NOT|NEAR)$/.test(text))) continue;
    terms.push(`"${text.replace(/\s+/g, " ")}"`);
  }
  return terms.length ? terms.join(" ") : undefined;
}

// ---------- query building ----------

interface Query {
  from: string;
  where: string[];
  params: unknown[];
  fts: boolean;
  notes: string[];
}

function buildQuery(args: Args, now: Date): Query {
  const q: Query = {from: "opportunities o", where: [], params: [], fts: false, notes: []};
  const keywords = str(args, "keywords");
  if (keywords !== undefined) {
    const match = ftsQuery(keywords);
    if (!match) throw new ToolError("keywords has no searchable words.");
    q.from = "opportunities_fts JOIN opportunities o ON o.rowid = opportunities_fts.rowid";
    q.where.push("opportunities_fts MATCH ?");
    q.params.push(match);
    q.fts = true;
  }
  const types = list(args, "notice_types", /./, "a SAM.gov notice type", NOTICE_TYPES);
  if (types.length) {
    q.where.push(`o.notice_type IN (${types.map(() => "?").join(", ")})`);
    q.params.push(...types);
  }
  const prefixes = (key: string, column: string, pattern: RegExp, hint: string) => {
    const codes = list(args, key, pattern, hint);
    if (!codes.length) return;
    q.where.push("(" + codes.map(() => `o.${column} LIKE ?`).join(" OR ") + ")");
    q.params.push(...codes.map(c => c + "%"));
  };
  prefixes("naics_codes", "naics_code", /^\d{2,6}$/, "a 2- to 6-digit NAICS code");
  prefixes("psc_codes", "psc_code", /^[A-Z0-9]{1,4}$/i, "a PSC code or prefix of up to 4 characters");
  const setAsides = list(args, "set_aside_codes", /./, "a SAM.gov set-aside code", SET_ASIDE_CODES);
  if (setAsides.length) {
    q.where.push(`o.set_aside_code IN (${setAsides.map(() => "?").join(", ")})`);
    q.params.push(...setAsides);
  }
  const agency = str(args, "agency", 200);
  if (agency !== undefined) {
    q.where.push("(o.department LIKE ? OR o.sub_tier LIKE ? OR o.office LIKE ?)");
    const like = `%${agency.replace(/[%_]/g, "")}%`;
    q.params.push(like, like, like);
  }
  for (const [key, column] of [["place_of_performance_state", "pop_state"], ["office_state", "office_state"]]) {
    const state = str(args, key, 2);
    if (state === undefined) continue;
    if (!/^[A-Za-z]{2}$/.test(state)) throw new ToolError(`${key} must be a two-letter code.`);
    q.where.push(`o.${column} = ?`);
    q.params.push(state.toUpperCase());
  }
  const sol = str(args, "solicitation_number", 100);
  if (sol !== undefined) {
    q.where.push("o.solicitation_number = ? COLLATE NOCASE");
    q.params.push(sol);
  }
  const ranges: [string, string, string][] = [
    ["posted_from", "o.posted_date >= ?", ""], ["posted_to", "o.posted_date <= ?", ""],
    ["deadline_from", "substr(o.response_deadline, 1, 10) >= ?", ""], ["deadline_to", "substr(o.response_deadline, 1, 10) <= ?", ""],
  ];
  for (const [key, clause] of ranges) {
    const value = date(args, key);
    if (value !== undefined) {
      q.where.push(clause);
      q.params.push(value);
    }
  }
  const today = now.toISOString().slice(0, 10);
  q.where.push("(o.archive_date IS NULL OR o.archive_date >= ?)");
  q.params.push(today);
  if (!bool(args, "include_earlier_versions")) {
    q.where.push("o.is_latest = 1");
  }
  if (!bool(args, "include_past_deadlines")) {
    // Award notices and justifications take no responses; a deadline on them
    // (e.g. GSA's placeholder on schedule awards) is not one to filter on.
    q.where.push(`(o.notice_type IN (${NO_RESPONSE_TYPES.map(() => "?").join(", ")}) OR o.response_deadline_utc IS NULL OR o.response_deadline_utc >= ?)`);
    q.params.push(...NO_RESPONSE_TYPES, now.toISOString().slice(0, 19) + "Z");
    q.notes.push("Notices whose response deadline has passed are excluded (award notices and justifications are kept); set include_past_deadlines to true to include them.");
  }
  return q;
}

const whereSql = (q: Query) => (q.where.length ? " WHERE " + q.where.join(" AND ") : "");

/** Most notices leave the place of performance blank. When filtering on it,
 * count the other matches whose contracting office is in that state. */
async function officeStateHint(db: Database, args: Args, now: Date): Promise<string | undefined> {
  const state = str(args, "place_of_performance_state", 2)?.toUpperCase();
  if (!state || str(args, "office_state", 2) !== undefined) return undefined;
  const q = buildQuery({...args, place_of_performance_state: undefined, office_state: state}, now);
  q.where.push("o.pop_state IS NULL");
  const {results} = await db.prepare(`SELECT COUNT(*) AS n FROM ${q.from}${whereSql(q)}`).bind(...q.params).all<{n: number}>();
  const n = results[0]?.n ?? 0;
  if (!n) return undefined;
  return `${n} more matching notices leave the place of performance blank but have a contracting office in ${state}; set office_state to "${state}" (instead of place_of_performance_state) to include them. An office's state is not always where the work happens.`;
}

/** Without a notice type filter, results mix in award notices and
 * justifications, which take no responses. Count them so answers can say so. */
async function noResponseCount(db: Database, args: Args, q: Query): Promise<number> {
  if (list(args, "notice_types", /./, "a SAM.gov notice type", NOTICE_TYPES).length) return 0;
  const where = [...q.where, `o.notice_type IN (${NO_RESPONSE_TYPES.map(() => "?").join(", ")})`];
  const {results} = await db.prepare(`SELECT COUNT(*) AS n FROM ${q.from} WHERE ${where.join(" AND ")}`).bind(...q.params, ...NO_RESPONSE_TYPES).all<{n: number}>();
  return results[0]?.n ?? 0;
}

function noResponseNote(n: number, total: number): string | undefined {
  if (!n) return undefined;
  const verb = n === 1 ? "is an award notice or justification" : "are award notices or justifications";
  return `${n} of the ${total} matches ${verb}, which take no responses; set notice_types (e.g. Solicitation, Combined Synopsis/Solicitation) to leave them out.`;
}

export function publicLink(noticeId: string): string {
  return `https://sam.gov/opp/${noticeId}/view`;
}

function award(row: Row) {
  if (!row.award_number && !row.awardee && row.award_amount === null && !row.award_date) return undefined;
  // An awardee alone on a notice that is not an award or justification is
  // stray text in the file (e.g. a ZIP code), not an award.
  if (!NO_RESPONSE_TYPES.includes(row.notice_type) && !row.award_number && row.award_amount === null && !row.award_date) return undefined;
  return {number: row.award_number, date: row.award_date, amount: row.award_amount, awardee: row.awardee};
}

function place(row: Row) {
  const value = {street: row.pop_street, city: row.pop_city, state: row.pop_state, zip: row.pop_zip, country: row.pop_country};
  return Object.values(value).some(v => v) ? value : undefined;
}

function summary(row: Row) {
  return {
    notice_id: row.notice_id,
    title: row.title,
    solicitation_number: row.solicitation_number,
    notice_type: row.notice_type,
    department: row.department,
    sub_tier: row.sub_tier,
    office: row.office,
    posted_date: row.posted_date,
    response_deadline: row.response_deadline,
    set_aside: row.set_aside_code ? {code: row.set_aside_code, name: row.set_aside} : undefined,
    naics_code: row.naics_code,
    psc_code: row.psc_code,
    place_of_performance: place(row),
    award: award(row),
    superseded_by_newer_version: row.is_latest === 0 ? true : undefined,
    link: publicLink(row.notice_id),
  };
}

async function status(db: Database): Promise<Row> {
  const {results} = await db.prepare("SELECT key, value FROM load_status").bind().all<{key: string; value: string}>();
  return Object.fromEntries(results.map(r => [r.key, JSON.parse(r.value)]));
}

async function dataAsOf(db: Database): Promise<string | null> {
  const {results} = await db.prepare("SELECT value FROM load_status WHERE key = 'file_date'").bind().all<{value: string}>();
  return results.length ? JSON.parse(results[0].value) : null;
}

const SUMMARY_COLUMNS = "o.notice_id, o.title, o.solicitation_number, o.notice_type, o.department, o.sub_tier, o.office, o.posted_date, o.response_deadline, o.set_aside_code, o.set_aside, o.naics_code, o.psc_code, o.pop_street, o.pop_city, o.pop_state, o.pop_zip, o.pop_country, o.award_number, o.award_date, o.award_amount, o.awardee, o.is_latest";

// ---------- tools ----------

export async function searchOpportunities(db: Database, args: Args, now = new Date()) {
  unknownKeys(args, Object.keys(TOOLS[0].inputSchema.properties));
  const q = buildQuery(args, now);
  const limit = int(args, "limit", 25, 1, 100);
  const offset = int(args, "offset", 0, 0, 10000);
  const sort = str(args, "sort", 20) ?? "deadline";
  let order: string;
  if (sort === "relevance") {
    if (!q.fts) throw new ToolError("sort=relevance needs keywords.");
    order = "bm25(opportunities_fts, 10.0, 1.0), o.posted_date DESC";
  } else if (sort === "newest") {
    order = "o.posted_at DESC, o.notice_id";
  } else if (sort === "deadline") {
    order = "o.response_deadline_utc IS NULL, o.response_deadline_utc, o.posted_at DESC, o.notice_id";
  } else {
    throw new ToolError("sort must be deadline, newest, or relevance.");
  }
  const where = whereSql(q);
  const [count, page, asOf, hint, noResponse] = await Promise.all([
    db.prepare(`SELECT COUNT(*) AS n FROM ${q.from}${where}`).bind(...q.params).all<{n: number}>(),
    db.prepare(`SELECT ${SUMMARY_COLUMNS} FROM ${q.from}${where} ORDER BY ${order} LIMIT ? OFFSET ?`).bind(...q.params, limit, offset).all(),
    dataAsOf(db),
    officeStateHint(db, args, now),
    noResponseCount(db, args, q),
  ]);
  const total = count.results[0]?.n ?? 0;
  const results = page.results.map(summary);
  const notes = [...q.notes];
  const typeNote = noResponseNote(noResponse, total);
  if (typeNote) notes.push(typeNote);
  if (hint) notes.push(hint);
  if (total === 0) notes.push("No active notices matched. Try fewer filters, a NAICS prefix, include_past_deadlines, or a wider date range. Archived notices are not searchable here.");
  return {
    total_matches: total,
    returned: results.length,
    offset,
    next_offset: offset + results.length < total ? offset + results.length : null,
    data_as_of: asOf,
    results,
    notes,
    source: SOURCE,
  };
}

export async function getOpportunity(db: Database, args: Args) {
  unknownKeys(args, ["notice_id", "solicitation_number"]);
  const id = str(args, "notice_id", 32);
  const sol = str(args, "solicitation_number", 100);
  let rows: Row[];
  if (id !== undefined) {
    if (!NOTICE_ID.test(id)) throw new ToolError("notice_id must be the 32-character hexadecimal notice ID from SAM.gov.");
    rows = (await db.prepare("SELECT * FROM opportunities WHERE notice_id = ?").bind(id.toLowerCase()).all()).results;
  } else if (sol !== undefined) {
    // Prefer the solicitation (or other current notice) over the award
    // notices and justifications that share its number.
    const awardFirst = `notice_type IN (${NO_RESPONSE_TYPES.map(() => "?").join(", ")})`;
    rows = (await db.prepare(`SELECT * FROM opportunities WHERE solicitation_number = ? COLLATE NOCASE ORDER BY is_latest DESC, ${awardFirst}, posted_at DESC LIMIT 1`).bind(sol, ...NO_RESPONSE_TYPES).all()).results;
  } else {
    throw new ToolError("Pass notice_id or solicitation_number.");
  }
  const asOf = await dataAsOf(db);
  if (!rows.length) {
    return {
      found: false,
      data_as_of: asOf,
      message: "No active notice matches. It may be archived, removed, or newer than the latest daily file. Check sam.gov directly.",
      ...(id ? {link: publicLink(id.toLowerCase())} : {}),
    };
  }
  const row = rows[0];
  let related: Row[] = [];
  let relatedTotal = 0;
  if (row.solicitation_number) {
    const [page, count] = await Promise.all([
      db.prepare("SELECT notice_id, notice_type, title, posted_date, response_deadline, award_number, awardee, award_amount, is_latest FROM opportunities WHERE solicitation_number = ? COLLATE NOCASE AND notice_id != ? ORDER BY is_latest DESC, posted_at DESC LIMIT 20")
        .bind(row.solicitation_number, row.notice_id).all<Row>(),
      db.prepare("SELECT COUNT(*) AS n FROM opportunities WHERE solicitation_number = ? COLLATE NOCASE AND notice_id != ?")
        .bind(row.solicitation_number, row.notice_id).all<{n: number}>(),
    ]);
    related = page.results.map(({is_latest, award_number, awardee, award_amount, ...r}) => ({
      ...r,
      ...(r.notice_type === "Award Notice" ? {award_number, awardee, award_amount} : {}),
      latest_version: is_latest === 1,
      link: publicLink(r.notice_id),
    }));
    relatedTotal = count.results[0]?.n ?? 0;
  }
  const notes = ["Attachments and amendment documents are not included; open the sam.gov link for them."];
  if (row.is_latest === 0) notes.unshift("A newer version of this notice exists; related_notices entries with latest_version true are current.");
  if (/T\d{2}:\d{2}(:\d{2})?$/.test(row.response_deadline ?? "")) {
    notes.push(`SAM.gov's file gives this response deadline without a time zone. It is most likely the contracting office's local time${row.office_state ? ` (office in ${row.office_state})` : ""}; confirm on the sam.gov page.`);
  }
  if (relatedTotal > related.length) notes.push(`${relatedTotal} other notices share this solicitation number; ${related.length} are listed.`);
  const contact = (prefix: string) => {
    const c = {title: row[`${prefix}_title`], name: row[`${prefix}_name`], email: row[`${prefix}_email`], phone: row[`${prefix}_phone`], fax: row[`${prefix}_fax`]};
    return Object.values(c).some(v => v) ? c : undefined;
  };
  return {
    found: true,
    data_as_of: asOf,
    notice_id: row.notice_id,
    title: row.title,
    solicitation_number: row.solicitation_number,
    notice_type: row.notice_type,
    original_notice_type: row.base_type,
    latest_version: row.is_latest === 1,
    posted_at: row.posted_at,
    response_deadline: row.response_deadline,
    archive_date: row.archive_date,
    agency: {
      department: row.department, sub_tier: row.sub_tier, office: row.office, cgac: row.cgac,
      fpds_code: row.fpds_code, aac_code: row.aac_code,
      office_location: {city: row.office_city, state: row.office_state, zip: row.office_zip, country: row.office_country},
    },
    naics_code: row.naics_code,
    psc_code: row.psc_code,
    set_aside: row.set_aside_code ? {code: row.set_aside_code, name: row.set_aside} : null,
    place_of_performance: place(row) ?? null,
    award: award(row) ?? null,
    contacts: [contact("primary_contact"), contact("secondary_contact")].filter(Boolean),
    description: row.description,
    links: {sam_gov: publicLink(row.notice_id), additional_info: row.additional_info_link},
    related_notices: related,
    notes,
    source: SOURCE,
  };
}

export async function summarizeOpportunities(db: Database, args: Args, now = new Date()) {
  unknownKeys(args, Object.keys(TOOLS[2].inputSchema.properties));
  const groupBy = str(args, "group_by", 40);
  if (!groupBy || !(groupBy in GROUPS)) throw new ToolError(`group_by must be one of: ${Object.keys(GROUPS).join(", ")}.`);
  const top = int(args, "top", 25, 1, 100);
  const q = buildQuery(args, now);
  const column = GROUPS[groupBy].startsWith("substr") ? "substr(o.posted_date, 1, 7)" : `o.${GROUPS[groupBy]}`;
  const where = whereSql(q);
  const byMonth = groupBy === "posted_month";
  const [groups, count, asOf, hint, noResponse] = await Promise.all([
    db.prepare(`SELECT ${column} AS value, COUNT(*) AS count FROM ${q.from}${where} GROUP BY value ORDER BY ${byMonth ? "value DESC" : "count DESC, value"} LIMIT ?`).bind(...q.params, top).all<{value: string | null; count: number}>(),
    db.prepare(`SELECT COUNT(*) AS n, COUNT(DISTINCT ${column}) AS g FROM ${q.from}${where}`).bind(...q.params).all<{n: number; g: number}>(),
    dataAsOf(db),
    officeStateHint(db, args, now),
    groupBy === "notice_type" ? 0 : noResponseCount(db, args, q),
  ]);
  const total = count.results[0]?.n ?? 0;
  const shown = groups.results.reduce((sum, g) => sum + g.count, 0);
  const typeNote = noResponseNote(noResponse, total);
  const rows = byMonth ? [...groups.results].reverse() : groups.results;
  const monthNote = byMonth ? "Months are in order. Each month counts only notices still active today; SAM.gov archives notices over time, so earlier months look smaller and the counts are not a posting trend." : undefined;
  return {
    group_by: groupBy,
    total_matches: total,
    distinct_values: count.results[0]?.g ?? 0,
    groups: rows.map(g => ({value: g.value ?? "(blank)", count: g.count})),
    other_count: total - shown,
    data_as_of: asOf,
    notes: [...q.notes, ...[typeNote, monthNote, hint].filter((n): n is string => !!n)],
    source: SOURCE,
  };
}

export async function getDataStatus(db: Database, _args: Args, now = new Date()) {
  unknownKeys(_args, []);
  const s = await status(db);
  if (!s.file_date) {
    return {status: "not_loaded", api_key_required: false, message: "The opportunities database has not been loaded yet.", source: SOURCE};
  }
  const ageDays = Math.floor((now.getTime() - Date.parse(s.file_date + "T00:00:00Z")) / 86400000);
  return {
    status: ageDays > 2 ? "stale" : "current",
    api_key_required: false,
    file_date: s.file_date,
    file_age_days: ageDays,
    loaded_at: s.loaded_at,
    active_notices: s.notices,
    latest_versions: s.latest_versions,
    by_notice_type: s.by_notice_type,
    last_load: {added: s.added, updated: s.updated, removed: s.removed, skipped_past_archive_date: s.skipped_past_archive_date},
    refresh: "Nightly. SAM.gov publishes the file once a day; notices posted since then appear after the next load.",
    coverage: "Active notices only. Archived notices, past fiscal years, and attachments are not included. active_notices counts every listed version of amended notices; latest_versions and by_notice_type count only the latest version of each.",
    source: SOURCE,
    source_url: s.source_url,
  };
}

export const HANDLERS: Record<string, (db: Database, args: Args) => Promise<unknown>> = {
  search_opportunities: searchOpportunities,
  get_opportunity: getOpportunity,
  summarize_opportunities: summarizeOpportunities,
  get_data_status: getDataStatus,
};
