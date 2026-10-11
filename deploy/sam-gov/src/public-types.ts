export interface Database {
  prepare(sql: string): {bind(...values: unknown[]): {all<T = Record<string, unknown>>(): Promise<{results: T[]}>}};
}
export class ToolError extends Error {}
