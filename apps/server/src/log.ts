import pino from "pino";

/**
 * One logger for every entrypoint. JSON in production; pretty in a terminal. A request
 * line carries the request id and the acting user id (never an email): enough to
 * correlate a report with its request without putting personal data in the logs.
 */
export const log = pino({
  level: process.env.LOG_LEVEL ?? "info",
  base: { service: process.env.SERVICE ?? "spoin" },
  transport:
    process.env.NODE_ENV === "production" || !process.stdout.isTTY
      ? undefined
      : { target: "pino-pretty", options: { translateTime: "SYS:HH:MM:ss", ignore: "pid,hostname,service" } },
});
