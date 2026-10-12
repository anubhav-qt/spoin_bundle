import type { Static, TSchema } from "typebox";
import { Compile } from "typebox/compile";
import type { TLocalizedValidationError } from "typebox/error";

/**
 * The one check at every boundary of the harness (Trotter's `@trotter/schemas` check, task 0045):
 * whatever a model hands over, and every record on its way in and out of the database. "Every
 * model output is checked in code first."
 */

type Validator = ReturnType<typeof Compile>;

/** A value that doesn't match its schema. Lists every problem, so an agent can fix them all at once. */
export class SchemaError extends Error {
  readonly problems: string[];

  constructor(what: string, problems: string[]) {
    super(`${what} doesn't match its schema:\n${problems.map((problem) => `  - ${problem}`).join("\n")}`);
    this.name = "SchemaError";
    this.problems = problems;
  }
}

const validators = new WeakMap<TSchema, Validator>();

/** The value typed by its schema, or a SchemaError. `what` names it in the message: "The call to write_map". */
export function checkValue<Schema extends TSchema>(
  schema: Schema,
  value: unknown,
  what: string,
): Static<Schema> {
  const validator = validatorFor(schema);
  if (validator.Check(value)) return value as Static<Schema>;
  const problems = validator.Errors(value).flatMap(describeError);
  throw new SchemaError(what, [...new Set(problems)]);
}

function validatorFor(schema: TSchema): Validator {
  let validator = validators.get(schema);
  if (!validator) {
    validator = Compile(schema);
    validators.set(schema, validator);
  }
  return validator;
}

function describeError(error: TLocalizedValidationError): string[] {
  // typebox reports each unexpected field twice: once here, once as a "boolean" error on the field.
  if (error.keyword === "boolean") return [];
  const path = error.instancePath === "" ? "root" : error.instancePath.slice(1).replaceAll("/", ".");
  if (error.keyword === "additionalProperties") {
    const fields = (error.params as { additionalProperties?: string[] }).additionalProperties ?? [];
    return fields.map((field) => `${path}: unexpected field "${field}"`);
  }
  return [`${path}: ${error.message}`];
}
