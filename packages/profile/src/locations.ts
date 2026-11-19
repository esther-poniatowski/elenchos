/**
 * The name of the logical location of a finding: `<resource>` or `<resource>#<locus>`, as section
 * 4.5 of the profile states. The resource writes `%` as `%25` and `#` as `%23`; the locus is
 * written as is, since the name splits at its first `#`.
 */
import { ProfileError } from "./errors.js";

/** The resource and the locus of a finding, read from the name of its logical location. */
export interface Location {
  /** The resource, `id:<identifier>` or `path:<path>`, decoded. */
  readonly resource: string;
  /** The locus, empty for the whole resource. */
  readonly locus: string;
}

const ESCAPES: Readonly<Record<string, string>> = { "%25": "%", "%23": "#" };

/** Write the name of the logical location of a finding. */
export function locationName(resource: string, locus = ""): string {
  const escaped = resource.replace(/%/g, "%25").replace(/#/g, "%23");
  return locus === "" ? escaped : `${escaped}#${locus}`;
}

/**
 * Read the resource and the locus back from the name of a logical location.
 *
 * A name ending with `#`, or whose resource holds a `%` other than `%25` or `%23`, raises
 * `ProfileError`: no producer writes it, and accepting it would map two names onto one identity.
 */
export function splitLocationName(name: string): Location {
  const separator = name.indexOf("#");
  const escaped = separator === -1 ? name : name.slice(0, separator);
  const locus = separator === -1 ? "" : name.slice(separator + 1);
  if (separator !== -1 && locus === "") {
    throw new ProfileError(`logical location ${JSON.stringify(name)} ends with # and no locus`);
  }
  const resource = escaped.replace(/%..|%.?$/g, (escape) => {
    const character = ESCAPES[escape];
    if (character === undefined) {
      throw new ProfileError(`invalid escape ${JSON.stringify(escape)} in ${JSON.stringify(name)}`);
    }
    return character;
  });
  return { resource, locus };
}
