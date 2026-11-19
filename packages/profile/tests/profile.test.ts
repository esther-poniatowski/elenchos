/** The vectors of the findings profile, run against the TypeScript implementation. */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  PROFILE_SCHEMA_ID,
  ProfileError,
  locationName,
  resolveLocus,
  splitLocationName,
  violations,
} from "../src/index.js";

interface Vector {
  readonly case: string;
  readonly log: unknown;
  readonly pointer?: string | null;
}

interface LocusVector {
  readonly case: string;
  readonly document: unknown;
  readonly locus: string;
  readonly resolution: { readonly path: (string | number)[]; readonly unresolved: string[] } | null;
}

function load<T>(name: string): T[] {
  const url = new URL(`../../../specs/vectors/${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, "utf8")) as T[];
}

const identity = load<Vector>("identity.json");
const rejected = load<Vector>("rejected.json");
const nonconforming = load<Vector>("nonconforming.json");
const loci = load<LocusVector>("loci.json");

describe("the schema", () => {
  it("is the published resource named by its absolute $id", () => {
    expect(PROFILE_SCHEMA_ID).toBe(
      "https://github.com/esther-poniatowski/elenchos/specs/schemas/findings-profile.schema.json",
    );
  });
});

describe.each(identity)("the identity vector $case", (vector) => {
  it("conforms", () => {
    expect(violations(vector.log)).toEqual([]);
  });
});

describe.each(rejected)("the rejected vector $case", (vector) => {
  it("breaks the rules of a producer", () => {
    expect(violations(vector.log)).not.toEqual([]);
  });
});

describe.each(nonconforming)("the nonconforming vector $case", (vector) => {
  it("is reported at its node", () => {
    const pointers = violations(vector.log).map((violation) => violation.pointer);
    if (vector.pointer === null || vector.pointer === undefined) expect(pointers).toEqual([]);
    else expect(pointers).toContain(vector.pointer);
  });
});

describe.each(loci)("the locus vector $case", (vector) => {
  it("resolves to its node", () => {
    expect(resolveLocus(vector.document, vector.locus)).toEqual(vector.resolution);
  });
});

describe("a location name", () => {
  it("splits back into the resource and the locus that it joins", () => {
    const name = locationName("path:docs/notes#old.md", "link:a#b");
    expect(name).toBe("path:docs/notes%23old.md#link:a#b");
    expect(splitLocationName(name)).toEqual({
      resource: "path:docs/notes#old.md",
      locus: "link:a#b",
    });
  });

  it.each(["path:a.md#", "path:a%2Fb.md", "path:a%2"])("rejects %s", (name) => {
    expect(() => splitLocationName(name)).toThrow(ProfileError);
  });
});
