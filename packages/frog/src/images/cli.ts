import { join } from "node:path";
import { parseArgs } from "node:util";
import { cliEmbedder, inUniverse, printFailures, UNIVERSE_DOCS } from "../cli.ts";
import { parseImages } from "./contract.ts";
import { imageSummary, ingestImages } from "./runner.ts";

/*
 * `npm run images:check` validates the image manifests and writes nothing, loads no
 * model and makes no network call, not even to see whether a `source_url` still
 * resolves; `npm run images:ingest` validates, then writes the catalog (ADR-0095).
 *
 *   --images <dir>     default docs/the_spoin_universe/images; missing means none delivered
 *   --force            re-embed unchanged entries too, after an embedding model change
 *   --embedder <name>  qwen3 (default) or hash, a meaningless stand-in for tests
 */

const { values } = parseArgs({
  options: {
    images: { type: "string", default: join(UNIVERSE_DOCS, "images") },
    check: { type: "boolean", default: false },
    force: { type: "boolean", default: false },
    embedder: { type: "string", default: "qwen3" },
  },
});

const print = (failures: { manifestPath: string; problems: string[] }[]) =>
  printFailures(failures.map((f) => ({ path: f.manifestPath, problems: f.problems })));

if (values.check) {
  const { parsed, failures } = parseImages(values.images);
  print(failures);
  const images = parsed.reduce((n, m) => n + m.images.length, 0);
  console.log(
    `checked ${parsed.length + failures.length} manifests: ${parsed.length} ok, ${failures.length} failing, ${images} images`,
  );
  process.exit(failures.length > 0 ? 1 : 0);
}

const embedder = cliEmbedder(values.embedder);
const report = await inUniverse((tx) =>
  ingestImages(tx, values.images, embedder, { force: values.force, log: console.log }),
);
print(report.errors);
console.log(imageSummary(report));
process.exit(report.failedManifests > 0 ? 1 : 0);
