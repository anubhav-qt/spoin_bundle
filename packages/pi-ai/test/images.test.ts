import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, test } from "vitest";

import {
	type Api,
	type AssistantMessage,
	type Message,
	type Model,
	normalizeContext,
	streamSimple,
	type ToolResultMessage,
} from "../src/index.ts";

// spoin's chats look at images (visual_toad at photographs, designer_toad at rendered cards), so
// these pin what reaches the wire for the two APIs spoin calls: Gemini through CLIProxyAPI, and
// OpenAI chat completions on NIM (task 0045).

const PNG =
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const GEMINI_REPLY = {
	candidates: [{ content: { role: "model", parts: [{ text: "seen" }] }, finishReason: "STOP", index: 0 }],
	usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 1, totalTokenCount: 11 },
};
const OPENAI_CHUNKS = [
	{ id: "c1", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta: { role: "assistant", content: "seen" }, finish_reason: null }] },
	{ id: "c1", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] },
];

let server: Server;
let baseUrl = "";
let lastBody: any;

beforeAll(async () => {
	server = createServer((request, response) => {
		let raw = "";
		request.on("data", (chunk) => {
			raw += chunk;
		});
		request.on("end", () => {
			lastBody = JSON.parse(raw);
			response.writeHead(200, { "Content-Type": "text/event-stream" });
			if (request.url?.includes(":streamGenerateContent")) {
				response.end(`data: ${JSON.stringify(GEMINI_REPLY)}\r\n\r\n`);
			} else {
				response.end(`${OPENAI_CHUNKS.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("")}data: [DONE]\n\n`);
			}
		});
	});
	await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
	baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
	await new Promise((resolve) => server.close(resolve));
});

function model(api: Api, id: string, input: Model<Api>["input"]): Model<Api> {
	return {
		id,
		name: id,
		api,
		provider: "test",
		baseUrl: api === "google-generative-ai" ? `${baseUrl}/v1beta` : `${baseUrl}/v1`,
		input,
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		reasoning: false,
		contextWindow: 100_000,
		maxTokens: 1000,
	} as Model<Api>;
}

const gemini = () => model("google-generative-ai", "gemini-3.8-flash-high", ["text", "image"]);
const nim = (input: Model<Api>["input"] = ["text", "image"]) => model("openai-completions", "moonshotai/kimi-k3", input);

function userWithImage(): Message {
	return {
		role: "user",
		content: [
			{ type: "text", text: "What is in this picture?" },
			{ type: "image", data: PNG, mimeType: "image/png" },
		],
		timestamp: 0,
	};
}

/** A turn that called `render_card`, and the tool's answer: a screenshot. */
function toolCallWithImage(target: Model<Api>): Message[] {
	const call: AssistantMessage = {
		role: "assistant",
		content: [{ type: "toolCall", id: "call_1", name: "render_card", arguments: { card: "c1" } }],
		api: target.api,
		provider: target.provider,
		model: target.id,
		usage: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "toolUse",
		timestamp: 0,
	};
	const result: ToolResultMessage = {
		role: "toolResult",
		toolCallId: "call_1",
		toolName: "render_card",
		content: [{ type: "image", data: PNG, mimeType: "image/png" }],
		isError: false,
		timestamp: 0,
	};
	return [{ role: "user", content: "Render card c1 and look at it.", timestamp: 0 }, call, result];
}

async function send(target: Model<Api>, messages: Message[]): Promise<void> {
	const reply = await streamSimple(target, normalizeContext({ messages }), { apiKey: "test-key" }).result();
	assert.equal(reply.stopReason, "stop", reply.errorMessage);
}

test("Gemini gets a user message's image as inline data", async () => {
	await send(gemini(), [userWithImage()]);

	const parts = lastBody.contents[0].parts;
	assert.deepEqual(parts[1], { inlineData: { mimeType: "image/png", data: PNG } });
});

test("Gemini 3 gets a tool result's image inside the function response", async () => {
	const target = gemini();
	await send(target, toolCallWithImage(target));

	const response = lastBody.contents.at(-1).parts[0].functionResponse;
	assert.equal(response.name, "render_card");
	assert.deepEqual(response.parts, [{ inlineData: { mimeType: "image/png", data: PNG } }]);
});

test("OpenAI chat gets a user message's image as a data URL", async () => {
	await send(nim(), [userWithImage()]);

	const content = lastBody.messages.at(-1).content;
	assert.deepEqual(content[1], { type: "image_url", image_url: { url: `data:image/png;base64,${PNG}` } });
});

test("OpenAI chat gets a tool result's image in a user message after it", async () => {
	const target = nim();
	await send(target, toolCallWithImage(target));

	const last = lastBody.messages.at(-1);
	assert.equal(last.role, "user");
	assert.ok(
		last.content.some(
			(part: any) => part.type === "image_url" && part.image_url.url === `data:image/png;base64,${PNG}`,
		),
	);
});

test("a text-only model gets a placeholder instead of the image", async () => {
	await send(nim(["text"]), [userWithImage()]);

	const sent = JSON.stringify(lastBody.messages);
	assert.ok(!sent.includes(PNG));
	assert.match(sent, /image omitted/);
});
