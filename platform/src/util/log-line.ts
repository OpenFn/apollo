// A line a service logged on purpose, as opposed to whatever else lands on a
// stream. Only these are forwarded to the caller. Shared by bridge.ts and
// bridge.fork.ts.
export const LOG_LINE = /^(INFO|DEBUG|ERROR|WARNING):/;
