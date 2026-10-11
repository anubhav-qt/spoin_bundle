import { existsSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { cliEmbedder, inUniverse, printFailures, UNIVERSE_DOCS } from "../cli.ts";
import { ingestCorpus, ingestSummary, parseCorpus } from "./runner.ts";

/*
 * `npm run corpus:check` validates the delivered corpus against the contract and writes
 * nothing; `npm run corpus:ingest` validates, then writes what passed into
 * the_spoin_universe, idempotent by content hash (ADR-0088).
 *
 *   --corpus <dir>     the tree, default docs/the_spoin_universe/corpus
 *   --force            re-embed unchanged documents too, after a chunking or header
 *                      change alters what is embedded without altering the file
 *   --embedder <name>  qwen3 (default) or hash, a meaningless stand-in for tests
 */

const { values } = parseArgs({
  options: {
    corpus: { type: "string", default: join(UNIVERSE_DOCS, "corpus") },
    check: { type: "boolean", default: false },
    force: { type: "boolean", default: false },
    embedder: { type: "string", default: "qwen3" },
  },
});

const root = values.corpus;
if (!existsSync(root)) {
  console.error(`corpus not found: ${root}`);
  process.exit(2);
}

if (values.check) {
  const { parsed, failures } = parseCorpus(root);
  printFailures(failures.map((f) => ({ path: f.sourcePath, problems: f.problems })));
  console.log(
    `checked ${parsed.length + failures.length} documents: ${parsed.length} ok, ${failures.length} failing`,
  );
  process.exit(failures.length > 0 ? 1 : 0);
}

const embedder = cliEmbedder(values.embedder);
const report = await inUniverse((tx) =>
  ingestCorpus(tx, root, embedder, { force: values.force, log: console.log }),
);
printFailures(report.errors.map((f) => ({ path: f.sourcePath, problems: f.problems })));
console.log(ingestSummary(report));
process.exit(report.failed > 0 ? 1 : 0);
