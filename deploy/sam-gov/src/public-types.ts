export type Statement = {all<T = Record<string, unknown>>(): Promise<{results: T[]}>};
export interface Database {
  prepare(sql: string): {bind(...values: unknown[]): Statement};
  // D1 runs a batch as one transaction, so its statements read one snapshot.
  batch?(statements: Statement[]): Promise<{results: any[]}[]>;
}
export class ToolError extends Error {}
