import { makeApp } from "../src/app.ts";
import { makeDeps } from "../src/deps.ts";
import { loadEnv } from "../src/env.ts";
import { testEnv } from "./env.ts";

export const env = loadEnv({ ...process.env, ...testEnv });
export const deps = makeDeps(env);
export const app = makeApp(deps);

let addresses = 0;

// biome-ignore lint/suspicious/noExplicitAny: response bodies are asserted on, not typed.
export type Res = { status: number; body: any; headers: Headers };

/**
 * One simulated client: its own address (for rate limits) and, once signed in, its
 * own bearer token, picked up from Better Auth's `set-auth-token` header.
 * `origin: null` is the mobile app, which sends none.
 */
export function client(opts: { origin?: string | null } = {}) {
  addresses += 1;
  const ip = `10.0.${Math.floor(addresses / 250)}.${addresses % 250}`;
  let token: string | null = null;
  const send = async (method: string, path: string, body?: unknown): Promise<Res> => {
    const headers = new Headers({ "x-forwarded-for": ip });
    if (opts.origin !== null) headers.set("origin", opts.origin ?? "http://localhost:3000");
    if (token) headers.set("authorization", `Bearer ${token}`);
    if (body !== undefined) headers.set("content-type", "application/json");
    const res = await app.request(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const issued = res.headers.get("set-auth-token");
    if (issued) token = issued;
    const text = await res.text();
    return { status: res.status, body: text ? JSON.parse(text) : null, headers: res.headers };
  };
  return {
    get: (path: string) => send("GET", path),
    post: (path: string, body?: unknown) => send("POST", path, body ?? {}),
    patch: (path: string, body?: unknown) => send("PATCH", path, body ?? {}),
    put: (path: string, body?: unknown) => send("PUT", path, body ?? {}),
    delete: (path: string) => send("DELETE", path),
    get token() {
      return token;
    },
  };
}

export type Client = ReturnType<typeof client>;

export const email = () => `reader-${Math.random().toString(36).slice(2, 10)}@example.com`;
export const PASSWORD = "correct horse battery";

export async function guest(): Promise<Client> {
  const c = client();
  const r = await c.post("/auth/sign-in/anonymous");
  if (r.status !== 200) throw new Error(`guest sign-in failed: ${r.status} ${JSON.stringify(r.body)}`);
  return c;
}

export async function signedUp(address = email()): Promise<Client> {
  const c = client();
  const r = await c.post("/auth/sign-up/email", { email: address, password: PASSWORD, name: "Reader" });
  if (r.status !== 200) throw new Error(`sign-up failed: ${r.status} ${JSON.stringify(r.body)}`);
  return c;
}
