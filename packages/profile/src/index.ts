/**
 * The findings profile of Elenchos in TypeScript: the check of a producer log, and the reading of
 * the location names and the loci of its findings. The specification is `docs/profile.md` of the
 * repository of Elenchos; the vectors of `specs/vectors/` fix the verdicts.
 */
export { ProfileError } from "./errors.js";
export { type Location, locationName, splitLocationName } from "./locations.js";
export { type Resolution, type Segment, pointer, resolveLocus } from "./loci.js";
export { PROFILE_SCHEMA_ID, type Violation, violations } from "./violations.js";
