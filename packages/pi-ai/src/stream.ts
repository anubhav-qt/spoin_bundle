import { lazyApi, lazyStream } from "./api/lazy.ts";
import type {
	Api,
	AssistantMessageEventStream,
	KnownApi,
	Model,
	ProviderStreams,
	SimpleStreamOptions,
	TranscriptContext,
} from "./types.ts";

// Each API module loads on its first request.
const apis: Record<KnownApi, ProviderStreams> = {
	"google-generative-ai": lazyApi(() => import("./api/google-generative-ai.ts")),
	"anthropic-messages": lazyApi(() => import("./api/anthropic-messages.ts")),
	"openai-responses": lazyApi(() => import("./api/openai-responses.ts")),
	"openai-completions": lazyApi(() => import("./api/openai-completions.ts")),
};

/**
 * Streams one assistant turn through the API named by `model.api`. Never throws:
 * failures, an unknown api included, end the stream with an error message.
 */
export function streamSimple(
	model: Model<Api>,
	context: TranscriptContext,
	options?: SimpleStreamOptions,
): AssistantMessageEventStream {
	const api = apis[model.api as KnownApi];
	if (!api) {
		return lazyStream(model, async () => {
			throw new Error(`No API implementation for "${model.api}"`);
		});
	}
	return api.streamSimple(model, context, options);
}
