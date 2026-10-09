// A D1-shaped adapter over node:sqlite for tests and the parity harness, and
// a loader run that builds the database the way production gets it.
import {execFileSync} from "node:child_process";
import {mkdtempSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {DatabaseSync} from "node:sqlite";
import {fileURLToPath} from "node:url";
import type {Database} from "../src/data.ts";

export const ROOT = fileURLToPath(new URL("../../../", import.meta.url));

class Statement {
  readonly sqlite: DatabaseSync;
  readonly sql: string;
  readonly values: unknown[];
  constructor(sqlite: DatabaseSync, sql: string, values: unknown[] = []) {
    this.sqlite = sqlite;
    this.sql = sql;
    this.values = values;
  }
  bind(...values: unknown[]) {
    return new Statement(this.sqlite, this.sql, values);
  }
  run<T>(): {results: T[]} {
    return {results: this.sqlite.prepare(this.sql).all(...(this.values as any[])) as T[]};
  }
  async all<T>() {
    return this.run<T>();
  }
}

export interface TestDatabase extends Database {
  sqlite: DatabaseSync;
  reads: number;
}

/** D1's prepare/bind/all and batch (one transaction) over a SQLite file or :memory:. */
export function d1(sqlite: DatabaseSync): TestDatabase {
  const db: TestDatabase = {
    sqlite,
    reads: 0,
    prepare: (sql: string) => {
      db.reads++;
      return new Statement(sqlite, sql) as any;
    },
    batch: async <T>(statements: any[]) => {
      sqlite.exec("BEGIN");
      try {
        const out = statements.map(s => (s as Statement).run<T>());
        sqlite.exec("COMMIT");
        return out;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  };
  return db;
}

/** Run scripts/load_gsa_perdiem.py --local into a fresh SQLite file; returns its path. */
export function loadedDatabaseFile(): string {
  const path = join(mkdtempSync(join(tmpdir(), "gsa-perdiem-")), "perdiem.sqlite");
  execFileSync("python3", [join(ROOT, "scripts/load_gsa_perdiem.py"), "--local", path], {stdio: ["ignore", "ignore", "inherit"]});
  return path;
}
