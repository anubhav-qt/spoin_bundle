// @spoin/pi-ai: Trotter's hard fork of pi-ai (https://github.com/earendil-works/pi, MIT, see LICENSE),
// forked at e37cdc4 (2026-10-10), copied into spoin as is (task 0045). Kept: the four streaming APIs
// (Gemini, Anthropic Messages, OpenAI Responses, OpenAI Chat Completions), image input included.
// Dropped: provider catalogs, the Models registry and credential layer, OAuth, image generation,
// classifiers, telemetry and every other API.
export type { Static, TSchema } from "typebox";
export { Type } from "typebox";

export type { AnthropicEffort, AnthropicOptions, AnthropicThinkingDisplay } from "./api/anthropic-messages.ts";
export type { GoogleOptions } from "./api/google-generative-ai.ts";
export type { GoogleApiThinkingLevel, ResolvedGoogleThinkingLevel } from "./api/google-shared.ts";
export * from "./api/lazy.ts";
export type { OpenAICompletionsOptions } from "./api/openai-completions.ts";
export type { OpenAIResponsesOptions } from "./api/openai-responses.ts";
export * from "./models.ts";
// Trotter: the thinking levels as a schema, so a level given on the command line can be checked.
export { ModelThinkingLevelSchema } from "./providers/model-schema.ts";
export * from "./stream.ts";
export * from "./types.ts";
export * from "./utils/diagnostics.ts";
// Trotter: estimates of a context's size, so a chat knows when to compact (ADR 0014).
export { estimateContextTokens, estimateTextTokens } from "./utils/estimate.ts";
export * from "./utils/event-stream.ts";
export * from "./utils/json-parse.ts";
export { contentText, getSystemMessageText, renderSystemMessageUpdate } from "./utils/text.ts";
export * from "./utils/transcript.ts";
export * from "./utils/validation.ts";
