/** Timestamps cross the wire as ISO 8601 strings; Drizzle hands back `Date`s. */
export const iso = (d: Date): string => d.toISOString();

export const isoOrNull = (d: Date | null | undefined): string | null => (d ? d.toISOString() : null);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True for a well-formed UUID; Postgres raises on anything else, so check before querying. */
export const isUuid = (value: string): boolean => UUID.test(value);
