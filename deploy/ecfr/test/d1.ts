// A D1-shaped adapter over node:sqlite for tests and the parity harness.
// batch() runs its statements in one transaction, as D1 does, and every
// statement is recorded so tests can check how the Worker queries.
import {DatabaseSync} from "node:sqlite";

export interface Recorded {
  sql: string;
  values: unknown[];
  batch: number;
}

export function d1(sqlite: DatabaseSync) {
  const log: Recorded[] = [];
  let batches = 0;
  const run = (sql: string, values: unknown[], batch: number) => {
    log.push({sql, values, batch});
    return {results: sqlite.prepare(sql).all(...(values as any[])) as any[]};
  };
  const statement = (sql: string, values: unknown[] = []): any => ({
    sql, values,
    bind: (...next: unknown[]) => statement(sql, next),
    all: async () => run(sql, values, ++batches),
  });
  return {
    log,
    prepare: (sql: string) => statement(sql),
    batch: async (statements: {sql: string; values: unknown[]}[]) => {
      const batch = ++batches;
      sqlite.exec("BEGIN");
      try {
        const results = statements.map(s => run(s.sql, s.values, batch));
        sqlite.exec("COMMIT");
        return results;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  };
}
