---
tags:
  - decision
status: proposed
created: 2026-10-31
revised: 2026-10-31
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Findings profile decision
---
# Findings profile

> [!QUESTION] Goal: which subset of SARIF 2.1.0 do the producers of findings write, and how does the gate build from it an identity that survives edits and splits back into its components?

The [decision on tool roles](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/tool-roles.md) of Geonexus assigns to Elenchos the findings profile, the construction of finding identities, the baselines and the runner of the checks. The accepted [decision on stable checker finding identities](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/stable-checker-finding-identities.md) fixes what an identity holds: the checker and rule, the resource, a semantic locus, and a discriminator for two instances at one locus. It excludes the message, the severity, the line and column, and the repair. The present record decides how SARIF carries these components, and how they join into one string. The [findings profile](../profile.md) states the result normatively.

## Decision

**One run per producer.** A log holds one run per invocation of a producer, and Elenchos adds one run of its own. Elenchos never alters the `tool` object of a run. ^runs

**One logical location.** A result holds exactly one location, with exactly one top-level logical location whose `name` is `<resource>#<locus>`, or `<resource>` for the whole resource. The resource is `id:<identifier>` or `path:<path>`. The locus is a JSON Pointer for a key path, or a typed locus from a closed list (`link`, `task`, `slot`, `term`, `symbol`). ^logical-location

**Discriminator as the only partial fingerprint.** A producer writes `partialFingerprints["discriminator/v1"]` only. Elenchos writes the identity in `fingerprints["elenchos/v1"]`. ^fingerprints

**Identity string.** The identity is `tool|ruleId|resource|locus|discriminator[|ordinal]`. Each component is normalized to NFC, then `%`, `|` and control characters are percent-escaped. Trailing empty components are removed, and a parser accepts a string only in its canonical form. ^identity-string

**Ordinal.** Results of one tool sharing one identity are sorted by line, column, message and input order, and the *k*-th receives the ordinal *k*, written from 2 on. ^ordinal

**Baselines as suppressions.** A baseline entry is an external suppression with status `accepted` and a justification. Every result emitted by Elenchos carries a `suppressions` array, empty when unsuppressed. `baselineState` is not written. ^baselines

**Renames.** The consumer declares a map of rules (tool and `ruleId`) and a map of resources (`path:` to `id:`), which Elenchos applies to stored suppressions. ^renames

## Constraints that decide the form

- **The elements of `logicalLocations` are alternatives.** SARIF lists in that array several expressions of one location (§3.28.4, NOTE). Therefore, a resource and its locus cannot occupy two elements.
- **A partial fingerprint repeats nothing deducible.** Appendix B advises an analysis tool against placing in `partialFingerprints` information deducible from the rest of the log. The tool, the resource and the locus are deducible; the discriminator is not.
- **A direct producer does not write `fingerprints`.** §3.27.16 leaves the property to converters and result management systems. Elenchos ingests the logs, so it writes the identity.
- **`/` occurs inside the components.** A `ruleId` is a hierarchical string (§3.27.5), and paths and JSON Pointers contain `/`. Therefore, `/` cannot separate the components.
- **A baseline is readable and states its reason.** The decision on stable identities requires each baseline entry to refer to the identity and to state its reason. Therefore, the identity is a readable string, and a suppression carries a justification.
- **Producers import no package.** Each producer implements the profile from its text and its test vectors. Therefore, the identity is defined by a short algorithm over the log, not by a library.
- **Current baselines count identical occurrences.** 414 entries of the glossary baseline of Geonexus count several identical occurrences at one locus. A discriminator derived from the content cannot separate them.

## Options weighed

**Identity separator.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| `/`, as first drafted in the decision on tool roles | Matches the hierarchical strings of SARIF | `/` occurs inside a `ruleId`, a path and a pointer, so the string cannot be split back |
| A hash of the components | Fixed length; any character admitted | Unreadable in a baseline, so a reviewer cannot match an entry to its object |
| A JSON array of the components | Unambiguous with standard tooling | Quoting doubles in a JSON baseline, and every producer must reproduce one exact serialization |
| The unit separator U+001F | No escaping of printable characters | Invisible in an editor and in a diff |
| **`\|` with percent escaping** | Readable; splits back; escaping touches only `%`, `\|` and control characters, which are rare in the components | Taken |

**Placement of the resource and the locus.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| Two elements of `logicalLocations`, the resource first | Each component in a field of its own | Breaks §3.28.4: the elements are alternatives, not a container and its part |
| A nested location through `run.logicalLocations` and `parentIndex` | Conforms (§3.33.8); suits a consumer that groups results by container | Every producer maintains a run-level table, and the identity of a result can no longer be computed from the result alone. It would win if a consumer of the logs required the hierarchy |
| `partialFingerprints` keys `tool/v1`, `resource/v1`, `locus/v1` | Each component under a named key | Contradicts Appendix B, since the three are deducible |
| A `properties` bag | Free structure | Invisible to SARIF viewers and to any other result management system |
| **One logical location named `<resource>#<locus>`** | Conforms; one result suffices; the name serves for display | Taken |

**Baselines.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| `baselineState` against a previous run | A field of SARIF made for comparison | A SARIF baseline is a previous run: the state must appear on every result, and each vanished finding must be emitted as `"absent"`. A debt that may only shrink, with a reason, has no place in it |
| A baseline format outside SARIF only | No constraint from the standard | Viewers and other consumers of the log cannot see which findings are tolerated |
| **External suppressions with status `accepted`** | The baseline file is the external store of §3.35.2, and the log shows the suppression state of each result | Taken |

**Identical occurrences at one locus.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| The discriminator alone | No numbering | Cannot separate identical occurrences, so 414 counted entries would merge |
| The line number in the identity | Separates every occurrence | Any edit above the finding renames it, and Appendix B advises against absolute line numbers |
| A hash of the surrounding text | Survives edits elsewhere in the file | Changes with nearby edits; unreadable |
| One result per locus, with a count | No ordinal | Keeps count baselines, which the decision on stable identities treats as temporary migration controls |
| **An ordinal over the identical occurrences, in region order** | Reproduces the current counts exactly; readable | Taken. Removing the first occurrence shifts the ordinals of the others, which then match the shrunk baseline count by count |

## Consequences

- **Decision on stable checker finding identities.** Acceptance of this record amends that decision in the same change. Elenchos, not a shared checker library, builds the identity. The fields of a finding are those of the profile, not `id`, `rule_id`, `resource` and `locus`. An ordinal numbers identical occurrences beside the discriminator, and the locus types `term` and `symbol` join the admitted loci. Its sentence "A checker reports two diagnostics that receive the same identifier" contradicts its own driver *Distinguishes instances*, and is rewritten.
- **Decision on tool roles.** Its section "Findings" omits the locus types `term` and `symbol` and the `uriBaseId` of relative URIs. It also lists the rename maps under the `properties` bag, although they belong to the configuration of the consumer. These points are corrected when the present record is accepted.
- **Producers.** Each producer that stays writes the profile; the [producer and baseline migration](../producer-migration.md) maps each current output.
- **Baselines.** The current count baselines convert into suppressions through the ordinal, one identity per counted instance.
- **Prose rules.** A locus for prose rules (Hermeneia, glossary occurrences) remains open. A new locus type, such as `section:`, takes a new version of the profile and of its key.
- **Normalization.** The whole identity string is not NFC in general, since an escape can precede a combining mark. Every consumer compares identities code point by code point, without normalizing them again.

---

## Sources

Marks follow the [legend of reading marks](../../CONTRIBUTING.md#^reading-marks).

- [oasis2023] ◐ [OASIS, *Static Analysis Results Interchange Format (SARIF) Version 2.1.0 Plus Errata 01*, OASIS Standard, 28 August 2023](https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/sarif-v2.1.0-errata01-os-complete.pdf); the clauses cited by the findings profile, each quoted there with its mark
