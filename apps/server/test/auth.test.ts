import { eq } from "drizzle-orm";
import { describe, expect, it } from "vitest";
import { appUser } from "../src/db/schema.ts";
import { app, client, deps, email, guest, PASSWORD, signedUp } from "./helpers.ts";

describe("the shell", () => {
  it("answers health with a database round-trip", async () => {
    const r = await client().get("/health");
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ status: "ok", env: "test" });
    expect(r.headers.get("x-request-id")).toBeTruthy();
  });

  it("keeps the request id the edge assigned", async () => {
    const res = await app.request("/health", { headers: { "X-Request-ID": "edge-123" } });
    expect(res.headers.get("x-request-id")).toBe("edge-123");
  });

  it("answers an unknown path with {detail}", async () => {
    const r = await client().get("/nope");
    expect(r.status).toBe(404);
    expect(r.body).toEqual({ detail: "Not Found" });
  });

  it("publishes the OpenAPI contract", async () => {
    const r = await client().get("/openapi.json");
    expect(r.status).toBe(200);
    expect(r.body.paths["/auth/claim"]).toBeDefined();
    expect(r.body.components.schemas.UserOut).toBeDefined();
  });

  it("lets the web app's origin read the session token header", async () => {
    const res = await app.request("/health", { headers: { origin: "http://localhost:3001" } });
    expect(res.headers.get("access-control-allow-origin")).toBe("http://localhost:3001");
    const other = await app.request("/health", { headers: { origin: "https://evil.example" } });
    expect(other.headers.get("access-control-allow-origin")).toBeNull();
  });
});

describe("accounts", () => {
  it("needs a session for /auth/me", async () => {
    const r = await client().get("/auth/me");
    expect(r.status).toBe(401);
    expect(r.body).toEqual({ detail: "Not authenticated" });
  });

  it("gives a guest a real user from the first request", async () => {
    const g = await guest();
    const me = await g.get("/auth/me");
    expect(me.status).toBe(200);
    expect(me.body).toMatchObject({ is_guest: true, email: null, display_name: "Guest", is_admin: false });
  });

  it("signs up and in with a bearer token, no cookies, and no origin from the mobile app", async () => {
    const address = email();
    const a = await signedUp(address);
    expect((await a.get("/auth/me")).body).toMatchObject({ email: address, is_guest: false });

    const mobile = client({ origin: null });
    const r = await mobile.post("/auth/sign-in/email", { email: address, password: PASSWORD });
    expect(r.status).toBe(200);
    expect(mobile.token).toBeTruthy();
    expect((await mobile.get("/auth/me")).body.email).toBe(address);
  });

  it("lets a phone on the owner's network sign in to a dev server, and no other page", async () => {
    const address = email();
    await signedUp(address);
    const credentials = { email: address, password: PASSWORD };
    const phone = client({ origin: "http://192.168.1.20:3001" });
    expect((await phone.post("/auth/sign-in/email", credentials)).status).toBe(200);
    const stranger = client({ origin: "https://evil.example" });
    expect((await stranger.post("/auth/sign-in/email", credentials)).status).toBe(403);
  });

  it("claims a guest in place, keeping the user id and the session", async () => {
    const g = await guest();
    const before = (await g.get("/auth/me")).body;
    const address = email();

    const r = await g.post("/auth/claim", { email: address, password: PASSWORD, display_name: "Ada" });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ id: before.id, email: address, display_name: "Ada", is_guest: false });
    expect((await g.get("/auth/me")).body.id).toBe(before.id);

    // The new password works from anywhere.
    const elsewhere = client();
    expect((await elsewhere.post("/auth/sign-in/email", { email: address, password: PASSWORD })).status).toBe(
      200,
    );
    expect((await elsewhere.get("/auth/me")).body.id).toBe(before.id);
  });

  it("refuses to claim onto a taken email, or twice", async () => {
    const taken = email();
    await signedUp(taken);

    const g = await guest();
    const clash = await g.post("/auth/claim", { email: taken, password: PASSWORD, display_name: "Ada" });
    expect(clash.status).toBe(409);
    expect(clash.body.detail).toBe("Email already registered");
    // The failed claim left the guest a guest.
    expect((await g.get("/auth/me")).body.is_guest).toBe(true);

    expect(
      (await g.post("/auth/claim", { email: email(), password: PASSWORD, display_name: "Ada" })).status,
    ).toBe(200);
    const again = await g.post("/auth/claim", { email: email(), password: PASSWORD, display_name: "Ada" });
    expect(again.status).toBe(409);
    expect(again.body.detail).toBe("Account is already claimed");
  });

  it("answers a malformed body with a readable 422", async () => {
    const g = await guest();
    const r = await g.post("/auth/claim", { email: "not-an-email", password: "short", display_name: "" });
    expect(r.status).toBe(422);
    expect(typeof r.body.detail).toBe("string");
    expect(r.body.detail).toMatch(/email/);
  });

  it("knows an admin by role", async () => {
    const address = email();
    const a = await signedUp(address);
    await deps.db.update(appUser).set({ role: "admin" }).where(eq(appUser.email, address));
    expect((await a.get("/auth/me")).body.is_admin).toBe(true);
  });
});
