/** Times as India reads them (Asia/Kolkata, always UTC+5:30), for what chats are told (Trotter's). */

export const INDIA_TIME_ZONE = "Asia/Kolkata";

/** For example "Tuesday 13 October 2026, 15:42". */
export function indiaTime(moment: Date): string {
  const format = new Intl.DateTimeFormat("en-GB", {
    timeZone: INDIA_TIME_ZONE,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const parts = new Map(format.formatToParts(moment).map((part) => [part.type, part.value]));
  const date = `${parts.get("weekday")} ${parts.get("day")} ${parts.get("month")} ${parts.get("year")}`;
  return `${date}, ${parts.get("hour")}:${parts.get("minute")}`;
}
