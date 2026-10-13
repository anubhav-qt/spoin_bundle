import type { HelperTask } from "@spoin/shared/enums";
import { type Chat, readChat } from "../harness/chats.ts";
import { everyChatTools } from "../harness/every-chat.ts";
import { patientGemini } from "../harness/gemini.ts";
import { intakeTools } from "../harness/intake.ts";
import type { ChatSetUp } from "../harness/scheduler.ts";
import type { HarnessTool } from "../harness/tools.ts";
import { topicReadingTools } from "../harness/topic-reading.ts";
import { webSearchTool } from "../harness/web-search.ts";
import { BALANCER_DEFAULTS, Balancer } from "../models/balancer.ts";
import { recordTo } from "../models/calls.ts";
import { geminiOpensAt } from "../models/limits.ts";
import { NIM_LADDER } from "../models/nim.ts";
import { nimThenGemini } from "../models/nim-then-gemini.ts";
import { GEMINI_THINKING, geminiFrom, type ProxyConfig, proxyAnswers } from "../models/proxy.ts";
import { attachArtTool, listArtRequestsTool, renderArtTool } from "./art.ts";
import type { AgentDeps } from "./context.ts";
import { listDocumentsTool, readDocumentTool, searchCorpusTool } from "./corpus.ts";
import {
  handOverCurriculumTool,
  listWaitingTool,
  readCurriculumTool,
  readIntakeTool,
  sendBackTool,
  startCurriculumWriterTool,
  writeCurriculumTool,
} from "./curriculum.ts";
import {
  auditDraftsTool,
  settleFindingTool,
  startDocumentWriterTool,
  writeDocumentTool,
} from "./documents.ts";
import {
  checkRubricsTool,
  correctCardsTool,
  readDraftsTool,
  readSurvivorsTool,
  solveQuestionsTool,
  verifyCardsTool,
} from "./gate.ts";
import { handOverTool, reviewTool } from "./handovers.ts";
import { reportTool, startHelperTool } from "./helpers.ts";
import { changeMapTool, writeMapTool } from "./maps.ts";
import { fetchTool, readPageTool, searchPagesTool } from "./pages.ts";
import {
  gateCardsTool,
  gateQuestionsTool,
  listSubtopicsTool,
  planCardsTool,
  readCardsTool,
  readGroundingTool,
  startSubtopicTool,
  startVerifierTool,
  submitTierTool,
  writeCardsTool,
  writeQuestionsTool,
} from "./tiers.ts";

/*
 * How each chat of the pipeline runs (task 0045): its tools, by its role or its helper's task, and
 * its model. The three writers write at length on NIM's ladder, which the owner means to use the
 * most; every other chat orchestrates or verifies, on Gemini, waiting its limits out. The worker
 * doesn't start without a NIM key, and a writer's call goes to Gemini only once NIM gives up on it.
 */

/** The helpers that write at length, on NIM. */
const WRITERS: HelperTask[] = ["document_writer", "curriculum_writer", "tier_writer"];

export interface AgentSetUpInput {
  deps: AgentDeps;
  proxy: ProxyConfig;
  nimKey: string;
}

export function agentSetUp(input: AgentSetUpInput): (chat: Chat) => Promise<ChatSetUp> {
  const gemini = geminiFrom(input.proxy);
  return async (chat) => {
    const tools = [...everyChatTools(input.deps.prompts, chat), ...(await roleTools(input.deps, chat))];
    const compactionTools = tools.filter((tool) => tool.kind === "read" || MAP_TOOLS.has(tool.name));
    const chatSetUp = { tools, compactionTools, compactWhileWaitingAt: compactWhileWaitingAt(chat) };
    if (runsOnNim(chat)) return { ...onNim(input, gemini), ...chatSetUp };
    return { ...(await onGemini(input, gemini)), ...chatSetUp };
  };
}

/** Whether the chat writes at length, on NIM; every other chat is on Gemini. */
export function runsOnNim(chat: Chat): boolean {
  if (!chat.task) return false;
  return WRITERS.includes(chat.task);
}

/** The context, in tokens, at which a chat that waits on others compacts once its turn ends (the owner's rule). */
export const COMPACT_WHILE_WAITING_AT = 100_000;

/**
 * Every main chat ends its turns waiting for other chats, and so does a tier writer, for its
 * verdicts. Any other helper is finished once it reports, so compacting it would be paid for
 * and never read.
 */
export function compactWhileWaitingAt(chat: Chat): number | undefined {
  if (chat.role !== "helper") return COMPACT_WHILE_WAITING_AT;
  if (chat.task === "tier_writer") return COMPACT_WHILE_WAITING_AT;
  return undefined;
}

/** A compaction run reads, and writes down the maps it keeps its work in. */
const MAP_TOOLS = new Set(["write_map", "change_map"]);

type ModelSetUp = Omit<ChatSetUp, "tools" | "compactionTools">;

async function onGemini(
  input: AgentSetUpInput,
  gemini: () => Promise<ChatSetUp["model"]>,
): Promise<ModelSetUp> {
  const proxy = input.proxy;
  return {
    model: await gemini(),
    thinkingLevel: GEMINI_THINKING,
    apiKey: proxy.apiKey,
    streamFn: (run) =>
      patientGemini({
        record: recordTo(input.deps.db, run.id),
        opensAt: () => geminiOpensAt(proxy),
        proxyAnswers: () => proxyAnswers(proxy),
      }),
  };
}

/** How long a writer's call waits for a NIM model before Gemini takes it: a bad day on NIM. */
export const NIM_PATIENCE_S = 30 * 60;

function onNim(input: AgentSetUpInput, gemini: () => Promise<ChatSetUp["model"]>): ModelSetUp {
  const [top] = NIM_LADDER;
  if (!top) throw new Error("NIM's ladder is empty.");
  const proxy = input.proxy;
  return {
    // The ladder picks the model for each call; this one names the run.
    model: top.model,
    thinkingLevel: GEMINI_THINKING,
    apiKey: input.nimKey,
    streamFn: (run) => {
      const record = recordTo(input.deps.db, run.id);
      return nimThenGemini({
        // The worker never ends, so a model that refuses the key is asked again later.
        nim: new Balancer(NIM_LADDER, input.nimKey, record, {
          ...BALANCER_DEFAULTS,
          patient: true,
          giveUpAfterS: NIM_PATIENCE_S,
        }),
        geminiModel: gemini,
        gemini: patientGemini({
          record,
          opensAt: () => geminiOpensAt(proxy),
          proxyAnswers: () => proxyAnswers(proxy),
        }),
        geminiApiKey: proxy.apiKey,
      });
    },
  };
}

async function roleTools(deps: AgentDeps, chat: Chat): Promise<HarnessTool[]> {
  if (chat.role === "helper") return helperTools(deps, chat);
  if (chat.role === "toad_sage") return [...toadSageTools(deps), startHelperTool(deps.prompts)];
  if (chat.role === "tadpole") return tadpoleTools(deps);
  if (chat.role === "curriculum") return curriculumTools(deps);
  if (chat.role === "designer_toad") return designerTools(deps);
  throw new Error(`No ${chat.role} chat runs in this pipeline yet.`);
}

async function helperTools(deps: AgentDeps, chat: Chat): Promise<HarnessTool[]> {
  const report = reportTool(deps.prompts);
  if (chat.task === "helper") {
    if (!chat.parentId) throw new Error(`Helper ${chat.id} has no main chat.`);
    const main = await readChat(deps.db, chat.parentId);
    if (main.role === "toad_sage") return [...toadSageTools(deps), report];
    if (main.role === "tadpole") return [...researchTools(deps), report];
    throw new Error(`A ${main.role} chat has no helpers.`);
  }
  if (chat.task === "document_writer") return [...researchTools(deps), writeDocumentTool(deps), report];
  if (chat.task === "curriculum_writer") {
    return [
      readIntakeTool(deps),
      listDocumentsTool(deps),
      readDocumentTool(deps),
      searchCorpusTool(deps),
      readCurriculumTool(deps),
      writeCurriculumTool(deps),
      report,
    ];
  }
  if (chat.task === "tier_writer") {
    return [
      readGroundingTool(deps),
      readCardsTool(deps),
      planCardsTool(deps),
      writeCardsTool(deps),
      gateCardsTool(deps),
      writeQuestionsTool(deps),
      gateQuestionsTool(deps),
      submitTierTool(deps),
      report,
    ];
  }
  if (chat.task === "corrector") return [readDraftsTool(deps), correctCardsTool(deps)];
  if (chat.task === "verifier") {
    return [
      readSurvivorsTool(deps),
      verifyCardsTool(deps),
      solveQuestionsTool(deps),
      checkRubricsTool(deps),
      searchCorpusTool(deps),
      readDocumentTool(deps),
    ];
  }
  throw new Error(`Helper ${chat.id} has no task.`);
}

/** toad_sage's own work, which its helpers share. */
function toadSageTools(deps: AgentDeps): HarnessTool[] {
  return [
    ...intakeTools(deps.prompts, deps.embedder),
    ...topicReadingTools(deps.prompts, deps.embedder),
    ...webSearch(deps),
    searchCorpusTool(deps),
    reviewTool(deps),
  ];
}

/** What a tadpole and the helpers it briefs read the topic's sources with. */
function researchTools(deps: AgentDeps): HarnessTool[] {
  return [
    searchPagesTool(deps),
    searchCorpusTool(deps),
    readDocumentTool(deps),
    listDocumentsTool(deps),
    ...webSearch(deps),
    fetchTool(deps),
    readPageTool(deps),
    readIntakeTool(deps),
  ];
}

function tadpoleTools(deps: AgentDeps): HarnessTool[] {
  return [
    ...researchTools(deps),
    writeMapTool(deps),
    changeMapTool(deps),
    handOverTool(deps),
    startDocumentWriterTool(deps),
    auditDraftsTool(deps),
    settleFindingTool(deps),
    startHelperTool(deps.prompts),
    listSubtopicsTool(deps),
    startSubtopicTool(deps),
    startVerifierTool(deps),
  ];
}

function curriculumTools(deps: AgentDeps): HarnessTool[] {
  return [
    listWaitingTool(deps),
    startCurriculumWriterTool(deps),
    readIntakeTool(deps),
    readCurriculumTool(deps),
    sendBackTool(deps),
    handOverCurriculumTool(deps),
  ];
}

function designerTools(deps: AgentDeps): HarnessTool[] {
  return [
    listArtRequestsTool(deps),
    renderArtTool(deps),
    attachArtTool(deps),
    ...webSearch(deps),
    fetchTool(deps),
  ];
}

function webSearch(deps: AgentDeps): HarnessTool[] {
  if (!deps.webSearch) return [];
  return [webSearchTool(deps.prompts, deps.webSearch)];
}
