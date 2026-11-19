/**
 * The locus of a finding resolved against its document. A locus that opens on `/` is a JSON
 * Pointer (RFC 6901), whose tokens descend from the root: under an object, a token names a
 * property; under an array, a token of decimal digits without leading zero names an index, and a
 * keyed token `<property>=<value>` names the one entry that holds the value under the property.
 */

/** One step of a positional path: a property name, or an index of an array. */
export type Segment = string | number;

/** The node of a document that a locus names, or its closest existing ancestor. */
export interface Resolution {
  /** Positional path of the deepest node reached, empty for the whole document. */
  readonly path: readonly Segment[];
  /** The decoded tokens below that node, empty when the locus names an existing node. */
  readonly unresolved: readonly string[];
}

const INDEX = /^(?:0|[1-9][0-9]*)$/;

/** Write a positional path as a JSON Pointer. */
export function pointer(path: readonly Segment[]): string {
  return path.map((step) => "/" + String(step).replace(/~/g, "~0").replace(/\//g, "~1")).join("");
}

function isObject(node: unknown): node is Record<string, unknown> {
  return typeof node === "object" && node !== null && !Array.isArray(node);
}

/** The child of `node` that `token` names, as its positional segment, or undefined. */
function step(node: unknown, token: string): Segment | undefined {
  if (isObject(node)) {
    return Object.prototype.hasOwnProperty.call(node, token) ? token : undefined;
  }
  if (!Array.isArray(node)) return undefined;
  if (INDEX.test(token)) return Number(token) < node.length ? Number(token) : undefined;
  const separator = token.indexOf("=");
  if (separator === -1) return undefined;
  const name = token.slice(0, separator);
  const value = token.slice(separator + 1);
  const holders = node.flatMap((item, index) =>
    isObject(item) && item[name] === value ? [index] : [],
  );
  return holders.length === 1 ? holders[0] : undefined;
}

/**
 * Resolve the locus of a finding against its document. A typed locus names no node of a document,
 * and yields `null`. A pointer holding a `~` followed by neither `0` nor `1` throws `TypeError`.
 */
export function resolveLocus(document: unknown, locus: string): Resolution | null {
  if (locus !== "" && !locus.startsWith("/")) return null;
  if (/~(?![01])/.test(locus)) {
    throw new TypeError(`pointer ${JSON.stringify(locus)} holds a ~ followed by neither 0 nor 1`);
  }
  const tokens = locus
    .split("/")
    .slice(1)
    .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
  const path: Segment[] = [];
  let node = document;
  for (const [position, token] of tokens.entries()) {
    const segment = step(node, token);
    if (segment === undefined) return { path, unresolved: tokens.slice(position) };
    node = (node as Record<string | number, unknown>)[segment];
    path.push(segment);
  }
  return { path, unresolved: [] };
}
