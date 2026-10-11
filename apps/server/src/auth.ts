import { randomUUID } from "node:crypto";
import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { admin, anonymous, bearer } from "better-auth/plugins";
import type { Db } from "./db/client.ts";
import { appUser, authAccount, authSession, authVerification } from "./db/schema.ts";
import type { Env } from "./env.ts";
import { originAllowed } from "./lib/http.ts";
import { log } from "./log.ts";

const DAY = 86_400;

/**
 * Accounts (ADR-0106), mounted at `/auth/*`.
 *
 * - **Bearer tokens**, not cookies: the web app and the API live on different sites,
 *   and the mobile client has no cookie jar. A sign-in returns the session token in
 *   `set-auth-token`; clients send it as `Authorization: Bearer`.
 * - **Guests** are anonymous users (ADR-0033): a real row from the first card, so
 *   progress is keyed off one id from the start. A guest becomes an account *in place*
 *   through `/auth/claim` (routes/auth.ts), so nothing keyed off the id moves. A guest
 *   who signs in to a different, existing account abandons the guest row, and Better
 *   Auth deletes it.
 * - **Google** accepts an ID token from the client's own Google Sign-In, the flow both
 *   the web and the mobile app use; the API never runs the redirect dance itself.
 * - **Admin** is a role on the user (closes task 0035).
 */
export function makeAuth(env: Env, db: Db) {
  const google = env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET;
  const ipHeader = env.CLIENT_IP_HEADER === "none" ? undefined : env.CLIENT_IP_HEADER;

  return betterAuth({
    appName: "Spoin",
    baseURL: env.PUBLIC_URL ?? `http://localhost:${env.PORT}`,
    basePath: "/auth",
    secret: env.AUTH_SECRET,
    // CORS's rule (lib/http.ts), so a phone on the owner's network can sign in to a dev server.
    trustedOrigins: (request) => {
      const origin = request?.headers.get("origin");
      return origin && originAllowed(env, origin) ? [...env.ALLOWED_ORIGINS, origin] : env.ALLOWED_ORIGINS;
    },
    database: drizzleAdapter(db, {
      provider: "pg",
      schema: { user: appUser, session: authSession, account: authAccount, verification: authVerification },
    }),
    emailAndPassword: { enabled: true, minPasswordLength: 8, maxPasswordLength: 128 },
    socialProviders: google
      ? {
          google: {
            clientId: env.GOOGLE_CLIENT_ID as string,
            clientSecret: env.GOOGLE_CLIENT_SECRET as string,
          },
        }
      : {},
    account: {
      // Signing in with Google on an email that already has a password joins the two.
      accountLinking: { enabled: true, trustedProviders: ["google"] },
    },
    session: { expiresIn: 90 * DAY, updateAge: DAY },
    plugins: [
      bearer(),
      anonymous({
        emailDomainName: "guest.spoin.invalid",
        generateName: () => "Guest",
      }),
      admin({ defaultRole: "user", adminRoles: ["admin"] }),
    ],
    rateLimit: {
      enabled: env.NODE_ENV !== "test",
      window: 60,
      max: 100,
      customRules: {
        "/sign-in/email": { window: 60, max: 10 },
        "/sign-up/email": { window: 60, max: 5 },
      },
    },
    advanced: {
      database: { generateId: () => randomUUID() },
      ipAddress: ipHeader ? { ipAddressHeaders: [ipHeader] } : undefined,
      // Better Auth drops the origin check under NODE_ENV=test; kept on so tests run production's.
      disableOriginCheck: false,
    },
    telemetry: { enabled: false },
    logger: {
      level: env.NODE_ENV === "production" ? "warn" : "info",
      log: (level, message, ...args) =>
        log[level]({ args: args.length ? args : undefined }, `auth: ${message}`),
    },
  });
}

export type Auth = ReturnType<typeof makeAuth>;
