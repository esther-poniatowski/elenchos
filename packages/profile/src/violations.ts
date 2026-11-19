/**
 * The check of a producer log against the findings profile. The schema of a producer log holds
 * every rule of sections 3 and 4 that JSON Schema expresses; four rules relate two members of a
 * log, and are checked here: each `ruleId` names a rule of the driver, each property of a result
 * opens on the driver name and `/`, a `fullyQualifiedName` equals the `name` of its logical
 * location, and the URI of the artifact of a `path:` resource decodes to its path.
 */
import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject, ValidateFunction } from "ajv";
import { ProfileError } from "./errors.js";
import { PROFILE_SCHEMA } from "./generated/schema.js";
import { splitLocationName } from "./locations.js";

/** One rule of the profile broken at one node of a log. */
export interface Violation {
  /** JSON Pointer of the node of the log at which the rule fails. */
  readonly pointer: string;
  /** The rule broken, in words. */
  readonly message: string;
}

/** The absolute `$id` of the schema of a producer log. */
export const PROFILE_SCHEMA_ID = String(PROFILE_SCHEMA["$id"]);

let compiled: ValidateFunction | undefined;

function validator(): ValidateFunction {
  compiled ??= new Ajv2020({ allErrors: true, verbose: true, strict: false }).compile(
    PROFILE_SCHEMA,
  );
  return compiled;
}

type Json = Record<string, unknown>;

function isObject(node: unknown): node is Json {
  return typeof node === "object" && node !== null && !Array.isArray(node);
}

function members(node: unknown, key: string): unknown[] {
  const value = isObject(node) ? node[key] : undefined;
  return Array.isArray(value) ? value : [];
}

/** The message of a violation of the schema, read from the rule that the schema states. */
function message(error: ErrorObject): string {
  const parent: unknown = error.parentSchema;
  const description = isObject(parent) ? parent["description"] : undefined;
  if (typeof description === "string") {
    if (error.keyword === "pattern")
      return `${JSON.stringify(error.data)} breaks the form of ${description}`;
    if (error.keyword === "not" || error.keyword === "anyOf") return description;
  }
  return error.message ?? error.keyword;
}

function decoded(uri: string): string | undefined {
  try {
    return decodeURIComponent(uri);
  } catch {
    return undefined;
  }
}

function locationViolations(location: unknown, here: string): Violation[] {
  const logical = members(location, "logicalLocations");
  const first = logical[0];
  if (logical.length !== 1 || !isObject(first) || typeof first["name"] !== "string") return [];
  const name = first["name"];
  const found: Violation[] = [];
  const qualified = first["fullyQualifiedName"];
  if (qualified !== undefined && qualified !== name) {
    found.push({
      pointer: `${here}/logicalLocations/0/fullyQualifiedName`,
      message: "fullyQualifiedName differs from name",
    });
  }
  let resource: string;
  try {
    resource = splitLocationName(name).resource;
  } catch (error) {
    if (error instanceof ProfileError) return found;
    throw error;
  }
  const physical = isObject(location) ? location["physicalLocation"] : undefined;
  const artifact = isObject(physical) ? physical["artifactLocation"] : undefined;
  const uri = isObject(artifact) ? artifact["uri"] : undefined;
  if (resource.startsWith("path:") && typeof uri === "string") {
    const path = resource.slice("path:".length);
    if (decoded(uri) !== path) {
      found.push({
        pointer: `${here}/physicalLocation/artifactLocation/uri`,
        message: `artifact URI ${JSON.stringify(uri)} does not encode the resource path ${JSON.stringify(path)}`,
      });
    }
  }
  return found;
}

function relationViolations(log: unknown): Violation[] {
  const found: Violation[] = [];
  members(log, "runs").forEach((run, runIndex) => {
    const tool = isObject(run) ? run["tool"] : undefined;
    const driver = isObject(tool) ? tool["driver"] : undefined;
    const name = isObject(driver) ? driver["name"] : undefined;
    const rules = isObject(driver) ? driver["rules"] : undefined;
    const ruleIds = Array.isArray(rules)
      ? new Set(
          rules.flatMap((rule) =>
            isObject(rule) && typeof rule["id"] === "string" ? [rule["id"]] : [],
          ),
        )
      : undefined;
    members(run, "results").forEach((result, index) => {
      if (!isObject(result)) return;
      const here = `/runs/${runIndex}/results/${index}`;
      const ruleId = result["ruleId"];
      if (ruleIds !== undefined && typeof ruleId === "string" && !ruleIds.has(ruleId)) {
        found.push({
          pointer: `${here}/ruleId`,
          message: `ruleId ${JSON.stringify(ruleId)} names no rule of the driver`,
        });
      }
      const payload = result["properties"];
      if (typeof name === "string" && isObject(payload)) {
        for (const property of Object.keys(payload)) {
          if (!property.startsWith(`${name}/`)) {
            found.push({
              pointer: `${here}/properties`,
              message: `property ${JSON.stringify(property)} does not open on ${name}/`,
            });
          }
        }
      }
      members(result, "locations").forEach((location, place) => {
        found.push(...locationViolations(location, `${here}/locations/${place}`));
      });
    });
  });
  return found;
}

/**
 * Return every rule of the profile that a producer log breaks, empty when the log conforms. The
 * violations of the schema come first, in the order of the validator.
 */
export function violations(log: unknown): Violation[] {
  const validate = validator();
  const found: Violation[] = validate(log)
    ? []
    : (validate.errors ?? []).flatMap((error) =>
        error.keyword === "if" ? [] : [{ pointer: error.instancePath, message: message(error) }],
      );
  return [...found, ...relationViolations(log)];
}
