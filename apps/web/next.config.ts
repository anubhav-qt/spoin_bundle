import type { NextConfig } from "next";

import { version } from "./package.json";

const config: NextConfig = {
  reactStrictMode: true,
  // Deployed to Cloudflare Pages, not Vercel: the Hobby tier prohibits commercial
  // use and we intend to monetize (ADR-0003).

  // The wire contract ships as TypeScript source, not a build (packages/shared).
  transpilePackages: ["@spoin/shared"],

  // Settings' About row shows the real version rather than a string hardcoded
  // a second time and left to drift. Read from package.json at build time —
  // `resolveJsonModule` is already on in tsconfig.
  env: {
    NEXT_PUBLIC_APP_VERSION: version,
  },
};

export default config;
