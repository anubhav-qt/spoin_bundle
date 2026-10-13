/**
 * The tag the handovers wrap around a requested topic name and description, the requester's own
 * words (`handovers/job.njk`, `merge.njk`). Taken out of the words, so they can't close it and stay
 * inside the part marked as data.
 */
const REQUEST_TAG = /<\s*\/?\s*request\b[^>]*>/gi;

export function withoutRequestTag(text: string): string {
  return text.replace(REQUEST_TAG, "");
}
