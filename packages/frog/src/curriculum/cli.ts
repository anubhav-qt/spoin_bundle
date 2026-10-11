import { existsSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";
import { inUniverse, printFailures, UNIVERSE_DOCS } from "../cli.ts";
import { curriculumSummary, ingestCurricula, validateCurricula } from "./runner.ts";

/*
 * `npm run curriculum:check` validates the authored curricula, grounding references
 * included, and writes nothing; `npm run curriculum:ingest` validates, then writes the
 * valid ones into the_spoin_universe, idempotent by content hash. Neither loads a model:
 * a curriculum is teaching structure and nothing in it is embedded.
 *
 *   --curricula <dir>  default docs/the_spoin_universe/curricula
 *   --corpus <dir>     default docs/the_spoin_universe/corpus, where grounding points
 */

const { values } = parseArgs({
  options: {
    curricula: { type: "string", default: join(UNIVERSE_DOCS, "curricula") },
    corpus: { type: "string", default: join(UNIVERSE_DOCS, "corpus") },
    check: { type: "boolean", default: false },
  },
});

if (!existsSync(values.curricula)) {
  // No curricula written yet is a valid state, not an error.
  console.log(`no curricula directory at ${values.curricula}: nothing to do`);
  process.exit(0);
}
if (!existsSync(values.corpus)) {
  console.error(`corpus not found: ${values.corpus} (needed to check grounding references)`);
  process.exit(2);
}

const print = (failures: { sourcePath: string; problems: string[] }[]) =>
  printFailures(failures.map((f) => ({ path: f.sourcePath, problems: f.problems })));

if (values.check) {
  const { passed, failures } = validateCurricula(values.curricula, values.corpus);
  print(failures);
  console.log(
    `checked ${passed.length + failures.length} curricula: ${passed.length} ok, ${failures.length} failing`,
  );
  process.exit(failures.length > 0 ? 1 : 0);
}

const report = await inUniverse((tx) => ingestCurricula(tx, values.curricula, values.corpus));
print(report.errors);
console.log(curriculumSummary(report));
process.exit(report.failed > 0 ? 1 : 0);
