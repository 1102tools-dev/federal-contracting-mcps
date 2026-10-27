import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {DatabaseSync} from "node:sqlite";
import {test} from "node:test";
import {searchEntities} from "../src/entity-tools.ts";
import {searchExclusions} from "../src/exclusion-tools.ts";
import {normalizedName, namePredicate, possibleNameMatches} from "../src/name-matching.ts";

function fixture() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec(readFileSync(new URL("../entity-schema.sql", import.meta.url), "utf8"));
  for (const kind of ["entities", "exclusions"]) {
    sqlite.prepare("INSERT INTO extract_status (kind,file_name,file_date,source_url,loaded_at,row_count,sha256,database_bytes,load_seconds) VALUES (?,?,?,?,?,?,?,?,?)")
      .run(kind, `${kind}-fixture.zip`, "2026-10-11", "https://sam.gov/public", "2026-10-11T12:00:00Z", 0, "fixture", 4096, 1);
  }
  let sequence = 0;
  const add = (name: string, extras: {dba?: string; first?: string; middle?: string; last?: string; individual?: boolean; state?: string} = {}) => {
    sequence++;
    const uei = `NAMETEST${String(sequence).padStart(4, "0")}`;
    const cage = `N${String(sequence).padStart(4, "0")}`;
    sqlite.prepare("INSERT INTO entities (entity_id,uei,cage_code,legal_business_name,dba_name,registration_status,state,naics_codes_json,business_type_codes_json,sba_business_type_codes_json) VALUES (?,?,?,?,?,?,?,?,?,?)")
      .run(`entity-${sequence}`, uei, cage, name, extras.dba ?? null, "Active", extras.state ?? "VA", "[]", "[]", "[]");
    sqlite.prepare("INSERT INTO exclusions (exclusion_id,uei,cage_code,name,first_name,middle_name,last_name,classification,record_status,state,country) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
      .run(`exclusion-${sequence}`, uei, cage, name, extras.first ?? null, extras.middle ?? null, extras.last ?? null, extras.individual ? "Individual" : "Firm", "Active", extras.state ?? "VA", "USA");
    return {uei, cage};
  };
  const queries: {sql: string; values: unknown[]}[] = [];
  const db = {prepare: (sql: string) => ({bind: (...values: unknown[]) => ({all: async () => {
    queries.push({sql, values});
    return {results: sqlite.prepare(sql).all(...values as any[]) as any[]};
  }})})};
  return {sqlite, db, add, queries};
}

const smithVariants = ["A and A Smith", "A&A Smith", "A & A Smith Corp", "AandA Smith"];
const boozVariants = ["Booz Allen Hamilton", "boozallen hamilton", "Booz-Allen Hamilton", "“Booz–Allen Hamilton”"];

test("canonical names equate conjunction, punctuation, and joined-word variants", () => {
  for (const variants of [smithVariants, boozVariants]) {
    for (const name of variants) assert.equal(normalizedName(name), normalizedName(variants[0]), name);
  }
});

test("suffix normalization keeps a distinctive name while rejecting suffix-only queries", () => {
  for (const suffix of ["Inc", "LLC", "Corp", "Corporation", "Co", "Company", "Ltd", "LP", "PLLC", "The"]) {
    assert.equal(normalizedName(`Distinctive Research ${suffix}`), normalizedName("Distinctive Research"), suffix);
    assert.equal(normalizedName(suffix), "", suffix);
  }
  assert.equal(normalizedName("The Distinctive Research LLC"), normalizedName("Distinctive Research"));
});

test("both hosted searches find ampersand and joined-word variants without broadening identifiers", async () => {
  const {db, add, sqlite} = fixture();
  const smith = smithVariants.map(name => add(name));
  const booz = boozVariants.map(name => add(name));
  add("Unrelated Smith Holdings");
  for (const name of smithVariants) {
    assert.equal((await searchEntities(db, {legal_business_name: name})).totalRecords, smith.length, name);
    assert.equal((await searchExclusions(db, {entity_name: name})).totalRecords, smith.length, name);
  }
  for (const name of [...boozVariants, "booz allen", "Booz-Allen"]) {
    assert.equal((await searchEntities(db, {legal_business_name: name})).totalRecords, booz.length, name);
    assert.equal((await searchExclusions(db, {entity_name: name})).totalRecords, booz.length, name);
  }
  assert.equal((await searchEntities(db, {uei: smith[0].uei, legal_business_name: "A&A Smith"})).totalRecords, 1);
  assert.equal((await searchExclusions(db, {cage_code: smith[0].cage, entity_name: "AandA Smith"})).totalRecords, 1);
  assert.equal((await searchEntities(db, {uei: smith[0].uei, legal_business_name: "Booz Allen"})).totalRecords, 0);
  assert.equal((await searchExclusions(db, {uei: smith[0].uei, entity_name: "Booz Allen"})).totalRecords, 0);
  sqlite.close();
});

test("every legal suffix remains searchable across entity and exclusion datasets", async () => {
  const {db, add, sqlite} = fixture();
  const suffixes = ["Inc", "LLC", "Corp", "Corporation", "Co", "Company", "Ltd", "LP", "PLLC", "The"];
  for (const suffix of suffixes) add(`Distinctive Research ${suffix}`);
  for (const suffix of suffixes) {
    assert.equal((await searchEntities(db, {legal_business_name: `Distinctive Research ${suffix}`})).totalRecords, suffixes.length);
    assert.equal((await searchExclusions(db, {entity_name: `Distinctive Research ${suffix}`})).totalRecords, suffixes.length);
  }
  sqlite.close();
});

test("entities match DBA names and exclusions assemble blank-name individual fields", async () => {
  const {db, add, sqlite} = fixture();
  const dba = add("Parent Legal Corporation", {dba: "Lightning Works LLC"});
  add("", {first: "Aaron", middle: "Jeffrey", last: "Smith", individual: true, state: "OR"});
  add("Aaron Different Smith", {first: "Aaron", middle: "Different", last: "Smith", individual: true, state: "WA"});
  const found = await searchEntities(db, {legal_business_name: "Lightning-Works"});
  assert.equal(found.totalRecords, 1);
  assert.equal(found.entityData[0].entityRegistration.ueiSAM, dba.uei);
  for (const name of ["Aaron Jeffrey Smith", "Aaron Smith"]) {
    const individuals = await searchExclusions(db, {entity_name: name, classification: "Individual", state_province: "OR"});
    assert.equal(individuals.totalRecords, 1, name);
    assert.equal(individuals.excludedEntity[0].exclusionIdentification.firstName, "Aaron");
    assert.equal(individuals.excludedEntity[0].exclusionIdentification.lastName, "Smith");
  }
  sqlite.close();
});

test("name predicate binds user values and never turns punctuation into SQL patterns", () => {
  const predicate = namePredicate(["legal_business_name", "dba_name"], "A&A Smith");
  assert.ok(predicate.values.length > 0);
  assert.doesNotMatch(predicate.sql, /A&A Smith/);
  assert.doesNotMatch(predicate.sql, /\bLIKE\b/i);
});

test("suffix-only queries fail closed rather than returning the entire registry", async () => {
  const {db, add, queries, sqlite} = fixture();
  add("Unrelated Vendor LLC");
  for (const name of ["LLC", "Inc Corp Company", "The", "& and"]) {
    const entityStart = queries.length;
    try { assert.equal((await searchEntities(db, {legal_business_name: name})).totalRecords, 0); }
    catch (error) { assert.match(String(error), /name|distinctive|meaningful|normaliz|invalid/i); }
    assert.ok(queries.length - entityStart <= 1);
    try { assert.equal((await searchExclusions(db, {entity_name: name})).totalRecords, 0); }
    catch (error) { assert.match(String(error), /name|distinctive|meaningful|normaliz|invalid/i); }
  }
  sqlite.close();
});

test("near typos are possible candidates, not confirmed exclusions or entity identity", async () => {
  const {db, add, sqlite} = fixture();
  const expected = add("Booz Allen Hamilton Inc");
  const entity = await searchEntities(db, {legal_business_name: "Booz Alen Hamilton"});
  const exclusion = await searchExclusions(db, {entity_name: "Booz Alen Hamilton"});
  for (const result of [entity, exclusion]) {
    assert.equal(result.totalRecords, 0);
    assert.ok(Array.isArray(result.possibleMatches));
    assert.ok(result.possibleMatches.length > 0);
    assert.ok(result.possibleMatches.length <= 5);
    for (const candidate of result.possibleMatches) {
      assert.equal(candidate.label, "possible matches, not confirmed");
      assert.equal(typeof candidate.matched_name, "string");
    }
    assert.match(JSON.stringify(result.possibleMatches), new RegExp(expected.uei));
    assert.match(JSON.stringify(result), /possible matches/i);
    assert.match(JSON.stringify(result), /not confirmed|not a confirmed|verify.*identit/i);
  }
  sqlite.close();
});

test("possible candidates preserve state and exact-identifier constraints", async () => {
  const {db, add, sqlite} = fixture();
  add("Booz Allen Hamilton Inc", {state: "VA"});
  for (const result of [
    await searchEntities(db, {legal_business_name: "Booz Alen Hamilton", state_code: "OH"}),
    await searchExclusions(db, {entity_name: "Booz Alen Hamilton", state_province: "OH"}),
    await searchEntities(db, {legal_business_name: "Booz Alen Hamilton", uei: "WRONGUEI0001"}),
    await searchExclusions(db, {entity_name: "Booz Alen Hamilton", cage_code: "WRONG"}),
  ]) {
    assert.equal(result.totalRecords, 0);
    assert.equal(result.possibleMatches?.length ?? 0, 0);
  }
  sqlite.close();
});

test("a name search that spans a refresh asks the caller to come back later", async () => {
  const {sqlite, db, add} = fixture();
  add("Acme Widgets");
  const options = {table: "entities" as const, kind: "entities" as const, columns: ["legal_business_name", "dba_name"], projection: ["entity_id", "legal_business_name", "dba_name"], where: [], values: [], query: "Acme Widgetz"};
  const message = "SAM.gov name search is refreshing. Try again in about 10 minutes; confirm current status on SAM.gov.";
  await assert.rejects(possibleNameMatches(db, {...options, snapshot: {sha256: "older", loaded_at: "2026-10-11T12:00:00Z"}}), {message});
  sqlite.exec("INSERT INTO public_refresh_runs VALUES ('entities','applying','target','parser','{}',3,100,10,'2026-10','now','now','owner','later')");
  await assert.rejects(possibleNameMatches(db, {...options, snapshot: {sha256: "fixture", loaded_at: "2026-10-11T12:00:00Z"}}), {message});
  sqlite.close();
});
