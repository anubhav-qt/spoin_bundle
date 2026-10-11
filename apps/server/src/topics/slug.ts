/**
 * A topic's slug from its name. One function for the request path and the curriculum
 * projection, so a pending topic and the authored topic it becomes agree on a slug.
 */
export const slugify = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .split(/\s+/u)
    .join("-")
    .replaceAll(/[^a-z0-9-]/g, "") || "topic";
