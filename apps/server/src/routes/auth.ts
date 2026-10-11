import { randomUUID } from "node:crypto";
import { createRoute } from "@hono/zod-openapi";
import { ClaimIn, GoogleClaimIn, UserOut } from "@spoin/shared";
import { verifyProviderIdToken } from "better-auth/oauth2";
import { and, eq } from "drizzle-orm";
import type { Deps } from "../context.ts";
import { appUser, authAccount } from "../db/schema.ts";
import { HttpError, notFound, pgCode, UNIQUE_VIOLATION } from "../lib/errors.ts";
import { needUser } from "../lib/http.ts";
import { body, errors, json, router } from "../lib/openapi.ts";
import { me } from "../profile/service.ts";
import { toUserOut } from "../users/out.ts";

/**
 * The account routes Better Auth doesn't own. Registered before its catch-all mount
 * on `/auth/*` (app.ts), so these paths are answered here.
 *
 * A guest claims in place (ADR-0033): the row keeps its id and gains a credential or
 * a Google account, so topics, progress and engagement carry over untouched. The
 * caller's session token stays valid; nothing new is issued.
 */
export function authRoutes(deps: Deps) {
  const { db } = deps;

  const load = async (id: string) => {
    const user = await db.query.appUser.findFirst({ where: eq(appUser.id, id) });
    if (!user) throw notFound("User");
    return user;
  };

  /** Turns the guest row into an account; a taken email is a 409, not a 500. */
  const claim = async (
    userId: string,
    set: Partial<typeof appUser.$inferInsert>,
    account: typeof authAccount.$inferInsert,
  ) => {
    try {
      await db.transaction(async (tx) => {
        await tx
          .update(appUser)
          .set({ ...set, isAnonymous: false, updatedAt: new Date() })
          .where(eq(appUser.id, userId));
        await tx.insert(authAccount).values(account);
      });
    } catch (e) {
      if (pgCode(e) === UNIQUE_VIOLATION) throw new HttpError(409, "Email already registered");
      throw e;
    }
  };

  const needGuest = async (c: Parameters<typeof needUser>[0]) => {
    const caller = needUser(c);
    if (!caller.isGuest) throw new HttpError(409, "Account is already claimed");
    return caller;
  };

  return router()
    .openapi(
      createRoute({
        method: "get",
        path: "/auth/me",
        tags: ["auth"],
        responses: { 200: json(UserOut), 401: errors[401] },
      }),
      async (c) => {
        const caller = needUser(c);
        // Preferences ride on this payload so the client can reconcile its pre-paint cache on load (ADR-0070).
        return c.json(await me(db, caller.id, true), 200);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/auth/claim",
        tags: ["auth"],
        summary: "A guest becomes an email-and-password account, keeping everything",
        request: body(ClaimIn),
        responses: { 200: json(UserOut), 401: errors[401], 409: errors[409], 422: errors[422] },
      }),
      async (c) => {
        const caller = await needGuest(c);
        const input = c.req.valid("json");
        const ctx = await deps.auth.$context;
        const hash = await ctx.password.hash(input.password);
        await claim(
          caller.id,
          { email: input.email.toLowerCase(), name: input.display_name },
          {
            id: randomUUID(),
            userId: caller.id,
            providerId: "credential",
            accountId: caller.id,
            password: hash,
          },
        );
        return c.json(toUserOut(await load(caller.id)), 200);
      },
    )
    .openapi(
      createRoute({
        method: "post",
        path: "/auth/claim/google",
        tags: ["auth"],
        summary: "A guest links Google, keeping everything",
        request: body(GoogleClaimIn),
        responses: { 200: json(UserOut), 401: errors[401], 409: errors[409], 422: errors[422] },
      }),
      async (c) => {
        const caller = await needGuest(c);
        const { id_token } = c.req.valid("json");
        const ctx = await deps.auth.$context;
        const google = ctx.socialProviders.find((p) => p.id === "google");
        if (!google) throw new HttpError(501, "Google auth not configured");
        if (!(await verifyProviderIdToken(google, id_token)))
          throw new HttpError(401, "Invalid Google token");
        const info = await google.getUserInfo({ idToken: id_token });
        if (!info?.user.email) throw new HttpError(401, "Google did not share an email address");

        const googleId = String(info.user.id);
        const taken = await db.query.authAccount.findFirst({
          where: and(eq(authAccount.providerId, "google"), eq(authAccount.accountId, googleId)),
        });
        // That Google account already belongs to someone; the client signs in with it instead.
        if (taken) throw new HttpError(409, "This Google account already has a Spoin account");

        await claim(
          caller.id,
          {
            email: info.user.email.toLowerCase(),
            name: info.user.name || "Reader",
            emailVerified: Boolean(info.user.emailVerified),
            image: info.user.image ?? null,
          },
          {
            id: randomUUID(),
            userId: caller.id,
            providerId: "google",
            accountId: googleId,
            idToken: id_token,
          },
        );
        return c.json(toUserOut(await load(caller.id)), 200);
      },
    );
}
