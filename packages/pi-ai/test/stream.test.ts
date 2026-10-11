import assert from "node:assert/strict";
import { test } from "vitest";

import { type Api, type Model, normalizeContext, streamSimple } from "../src/index.ts";

function modelWithApi(api: Api): Model<Api> {
	return {
		id: "test-model",
		name: "Test model",
		api,
		provider: "test",
		baseUrl: "http://127.0.0.1:1",
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		reasoning: false,
		contextWindow: 1000,
		maxTokens: 100,
	} as Model<Api>;
}

test("an API the fork dropped ends the stream with an error instead of throwing", async () => {
	const model = modelWithApi("bedrock-converse-stream");
	const stream = streamSimple(model, normalizeContext({ messages: [] }));

	const message = await stream.result();

	assert.equal(message.stopReason, "error");
	assert.match(message.errorMessage ?? "", /No API implementation for "bedrock-converse-stream"/);
});
