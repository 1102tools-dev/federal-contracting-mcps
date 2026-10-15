import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {searchEntities} from "../src/entity-tools.ts";
import {searchExclusions} from "../src/exclusion-tools.ts";
import {dataFreshness} from "../src/data-freshness.ts";

const NOW = new Date("2026-10-11T12:00:00Z");
function fixture() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  for (const kind of ["entities", "exclusions"]) sqlite.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)")
    .run(kind, `${kind}-fixture.zip`, "2026-10-11", "https://sam.gov/public", "2026-10-11T11:59:00Z", 0, "fixture", 4096, 1);
  let sequence = 0;
  const add = (name: string, options: {dba?: string; certifications?: Record<string, unknown>[]} = {}) => {
    const id = String(++sequence), uei = `FOLLOWUP${id.padStart(4, "0")}`;
    const record = {entityRegistration: {ueiSAM: uei, legalBusinessName: name, registrationStatus: "Active"}, coreData: {businessTypes: {sbaBusinessTypeList: options.certifications ?? []}}, assertions: {goodsAndServices: {primaryNaics: "541512", naicsList: [{naicsCode: "541512", sbaSmallBusiness: "Y"}]}}};
    sqlite.prepare("INSERT INTO entities (entity_id,uei,cage_code,legal_business_name,dba_name,registration_status,state,naics_codes_json,business_type_codes_json,sba_business_type_codes_json,record_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
      .run(`entity-${id}`, uei, `F${id.padStart(4, "0")}`, name, options.dba ?? null, "Active", "VA", '["541512"]', "[]", JSON.stringify((options.certifications ?? []).map(c => c.sbaBusinessTypeCode)), JSON.stringify(record));
    for (const certification of options.certifications ?? []) sqlite.prepare("INSERT INTO entity_business_types (entity_id,code,kind) VALUES (?,?,?)").run(`entity-${id}`, String(certification.sbaBusinessTypeCode), "sba");
    sqlite.prepare("INSERT INTO exclusions (exclusion_id,uei,name,classification,record_status,state,country) VALUES (?,?,?,?,?,?,?)")
      .run(`exclusion-${id}`, uei, name, "Firm", "Active", "VA", "USA");
    return {uei, id, record};
  };
  const db = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => ({results: sqlite.prepare(sql).all(...values as any[]) as any[]})})})};
  return {sqlite, db, add};
}

test("certification flags preserve true, false and unknown for each source entry", async () => {
  const {db, sqlite, add} = fixture();
  const firm = add("CERTIFICATION FLAGS LLC", {certifications: [
    {sbaBusinessTypeCode: "A6", certificationExitDate: "2026-10-10"},
    {sbaBusinessTypeCode: "XX", certificationExitDate: "2026-10-11"},
    {sbaBusinessTypeCode: "A9", certificationExitDate: "2027-10-11"},
    {sbaBusinessTypeCode: "A0"},
    {sbaBusinessTypeCode: "A4", certificationExitDate: "2026-02-30"},
  ]});
  const result = await searchEntities(db, {uei: firm.uei, include_sections: ["All"]}, NOW);
  const record = result.entityData[0];
  assert.deepEqual(record.coreData.businessTypes.sbaBusinessTypeList.map((c: any) => c.lapsed), [true, false, false, null, null]);
  assert.deepEqual(record.sbaCertificationStatus.map((c: any) => c.lapsed), [true, false, false, null, null]);
  assert.equal(record.sbaCertificationStatus[3].certificationExitDate, null);
  assert.equal(record.coreData.businessTypes.sbaBusinessTypeList[0].certificationExitDate, "2026-10-10");
  assert.equal((sqlite.prepare("SELECT record_json FROM entities WHERE uei=?").get(firm.uei) as any).record_json, JSON.stringify(firm.record));
  sqlite.close();
});

test("8(a) discovery retains lapsed firms but sorts current, unknown, then lapsed", async () => {
  const {db, sqlite, add} = fixture();
  const lapsed = add("AAAA EXPIRED FIRM", {certifications: [{sbaBusinessTypeCode: "A6", certificationExitDate: "2026-10-10"}]});
  const unknown = add("MMMM UNKNOWN FIRM", {certifications: [{sbaBusinessTypeCode: "A6"}]});
  const current = add("ZZZZ CURRENT FIRM", {certifications: [{sbaBusinessTypeCode: "A6", certificationExitDate: "2026-10-11"}]});
  const result = await searchEntities(db, {sba_business_type_code: "A6", include_sections: ["All"]}, NOW);
  assert.equal(result.totalRecords, 3);
  assert.deepEqual(result.entityData.map((r: any) => r.entityRegistration.ueiSAM), [current.uei, unknown.uei, lapsed.uei]);
  assert.deepEqual(result.entityData.map((r: any) => r.sbaCertificationStatus[0].lapsed), [false, null, true]);
  const page = await searchEntities(db, {sba_business_type_code: "A6", size: 1, page: 2}, NOW);
  assert.equal(page.entityData[0].entityRegistration.ueiSAM, lapsed.uei);
  sqlite.close();
});

test("SBA status remains visible when requested sections omit coreData", async () => {
  const {db, sqlite, add} = fixture();
  const firm = add("ASSERTIONS ONLY LLC", {certifications: [{sbaBusinessTypeCode: "A6", certificationExitDate: "2026-10-10"}]});
  const record = (await searchEntities(db, {uei: firm.uei, include_sections: ["assertions"]}, NOW)).entityData[0];
  assert.equal(record.coreData, undefined);
  assert.ok(record.assertions);
  assert.deepEqual(record.sbaCertificationStatus, [{sbaBusinessTypeCode: "A6", certificationExitDate: "2026-10-10", lapsed: true}]);
  sqlite.close();
});

for (const [query, exactName, dbaName, partialName] of [
  ["Lockheed Martin", "Lockheed Martin Corporation", "Lockheed-Martin LLC", "AAA Lockheed Martin Services"],
  ["boozallen hamilton", "Booz-Allen Hamilton Inc", "Booz Allen Hamilton LLC", "AAA Booz Allen Hamilton Services"],
]) test(`normalized exact legal name ranks before DBA and partial matches: ${query}`, async () => {
  const {db, sqlite, add} = fixture();
  const partial = add(partialName), dba = add("AAA Parent Holdings", {dba: dbaName}), exact = add(exactName);
  const expected = [exact.uei, dba.uei, partial.uei];
  for (let page = 0; page < expected.length; page++) {
    const result = await searchEntities(db, {legal_business_name: query, size: 1, page}, NOW);
    assert.equal(result.totalRecords, 3);
    assert.equal(result.entityData[0].entityRegistration.ueiSAM, expected[page]);
  }
  sqlite.close();
});

test("zero matches lead with dated non-clearance summary and untruncated empty candidates", async () => {
  const {db, sqlite, add} = fixture();
  for (let n = 0; n < 25; n++) add(`ZZ Irrelevant Vendor ${n} LLC`);
  const entity = await searchEntities(db, {legal_business_name: "ZZ Quux Unimaginable"}, NOW);
  const exclusion = await searchExclusions(db, {entity_name: "ZZ Quux Unimaginable"}, NOW);
  assert.match(entity.summary, /hide their record from public view/);
  assert.match(entity.summary, /does not mean the entity is unregistered/);
  assert.doesNotMatch(exclusion.summary, /public view/);
  for (const result of [entity, exclusion]) {
    assert.equal(Object.keys(result)[0], "summary");
    assert.match(result.summary, /No record matched/);
    assert.match(result.summary, /2026-10-11/);
    assert.match(result.summary, /not a clearance or eligibility determination/);
    assert.match(result.summary, /confirm on SAM.gov/);
    assert.equal(result.totalRecords, 0);
    assert.deepEqual(result.possibleMatches, []);
    assert.equal(result.possibleMatchCandidatesTruncated, false);
  }
  sqlite.close();
});

test("date-only freshness marks stale only after each dataset boundary", () => {
  for (const kind of ["opportunities"] as const) {
    const at = dataFreshness(kind, "2026-10-10", new Date("2026-10-11T06:00:00Z"));
    assert.equal(at.stale, false);
    assert.equal(at.file_age_hours, 30);
    assert.equal(at.stale_after_hours, 30);
    assert.equal(dataFreshness(kind, "2026-10-10", new Date("2026-10-11T06:00:00.001Z")).stale, true);
    assert.match(at.freshness_basis, /Source file date at 00:00 UTC/);
  }
  const at = dataFreshness("entities", "2026-09-01", new Date("2026-10-11T00:00:00Z"));
  assert.equal(at.stale, false);
  assert.equal(at.file_age_hours, 960);
  assert.equal(at.stale_after_hours, 960);
  assert.equal(dataFreshness("entities", "2026-09-01", new Date("2026-10-11T00:00:00.001Z")).stale, true);
  for (const value of [null, undefined, "", "2026-02-30"]) assert.equal(dataFreshness("entities", value, NOW).stale, true);
});

test("recent load time cannot freshen an old source file in either search response", async () => {
  const {db, sqlite} = fixture();
  sqlite.exec("UPDATE extract_status SET file_date='2026-08-01', loaded_at='2026-10-11T11:59:59Z'");
  for (const result of [
    await searchEntities(db, {uei: "NOTFOUND0001"}, NOW),
    await searchExclusions(db, {uei: "NOTFOUND0001"}, NOW),
  ]) {
    assert.equal(Object.keys(result)[0], "summary");
    assert.equal(result.stale, true);
    assert.match(result.notes.join(" "), /STALE SAM.gov/);
    assert.match(result.freshness_basis, /not based on load time/);
    assert.match(result.summary, /2026-08-01/);
  }
  sqlite.close();
});


test("Oct 11 exclusions remain current at Oct 12 09:00 UTC and stale at 13:00 UTC", () => {
  const current = dataFreshness("exclusions", "2026-10-11", new Date("2026-10-12T09:00:00Z"));
  assert.equal(current.stale, false);
  assert.equal(current.file_age_hours, 33);
  assert.equal(current.stale_after_hours, 36);
  assert.equal(dataFreshness("exclusions", "2026-10-11", new Date("2026-10-12T12:00:00Z")).stale, false);
  const stale = dataFreshness("exclusions", "2026-10-11", new Date("2026-10-12T13:00:00Z"));
  assert.equal(stale.stale, true);
  assert.equal(stale.file_age_hours, 37);
  assert.match(stale.notes[0], /36 hours/);
});
