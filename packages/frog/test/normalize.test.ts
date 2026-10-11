import { describe, expect, it } from "vitest";
import { normalizeTopicText } from "../src/normalize.ts";

// ADR-0093: one normalizer for topic names, categories and tags, so "Computer Science"
// and "computer-science" can never become two categories.
describe("normalizeTopicText", () => {
  it.each([
    ["Computer Science", "computer science"],
    ["computer-science", "computer science"],
    ["  Distributed   Systems ", "distributed systems"],
    ["C++ & Rust!", "c rust"],
    ["Écoles françaises", "écoles françaises"],
    ["PostgreSQL 17", "postgresql 17"],
    ["?!", ""],
  ])("%j becomes %j", (raw, expected) => {
    expect(normalizeTopicText(raw)).toBe(expected);
  });
});
