// Harness stub: log to stderr with a timestamp (no files).
const p = (lvl: string, a: unknown[]) => process.stderr.write(`[${Date.now()}] ${lvl} ${a.map(String).join(' ')}\n`)
export function logError(...args: unknown[]): void { p('ERR', args) }
export function logWarn(...args: unknown[]): void { p('WARN', args) }
export function logInfo(...args: unknown[]): void { p('INFO', args) }
export function recentLogLines(): string[] { return [] }
export function logTail(): string { return '' }
