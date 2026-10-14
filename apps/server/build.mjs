import { cpSync } from "node:fs";
import { build } from "esbuild";

// One self-contained file per entry point, so the runtime image needs next to no node_modules.
await build({
  entryPoints: ["src/api.ts", "src/migrate.ts", "src/worker.ts"],
  outdir: "dist",
  bundle: true,
  platform: "node",
  target: "node24",
  format: "esm",
  sourcemap: true,
  // pg tries pg-native only when asked to; it isn't installed. The ONNX runtime loads
  // native code and model files of its own, and Playwright finds its browser from its own
  // package, so both stay packages beside the bundle.
  external: ["pg-native", "@huggingface/transformers", "onnxruntime-node", "playwright-core"],
  // Bundled CommonJS packages still call require().
  banner: {
    js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);",
  },
  logLevel: "info",
});

// Data read at runtime beside the bundle, by the same relative URL as in the source tree.
cpSync("src/content/ascii-library", "dist/ascii-library", { recursive: true });
// The embedder's thread runs its own file (frog's embeddings.ts), which Node strips the types of.
cpSync("../../packages/frog/src/embed-worker.ts", "dist/embed-worker.ts");
