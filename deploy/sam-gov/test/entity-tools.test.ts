import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {ENTITY_TOOL, searchEntities} from "../src/entity-tools.ts";

function database(loaded = true) {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  if (loaded) sqlite.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)").run("entities", "SAM_PUBLIC_UTF-8_MONTHLY_V2_20261001.ZIP", "2026-10-01", "https://sam.gov/public", "2026-10-11T10:00:00Z", 3, "sha", 12345, 2);
  for (const [uei, name, status, primary, state, cage] of [
    ["ABCDEFGHIJK1", "Alpha Systems LLC", "Active", "541512", "VA", "1ABCD"],
    ["ABCDEFGHIJK2", "Beta Alpha Systems", "Inactive", "541511", "CA", "2ABCD"],
    ["ABCDEFGHIJK3", "Alpha_100% Incorporated", "Active", "541512", "VA", "3ABCD"],
  ]) {
    sqlite.prepare("INSERT INTO entities (entity_id,uei,legal_business_name,registration_status,primary_naics,state,cage_code,naics_codes_json,business_type_codes_json,sba_business_type_codes_json) VALUES (?,?,?,?,?,?,?,?,?,?)").run(uei + "-record",uei,name,status,primary,state,cage,'["541511","541512"]','["QF","NB"]','["XX"]');
    for (const code of ["541511", "541512"]) sqlite.prepare("INSERT INTO entity_naics VALUES (?,?)").run(uei + "-record", code);
    for (const [code, kind] of [["QF", "business"], ["NB", "business"], ["XX", "sba"]]) sqlite.prepare("INSERT INTO entity_business_types VALUES (?,?,?)").run(uei + "-record", code, kind);
  }
  const queries: {sql: string; values: unknown[]}[] = [];
  const db = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => {
    queries.push({sql,values});
    return {results: sqlite.prepare(sql).all(...values as any[]) as any[]};
  }})})};
  return {db, sqlite, queries};
}

test("entity tool has directory title, read-only metadata and bounded paging", () => {
  assert.equal(ENTITY_TOOL.annotations.title, "Search Entities");
  assert.equal(ENTITY_TOOL.annotations.readOnlyHint, true);
  assert.equal(ENTITY_TOOL.inputSchema.properties.size.maximum, 10);
});

test("search defaults Active, but UEI/CAGE lookups retain expired registrations", async () => {
  const {db} = database();
  assert.equal((await searchEntities(db, {})).totalRecords, 2);
  const result = await searchEntities(db, {uei: "abcdefghijk2"});
  assert.equal(result.entityData[0].entityRegistration.registrationStatus, "Inactive");
  assert.equal((await searchEntities(db, {cage_code: "2abcd"})).totalRecords, 1);
  assert.equal((await searchEntities(db, {uei: "ABCDEFGHIJK2", registration_status: "A"})).totalRecords, 0);
});

test("local shared filters combine and distinguish primary from any NAICS", async () => {
  const {db} = database();
  const args = {any_naics: 541511, state_code: "va", business_type_code: "nb", sba_business_type_code: "xx"};
  assert.equal((await searchEntities(db, args)).totalRecords, 2);
  assert.equal((await searchEntities(db, {...args, primary_naics: "541511"})).totalRecords, 0);
  assert.equal((await searchEntities(db, {registration_status: "E", legal_business_name: "Alpha"})).totalRecords, 1);
});

test("name partial matching treats SQL wildcard characters literally", async () => {
  const {db} = database();
  assert.equal((await searchEntities(db, {legal_business_name: "100%"})).totalRecords, 1);
  assert.equal((await searchEntities(db, {legal_business_name: "Alpha_"})).totalRecords, 1);
  assert.equal((await searchEntities(db, {legal_business_name: "' OR 1=1 --"})).totalRecords, 0);
});

test("literal entity names fit the input contract without D1's 50-byte LIKE limit", async () => {
  const {db, sqlite} = database();
  // Enforce the documented D1 limit in the real SQLite test backend.
  sqlite.function("like", {varargs: true}, (pattern: any) => {
    assert.ok(Buffer.byteLength(String(pattern)) <= 50, "D1 LIKE pattern exceeds 50 bytes");
    return 0;
  });
  for (const name of ["Long Legal Company Name ".repeat(4) + "100%_\\LLC", "A".repeat(200), "é".repeat(30) + " ASCII_%\\LLC"]) {
    sqlite.prepare("UPDATE entities SET legal_business_name=? WHERE uei=?").run(name, "ABCDEFGHIJK1");
    const result = await searchEntities(db, {legal_business_name: name.toLowerCase()});
    assert.equal(result.totalRecords, 1);
    assert.equal(result.entityData[0].entityRegistration.ueiSAM, "ABCDEFGHIJK1");
  }
});

test("source metadata and both caveats accompany no matches and unloaded responses", async () => {
  const result = await searchEntities(database().db, {uei: "XXXXXXXXXXXX"});
  assert.equal(result.file_name, "SAM_PUBLIC_UTF-8_MONTHLY_V2_20261001.ZIP");
  assert.equal(result.file_date, "2026-10-01");
  assert.match(result.notes.join(" "), /opted out of public display/);
  assert.match(result.notes.join(" "), /Confirm current registration status on SAM.gov/);
  const empty = await searchEntities(database(false).db, {});
  assert.equal(empty.status, "not_loaded");
  assert.equal(empty.file_name, null);
  assert.equal(empty.entityData.length, 0);
});

test("public record JSON preserves every shared field and filters sections", async () => {
  const {db, sqlite} = database();
  const record = {entityRegistration: {ueiSAM: "ABCDEFGHIJK1", legalBusinessName: "Alpha Systems LLC", registrationStatus: "Active"}, coreData: {physicalAddress: {city: "Reston"}}, assertions: {goodsAndServices: {naicsList: [{naicsCode: "541512", sbaSmallBusiness: "Y"}]}}};
  sqlite.prepare("UPDATE entities SET record_json=? WHERE uei=?").run(JSON.stringify(record), "ABCDEFGHIJK1");
  assert.deepEqual((await searchEntities(db, {uei: "ABCDEFGHIJK1", include_sections: ["All"]})).entityData[0], record);
  assert.deepEqual((await searchEntities(db, {uei: "ABCDEFGHIJK1", include_sections: ["assertions"]})).entityData[0], {entityRegistration: record.entityRegistration, assertions: record.assertions});
});

test("active registration with a past 8(a) exit date is not presented as current certification", async () => {
  const {db, sqlite} = database();
  const record = {entityRegistration: {ueiSAM: "ABCDEFGHIJK1", registrationStatus: "Active"}, coreData: {businessTypes: {sbaBusinessTypeList: [{sbaBusinessTypeCode: "A6", certificationExitDate: "2021-01-03"}]}}};
  sqlite.prepare("UPDATE entities SET record_json=? WHERE uei=?").run(JSON.stringify(record), "ABCDEFGHIJK1");
  sqlite.prepare("INSERT INTO entity_business_types VALUES (?,?,?)").run("ABCDEFGHIJK1-record", "A6", "sba");
  const result = await searchEntities(db, {uei: "ABCDEFGHIJK1", sba_business_type_code: "A6"});
  assert.deepEqual(result.entityData[0], record);
  assert.match(result.notes.join(" "), /not that an SBA certification is current/);
  assert.match(result.notes.join(" "), /certificationExitDate/);
  assert.match(result.notes.join(" "), /confirm current certification with SBA/);
});

test("paging is stable, SQL bounds results and identifier/NAICS/state filters use indexes", async () => {
  const {db, sqlite, queries} = database();
  const a = await searchEntities(db, {size: 1, page: 0});
  const b = await searchEntities(db, {size: 1, page: 1});
  assert.notEqual(a.entityData[0].entityRegistration.ueiSAM, b.entityData[0].entityRegistration.ueiSAM);
  await searchEntities(db, {uei: "ABCDEFGHIJK1", state_code: "VA", any_naics: "541512"});
  const query = queries.at(-1)!;
  assert.match(query.sql, /LIMIT \? OFFSET \?/);
  const plan = sqlite.prepare("EXPLAIN QUERY PLAN " + query.sql).all(...query.values as any[]) as any[];
  assert.match(plan.map(r => r.detail).join(" "), /INDEX/);
  assert.doesNotMatch(plan.map(r => r.detail).join(" "), /SCAN e\b/);
});

test("invalid arguments fail before querying and SBA codes redirect to the right field", async () => {
  for (const args of [{uei: "short"}, {cage_code: "too-long"}, {uei: " "}, {size: 11}, {page: 1001}, {page: -1}, {primary_naics: "5415!"}, {registration_status: "A,E"}, {state_code: "1A"}, {sba_business_type_code: "QF"}, {include_sections: ["pointsOfContact"]}, {free_text: "unsupported"}, {legal_business_name: "a\nb"}]) {
    const {db, queries} = database();
    await assert.rejects(searchEntities(db, args));
    assert.equal(queries.length, 0);
  }
  await assert.rejects(searchEntities(database().db, {business_type_code: "A6"}), /sba_business_type_code instead/);
});

test("a swap immediately after the query cannot mix entity rows with a newer source date", async () => {
  const {db, sqlite, queries} = database();
  const swapping = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => {
    const result = await db.prepare(sql).bind(...values).all();
    sqlite.exec("UPDATE extract_status SET file_date='2026-11-01'; UPDATE entities SET legal_business_name='Replacement generation'");
    return result;
  }})})};
  const result = await searchEntities(swapping, {uei: "ABCDEFGHIJK1"});
  assert.equal(queries.length, 1);
  assert.equal(result.file_date, "2026-10-01");
  assert.equal(result.entityData[0].entityRegistration.legalBusinessName, "Alpha Systems LLC");
  assert.match(queries[0].sql, /WITH matches AS NOT MATERIALIZED/);
  assert.match(queries[0].sql, /s\.\* FROM extract_status/);
});

test("quarantined source rows are disclosed, and missing database gives a corrective ToolError", async () => {
  const {db, sqlite} = database();
  sqlite.exec("UPDATE extract_status SET rejected_rows=7");
  assert.match((await searchEntities(db, {})).notes.join(" "), /7 malformed source rows were quarantined and excluded/);
  await assert.rejects(searchEntities(undefined as any, {}), /public entity data is unavailable/);
});

test("registrations sharing a UEI retain separate CAGE, NAICS and certification matches", async () => {
  const {db, sqlite} = database();
  sqlite.prepare("INSERT INTO entities (entity_id,uei,cage_code,legal_business_name,registration_status,primary_naics) VALUES (?,?,?,?,?,?)")
    .run("second-registration", "ABCDEFGHIJK1", "9ABCD", "Alpha Systems LLC", "Active", "236220");
  sqlite.prepare("INSERT INTO entity_naics (entity_id,code) VALUES (?,?)").run("second-registration", "236220");
  sqlite.prepare("INSERT INTO entity_business_types (entity_id,code,kind) VALUES (?,?,?)").run("second-registration", "A9", "sba");
  const lookup = await searchEntities(db, {uei: "ABCDEFGHIJK1"});
  assert.equal(lookup.totalRecords, 2);
  assert.deepEqual(lookup.entityData.map(row => row.entityRegistration.cageCode), ["1ABCD", "9ABCD"]);
  assert.equal((await searchEntities(db, {cage_code: "9ABCD", any_naics: "541512"})).totalRecords, 0);
  assert.equal((await searchEntities(db, {cage_code: "9ABCD", sba_business_type_code: "XX"})).totalRecords, 0);
  assert.equal((await searchEntities(db, {uei: "ABCDEFGHIJK1", any_naics: "236220", sba_business_type_code: "A9"})).totalRecords, 1);
  const page = await searchEntities(db, {uei: "ABCDEFGHIJK1", size: 1, page: 1});
  assert.equal(page.entityData[0].entityRegistration.cageCode, "9ABCD");
});

test("unfiltered discovery does not materialize full entity records for counting", async () => {
  const {db, sqlite, queries} = database();
  await searchEntities(db, {});
  const query = queries[0];
  const plan = sqlite.prepare("EXPLAIN QUERY PLAN " + query.sql).all(...query.values as any[]) as any[];
  const details = plan.map(row => row.detail).join("\n");
  assert.doesNotMatch(details, /MATERIALIZE matches/);
  assert.match(details, /COVERING INDEX/);
  assert.match(details, /SEARCH e USING INDEX entities_status_name/);
  assert.doesNotMatch(details, /TEMP B-TREE/);
  assert.match(query.sql, /e\.registration_status = \?/);
  assert.equal(query.values[0], "Active");
});

test("legacy cached NAICS aliases normalize to the official API key without changing flags", async () => {
  const {db, sqlite} = database();
  const cached = {entityRegistration: {ueiSAM: "ABCDEFGHIJK1"}, assertions: {goodsAndServices: {naicsList: [
    {naicsCode: "541512", naicsSmallBusinessIndicator: "Y", isPrimary: "Y"},
    {naicsCode: "541511", naicsSmallBusinessIndicator: "N", isPrimary: "N"},
    {naicsCode: "236220", naicsSmallBusinessIndicator: "N", sbaSmallBusiness: "Y", isPrimary: "N"},
    {naicsCode: "541519", naicsSmallBusinessIndicator: "E", isPrimary: "N"},
    {naicsCode: "541513", naicsSmallBusinessIndicator: null, isPrimary: "N"},
    {naicsCode: "541514", naicsSmallBusinessIndicator: "", isPrimary: "N"},
  ]}}};
  sqlite.prepare("UPDATE entities SET record_json=? WHERE uei=?").run(JSON.stringify(cached), "ABCDEFGHIJK1");
  const result = await searchEntities(db, {uei: "ABCDEFGHIJK1", include_sections: ["assertions"]});
  assert.deepEqual(result.entityData[0].assertions.goodsAndServices.naicsList, [
    {naicsCode: "541512", sbaSmallBusiness: "Y", isPrimary: "Y"},
    {naicsCode: "541511", sbaSmallBusiness: "N", isPrimary: "N"},
    {naicsCode: "236220", sbaSmallBusiness: "Y", isPrimary: "N"},
    {naicsCode: "541519", isPrimary: "N"},
    {naicsCode: "541513", isPrimary: "N"},
    {naicsCode: "541514", isPrimary: "N"},
  ]);
  assert.doesNotMatch(JSON.stringify(result), /naicsSmallBusinessIndicator/);
  assert.match((sqlite.prepare("SELECT record_json FROM entities WHERE uei=?").get("ABCDEFGHIJK1") as any).record_json, /naicsSmallBusinessIndicator/);
});

test("unfinished incremental entities refresh hides partial records until completion", async () => {
 const {db, sqlite} = database();
 sqlite.exec("INSERT INTO public_refresh_runs VALUES ('entities','applying','target','parser','{}',3,100,10,'2026-10','now','now','owner','later')");
 await assert.rejects(() => searchEntities(db, {}), /refreshing/);
 sqlite.exec("UPDATE public_refresh_runs SET state='complete'");
 assert.ok(await searchEntities(db, {}));
 sqlite.close();
});
