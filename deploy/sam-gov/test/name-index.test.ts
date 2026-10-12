// The trigram name index only narrows candidates; results must equal the
// unindexed search, and a stale or missing index must be ignored.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {searchEntities} from "../src/entity-tools.ts";
import {searchExclusions} from "../src/exclusion-tools.ts";
import {normalizedName, trigramMatch} from "../src/name-matching.ts";

function adapter(sqlite: DatabaseSync, log: string[] = []) {
  return {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => {
    log.push(sql);
    return {results: sqlite.prepare(sql).all(...values as any[]) as any[]};
  }})})};
}

function databases(indexSha = "sha") {
  const source = new DatabaseSync(":memory:");
  source.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  for (const kind of ["entities", "exclusions"]) source.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)").run(kind, "file.zip", "2026-10-11", "https://sam.gov/public", "2026-10-11T10:00:00Z", 3, "sha", 1, 1);
  const names: [string, string | null][] = [["Booz Allen Hamilton Inc.", null], ["Allen & Sons LLC", "Hamilton Allen"], ["Acme Widgets", "Allen Federal"], ["Unrelated Co", null]];
  names.forEach(([legal, dba], i) => source.prepare("INSERT INTO entities (entity_id,uei,legal_business_name,dba_name,registration_status) VALUES (?,?,?,?,?)").run(`e${i}`, `UEI00000000${i}`, legal, dba, "Active"));
  const people: [string | null, string | null, string | null, string | null][] = [[null, "Allen", "Q", "Smith"], ["Allen Industries", null, null, null], [null, "Mary", null, "Hamilton"]];
  people.forEach(([name, first, middle, last], i) => source.prepare("INSERT INTO exclusions (exclusion_id,name,first_name,middle_name,last_name,record_status) VALUES (?,?,?,?,?,?)").run(`x${i}`, name, first, middle, last, "Active"));
  const index = new DatabaseSync(":memory:");
  index.exec(readFileSync(new URL("../name-index-schema.sql", import.meta.url), "utf8"));
  for (const row of source.prepare("SELECT rowid AS r, legal_business_name AS a, dba_name AS b FROM entities").all() as any[]) index.prepare("INSERT INTO entities_name_index(rowid,legal,dba) VALUES (?,?,?)").run(row.r, normalizedName(row.a ?? ""), normalizedName(row.b ?? ""));
  for (const row of source.prepare("SELECT rowid AS r, name AS a, coalesce(first_name,'')||' '||coalesce(middle_name,'')||' '||coalesce(last_name,'') AS b, coalesce(first_name,'')||' '||coalesce(last_name,'') AS c FROM exclusions").all() as any[]) index.prepare("INSERT INTO exclusions_name_index(rowid,name,full_name,short_name) VALUES (?,?,?,?)").run(row.r, normalizedName(row.a ?? ""), normalizedName(row.b), normalizedName(row.c));
  for (const kind of ["entities", "exclusions"]) index.prepare("INSERT INTO name_index_status VALUES (?,?,?,?,datetime('now'))").run(kind, indexSha, "2026-10-11T10:00:00Z", 3);
  return {source, index};
}

const strip = (result: any) => ({...result, notes: undefined});

test("indexed entity and exclusion name searches equal the unindexed results", async () => {
  const {source, index} = databases();
  for (const name of ["allen", "Hamilton", "booz allen", "Allen Federal", "acme", "nothing here", "allen&sons"]) {
    const log: string[] = [];
    const indexed = await searchEntities(adapter(source, log), {legal_business_name: name}, undefined, adapter(index));
    assert.deepEqual(strip(indexed), strip(await searchEntities(adapter(source), {legal_business_name: name})), name);
    if (trigramMatch(name) && indexed.totalRecords) assert.match(log[0], /json_each/, name);
    assert.deepEqual(strip(await searchExclusions(adapter(source), {entity_name: name}, undefined, adapter(index))), strip(await searchExclusions(adapter(source), {entity_name: name})), name);
  }
  assert.deepEqual((await searchEntities(adapter(source), {legal_business_name: "allen"}, undefined, adapter(index))).entityData.map((e: any) => e.entityRegistration.legalBusinessName).sort(),
    ["Acme Widgets", "Allen & Sons LLC", "Booz Allen Hamilton Inc."]);
});

test("an index built for another source generation, or a missing index, is not used", async () => {
  const {source, index} = databases("older-sha");
  const log: string[] = [];
  const result = await searchEntities(adapter(source, log), {legal_business_name: "allen"}, undefined, adapter(index));
  assert.equal(result.totalRecords, 3);
  assert.equal(log.length, 2);
  assert.doesNotMatch(log[1], /json_each\(\?\)\)/);
  const broken = {prepare: () => { throw new Error("no such table"); }};
  assert.equal((await searchExclusions(adapter(source), {entity_name: "allen"}, undefined, broken as any)).totalRecords, 2);
});

test("short queries skip the index", async () => {
  assert.equal(trigramMatch("ab"), undefined);
  assert.equal(trigramMatch("Co, Inc."), undefined);
  assert.equal(trigramMatch("abcd"), '"abc" AND "bcd"');
});
