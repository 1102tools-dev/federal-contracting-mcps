// The bundled GSA files in D1 (see schema.sql and scripts/load_gsa_perdiem.py),
// read the way the package's snapshot.py and _geo.py read them from disk.
import {loads, squash, strip, WORD} from "./py.ts";

export interface Statement {
  bind(...values: unknown[]): Statement;
  all<T = Record<string, unknown>>(): Promise<{results: T[]}>;
}

export interface Database {
  prepare(sql: string): Statement;
  batch<T = Record<string, unknown>>(statements: Statement[]): Promise<{results: T[]}[]>;
}

/** Thrown when D1 holds no loaded release; reported as temporarily unavailable. */
export class DataUnavailable extends Error {}

export const STANDARD = "S";
export type Area = number | typeof STANDARD;
type Hits = [string, string][];

interface Destination {id: number; name: string; state: string; location_defined: string; meals: number; months: number[]}

export interface YearData {
  fiscal_year: number;
  months: string[];
  standard: {meals: number; months: number[]};
  destinations: Destination[];
  state_members: Record<string, number[]>;
  county_map: Record<string, number>;
  place_map: Record<string, number>;
  excluded: Record<string, string[]>;
  mie_tiers: Record<string, unknown>[];
  source: Record<string, unknown>;
}

export interface AreaRecord {
  area_id: Area;
  destination: string;
  state: string;
  location_defined: string;
  is_standard_rate: boolean;
  lodging_by_month: Record<string, number>;
  meals: number;
}

// ---------- _geo.py ----------

const SAINT = new RegExp(`(?<!${WORD})saint(?!${WORD})`, "gu");
const ST_DOT = new RegExp(`(?<!${WORD})st\\.`, "gu");
const COUNTY_SUFFIX = new RegExp(`[\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+(county|parish|counties|parishes)$`, "iu");

export function norm(name: string): string {
  let s = name.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replaceAll("’", "'").replaceAll("‘", "'");
  s = s.replace(SAINT, "st").replace(ST_DOT, "st");
  s = s.replaceAll("'", "").replaceAll("`", "").replaceAll(".", "");
  s = s.replaceAll("-", " ").replaceAll("/", " ").replaceAll(",", " ");
  return squash(s);
}

export const countyKey = (state: string, county: string) =>
  `${strip(state).toUpperCase()}|${norm(strip(county).replace(COUNTY_SUFFIX, ""))}`;
export const placeKey = (state: string, place: string) => `${strip(state).toUpperCase()}|${norm(place)}`;

// ---------- snapshot.py ----------

export class Year {
  readonly data: YearData;
  readonly fiscal_year: number;
  readonly destinations = new Map<number, Destination>();
  private places: Places;
  private byStateName = new Map<string, number>();

  constructor(data: YearData, places: Places) {
    this.data = data;
    this.places = places;
    this.fiscal_year = data.fiscal_year;
    for (const d of data.destinations) this.destinations.set(d.id, d);
    for (const [st, ids] of Object.entries(data.state_members)) {
      for (const i of ids) this.byStateName.set(`${st}\0${this.destinations.get(i)!.name}`, i);
    }
  }

  get source() { return this.data.source; }
  get mie_tiers() { return this.data.mie_tiers; }

  areaRate(area: Area, state: string): AreaRecord {
    const months = this.data.months;
    if (area === STANDARD) {
      return {
        area_id: STANDARD, destination: "Standard Rate", state,
        location_defined: `All ${state} locations outside a listed rate area`, is_standard_rate: true,
        lodging_by_month: Object.fromEntries(months.map((m, i) => [m, this.data.standard.months[i]])),
        meals: this.data.standard.meals,
      };
    }
    const d = this.destinations.get(area)!;
    return {
      area_id: d.id, destination: d.name, state: d.state, location_defined: d.location_defined, is_standard_rate: false,
      lodging_by_month: Object.fromEntries(months.map((m, i) => [m, d.months[i]])), meals: d.meals,
    };
  }

  zipAreas(entries: (number | string)[]): [Area, string][] {
    return entries.map(e => (typeof e === "string" ? [STANDARD, e] : [e, this.destinations.get(e)!.state]));
  }

  stateDestinationIds(state: string): number[] {
    return [...(this.data.state_members[state] ?? [])];
  }

  destinationId(state: string, name: string): number | undefined {
    return this.byStateName.get(`${state}\0${name}`);
  }

  private excludes(dest: number, key: string) {
    return (this.data.excluded[String(dest)] ?? []).includes(key);
  }

  /** Area for a county (plus optional place for carve-outs). null if not a county. */
  async areaForCounty(state: string, county: string, place?: string | null): Promise<Area | null> {
    let ck = countyKey(state, county);
    const alt = countyKey(state, county + " city");
    const known = await this.places.get([ck, alt]);
    if (!known.has(ck)) {
      if (!known.has(alt)) return null;
      ck = alt;
    }
    if (place) {
      const pk = placeKey(state, place);
      if (pk in this.data.place_map) {
        const hits = ((await this.places.get([pk])).get(pk) ?? []).filter(([, kind]) => kind !== "county");
        if (hits.length && !hits.some(([county]) => county === ck)) return null;
        return this.data.place_map[pk];
      }
    }
    const dest = this.data.county_map[ck];
    if (dest !== undefined && place && this.excludes(dest, placeKey(state, place))) return null;
    return dest !== undefined ? dest : STANDARD;
  }

  /** Areas a Census place/town/county of this name falls in, and its counties. */
  async censusAreas(state: string, place: string): Promise<[Set<Area>, string[]]> {
    const pk = placeKey(state, place);
    if (pk in this.data.place_map) return [new Set([this.data.place_map[pk]]), []];
    let hits = (await this.places.get([pk])).get(pk) ?? [];
    if (hits.some(([, kind]) => kind !== "county")) hits = hits.filter(h => h[1] !== "county");
    const areas = new Set<Area>();
    const counties: string[] = [];
    for (const [ck] of hits) {
      counties.push(ck);
      const dest = this.data.county_map[ck];
      if (dest !== undefined && this.excludes(dest, pk)) continue;
      areas.add(dest !== undefined ? dest : STANDARD);
    }
    return [areas, [...new Set(counties)].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))];
  }
}

/** Census names from the places table, memoized for one tool call. */
export class Places {
  private memo = new Map<string, Hits | null>();
  private db: Database;
  constructor(db: Database) {
    this.db = db;
  }

  async get(keys: string[]): Promise<Map<string, Hits>> {
    const missing = [...new Set(keys)].filter(k => !this.memo.has(k));
    if (missing.length) {
      const {results} = await this.db.prepare(
        `SELECT key, hits FROM places WHERE part = (SELECT json_extract(parts, '$.places') FROM release WHERE id = 1) AND key IN (${missing.map(() => "?").join(", ")})`,
      ).bind(...missing).all<{key: string; hits: string}>();
      for (const k of missing) this.memo.set(k, null);
      for (const r of results) this.memo.set(r.key, JSON.parse(r.hits));
    }
    const out = new Map<string, Hits>();
    for (const k of keys) {
      const hit = this.memo.get(k);
      if (hit) out.set(k, hit);
    }
    return out;
  }
}

// Parsed year files by part id. Parts are immutable, so entries never go stale.
const YEAR_CACHE = new Map<string, YearData>();
const YEAR_CACHE_MAX = 8;

const PART = "(SELECT json_extract(parts, '$.' || ?1) FROM release WHERE id = 1)";

/** Per-call access to the active release. */
export class Snapshot {
  readonly places: Places;
  private db: Database;
  private years = new Map<number, Promise<Year | null>>();

  constructor(db: Database) {
    this.db = db;
    this.places = new Places(db);
  }

  private async fetchYear(fy: number, zip?: string): Promise<[Year | null, (number | string)[]]> {
    const name = `fy${fy}`;
    const cachedPart = [...YEAR_CACHE.keys()].find(k => YEAR_CACHE.get(k)!.fiscal_year === fy) ?? "";
    const yearSql = `SELECT r.release, y.part, CASE WHEN y.part = ?2 THEN NULL ELSE y.data END AS data
      FROM release r LEFT JOIN years y ON y.part = json_extract(r.parts, '$.' || ?1) WHERE r.id = 1`;
    const statements = [this.db.prepare(yearSql).bind(name, cachedPart)];
    if (zip !== undefined) statements.push(this.db.prepare(`SELECT entries FROM zips WHERE part = ${PART} AND zip = ?2`).bind(name, zip));
    const [yearResult, zipResult] = await this.db.batch<any>(statements);
    const row = yearResult.results[0];
    if (!row) throw new DataUnavailable("GSA per diem data has not been loaded.");
    let year: Year | null = null;
    if (row.part) {
      let data = YEAR_CACHE.get(row.part);
      if (!data) {
        data = loads(row.data) as YearData;
        for (const [k, v] of YEAR_CACHE) if (v.fiscal_year === fy) YEAR_CACHE.delete(k);
        YEAR_CACHE.set(row.part, data);
        while (YEAR_CACHE.size > YEAR_CACHE_MAX) YEAR_CACHE.delete(YEAR_CACHE.keys().next().value!);
      }
      year = new Year(data, this.places);
    }
    const entries = zipResult?.results[0]?.entries;
    return [year, entries ? JSON.parse(entries) : []];
  }

  /** snapshot.load_year(): null when the fiscal year is not bundled. */
  year(fy: number): Promise<Year | null> {
    if (!this.years.has(fy)) this.years.set(fy, this.fetchYear(fy).then(([y]) => y));
    return this.years.get(fy)!;
  }

  /** The year and the ZIP's rate-area entries in one round trip. */
  async yearWithZip(fy: number, zip: string): Promise<[Year | null, (number | string)[]]> {
    const [year, entries] = await this.fetchYear(fy, zip);
    this.years.set(fy, Promise.resolve(year));
    return [year, entries];
  }

  async manifest(): Promise<any> {
    const {results} = await this.db.prepare("SELECT manifest FROM release WHERE id = 1").bind().all<{manifest: string}>();
    if (!results.length) throw new DataUnavailable("GSA per diem data has not been loaded.");
    return JSON.parse(results[0].manifest);
  }
}
