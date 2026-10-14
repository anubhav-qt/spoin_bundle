import { and, eq, sql } from "drizzle-orm";
import { Type } from "typebox";
import { harnessRecord, subtopic } from "../db/schema.ts";
import { topicById } from "../harness/intake.ts";
import { recordsStored } from "../harness/outputs.ts";
import { createRecord, readLatestRecord, readSharedRecord, refOf } from "../harness/records.ts";
import { CLOSED, CurriculumRecord, HandoverRecord, Id, ReviewRecord } from "../harness/schemas.ts";
import { type HarnessTool, ToolError } from "../harness/tools.ts";
import type { AgentDeps } from "./context.ts";
import { publishCurriculum } from "./curriculum.ts";
import { closingReportProblems, ingestTopicCorpus } from "./documents.ts";
import { mapsHandoverFacts, mapsHandoverProblems } from "./maps.ts";
import { putCardsLiveIfDone, startReadyTiers, tierById } from "./tiers.ts";

/*
 * The procedure's approval points (ADR-0100, task 0045): a tadpole hands toad_sage its coverage
 * note, its maps, an "insufficient evidence" or its closing report, and the curriculum chat hands
 * it a curriculum. toad_sage answers each with one review, go on or change, which wakes the chat
 * that sent it. On go-on, code takes the next step: past the closing report it ingests the
 * topic's documents, past the curriculum it writes, ingests and projects it and starts the first
 * tiers' writers, and past an "insufficient evidence" it puts the tier's cards live if nothing
 * else waits.
 */

const HandOverParameters = Type.Object(
  {
    kind: Type.Enum(["coverage", "maps", "closing_report", "insufficient_evidence"]),
    records: Type.Array(Id, { description: "The records handed over, by id: maps, drafts, plans" }),
    note: Type.String({
      minLength: 1,
      description: "The coverage note, the closing report, or what the tier lacks and why",
    }),
    subtopic: Type.Optional(
      Type.String({ format: "uuid", description: "For insufficient_evidence: the tier" }),
    ),
  },
  CLOSED,
);

/** The tadpole's: its work at an approval point, to toad_sage. */
export function handOverTool(deps: AgentDeps): HarnessTool<typeof HandOverParameters> {
  return {
    name: "hand_over",
    label: "Hand over to toad_sage",
    description: deps.prompts.render("tools/hand-over.njk", {}),
    parameters: HandOverParameters,
    kind: "change",
    async execute(params, context) {
      const topicId = context.chat.topicId;
      if (!topicId) throw new ToolError("Only a topic's tadpole hands its work over.");
      const found = await topicById(context.db, topicId);
      if (params.kind === "closing_report") {
        const problems = await closingReportProblems(deps, context.db, found);
        if (problems.length > 0) {
          throw new ToolError(`The closing report can't go yet:\n- ${problems.join("\n- ")}`);
        }
      }
      let facts: string | undefined;
      if (params.kind === "maps") {
        const problems = await mapsHandoverProblems(context.db, topicId);
        if (problems.length > 0) {
          throw new ToolError(`The maps can't go yet:\n- ${problems.join("\n- ")}`);
        }
        facts = await mapsHandoverFacts(context.db, topicId);
      }
      let tier: string | null = null;
      if (params.kind === "insufficient_evidence") {
        if (!params.subtopic)
          throw new ToolError("Name the tier that can't reach its target: give subtopic.");
        const [row] = await context.db
          .select({ id: subtopic.id })
          .from(subtopic)
          .where(and(eq(subtopic.id, params.subtopic), eq(subtopic.topicId, topicId)));
        if (!row) throw new ToolError(`Subtopic ${params.subtopic} is not one of your topic's tiers.`);
        tier = row.id;
      }
      const refs = [];
      for (const id of params.records) {
        try {
          refs.push(refOf(await readSharedRecord(context.db, id)));
        } catch {
          throw new ToolError(`There is no record ${id}.`);
        }
      }
      const body: HandoverRecord["body"] = {
        kind: params.kind,
        topic: topicId,
        records: refs,
        note: params.note,
        subtopic: tier,
      };
      if (facts) body.facts = facts;
      const handover = await createRecord(context.db, HandoverRecord, {
        kind: "handover",
        author: context.author,
        body,
      });
      const stored = await recordsStored(context.db, deps.prompts, [handover]);
      return {
        ...stored,
        value: `${String(stored.value)}\nEnd your turn now: toad_sage's review wakes you.`,
      };
    },
  };
}

const ReviewParameters = Type.Object(
  {
    handover: Id,
    verdict: Type.Enum(["go_on", "change"]),
    notes: Type.String({
      minLength: 1,
      description: "On change, exactly what to change; on go on, anything the next stage should keep in mind",
    }),
  },
  CLOSED,
);

/** toad_sage's: one review per handover. A go-on that can't take its next step stores nothing. */
export function reviewTool(deps: AgentDeps): HarnessTool<typeof ReviewParameters> {
  return {
    name: "review",
    label: "Review a handover",
    description: deps.prompts.render("tools/review.njk", {}),
    parameters: ReviewParameters,
    kind: "change",
    async execute(params, context) {
      const [row] = await context.db
        .select({ id: harnessRecord.id })
        .from(harnessRecord)
        .where(and(eq(harnessRecord.kind, "handover"), eq(harnessRecord.id, params.handover)))
        .limit(1);
      if (!row) throw new ToolError(`There is no handover ${params.handover}.`);
      const handover = await readLatestRecord(context.db, HandoverRecord, "handover", params.handover);
      const [reviewed] = await context.db
        .select({ id: harnessRecord.id })
        .from(harnessRecord)
        .where(
          and(
            eq(harnessRecord.kind, "review"),
            sql`${harnessRecord.body} -> 'handover' ->> 'id' = ${handover.id}`,
          ),
        )
        .limit(1);
      if (reviewed) throw new ToolError(`Handover ${handover.id} is reviewed already (${reviewed.id}).`);

      let done = "";
      if (params.verdict === "go_on" && handover.body.kind === "closing_report") {
        const sections = await ingestTopicCorpus(deps, await topicById(context.db, handover.body.topic));
        done = `The topic's documents are ingested (${sections} sections written), and the curriculum chat is woken.`;
      }
      if (params.verdict === "go_on" && handover.body.kind === "curriculum") {
        const [ref] = handover.body.records;
        if (!ref) throw new ToolError("The handover names no curriculum.");
        const latest = await readLatestRecord(context.db, CurriculumRecord, "curriculum", ref.id);
        if (latest.version !== ref.version) {
          throw new ToolError(
            "The curriculum changed after it was handed over: review its new handover instead.",
          );
        }
        await publishCurriculum(deps, latest.body);
        const started = await context.db.transaction((tx) => startReadyTiers(tx, latest.body.topic));
        done = `The curriculum is written, ingested and projected onto the topic's subtopics, and ${started.length} tiers' writers are started.`;
      }
      const review = await createRecord(context.db, ReviewRecord, {
        kind: "review",
        author: context.author,
        body: { handover: refOf(handover), verdict: params.verdict, notes: params.notes },
      });
      const short = handover.body.subtopic;
      if (params.verdict === "go_on" && handover.body.kind === "insufficient_evidence" && short) {
        const tier = await tierById(context.db, short);
        if (await context.db.transaction((tx) => putCardsLiveIfDone(tx, tier))) {
          done = "The tier finishes short: its cards are live, and its writer is briefed on its questions.";
        }
      }
      const stored = await recordsStored(context.db, deps.prompts, [review]);
      if (!done) return stored;
      return { ...stored, value: `${String(stored.value)}\n${done}` };
    },
  };
}
