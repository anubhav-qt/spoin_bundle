import { CARD_TYPES, MAX_TARGET_CARDS, MIN_TARGET_CARDS, TIERS } from "@spoin/frog/curriculum/contract";
import { documentScope } from "@spoin/frog/schema";
import { DIFFICULTIES, CARD_TYPES as SHARED_CARD_TYPES, TOPIC_SCOPES } from "@spoin/shared/enums";
import { describe, expect, test } from "vitest";
import { subtopic } from "../src/db/schema.ts";
import { makeTopic } from "./fixtures.ts";
import { deps } from "./helpers.ts";

/*
 * frog never imports the server or the shared contract (ADR-0087), so the values the two
 * sides must agree on are mirrored by value. This is what keeps the copies equal: a
 * curriculum frog passes has to project onto rows the app database accepts.
 */

describe("frog's mirrored values equal the app's", () => {
  test("scopes, tiers and card types", () => {
    expect(documentScope.enumValues).toEqual([...TOPIC_SCOPES]);
    expect(TIERS).toEqual(DIFFICULTIES);
    expect(CARD_TYPES).toEqual(SHARED_CARD_TYPES);
  });

  test("the target_cards band is the one the database enforces", async () => {
    const { topic } = await makeTopic({ subtopicsPerTier: 0 });
    const insert = (targetCards: number) =>
      deps.db.insert(subtopic).values({
        topicId: topic.id,
        difficulty: "beginner",
        title: `Band ${targetCards}`,
        description: "At the edge of the band.",
        targetCards,
        minCards: 1,
        position: 0,
      });
    await insert(MIN_TARGET_CARDS);
    await insert(MAX_TARGET_CARDS);
    for (const outside of [MIN_TARGET_CARDS - 1, MAX_TARGET_CARDS + 1]) {
      await expect(insert(outside)).rejects.toMatchObject({
        cause: expect.objectContaining({ constraint: "ck_subtopic_target_cards_band" }),
      });
    }
  });
});
