import { defineConfig } from "vitest/config";
import { testEnv } from "./test/env.ts";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    globalSetup: "./test/global-setup.ts",
    fileParallelism: false,
    testTimeout: 30_000,
    env: testEnv,
  },
});
