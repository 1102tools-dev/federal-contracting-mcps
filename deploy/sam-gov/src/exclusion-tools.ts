import {dataFreshness, noMatchSummary} from "./data-freshness.ts";
import {namePredicate, possibleNameMatches} from "./name-matching.ts";
import {ToolError, type Database} from "./public-types.ts";
import {ENTITY_CAVEATS} from "./entity-tools.ts";

type Args = Record<string, unknown>;
type Row = Record<string, any>;

const CAVEATS = [
  "Results come from the SAM.gov public exclusions extract, not a live SAM.gov clearance check. Confirm current exclusion status on SAM.gov before relying on these results.",
  "No matches means no matching records in this public file; it does not establish eligibility or responsibility. Names can match different people or organizations; compare identifiers and addresses.",
  "This public snapshot is not a complete exclusion history; inactive or terminated historical records may be absent. Check exclusionActions.listOfActions[].recordStatus and the activation and termination dates for any returned record; an exclusion record alone does not establish that an exclusion is currently in effect.",
];

export const EXCLUSION_TOOL = {
  name: "search_exclusions",
  description: "Check SAM.gov public exclusion/debarment records by UEI, CAGE, or name. Filters combine. Searches the dated public extract, which is not a complete exclusion history; inactive or terminated historical records may be absent. Every result identifies the source file and date. No matches in the extract is not a live clearance or eligibility determination; confirm current status on SAM.gov.",
  inputSchema: {
    type: "object",
    properties: {
      uei: {type: "string", pattern: "^[A-Za-z0-9]{12}$", description: "12-character Unique Entity ID; exact match."},
      cage_code: {type: "string", pattern: "^[A-Za-z0-9]{5}$", description: "5-character CAGE; exact match."},
      entity_name: {type: "string", maxLength: 200, description: "Partial firm or individual name; punctuation, spacing, ampersands and common company suffixes are normalized, including first/middle/last names. Zero results include separately labeled possible name matches; names alone do not confirm identity."},
      classification: {type: "string", enum: ["Firm", "Individual", "Vessel", "Special Entity Designation"]},
      exclusion_program: {type: "string", enum: ["Reciprocal", "NonProcurement", "Procurement"]},
      excluding_agency_code: {type: "string", maxLength: 100},
      state_province: {type: "string", maxLength: 100},
      country: {type: "string", pattern: "^[A-Za-z]{3}$", description: "3-character ISO alpha-3 country code, e.g. USA."},
      page: {type: "integer", minimum: 0, maximum: 100000, default: 0},
      size: {type: "integer", minimum: 1, maximum: 100, default: 10},
    },
    additionalProperties: false,
  },
  annotations: {title: "Search Exclusions", readOnlyHint: true, destructiveHint: false, openWorldHint: false},
};

function text(args: Args, key: string, maximum = 200): string | undefined {
  const value = args[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw new ToolError(`${key} must be a string.`);
  if (/[\u0000-\u001f\u007f]/.test(value)) throw new ToolError(`${key} contains a control character. Remove the offending character and retry.`);
  const result = value.trim();
  if (!result) throw new ToolError(`${key} cannot be empty.`);
  if (result.length > maximum) throw new ToolError(`${key} is longer than ${maximum} characters.`);
  return result;
}

function integer(args: Args, key: string, fallback: number, minimum: number, maximum: number): number {
  const value = args[key] ?? fallback;
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) {
    throw new ToolError(`${key} must be a whole number from ${minimum} to ${maximum}.`);
  }
  return value;
}

function code(args: Args, key: string, length: number): string | undefined {
  const value = text(args, key)?.toUpperCase();
  if (value && !new RegExp(`^[A-Z0-9]{${length}}$`).test(value)) {
    throw new ToolError(`${key} must be ${length} uppercase alphanumeric characters.`);
  }
  return value;
}

function choice(args: Args, key: string, allowed: string[]): string | undefined {
  const value = text(args, key);
  if (value && !allowed.includes(value)) throw new ToolError(`${key} must be one of: ${allowed.join(", ")}.`);
  return value;
}

/** Both datasets are in the separate public extract database. */
export async function getPublicDataStatus(db: Database, now = new Date()) {
  const rows = (await db.prepare("SELECT s.*, EXISTS(SELECT 1 FROM public_refresh_runs r WHERE r.kind=s.kind AND r.state='applying') AS refreshing FROM extract_status s WHERE kind IN ('entities', 'exclusions') ORDER BY kind").bind().all<Row>()).results;
  const status = (kind: string) => {
    const row = rows.find(row => row.kind === kind);
    const quarantined = Number(row?.quarantined_rows ?? row?.rejected_rows ?? 0);
    const freshness = dataFreshness(kind as "entities" | "exclusions", row?.file_date, now);
    const notes = [...freshness.notes, ...(kind === "entities" ? [...ENTITY_CAVEATS, ...(quarantined > 0 ? [`${quarantined} malformed source rows were quarantined and excluded from this hosted mirror; coverage is incomplete.`] : [])] : [...CAVEATS])];
    if (row?.refreshing) notes.push("Public data is refreshing; retry later. The listed source describes the last completed refresh.");
    return row ? {...row, ...freshness, available: !row.refreshing, notes, ...(row.refreshing ? {status: "refreshing"} : {})} : {...freshness, available: false, kind, file_name: null, file_date: null, row_count: 0, notes};
  };
  return {entities: status("entities"), exclusions: status("exclusions")};
}

/** Preserve parser-provided API-style fields; fallback only for scalar-only rows. */
function record(row: Row) {
  if (row.record_json) {
    const parsed = JSON.parse(row.record_json);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid stored exclusion record");
    return parsed;
  }
  return {
    exclusionIdentification: {
      ueiSAM: row.uei, cageCode: row.cage_code, entityName: row.name,
      firstName: row.first_name, middleName: row.middle_name, lastName: row.last_name, suffix: row.suffix,
    },
    exclusionDetails: {
      classificationType: row.classification, exclusionType: row.exclusion_type,
      exclusionProgram: row.exclusion_program, excludingAgencyCode: row.excluding_agency_code,
      ...(row.excluding_agency_name ? {excludingAgencyName: row.excluding_agency_name} : {}),
    },
    exclusionPrimaryAddress: {
      addressLine1: row.address_line_1, addressLine2: row.address_line_2,
      city: row.city, stateOrProvinceCode: row.state, zipCode: row.zip_code, countryCode: row.country,
    },
    exclusionOtherInformation: {additionalComments: row.description},
    exclusionActions: {listOfActions: [{
      recordStatus: row.record_status, activateDate: row.activation_date,
      terminationDate: row.termination_date,
    }]},
  };
}

export async function searchExclusions(db: Database | undefined, args: Args, now = new Date()) {
  if (!db) throw new ToolError("SAM.gov public exclusions database is not configured; no exclusion determination can be made.");
  for (const key of Object.keys(args)) {
    if (!Object.hasOwn(EXCLUSION_TOOL.inputSchema.properties, key)) throw new ToolError(`Unknown argument: ${key}.`);
  }
  const uei = code(args, "uei", 12);
  const cage = code(args, "cage_code", 5);
  const name = text(args, "entity_name");
  const classification = choice(args, "classification", ["Firm", "Individual", "Vessel", "Special Entity Designation"]);
  const program = choice(args, "exclusion_program", ["Reciprocal", "NonProcurement", "Procurement"]);
  const agency = text(args, "excluding_agency_code", 100);
  const state = text(args, "state_province", 100);
  const country = text(args, "country")?.toUpperCase();
  if (country && !/^[A-Z]{3}$/.test(country)) throw new ToolError("country must be 3-character ISO alpha-3 (USA, CAN, GBR).");
  const indexedState = country === "USA" && !!state && /^[A-Za-z]{2}$/.test(state);
  const page = integer(args, "page", 0, 0, 100000);
  const size = integer(args, "size", 10, 1, 100);
  // One statement snapshots rows and metadata together, even across a loader swap.
  const predicates: string[] = [];
  const values: unknown[] = [];
  for (const [column, value] of [["uei", uei], ["cage_code", cage], ["classification", classification], ["exclusion_program", program], ["excluding_agency_code", agency], ["state", state], ["country", country]]) {
    if (value) {
      // Identifiers are normalized uppercase at ingestion; use their binary indexes.
      predicates.push(`${column} = ?${column === "uei" || column === "cage_code" || (column === "state" && indexedState) ? "" : " COLLATE NOCASE"}`);
      values.push(column === "state" && indexedState ? value.toUpperCase() : value);
    }
  }
  const baseWhere = [...predicates], baseValues = [...values];
  if (name) {
    const filter = namePredicate(["name", "coalesce(first_name, '') || ' ' || coalesce(middle_name, '') || ' ' || coalesce(last_name, '')", "coalesce(first_name, '') || ' ' || coalesce(last_name, '')"], name);
    predicates.push(filter.sql); values.push(...filter.values);
  }
  const clause = `${predicates.join(" AND ") || "1=1"} AND NOT EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='exclusions' AND state='applying')`;
  const matching = name ? `matched_keys AS MATERIALIZED (SELECT rowid AS matched_rowid FROM exclusions WHERE ${clause}), matches AS NOT MATERIALIZED (SELECT * FROM exclusions WHERE rowid IN (SELECT matched_rowid FROM matched_keys))` : `matches AS NOT MATERIALIZED (SELECT * FROM exclusions WHERE ${clause})`;
  const result = (await db.prepare(`WITH ${matching},
    selected AS (SELECT * FROM matches ORDER BY name COLLATE NOCASE, exclusion_id LIMIT ? OFFSET ?)
    SELECT (SELECT json_group_array(json_object('row', json_object(
      'exclusion_id', exclusion_id, 'uei', uei, 'cage_code', cage_code, 'name', name,
      'first_name', first_name, 'middle_name', middle_name, 'last_name', last_name, 'suffix', suffix,
      'classification', classification, 'exclusion_type', exclusion_type, 'exclusion_program', exclusion_program,
      'excluding_agency_code', excluding_agency_code, 'excluding_agency_name', excluding_agency_name,
      'record_status', record_status, 'activation_date', activation_date, 'termination_date', termination_date,
      'creation_date', creation_date, 'last_update_date', last_update_date,
      'address_line_1', address_line_1, 'address_line_2', address_line_2, 'city', city, 'state', state,
      'zip_code', zip_code, 'country', country, 'description', description, 'record_json', record_json))) FROM selected) AS records,
    (SELECT COUNT(*) FROM matches) AS total_records,
    (SELECT COUNT(*) FROM matches WHERE record_status = 'Active' COLLATE NOCASE) AS active_records,
    EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='exclusions' AND state='applying') AS refreshing,
    s.* FROM extract_status s WHERE kind = 'exclusions'`).bind(...values, size, page * size).all<Row>()).results[0];
  if (result?.refreshing) throw new ToolError("SAM.gov public exclusions data is refreshing. Retry later; no exclusion determination can be made.");
  if (!result) throw new ToolError("SAM.gov public exclusions data has not been loaded yet; no exclusion determination can be made.");
  const possible = name && result.total_records === 0 ? await possibleNameMatches(db, {
    table: "exclusions", kind: "exclusions", columns: ["name", "coalesce(first_name, '') || ' ' || coalesce(middle_name, '') || ' ' || coalesce(last_name, '')"],
    projection: ["exclusion_id", "uei", "cage_code", "name", "first_name", "middle_name", "last_name", "classification", "state", "city", "zip_code", "address_line_1"],
    where: baseWhere, values: baseValues, query: name, snapshot: result,
  }) : {};
  const freshness = dataFreshness("exclusions", result.file_date, now);
  return {
    ...(result.total_records === 0 ? {summary: noMatchSummary(result.file_date)} : {}),
    ...possible,
    ...freshness,
    totalRecords: result.total_records,
    excludedEntity: JSON.parse(result.records).map((item: {row: Row}) => record(item.row)),
    page, size,
    activeRecordsInFile: result.active_records,
    source: "SAM.gov public Exclusions/Public V2 extract",
    file_name: result.file_name, file_date: result.file_date, data_as_of: result.file_date,
    loaded_at: result.loaded_at,
    notes: [...freshness.notes, ...CAVEATS],
  };
}
