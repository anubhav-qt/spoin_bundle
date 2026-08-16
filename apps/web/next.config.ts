import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Deployed to Cloudflare Pages, not Vercel: the Hobby tier prohibits commercial
  // use and we intend to monetize (ADR-0003).
};

export default config;
