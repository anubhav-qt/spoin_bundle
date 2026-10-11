import { cpSync } from "node:fs";
import { build } from "esbuild";

// One self-contained file per entry point, so the runtime image needs next to no node_modules.
await build({
  entryPoints: ["src/api.ts", "src/migrate.ts"],
  outdir: "dist",
  bundle: true,
  platform: "node",
  target: "node24",
  format: "esm",
  sourcemap: true,
  // pg tries pg-native only when asked to; it isn't installed. The ONNX runtime loads
  // native code and model files of its own, so it stays a package beside the bundle.
  external: ["pg-native", "@huggingface/transformers", "onnxruntime-node"],
  // Bundled CommonJS packages still call require().
  banner: {
    js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);",
  },
  logLevel: "info",
});

// Data read at runtime beside the bundle, by the same relative URL as in the source tree.
cpSync("src/content/ascii-library", "dist/ascii-library", { recursive: true });
