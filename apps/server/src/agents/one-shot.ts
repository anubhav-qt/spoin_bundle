import type { StreamFn } from "@spoin/pi-agent";
import {
  type Api,
  type AssistantMessage,
  type Message,
  type Model,
  normalizeContext,
  type Static,
  type Tool,
  type ToolCall,
  type TSchema,
  validateToolArguments,
} from "@spoin/pi-ai";
import { GEMINI_THINKING } from "../models/proxy.ts";

/*
 * A fixed call outside any chat (task 0045): the auditors' three, each with its own prompt the
 * tadpole doesn't brief. Gemini answers by calling one tool, whose arguments are checked in code;
 * an answer that fails the check is sent back with what was wrong, twice at most.
 */

/** Tries per call: the first, and two with the last one's faults named. */
const TRIES = 3;

export interface OneShotCall<Parameters extends TSchema> {
  systemPrompt: string;
  prompt: string;
  tool: Tool<Parameters>;
  /** The run the call is made for, so its `model_call` rows name it. */
  runId: string;
  signal?: AbortSignal;
}

export type OneShot = <Parameters extends TSchema>(
  call: OneShotCall<Parameters>,
) => Promise<Static<Parameters>>;

export interface OneShotOptions {
  model: () => Promise<Model<Api>>;
  apiKey: string;
  /** How the model is called for a run: `patientGemini`, which waits out the accounts' limits. */
  streamFn: (runId: string) => StreamFn;
}

export function oneShot(options: OneShotOptions): OneShot {
  return async (call) => {
    const model = await options.model();
    const stream = options.streamFn(call.runId);
    const messages: Message[] = [{ role: "user", content: call.prompt, timestamp: Date.now() }];
    let fault = "";
    for (let tries = 1; tries <= TRIES; tries++) {
      const context = normalizeContext({ systemPrompt: call.systemPrompt, tools: [call.tool], messages });
      const answer: AssistantMessage = await (
        await stream(model, context, {
          apiKey: options.apiKey,
          reasoning: GEMINI_THINKING,
          signal: call.signal,
          onPayload: (payload) => forceTool(payload, call.tool.name),
        })
      ).result();
      if (answer.stopReason === "error" || answer.stopReason === "aborted") {
        throw new Error(answer.errorMessage ?? `The call ended: ${answer.stopReason}.`);
      }
      const toolCall = answer.content.find(
        (block): block is ToolCall => block.type === "toolCall" && block.name === call.tool.name,
      );
      if (!toolCall) {
        fault = `It answered without calling ${call.tool.name}.`;
        messages.push(answer, {
          role: "user",
          content: `Call ${call.tool.name} with your answer.`,
          timestamp: Date.now(),
        });
        continue;
      }
      try {
        return validateToolArguments(call.tool, toolCall);
      } catch (error) {
        fault = error instanceof Error ? error.message : String(error);
        messages.push(answer, {
          role: "toolResult",
          toolCallId: toolCall.id,
          toolName: toolCall.name,
          content: [{ type: "text", text: `Not accepted: ${fault} Call ${call.tool.name} again, fixed.` }],
          isError: true,
          timestamp: Date.now(),
        });
      }
    }
    throw new Error(`The call to ${call.tool.name} failed ${TRIES} times; the last fault: ${fault}`);
  };
}

/** Gemini answers by calling the tool: function calling in mode ANY, limited to it (as the grader's). */
function forceTool(payload: unknown, name: string): unknown {
  const request = payload as { config?: object };
  const toolConfig = { functionCallingConfig: { mode: "ANY", allowedFunctionNames: [name] } };
  return { ...request, config: { ...request.config, toolConfig } };
}
