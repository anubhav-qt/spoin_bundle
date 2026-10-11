import { randomUUID } from "node:crypto";
import { DIFFICULTIES } from "@spoin/shared/enums";
import { describe, expect, test } from "vitest";
import { buildPlan, filterKey } from "../src/feed/interleave.ts";
import { type Candidate, diversify, freshness, rank, score } from "../src/feed/ranking.ts";
import {
  clampShares,
  MIN_RAW_WEIGHT,
  rawWeight,
  shareFingerprint,
  squash,
} from "../src/feed/session-profile.ts";
import { allocate, DIFFICULTY_MIX, resolveInOrder, resolveMix, served } from "../src/feed/strata.ts";
import { seeded } from "./fixtures.ts";
import { env } from "./helpers.ts";

const A = "00000000-0000-0000-0000-0000000000aa";
const B = "00000000-0000-0000-0000-0000000000bb";
const C = "00000000-0000-0000-0000-0000000000cc";
const D = "00000000-0000-0000-0000-0000000000dd";

const counts = (plan: string[]) => {
  const out = new Map<string, number>();
  for (const t of plan) out.set(t, (out.get(t) ?? 0) + 1);
  return out;
};
const runs = (plan: string[]) => {
  const out: number[] = [];
  plan.forEach((t, i) => {
    if (i > 0 && plan[i - 1] === t) out[out.length - 1] = (out.at(-1) ?? 0) + 1;
    else out.push(1);
  });
  return out;
};
const pairs = <T>(xs: T[]) => xs.slice(1).map((x, i) => [xs[i] as T, x] as const);

describe("the interleave plan (ADR-0010)", () => {
  test("equal weights alternate, and double weight gets double the slots", () => {
    expect(
      counts(
        buildPlan(
          new Map([
            [A, 1],
            [B, 1],
          ]),
          10,
        ),
      ),
    ).toEqual(
      new Map([
        [A, 5],
        [B, 5],
      ]),
    );
    const c = counts(
      buildPlan(
        new Map([
          [A, 2],
          [B, 1],
        ]),
        30,
      ),
    );
    expect(c.get(A)).toBe(2 * (c.get(B) ?? 0));
  });

  test("slots are spread, not clumped", () => {
    expect(
      Math.max(
        ...runs(
          buildPlan(
            new Map([
              [A, 2],
              [B, 1],
            ]),
            30,
          ),
        ),
      ),
    ).toBeLessThanOrEqual(2);
    expect(
      pairs(
        buildPlan(
          new Map([
            [A, 1],
            [B, 1],
          ]),
          10,
        ),
      ).every(([x, y]) => x !== y),
    ).toBe(true);
  });

  test("runs change the granularity of alternation, never the share", () => {
    const grouped = buildPlan(
      new Map([
        [A, 2],
        [B, 1],
      ]),
      30,
      3,
    );
    const c = counts(grouped);
    expect(grouped).toHaveLength(30);
    // Whole runs at a time, so 2:1 holds to within one run.
    expect(Math.abs((c.get(A) ?? 0) - 2 * (c.get(B) ?? 0))).toBeLessThanOrEqual(3);
    expect(
      Math.max(
        ...runs(
          buildPlan(
            new Map([
              [A, 1],
              [B, 1],
            ]),
            12,
            3,
          ),
        ),
      ),
    ).toBeGreaterThanOrEqual(3);
  });

  test("a run that would overshoot is truncated", () => {
    expect(
      buildPlan(
        new Map([
          [A, 1],
          [B, 1],
        ]),
        10,
        4,
      ),
    ).toHaveLength(10);
    expect(buildPlan(new Map([[A, 1]]), 7, 5)).toHaveLength(7);
  });

  test("deterministic, empty for no topics, and zero weight is excluded", () => {
    const w = new Map([
      [A, 1.5],
      [B, 1],
      [C, 0.5],
    ]);
    expect(buildPlan(w, 20)).toEqual(buildPlan(new Map(w), 20));
    expect(buildPlan(new Map(), 50)).toEqual([]);
    expect(
      new Set(
        buildPlan(
          new Map([
            [A, 1],
            [B, 0],
          ]),
          10,
        ),
      ),
    ).toEqual(new Set([A]));
  });

  test("the filter key ignores order, and no filter is the empty key", () => {
    expect(filterKey([A, B])).toBe(filterKey([B, A]));
    expect(filterKey(undefined)).toBe("");
    expect(filterKey([])).toBe("");
    expect(filterKey([A])).not.toBe(filterKey([A, randomUUID()]));
  });
});

describe("the difficulty mix is exact (ADR-0010)", () => {
  test("allocation always sums to the size, using only the tier's strata", () => {
    for (const tier of DIFFICULTIES)
      for (const size of [1, 5, 7, 10, 25, 33, 50]) {
        const a = allocate(size, tier);
        expect([...a.values()].reduce((x, y) => x + y, 0)).toBe(size);
        expect(new Set(a.keys())).toEqual(new Set(Object.keys(DIFFICULTY_MIX[tier])));
      }
  });

  test("beginner is exactly 80/20, and the upward slice survives a small page", () => {
    expect(allocate(25, "beginner")).toEqual(
      new Map([
        ["beginner", 20],
        ["intermediate", 5],
      ]),
    );
    expect(allocate(10, "beginner").get("intermediate")).toBeGreaterThanOrEqual(1);
  });

  test("every mix sums to one and keeps an upward slice", () => {
    for (const tier of DIFFICULTIES)
      expect(Object.values(DIFFICULTY_MIX[tier]).reduce((x, y) => x + y, 0)).toBeCloseTo(1, 9);
    expect(DIFFICULTY_MIX.beginner.intermediate).toBeGreaterThan(0);
    expect(DIFFICULTY_MIX.intermediate.advanced).toBeGreaterThan(0);
  });

  test("a starved stratum is served short, never backfilled", () => {
    const o = resolveMix(
      10,
      "beginner",
      new Map([
        ["beginner", 8],
        ["intermediate", 0],
      ]),
      {
        wasDegraded: false,
        poolLow: 5,
        poolHigh: 15,
      },
    );
    const by = new Map(o.fills.map((f) => [f.difficulty, served(f)]));
    expect(by).toEqual(
      new Map([
        ["beginner", 8],
        ["intermediate", 0],
      ]),
    );
    expect(o.fills.filter((f) => f.available < f.requested).map((f) => f.difficulty)).toEqual([
      "intermediate",
    ]);
  });

  test("hysteresis: enter below the low mark, leave only above the high one", () => {
    const degraded = (available: number, wasDegraded: boolean) =>
      resolveMix(10, "beginner", new Map([["beginner", available]]), {
        wasDegraded,
        poolLow: 5,
        poolHigh: 15,
      }).degraded;
    expect(degraded(4, false)).toBe(true);
    expect(degraded(10, false)).toBe(false);
    expect(degraded(10, true)).toBe(true);
    expect(degraded(16, true)).toBe(false);
  });

  test("the pool thresholds have a gap", () => {
    expect(env.POOL_LOW).toBeLessThan(env.POOL_HIGH);
  });
});

describe("a tierless slate fills in order (ADR-0106)", () => {
  const hysteresis = { wasDegraded: false, poolLow: 5, poolHigh: 15 };
  const servedBy = (o: ReturnType<typeof resolveInOrder>) => o.fills.map((f) => [f.difficulty, served(f)]);

  test("easy first, each stratum taking what the ones before it left", () => {
    const o = resolveInOrder(
      10,
      new Map([
        ["beginner", 4],
        ["intermediate", 3],
        ["advanced", 9],
      ]),
      hysteresis,
    );
    expect(servedBy(o)).toEqual([
      ["beginner", 4],
      ["intermediate", 3],
      ["advanced", 3],
    ]);
  });

  test("a full first stratum leaves nothing to the harder ones", () => {
    const o = resolveInOrder(
      10,
      new Map([
        ["beginner", 12],
        ["advanced", 5],
      ]),
      hysteresis,
    );
    expect(servedBy(o)).toEqual([
      ["beginner", 10],
      ["intermediate", 0],
      ["advanced", 0],
    ]);
  });

  test("degraded on the whole pool, with the same hysteresis as a mix", () => {
    const degraded = (available: number, wasDegraded: boolean) =>
      resolveInOrder(10, new Map([["advanced", available]]), { ...hysteresis, wasDegraded }).degraded;
    expect([degraded(4, false), degraded(10, false), degraded(10, true), degraded(16, true)]).toEqual([
      true,
      false,
      true,
      false,
    ]);
  });
});

describe("ranking", () => {
  const NOW = new Date("2026-08-15T00:00:00Z");
  const make = (o: Partial<Candidate> & { ageDays?: number } = {}): Candidate => ({
    cardId: randomUUID(),
    subtopicId: o.subtopicId ?? randomUUID(),
    createdAt: new Date(NOW.getTime() - (o.ageDays ?? 0) * 86_400_000),
    cardQuality: o.cardQuality ?? 0,
    topicAffinity: o.topicAffinity ?? 1,
    coverageNeed: o.coverageNeed ?? 0,
    archetype: o.archetype ?? [],
    subtopicPosition: o.subtopicPosition ?? 0,
  });
  const k = { ...env, RANK_EPSILON: 0 };

  test("curriculum order comes before score", () => {
    const later = make({ cardQuality: 0.9, subtopicPosition: 5 });
    const earlier = make({ cardQuality: 0.1, subtopicPosition: 1 });
    expect(rank([later, earlier], k, { now: NOW, limit: 2 }).map((c) => c.cardId)).toEqual([
      earlier.cardId,
      later.cardId,
    ]);
  });

  test("freshness halves every fortnight", () => {
    expect(freshness(NOW, NOW)).toBe(1);
    expect(freshness(new Date(NOW.getTime() - 14 * 86_400_000), NOW)).toBe(0.5);
    expect(freshness(new Date(NOW.getTime() - 365 * 86_400_000), NOW)).toBeLessThan(0.01);
  });

  test("quality scores higher, by weights from the env", () => {
    expect(score(make({ cardQuality: 0.9 }), env, NOW)).toBeGreaterThan(
      score(make({ cardQuality: 0.1 }), env, NOW),
    );
    const c = make({ cardQuality: 1 });
    expect(score(c, { ...env, RANK_W_QUALITY: 0 }, NOW)).toBeLessThan(
      score(c, { ...env, RANK_W_QUALITY: 5 }, NOW),
    );
  });

  test("exploration reserves slots for unproven cards; zero epsilon is pure exploitation", () => {
    const proven = Array.from({ length: 20 }, () => make({ cardQuality: 0.9 }));
    const unproven = Array.from({ length: 20 }, () => make({ cardQuality: 0 }));
    const explored = rank(
      [...proven, ...unproven],
      { ...env, RANK_EPSILON: 0.2 },
      { now: NOW, limit: 10, rng: seeded(0) },
    );
    expect(explored).toHaveLength(10);
    expect(explored.some((c) => unproven.includes(c))).toBe(true);
    const exploited = rank([...proven, ...unproven], k, { now: NOW, limit: 10, rng: seeded(0) });
    expect(exploited.every((c) => proven.includes(c))).toBe(true);
  });

  test("never past the limit", () => {
    expect(
      rank(
        Array.from({ length: 50 }, () => make()),
        env,
        { now: NOW, limit: 7, rng: seeded(0) },
      ),
    ).toHaveLength(7);
  });

  test("diversify spreads subtopics, then archetypes, and never drops a card", () => {
    const [s1, s2] = [randomUUID(), randomUUID()];
    const bySub = diversify([
      ...Array.from({ length: 3 }, () => make({ subtopicId: s1 })),
      ...Array.from({ length: 3 }, () => make({ subtopicId: s2 })),
    ]);
    expect(bySub).toHaveLength(6);
    expect(pairs(bySub.map((c) => c.subtopicId)).every(([x, y]) => x !== y)).toBe(true);

    const byShape = diversify([
      ...Array.from({ length: 3 }, () => make({ archetype: ["diagram"] })),
      ...Array.from({ length: 3 }, () => make({ archetype: ["code"] })),
    ]);
    expect(pairs(byShape.map((c) => c.archetype[0])).every(([x, y]) => x !== y)).toBe(true);

    const only = randomUUID();
    expect(
      diversify(Array.from({ length: 4 }, () => make({ subtopicId: only, archetype: ["code"] }))),
    ).toHaveLength(4);
  });
});

describe("session shares (ADR-0055)", () => {
  const bounds = { lo: 0.05, hi: 0.5 };
  const sum = (m: Map<string, number>) => [...m.values()].reduce((x, y) => x + y, 0);
  const within = (m: Map<string, number>) =>
    [...m.values()].every((s) => s >= bounds.lo - 1e-9 && s <= bounds.hi + 1e-9);

  test("squash is zero at zero, half at k, bounded and monotonic", () => {
    expect(squash(0, 10)).toBe(0);
    expect(squash(10, 10)).toBeCloseTo(0.5);
    expect(squash(-10, 10)).toBeCloseTo(-0.5);
    let previous = -1;
    for (let s = -1000; s < 1000; s += 7) {
      const v = squash(s, 10);
      expect(v).toBeGreaterThan(previous);
      expect(Math.abs(v)).toBeLessThan(1);
      previous = v;
    }
  });

  test("no signal is the uniform baseline, and a weight never reaches zero", () => {
    expect(rawWeight(0, env)).toBeCloseTo(1);
    expect(rawWeight(20, env)).toBeGreaterThan(1);
    expect(rawWeight(-20, env)).toBeLessThan(1);
    expect(rawWeight(-1e9, env)).toBeGreaterThanOrEqual(MIN_RAW_WEIGHT);
  });

  test("shares sum to one within bounds, keeping order", () => {
    expect(clampShares(new Map(), bounds)).toEqual(new Map());
    const s = clampShares(
      new Map([
        [A, 8],
        [B, 4],
        [C, 2],
        [D, 1],
      ]),
      bounds,
    );
    expect(sum(s)).toBeCloseTo(1);
    expect(within(s)).toBe(true);
    const [a, b, c, d] = [A, B, C, D].map((t) => s.get(t) ?? 0) as [number, number, number, number];
    expect(a >= b && b >= c && c >= d).toBe(true);
  });

  test("a dominant topic is capped and an ignored one keeps the floor", () => {
    expect(
      clampShares(
        new Map([
          [A, 1000],
          [B, 1],
          [C, 1],
          [D, 1],
        ]),
        bounds,
      ).get(A),
    ).toBeCloseTo(0.5);
    expect(
      clampShares(
        new Map([
          [A, 100],
          [B, 100],
          [C, 100],
          [D, 0],
        ]),
        bounds,
      ).get(D),
    ).toBeCloseTo(0.05);
    expect(
      clampShares(
        new Map([
          [A, 5],
          [B, -3],
          [C, 1],
        ]),
        bounds,
      ).get(B),
    ).toBeCloseTo(0.05);
  });

  test("uniform when equal or all zero; a lone topic takes everything; two both pin at half", () => {
    for (const v of clampShares(new Map([A, B, C, D].map((t) => [t, 2])), bounds).values())
      expect(v).toBeCloseTo(0.25);
    for (const v of clampShares(new Map([A, B, C].map((t) => [t, 0])), bounds).values())
      expect(v).toBeCloseTo(1 / 3);
    expect(clampShares(new Map([[A, 4]]), bounds).get(A)).toBeCloseTo(1);
    const two = clampShares(
      new Map([
        [A, 99],
        [B, 1],
      ]),
      bounds,
    );
    expect(two.get(A)).toBeCloseTo(0.5);
    expect(two.get(B)).toBeCloseTo(0.5);
  });

  test("an impossible floor degrades to 1/n", () => {
    const s = clampShares(new Map(Array.from({ length: 25 }, () => [randomUUID(), 1])), bounds);
    for (const v of s.values()) expect(v).toBeCloseTo(1 / 25);
  });

  test("wide spreads and two topics over the ceiling never over-allocate, and nothing is NaN", () => {
    for (const weights of [Array.from({ length: 12 }, (_, i) => 2 ** i), [48, 47, 0.5, 0.5, 0.5, 0.5]]) {
      const s = clampShares(new Map(weights.map((w) => [randomUUID(), w])), bounds);
      expect(sum(s)).toBeCloseTo(1);
      expect(within(s)).toBe(true);
    }
    for (const v of clampShares(
      new Map([
        [A, 1e18],
        [B, 1e-18],
        [C, 0],
      ]),
      bounds,
    ).values())
      expect(v).not.toBeNaN();
  });

  test("the fingerprint is stable, order-free, absorbs drift and sees a bucket crossing", () => {
    const f = (m: [string, number][]) => shareFingerprint(new Map(m), 0.05);
    expect(
      f([
        [A, 0.6],
        [B, 0.4],
      ]),
    ).toBe(
      f([
        [B, 0.4],
        [A, 0.6],
      ]),
    );
    expect(
      f([
        [A, 0.5],
        [B, 0.5],
      ]),
    ).toBe(
      f([
        [A, 0.505],
        [B, 0.495],
      ]),
    );
    expect(
      f([
        [A, 0.5],
        [B, 0.5],
      ]),
    ).not.toBe(
      f([
        [A, 0.6],
        [B, 0.4],
      ]),
    );
    expect(
      f([
        [A, 0.5],
        [B, 0.5],
      ]),
    ).not.toBe(
      f([
        [A, 0.5],
        [C, 0.5],
      ]),
    );
  });
});
