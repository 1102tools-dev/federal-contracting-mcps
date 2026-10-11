import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {EXCLUSION_TOOL, getPublicDataStatus, searchExclusions} from "../src/exclusion-tools.ts";
import {ToolError} from "../src/tools.ts";

function database(loaded = true) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  const records = [
    {exclusion_id: "1", uei: "TESTUEI00001", cage_code: "A1B2C", name: "ACME GROUP", record_status: "Active", classification: "Firm", exclusion_program: "Reciprocal", country: "USA", state: "MD", termination_date: "2100-01-01"},
    {exclusion_id: "2", uei: "TESTUEI00001", cage_code: "A1B2C", name: "ACME GROUP", record_status: "Inactive", classification: "Firm", exclusion_program: "Procurement", country: "USA", state: "MD", termination_date: "2001-01-01", description: "Archived exclusion note", excluding_agency_code: "HHS"},
    {exclusion_id: "3", uei: "OTHERUEI0001", cage_code: "ZZZZZ", name: "ACME OTHER", record_status: "Inactive", classification: "Firm", country: "CAN", state: "ON"},
    {exclusion_id: "4", name: "100%_ LLC", record_status: "Active", classification: "Firm"},
  ];
  for (const row of records) {
    const keys = Object.keys(row);
    sqlite.prepare(`INSERT INTO exclusions (${keys.join(",")}) VALUES (${keys.map(() => "?").join(",")})`).run(...Object.values(row));
  }
  const native = {exclusionIdentification: {ueiSAM: "TESTUEI00001", entityName: "ACME GROUP", samNumber: "S4MRTEST"}, exclusionActions: {listOfActions: [{recordStatus: "Active", terminationType: "Indefinite"}]}};
  sqlite.prepare("UPDATE exclusions SET record_json = ? WHERE exclusion_id = '1'").run(JSON.stringify(native));
  if (loaded) {
    for (const [kind, file_name, row_count] of [["entities", "SAM_PUBLIC_UTF-8_MONTHLY_V2_20261001.ZIP", 25], ["exclusions", "SAM_Exclusions_Public_Extract_V2_26284.ZIP", 4]]) {
      sqlite.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?, ?,?,?,?,?,?)")
        .run(kind, file_name, "2026-10-11", "https://sam.gov/public", "2026-10-11T12:00:00Z", row_count, "fixture", 4096, 1);
    }
  }
  const plans: string[] = [];
  const db = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => {
    if (sql.startsWith("WITH matches")) {
      plans.push(...sqlite.prepare(`EXPLAIN QUERY PLAN ${sql}`).all(...values as any[]).map(row => String(row.detail)));
    }
    return {results: sqlite.prepare(sql).all(...values as any[]) as any[]};
  }})})};
  return {db, sqlite, native, plans};
}

test("exclusion tool title and annotations declare read-only public search", () => {
  assert.equal(EXCLUSION_TOOL.name, "search_exclusions");
  assert.equal(EXCLUSION_TOOL.annotations.title, "Search Exclusions");
  assert.equal(EXCLUSION_TOOL.annotations.readOnlyHint, true);
});

test("UEI and CAGE checks preserve shared fields and include active and expired records", async () => {
  const {db, native} = database();
  const result = await searchExclusions(db, {uei: " testuei00001 "});
  assert.equal(result.totalRecords, 2);
  assert.equal(result.activeRecordsInFile, 1);
  assert.deepEqual(result.excludedEntity[0], native);
  assert.equal(result.excludedEntity[1].exclusionIdentification.entityName, "ACME GROUP");
  assert.equal(result.excludedEntity[1].exclusionIdentification.name, undefined);
  assert.equal(result.excludedEntity[1].exclusionPrimaryAddress.stateOrProvinceCode, "MD");
  assert.equal(result.excludedEntity[1].exclusionAddress, undefined);
  assert.deepEqual(result.excludedEntity[1].exclusionOtherInformation, {additionalComments: "Archived exclusion note"});
  assert.equal(result.excludedEntity[1].exclusionDetails.excludingAgencyName, undefined);
  assert.equal(result.excludedEntity[1].exclusionActions.listOfActions[0].recordStatus, "Inactive");
  assert.equal(result.excludedEntity[1].exclusionActions.listOfActions[0].terminationDate, "2001-01-01");
  assert.deepEqual((await searchExclusions(db, {cage_code: "a1b2c"})).excludedEntity, result.excludedEntity);
  assert.match(result.file_name, /^SAM_Exclusions_Public_Extract_V2_/);
  assert.equal(result.file_date, "2026-10-11");
  assert.match(result.notes.join(" "), /not a live SAM.gov clearance check/);
  assert.match(result.notes.join(" "), /inactive or terminated historical records may be absent/);
  assert.doesNotMatch(EXCLUSION_TOOL.description, /Includes active and inactive/);
});

test("name filters combine, paginate deterministically, and reject punctuation-only names", async () => {
  const {db} = database();
  assert.equal((await searchExclusions(db, {})).totalRecords, 4);
  const result = await searchExclusions(db, {entity_name: "acme", country: "usa", size: 1, page: 1});
  assert.equal(result.totalRecords, 2);
  assert.equal(result.excludedEntity.length, 1);
  assert.equal(result.excludedEntity[0].exclusionActions.listOfActions[0].recordStatus, "Inactive");
  await assert.rejects(searchExclusions(db, {entity_name: "%_"}), /meaningful name/);
  assert.equal((await searchExclusions(db, {uei: "TESTUEI00001", cage_code: "ZZZZZ"})).totalRecords, 0);
});

test("no matches never claim clearance, and missing data fails closed", async () => {
  const result = await searchExclusions(database().db, {uei: "NOTFOUND0001"});
  assert.equal(result.totalRecords, 0);
  assert.deepEqual(result.excludedEntity, []);
  assert.match(result.notes.join(" "), /does not establish eligibility or responsibility/);
  await assert.rejects(searchExclusions(database(false).db, {entity_name: "ACME"}), /has not been loaded/);
});

test("invalid identifiers, countries, controls, pagination and unknown properties reject before query", async () => {
  const {db} = database();
  for (const args of [{uei: "short"}, {uei: ""}, {cage_code: "123456"}, {country: "US"}, {entity_name: "a\u0000b"}, {size: 101}, {page: -1}, {classification: "firm"}, {free_text: "a*"}]) {
    await assert.rejects(searchExclusions(db, args), ToolError);
  }
});

test("data status reports both file dates, row counts and availability", async () => {
  const status = await getPublicDataStatus(database().db);
  assert.equal(status.entities.available, true);
  assert.equal(status.entities.row_count, 25);
  assert.equal(status.exclusions.row_count, 4);
  assert.equal(status.exclusions.file_date, "2026-10-11");
  assert.match(status.entities.notes.join(" "), /opted out/);
  assert.match(status.entities.notes.join(" "), /certification exit date/);
  assert.match(status.exclusions.notes.join(" "), /not a complete exclusion history/);
  assert.match(status.exclusions.notes.join(" "), /Confirm current exclusion status on SAM.gov/);
  const unloaded = await getPublicDataStatus(database(false).db);
  assert.equal(unloaded.entities.available, false);
  assert.equal(unloaded.exclusions.available, false);
});


test("default search never materializes the full matching records and missing DB fails clearly", async () => {
  const {db, plans} = database();
  const result = await searchExclusions(db, {});
  assert.equal(result.totalRecords, 4);
  assert.ok(plans.length > 0);
  assert.ok(!plans.some(plan => /MATERIALIZE matches/i.test(plan)), plans.join("\n"));
  await assert.rejects(searchExclusions(undefined, {}), ToolError);
  for (const code of [1, 2, 8, 11, 12, 31, 127]) {
    await assert.rejects(searchExclusions(db, {entity_name: `ACME${String.fromCharCode(code)}`}), /control character/);
  }
});


test("identifier lookups use ingestion indexes", async () => {
  const {db, plans} = database();
  await searchExclusions(db, {uei: "testuei00001"});
  assert.ok(plans.some(plan => /USING (?:COVERING )?INDEX exclusions_0/.test(plan)), plans.join("\n"));
  plans.length = 0;
  await searchExclusions(db, {cage_code: "a1b2c"});
  assert.ok(plans.some(plan => /USING (?:COVERING )?INDEX exclusions_1/.test(plan)), plans.join("\n"));
});

test("unfinished incremental exclusions refresh hides partial records until completion", async () => {
 const {db, sqlite} = database();
 sqlite.exec("INSERT INTO public_refresh_runs VALUES ('exclusions','applying','target','parser','{}',3,100,10,'2026-10','now','now','owner','later')");
 await assert.rejects(() => searchExclusions(db, {}), /refreshing/);
 const during = await getPublicDataStatus(db);
 assert.equal(during.exclusions.available, false);
 assert.equal(during.exclusions.status, "refreshing");
 assert.equal(during.entities.available, true);
 sqlite.exec("UPDATE public_refresh_runs SET state='complete'");
 assert.ok(await searchExclusions(db, {}));
 sqlite.close();
});

test("explicit US two-letter state filters seek the existing index and preserve case-insensitive input", async () => {
 const {db, sqlite, plans} = database();
 const result = await searchExclusions(db, {state_province: "md", country: "usa"});
 assert.equal(result.totalRecords, 2);
 assert.ok(plans.some(plan => plan.includes("exclusions_3")));
 sqlite.prepare("UPDATE exclusions SET state='Ontario' WHERE exclusion_id='3'").run();
 assert.equal((await searchExclusions(db, {state_province: "ontario", country: "CAN"})).totalRecords, 1);
 sqlite.close();
});
