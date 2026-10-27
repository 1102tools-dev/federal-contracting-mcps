import {dataFreshness, entityNoMatchSummary} from "./data-freshness.ts";
import {compactSQL, normalizedName, namePredicate, possibleNameMatches, nameIndexCandidates, nameIndexMatches, type NameIndexCandidates} from "./name-matching.ts";
import type {Database} from "./public-types.ts";
import {ToolError} from "./public-types.ts";
import {BUSINESS, SBA, COMMON_BUSINESS_CODES} from "./entity-business-codes.ts";

type Args = Record<string, unknown>;
type Row = Record<string, any>;
export const ENTITY_CAVEATS = [
  "Entities who opted out of public display are not included in the hosted public mirror. No match does not establish that an entity is unregistered.",
  "Confirm current registration status on SAM.gov before relying on this monthly public extract.",
  "Active means the registration is active in this file, not that an SBA certification is current. SBA codes can remain after an 8(a) certification exit date; check certificationExitDate and confirm current certification with SBA before relying on it.",
];
const stringField = (description: string, maxLength = 200) => ({type: "string", maxLength, description});
export const ENTITY_TOOL = {
  name: "search_entities",
  description: "Answer SAM registration and socioeconomic questions: women-owned/WOSB/EDWOSB, veteran-owned/SDVOSB, HUBZone, 8(a), and small business. Search the monthly public extract by UEI, CAGE, name, NAICS and state; filters combine. any_naics includes secondary codes. Search defaults Active; UEI/CAGE includes inactive. Use the labeled business or SBA code filters below. For NAICS-specific small-business status, request assertions or All and check sbaSmallBusiness; 2X means for-profit, not small. Codes and active registration do not prove current SBA certification; check certificationExitDate and confirm SBA/SAM.gov status. Public-display opt-outs are excluded. Up to 10 records/page.",
  inputSchema: {
    type: "object", properties: {
      uei: {type: "string", pattern: "^[A-Za-z0-9]{12}$", description: "Exact 12-character UEI."},
      cage_code: {type: "string", pattern: "^[A-Za-z0-9]{5}$", description: "Exact 5-character CAGE code."},
      legal_business_name: stringField("Partial legal or DBA name; punctuation, spacing, ampersands and common company suffixes are normalized. Zero results include separately labeled possible name matches; names alone do not confirm identity."),
      primary_naics: {anyOf: [{type: "string", pattern: "^[0-9]{2,6}$"}, {type: "integer"}], description: "Designated primary NAICS, 2-6 digits."},
      any_naics: {anyOf: [{type: "string", pattern: "^[0-9]{2,6}$"}, {type: "integer"}], description: "Any listed NAICS, 2-6 digits."},
      state_code: {type: "string", pattern: "^[A-Za-z]{2}$", description: "Physical address state, 2-letter USPS code."},
      business_type_code: stringField("SAM business-type codes; ownership is generally self-selected, not SBA certification. Common codes: " + COMMON_BUSINESS_CODES.map(code => `${code}=${BUSINESS[code]}`).join("; ") + ". Other official 2-character business codes are accepted.", 2),
      sba_business_type_code: {type: "string", enum: Object.keys(SBA), description: "SBA source codes: " + Object.entries(SBA).map(([code, label]) => `${code}=${label}`).join("; ") + ". A4 is retired. These are monthly source codes, not proof of current certification; check certificationExitDate and confirm with SBA."},
      registration_status: {type: "string", enum: ["A", "E"], description: "A=Active (search default), E=expired (displayed as Inactive)."},
      purpose_of_registration: {type: "string", enum: ["Z1", "Z2", "Z3", "Z4", "Z5"]},
      include_sections: {type: "array", items: {type: "string", enum: ["entityRegistration", "coreData", "assertions", "All"]}, description: "Public sections only. Defaults to entityRegistration + coreData; entityRegistration is always included."},
      page: {type: "integer", minimum: 0, maximum: 1000, default: 0},
      size: {type: "integer", minimum: 1, maximum: 10, default: 10},
    }, additionalProperties: false,
  },
  annotations: {title: "Search Entities", readOnlyHint: true, destructiveHint: false, openWorldHint: false},
};

function text(args: Args, key: string, max = 200): string | undefined {
  const value = args[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw new ToolError(`${key} must be a string.`);
  if (value.length > max) throw new ToolError(`${key} exceeds maximum length of ${max} chars. Got ${value.length}.`);
  if (/[\x00-\x1f\x7f]/.test(value)) throw new ToolError(`${key} contains control characters. Remove the offending character and retry.`);
  return value.trim() || undefined;
}
function integer(args: Args, key: string, fallback: number, min: number, max: number): number {
  const n = args[key] ?? fallback;
  if (typeof n !== "number" || !Number.isInteger(n) || n < min || n > max) throw new ToolError(`${key} must be a whole number from ${min} to ${max}. Paginate instead.`);
  return n;
}
function naics(args: Args, key: string): string | undefined {
  const value = args[key];
  if (value === undefined || value === null || value === "") return undefined;
  const result = typeof value === "number" && Number.isInteger(value) ? String(value) : text(args, key, 6);
  if (!result || !/^\d{2,6}$/.test(result)) throw new ToolError(`${key}=${JSON.stringify(value)} must be a 2-6 digit NAICS code (no operators).`);
  return result;
}
function codes(row: Row, key: string): string[] {
  const value = row[key];
  if (!value) return [];
  const parsed = typeof value === "string" ? JSON.parse(value) : value;
  if (!Array.isArray(parsed) || parsed.some(v => typeof v !== "string")) throw new ToolError("The public entity extract contains invalid code data.");
  return parsed;
}
function entity(row: Row, sections: Set<string>, now: Date): Row {
  const raw = row.record_json ? (typeof row.record_json === "string" ? JSON.parse(row.record_json) : row.record_json) : {};
  const value: Row = {
    entityRegistration: raw.entityRegistration ?? {
      ueiSAM: row.uei, cageCode: row.cage_code, legalBusinessName: row.legal_business_name,
      dbaName: row.dba_name, registrationStatus: row.registration_status === "A" ? "Active" : row.registration_status === "E" ? "Inactive" : row.registration_status,
      purposeOfRegistrationCode: row.purpose_of_registration, registrationDate: row.registration_date,
      activationDate: row.activation_date, registrationExpirationDate: row.expiration_date,
      lastUpdateDate: row.last_update_date, ueiStatus: row.uei_status,
      exclusionStatusFlag: row.exclusion_status_flag, publicDisplayFlag: row.public_display_flag,
    },
  };
  if (sections.has("coreData")) value.coreData = raw.coreData ?? {
    physicalAddress: {addressLine1: row.address_line_1, addressLine2: row.address_line_2, city: row.city, stateOrProvinceCode: row.state, zipCode: row.zip_code, countryCode: row.country},
    businessTypes: {
      businessTypeList: codes(row, "business_type_codes_json").map(code => ({businessTypeCode: code, ...(BUSINESS[code] ? {businessTypeDesc: BUSINESS[code]} : {})})),
      sbaBusinessTypeList: codes(row, "sba_business_type_codes_json").map(code => ({sbaBusinessTypeCode: code, ...(SBA[code] ? {sbaBusinessTypeDesc: SBA[code]} : {})})),
    },
  };
  if (sections.has("assertions")) value.assertions = raw.assertions ?? {
    goodsAndServices: {primaryNaics: row.primary_naics, naicsList: codes(row, "naics_codes_json").map(code => ({naicsCode: code, isPrimary: code === row.primary_naics ? "Y" : "N"}))},
  };
  const certifications = raw.coreData?.businessTypes?.sbaBusinessTypeList ?? value.coreData?.businessTypes?.sbaBusinessTypeList ?? [];
  const statuses = certifications.map((item: Row) => ({...item, lapsed: certificationLapsed(item.certificationExitDate, now)}));
  if (value.coreData?.businessTypes) value.coreData.businessTypes.sbaBusinessTypeList = statuses;
  // Status remains visible when callers request sections without coreData.
  if (statuses.length) value.sbaCertificationStatus = statuses.map((item: Row) => ({sbaBusinessTypeCode: item.sbaBusinessTypeCode, certificationExitDate: item.certificationExitDate ?? null, lapsed: item.lapsed}));
  // Older public imports used an extract-specific alias for the API field.
  // record_json is freshly parsed above; normalize only that key, preserving flags.
  const naicsList = value.assertions?.goodsAndServices?.naicsList;
  if (Array.isArray(naicsList)) for (const entry of naicsList) {
    if (entry && typeof entry === "object" && Object.hasOwn(entry, "naicsSmallBusinessIndicator")) {
      if (!Object.hasOwn(entry, "sbaSmallBusiness") && ["Y", "N"].includes(entry.naicsSmallBusinessIndicator)) {
        entry.sbaSmallBusiness = entry.naicsSmallBusinessIndicator;
      }
      delete entry.naicsSmallBusinessIndicator;
    }
  }
  return value;
}

export function certificationLapsed(exit: unknown, now: Date): boolean | null {
  if (typeof exit !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(exit.slice(0, 10))) return null;
  const date = exit.slice(0, 10), parsed = Date.parse(date + "T00:00:00Z");
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== date) return null;
  return date < now.toISOString().slice(0, 10);
}
export async function searchEntities(db: Database, args: Args, now = new Date(), nameIndexDb?: Database) {
  if (!db || typeof db.prepare !== "function") throw new ToolError("SAM.gov public entity data is unavailable; confirm registration status on SAM.gov.");
  const allowed = Object.keys(ENTITY_TOOL.inputSchema.properties);
  const extra = Object.keys(args).filter(k => !allowed.includes(k));
  if (extra.length) throw new ToolError(`Unknown argument${extra.length > 1 ? "s" : ""}: ${extra.join(", ")}. Allowed: ${allowed.join(", ")}.`);
  const page = integer(args, "page", 0, 0, 1000), size = integer(args, "size", 10, 1, 10);
  const where: string[] = [], params: unknown[] = [];
  const exact = (column: string, value: string | undefined) => {if (value !== undefined) {where.push(`${column} = ?`); params.push(value);}};
  const uei = text(args, "uei", 12)?.toUpperCase(), cage = text(args, "cage_code", 5)?.toUpperCase();
  if (uei && !/^[A-Z0-9]{12}$/.test(uei)) throw new ToolError(`uei must be 12 uppercase alphanumeric characters. Got ${JSON.stringify(args.uei)}.`);
  if (cage && !/^[A-Z0-9]{5}$/.test(cage)) throw new ToolError(`cage_code must be 5 uppercase alphanumeric characters. Got ${JSON.stringify(args.cage_code)}.`);
  if (args.uei !== undefined && !uei) throw new ToolError("uei cannot be empty.");
  if (args.cage_code !== undefined && !cage) throw new ToolError("cage_code cannot be empty.");
  exact("e.uei", uei); exact("e.cage_code", cage);
  const name = text(args, "legal_business_name");
  const nameFilter = name ? namePredicate(["e.legal_business_name", "e.dba_name"], name) : undefined;
  exact("e.primary_naics", naics(args, "primary_naics"));
  const anyNaics = naics(args, "any_naics");
  if (anyNaics) {where.push("e.entity_id IN (SELECT entity_id FROM entity_naics WHERE code = ?)"); params.push(anyNaics);}
  const state = text(args, "state_code", 2)?.toUpperCase();
  if (state && !/^[A-Z]{2}$/.test(state)) throw new ToolError(`state_code must be 2-letter USPS (e.g. 'VA', 'CA'). Got ${JSON.stringify(args.state_code)}.`);
  exact("e.state", state);
  const business = text(args, "business_type_code", 2)?.toUpperCase(), sba = text(args, "sba_business_type_code", 2)?.toUpperCase();
  if (business && Object.hasOwn(SBA, business)) throw new ToolError(`business_type_code=${JSON.stringify(args.business_type_code)} is an SBA certification code (${SBA[business]}). SAM.gov filters SBA certifications through a separate parameter; pass it as sba_business_type_code instead.`);
  if (business && !/^[A-Z0-9]{2}$/.test(business)) throw new ToolError("business_type_code must be a 2-character code from the SAM Functional Data Dictionary (e.g. QF, A2, 8W, NB, A3).");
  if (sba && !Object.hasOwn(SBA, sba)) throw new ToolError(`sba_business_type_code must be one of: ${Object.keys(SBA).join(", ")}.`);
  for (const [kind, code] of [["business", business], ["sba", sba]]) if (code) {where.push("e.entity_id IN (SELECT entity_id FROM entity_business_types WHERE kind = ? AND code = ?)"); params.push(kind, code);}
  const status = text(args, "registration_status", 1) ?? (uei || cage ? undefined : "A");
  if (status && status !== "A" && status !== "E") throw new ToolError("registration_status must be A (Active) or E (expired, displayed as Inactive).");
  if (status) {where.push("e.registration_status = ?"); params.push(status === "A" ? "Active" : "Inactive");}
  const purpose = text(args, "purpose_of_registration", 2);
  if (purpose && !/^Z[1-5]$/.test(purpose)) throw new ToolError("purpose_of_registration must be one of: Z1, Z2, Z3, Z4, Z5.");
  exact("e.purpose_of_registration", purpose);
  const requested = args.include_sections ?? ["entityRegistration", "coreData"];
  if (!Array.isArray(requested) || requested.some(s => typeof s !== "string" || !["entityRegistration", "coreData", "assertions", "All"].includes(s))) throw new ToolError("include_sections supports only public entityRegistration, coreData, assertions, or All.");
  const sections = new Set<string>(requested.includes("All") ? ["entityRegistration", "coreData", "assertions"] : requested as string[]);
  // One SQL statement gives rows, total and provenance the same snapshot during swaps.
  const baseWhere = [...where];
  const baseParams = [...params];
  if (nameFilter) {where.push(nameFilter.sql); params.push(...nameFilter.values);}
  const clause = " WHERE " + [...where, "NOT EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='entities' AND state='applying')"].join(" AND ");
  const columns = ["entity_id", "uei", "cage_code", "legal_business_name", "dba_name", "registration_status",
    "purpose_of_registration", "registration_date", "activation_date", "expiration_date", "last_update_date",
    "uei_status", "exclusion_status_flag", "public_display_flag", "address_line_1", "address_line_2",
    "city", "state", "zip_code", "country", "primary_naics", "entity_structure", "entity_url",
    "naics_codes_json", "business_type_codes_json", "sba_business_type_codes_json", "record_json"];
  const projection = columns.map(column => `'${column}', ${column}`).join(", ");
  const candidates = name ? await nameIndexCandidates(nameIndexDb, "entities", name) : undefined;
  const runQuery = async (indexed: NameIndexCandidates | undefined) => {
    let queryParams = params;
    let matching = `matches AS NOT MATERIALIZED (SELECT e.* FROM entities e${clause})`;
    if (name) {
      // D1 has no ANALYZE statistics, so a plain rowid IN filter lets SQLite
      // walk every active registration. CROSS JOIN fixes the order: candidates first.
      const legalSource = indexed ? "json_each(?) AS c CROSS JOIN entities e ON e.rowid = c.value" : "entities e";
      const dbaSource = indexed ? legalSource : `entities e ${uei || cage ? "" : "INDEXED BY entities_dba_name"}`;
      const narrowedParams = indexed ? [indexed.ids] : [];
      const legal = namePredicate(["e.legal_business_name"], name), dba = namePredicate(["e.dba_name"], name);
      const stable = "NOT EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='entities' AND state='applying')";
      const legalClause = [...baseWhere, legal.sql, stable].join(" AND ");
      const dbaClause = [...baseWhere, "e.dba_name IS NOT NULL", "e.dba_name <> ''", dba.sql, stable].join(" AND ");
      matching = `name_keys AS MATERIALIZED (
        SELECT e.rowid AS matched_rowid, CASE WHEN ${compactSQL("e.legal_business_name", name)} = ? THEN 0 ELSE 3 END AS name_rank FROM ${legalSource} WHERE ${legalClause}
        UNION ALL SELECT e.rowid AS matched_rowid, CASE WHEN ${compactSQL("e.dba_name", name)} = ? THEN 1 ELSE 2 END AS name_rank FROM ${dbaSource} WHERE ${dbaClause}),
        matched_keys AS MATERIALIZED (SELECT matched_rowid, min(name_rank) AS name_rank FROM name_keys GROUP BY matched_rowid),
        matches AS NOT MATERIALIZED (SELECT e.*, k.name_rank FROM entities e JOIN matched_keys k ON e.rowid=k.matched_rowid)`;
      queryParams = [normalizedName(name), ...narrowedParams, ...baseParams, ...legal.values, normalizedName(name), ...narrowedParams, ...baseParams, ...dba.values];
    }
    const order: string[] = [];
    const sortParams: unknown[] = [];
    if (sba) {
      const entries = "json_each(coalesce(json_extract(record_json, '$.coreData.businessTypes.sbaBusinessTypeList'), '[]'))";
      const code = "json_extract(value, '$.sbaBusinessTypeCode') = ?";
      const exit = "substr(json_extract(value, '$.certificationExitDate'), 1, 10)";
      const valid = `length(${exit})=10 AND ${exit} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(${exit}, '+0 days')=${exit}`;
      order.push(`CASE WHEN EXISTS(SELECT 1 FROM ${entries} WHERE ${code} AND ${valid} AND ${exit} >= ?) THEN 0 WHEN EXISTS(SELECT 1 FROM ${entries} WHERE ${code} AND ${valid} AND ${exit} < ?) THEN 2 ELSE 1 END`);
      sortParams.push(sba, now.toISOString().slice(0,10), sba, now.toISOString().slice(0,10));
    }
    if (name) order.push("name_rank");
    order.push("legal_business_name COLLATE NOCASE", "uei", "entity_id");
    const {results} = await db.prepare(`WITH ${matching},
      selected AS (SELECT * FROM matches ORDER BY ${order.join(", ")} LIMIT ? OFFSET ?)
      SELECT (SELECT COUNT(*) FROM matches) AS total_records,
      (SELECT json_group_array(json_object(${projection})) FROM selected) AS records,
      EXISTS(SELECT 1 FROM public_refresh_runs WHERE kind='entities' AND state='applying') AS refreshing,
      s.* FROM extract_status s WHERE s.kind = 'entities'`).bind(...queryParams, ...sortParams, size, page * size).all<Row>();
    return results[0];
  };
  let snapshot = await runQuery(candidates);
  // The index must describe the snapshot this search read; otherwise search without it.
  if (!nameIndexMatches(candidates, snapshot)) snapshot = await runQuery(undefined);
  if (snapshot?.refreshing) throw new ToolError("SAM.gov public entity data is refreshing. Try again in about 30 minutes; confirm current registration on SAM.gov.");
  const quarantined = Number(snapshot?.quarantined_rows ?? snapshot?.rejected_rows ?? 0);
  const freshness = dataFreshness("entities", snapshot?.file_date, now);
  const provenance = {
    ...freshness,
    source: "SAM.gov public Entity Registration monthly V2 extract",
    file_name: snapshot?.file_name ?? null, file_date: snapshot?.file_date ?? null,
    source_url: snapshot?.source_url ?? null,
    notes: [...freshness.notes, ...ENTITY_CAVEATS, ...(quarantined > 0 ? [`${quarantined} malformed source rows were quarantined and excluded from this hosted mirror; coverage is incomplete.`] : [])],
  };
  if (!snapshot?.file_date) return {summary: entityNoMatchSummary(null), status: "not_loaded", totalRecords: 0, entityData: [], page, size, ...provenance};
  const rows: Row[] = JSON.parse(snapshot.records);
  const possible = name && snapshot.total_records === 0 ? await possibleNameMatches(db, {
    table: "entities", kind: "entities", columns: ["legal_business_name", "dba_name"],
    projection: ["entity_id", "uei", "cage_code", "legal_business_name", "dba_name", "state", "city", "zip_code", "address_line_1"],
    where: baseWhere.map(w => w.replaceAll("e.", "")), values: baseParams, query: name, snapshot,
  }) : {};
  return {...(snapshot.total_records === 0 ? {summary: entityNoMatchSummary(snapshot.file_date)} : {}), ...possible, totalRecords: snapshot.total_records, entityData: rows.map(row => entity(row, sections, now)), page, size, ...provenance};
}
