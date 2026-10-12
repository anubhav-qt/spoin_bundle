import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * A stand-in NVIDIA and Gemini on one local port: each request gets the next reply set, and every
 * request is kept for the test to read.
 */

export type Reply = { status: number; body: string; headers?: Record<string, string> };

export function modelStandIn() {
  let replies: Reply[] = [];
  let server: Server | null = null;
  const standIn = {
    base: "",
    requests: [] as { url: string; body: Record<string, unknown> }[],
    /** Sets the replies, in order, and forgets earlier requests. */
    start(answers: Reply[]) {
      replies = [...answers];
      standIn.requests = [];
    },
    async listen() {
      server = createServer((request, response) => {
        let raw = "";
        request.on("data", (chunk) => {
          raw += chunk;
        });
        request.on("end", () => {
          standIn.requests.push({ url: request.url ?? "", body: JSON.parse(raw) });
          const reply = replies.shift() ?? { status: 500, body: "no reply set" };
          response.writeHead(reply.status, { "Content-Type": "text/event-stream", ...reply.headers });
          response.end(reply.body);
        });
      });
      const listening = server;
      await new Promise<void>((resolve) => listening.listen(0, "127.0.0.1", resolve));
      standIn.base = `http://127.0.0.1:${(listening.address() as AddressInfo).port}`;
    },
    async close() {
      const listening = server;
      if (listening) await new Promise((resolve) => listening.close(resolve));
    },
  };
  return standIn;
}

/** One chunk of an OpenAI chat stream, as NVIDIA sends it. */
export const chunk = (delta: Record<string, unknown>, finish: string | null = null) =>
  `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`;
export const usage = `data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [], usage: { prompt_tokens: 12, completion_tokens: 3, total_tokens: 15 } })}\n\n`;

export const answer = (text = "ok"): Reply => ({
  status: 200,
  body: `${chunk({ role: "assistant", content: text })}${chunk({}, "stop")}${usage}data: [DONE]\n\n`,
});
export const refuse = (status: number, message: string, headers?: Record<string, string>): Reply => ({
  status,
  body: JSON.stringify({ error: { message } }),
  headers: { "Content-Type": "application/json", ...headers },
});
