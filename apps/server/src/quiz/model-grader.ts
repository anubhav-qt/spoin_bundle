import {
  type Api,
  type AssistantMessage,
  type Model,
  normalizeContext,
  type Static,
  type Tool,
  type ToolCall,
  type TranscriptContext,
  Type,
  validateToolArguments,
} from "@spoin/pi-ai";
import { log } from "../log.ts";
import type { Balancer } from "../models/balancer.ts";
import { type RecordCall, runCall } from "../models/calls.ts";
import { GEMINI_THINKING } from "../models/proxy.ts";
import type { Prompts } from "../prompts.ts";
import type { FreeTextGrade, FreeTextGradeQuery, Grader } from "./grader.ts";

/*
 * The grader on the model layer (task 0045): Gemini through CLIProxyAPI, and when that call fails,
 * the same call on NIM through the balancer, so a reader more often gets a grade, sometimes a slow
 * one. The prompts are `prompts/grader.njk` and `grader-answers.njk`; the grades come back as one
 * call of the `grade` tool, checked here before the quiz uses any of them.
 */

const GRADE = "grade";

const GradeArguments = Type.Object({
  grades: Type.Array(
    Type.Object({
      index: Type.Integer({ description: "The index of the answer's question" }),
      rubric_level: Type.Integer({ minimum: 0, maximum: 3 }),
      justification: Type.String({ minLength: 1, description: "To the reader, as you" }),
    }),
  ),
});

/**
 * The tags `grader-answers.njk` wraps around each part. A reader's answer can neither close its
 * own `<answer>` nor open a part of its own, so its text stays inside the block marked as data.
 */
const DELIMITERS = /<\s*\/?\s*(?:question|stem|rubric|reference_answer|answer)\b[^>]*>/gi;

/**
 * Gemini always calls `grade`: function calling in mode ANY, limited to it. pi's simple options
 * name only auto and none, so it is set on the request itself. NIM gets the tool as auto, since
 * Kimi K3 refuses a forced tool choice while it thinks (a 400), and the call is required below.
 */
function forceGrade(payload: unknown): unknown {
  const request = payload as { config?: object };
  const toolConfig = { functionCallingConfig: { mode: "ANY", allowedFunctionNames: [GRADE] } };
  return { ...request, config: { ...request.config, toolConfig } };
}

export interface ModelGraderOptions {
  prompts: Prompts;
  /** Null when this process has no proxy key. */
  gemini: { model: () => Promise<Model<Api>>; apiKey: string } | null;
  /** Null when this process has no NIM key. */
  nim: Balancer | null;
  record: RecordCall;
}

export function modelGrader({ prompts, gemini, nim, record }: ModelGraderOptions): Grader {
  const tool: Tool<typeof GradeArguments> = {
    name: GRADE,
    description: prompts.render("tools/grade.njk", {}),
    parameters: GradeArguments,
  };
  const systemPrompt = prompts.render("grader.njk", {});

  const onGemini = async (context: TranscriptContext, signal?: AbortSignal) => {
    if (!gemini) return null;
    const model = await gemini.model();
    const outcome = await runCall(model, context, {
      apiKey: gemini.apiKey,
      reasoning: GEMINI_THINKING,
      // CLIProxyAPI retries across the accounts itself.
      maxRetries: 0,
      signal,
      onPayload: forceGrade,
    });
    record(model, outcome);
    if (outcome.failure) throw new Error(`${outcome.failure}: ${outcome.reason}`);
    return outcome.message;
  };
  const onNim = async (context: TranscriptContext, signal?: AbortSignal) => {
    if (!nim) return null;
    return (await nim.stream(context, { signal })).result();
  };

  return {
    async gradeFreeText(queries, signal) {
      if (!queries.length) return [];
      const items = queries.map((q) => ({ ...q, userAnswer: q.userAnswer.replace(DELIMITERS, "") }));
      const context = normalizeContext({
        systemPrompt,
        tools: [tool],
        messages: [
          { role: "user", content: prompts.render("grader-answers.njk", { items }), timestamp: Date.now() },
        ],
      });
      for (const [leg, ask] of [
        ["Gemini", onGemini],
        ["NIM", onNim],
      ] as const) {
        if (signal?.aborted) return [];
        try {
          const message = await ask(context, signal);
          if (message) return gradesIn(message, tool, queries);
        } catch (error) {
          log.warn({ err: error, leg }, "grading failed");
        }
      }
      return [];
    },
  };
}

/** The grades in an answer, one for every query, or an error saying what was wrong with it. */
function gradesIn(
  message: AssistantMessage,
  tool: Tool<typeof GradeArguments>,
  queries: FreeTextGradeQuery[],
): FreeTextGrade[] {
  if (message.stopReason === "error" || message.stopReason === "aborted") {
    throw new Error(message.errorMessage ?? message.stopReason);
  }
  const call = message.content.find(
    (block): block is ToolCall => block.type === "toolCall" && block.name === GRADE,
  );
  if (!call) throw new Error(`answered without calling ${GRADE}`);
  const { grades }: Static<typeof GradeArguments> = validateToolArguments(tool, call);

  const byIndex = new Map<number, FreeTextGrade>();
  for (const g of grades) {
    if (byIndex.has(g.index)) continue;
    byIndex.set(g.index, {
      index: g.index,
      rubricLevel: g.rubric_level,
      justification: g.justification.trim(),
    });
  }
  const out: FreeTextGrade[] = [];
  for (const q of queries) {
    const grade = byIndex.get(q.index);
    if (!grade) throw new Error(`no grade for answer ${q.index}`);
    out.push(grade);
  }
  return out;
}
