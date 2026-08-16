/**
 * Client-only aggregate types — not a 1:1 mirror of any single API response,
 * so they don't belong in api.ts alongside the wire contracts.
 */

export interface TopicProgress {
  coverage: number;
  quizUnlocked: boolean;
  mastered: boolean;
  /** Count of tiers (beginner/intermediate/advanced) whose quiz has been passed. */
  quizTiersPassed: number;
}
