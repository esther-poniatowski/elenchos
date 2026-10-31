---
tags:
  - migration
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Producer and baseline migration
---
# Producer and baseline migration

This document maps the current output of each producer of findings onto the [findings profile](profile.md), and maps each entry of the current baselines of Geonexus onto the identities of the profile. It serves the migration only: once every producer writes the profile and every baseline is converted, the document has no further reader.

## 1. Order of the migration

Migrating the baselines requires the identity builder of the gate, so the migration runs in four steps:

1. write the profile and its test vectors;
2. create Elenchos with the identity builder and the converter of legacy baselines;
3. add SARIF output to each producer that stays, skipping the duplicates to retire;
4. migrate the baselines, verified at one commit ([section 4](#4-entries-that-need-manual-mapping-or-review)).

## 2. Producers

The producers are ordered by migration effort, lowest first. The column "Locus" states whether the current output carries a semantic locus.

| Producer | Output now | Fields | Severity scale | Locus | Code that builds it | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| Ekthesis `ekthesis check` | text line `record:field: severity [rule] message`; exit 1 on an error | `rule`, `record` (path), `field` (Ekphrasis field path), `severity`, `message` | `error`, `warning` | yes, field path | `src/ekthesis/findings.py` (`Finding`, `Severity`), `rules.py`, `cli.py` | lowest: a serializer, a resource identifier, field path → pointer. Its docstring already maps onto SARIF |
| Kleisis `kleisis check` | one stderr line `kleisis: <problems joined by "; ">`; exit 1 | message only, from `DriftError`, `RegistryError`, … | none: every failure blocks | no; the subject is the record or a generated file | `src/kleisis/cli.py`, `application/service.py` (`check`, `problems` list) | low: the problems are already collected in a list; each needs a `ruleId` and a resource |
| Anagraphe `anagraphe` commands | text line `path:line: [warning: ]kind: detail`; exit 0/1/2 | `rel`, `line`, `kind`, `detail`, `blocking` | blocking, warning | no | `src/anagraphe/core/issues.py` (`Issue`, `Report`), `cli.py` | low to medium: one `Issue` type, but a locus must be added to every kind |
| Ekphrasis custom checkers | a list of strings or of mappings `{message, path, severity}`, returned over JSON to the plugin | `message`, `path` (field path), `severity`; the checker name is the registration name | `error`, `warning` (default `error`) | yes, field path | `docs/features/custom-checkers.md`; `src/domain/validation/issues.ts` (`Issue`: `path`, `id`, `checker`, `severity`, `missing`, `message`) | low for the mapping (`checker` → `ruleId`, `path` → pointer); a key for the discriminator must be added to the contract. The gate reaches these functions only through the command of the domain tool that owns them |
| Hermeneia `hermeneia … --format json` | JSON `{diagnostics: [{code, message, path}], results: [{path, violations, revision_plan, scorecard}]}`; also text and compact formats | violation: `rule_id`, `message`, `span` (`start`, `end`, `start_line`, `start_column`, `end_line`, `end_column`), `severity`, `layer`, `evidence`, `confidence`, `rationale`, `rewrite_tactics` | `info`, `warning`, `error`; `--fail-on` threshold | no: offsets and lines only | `src/hermeneia/rules/base.py` (`Violation`, `Severity`), `report/diagnostic.py`, `cli.py` (`_render_json`, `_located`) | medium: serialization is direct, but a prose rule needs a locus that survives edits; `info` → `note`; the column base must be checked |
| Gnomon | itinerary command: line `<itinerary id>: <locus>: <message>`, exit 1; library checks return `"<field path>: <message>"` strings; `validate` not implemented | free strings, locus as a prefix | none: every problem blocks | yes, in the string prefix | `src/gnomon/itineraries.py` (`itinerary_problems`, `malformed_registry`), `completeness.py` (`unresolved_slots`, `unmet_by_aim`, …), `cli.py` | medium: every check function must return typed findings with a `ruleId` |
| Kataskeue `kataskeue check` | the first `DriftError` message on stderr, exit 1; "plugin profile matches the canonical record" on success | message only | none | no | `src/cli.ts`, `src/application/materializer.ts` (`checkProfile`), `src/errors.ts` | low: the check stops at the first drift, so its run declares itself incomplete, as the profile defines for partial runs; collecting every drift is optional |
| Geonexus checkers (`utils/scripts/`) | text line `path[:line]: [keys: ][warning: ]kind: detail`, summary line, exit status; parsed by `check_baseline.py` (`FINDING`, `normalize`, `classify`) | five `Issue` classes (`check_links.py`: `path, line, kind, target, detail`; `check_frontmatter.py`, `check_tasks.py`, `index_entries/generator.py`: `path/rel, line, kind, detail[, blocking]`; `glossary_checks/issues.py`: `rel, keys, kind, detail, blocking`), and plain strings in `check_structure.py`, `check_dependencies.py`, `check_manifests.py`, `check_schema_bindings.py`, `check_schema_resources.py`, `build_metadata_options.py`, `check_tool_sources.py` | blocking, `warning:`; per-kind severities from `config/checks.yaml` (glossary) | key path in the glossary checks only; link target in the text of link findings | the files named; the runner `check.py`, the baselines `check_baseline.py` | highest by volume: about fifteen checkers and many kinds. Most of them move to another tool, so SARIF output should be written once, in the successor |

**Mapping of the current outputs.**

- **Geonexus.** Driver `geonexus`. `ruleId` = `<checker name>/<kind>`, as named under `baselines` in `config/checks.yaml` (`links/broken`). A declared rule of `check_dependencies.py` becomes a further component (`dependencies/foundations-stand-alone`). `level` = `warning` when the line holds `warning:`, `error` otherwise. `message.text` = the detail. `region.startLine` = the line, when given. Resource = `path:<path>`. Locus per kind, as in [section 3](#3-baselines).
- **Anagraphe.** `ruleId` = `<section>/<kind>`, `blocking` → `error`/`warning`, `rel`/`line` → physical location; a locus is added per kind.
- **Ekthesis.** `rule` → `ruleId`; `record` → physical location, and resource = `id:` once the schema declares `x-identifier`; `field` → pointer locus; `severity` → `level`.
- **Hermeneia.** `rule_id` → `ruleId`; `severity` → `level` (`info` → `note`); `span` → `region`; `layer`, `evidence`, `confidence`, `rationale`, `rewrite_tactics` → `properties` under `hermeneia/`. A locus must be designed; a candidate is the heading path of the section, with the normalized offending sentence as discriminator. That candidate requires a new locus type, `section:`, and therefore a new version of the profile.
- **Gnomon.** Each check function returns a finding with a `ruleId` named after the check (`completeness/unresolved-slot`, `itinerary/unknown-activity`); its string prefix → pointer locus; resource = `id:` of the record; `level` = `error`.
- **Kleisis, Kataskeue.** One `ruleId` per kind of problem (`drift-resources`, `drift-registry`, `registry-absent`, …); resource = `path:` of the record or of the generated file; `level` = `error`; no region.
- **Ekphrasis custom checkers.** A returned string → `ruleId` = registration name, locus = the declaring field, `level` = `error`. A returned mapping → its `path` as locus and its `severity` as `level`. The `missing` flag of an Ekphrasis issue goes to `properties["ekphrasis/missing"]`.

## 3. Baselines

**Current form.** Each `specs/baselines/<name>.json` of Geonexus holds `checker`, `command`, `count` and `findings`, a map from a *normalized line* to a count. The line is normalized by `check_baseline.normalize`, which removes `:<line>` and `line <n>`. A finding is new when the run holds more instances of a normalized line than the baseline counts. A baseline may only shrink (`--update`), and `--freeze` rewrites it. All files were first committed on 2026-10-15. The entries carry no reason, whereas the decision on stable checker finding identities requires one.

| File | Instances | Entries | Entries counted more than once | Kinds (instances) |
| --- | --- | --- | --- | --- |
| `links.json` | 79 | 78 | 1 | `broken` 39, `heading-fragment` 34, `broken-anchor` 6 |
| `frontmatter.json` | 11 | 9 | 2 | `unlinkable-target` 10 (7 as warnings), `retired-key` 1 |
| `glossary.json` | 2752 | 888 | 414 | `forbidden-term` 2387, `deprecated-symbol` 211, `undeclared-concept` 142 (warnings), `unresolved-binding` 7 (warnings), `gloss-form` 5 |
| `dependencies.json` | 8 | 7 | 1 | `dependency` 8 |
| `indexes.json`, `structure.json`, `tasks.json` | 0 | 0 | 0 | — |

The checkers `metadata-options`, `schema-resources`, `schema-bindings`, `manifests` and `tool-sources` hold no baseline, and fail on any blocking finding. The glossary checker holds a baseline but is not gating.

**Mapping of each entry.**

| Kind | Resource | Locus | Discriminator |
| --- | --- | --- | --- |
| `broken`, `heading-fragment`, `broken-anchor` | path before the first colon followed by a space | `link:<target>`, the text before the first dash `—` surrounded by spaces | — |
| `unlinkable-target` | path | `link:<target>` | — |
| `retired-key` | path | `/<key>` | — |
| `forbidden-term` | path | `term:<glossary id>` | the matched surface form |
| `deprecated-symbol` | path | `symbol:<notation id>` | the matched expression, decoded from its Python `repr` |
| `undeclared-concept` | path (or `id:` once declared) | the dotted key path as a pointer (`/knowledge/0/undeclared`) | the concept |
| `unresolved-binding` | path | `/<role>`, the frontmatter key of the role (assumed) | the unresolved value |
| `gloss-form` | path | the dotted key path as a pointer | — |
| `dependency` | path | `link:<target>`, after the last colon followed by a space | — |

`ruleId` = `<checker>/<kind>`; for `dependency`, `dependencies/<declared rule id>`. An entry counted *c* times yields *c* identities through the ordinal of the [profile](profile.md#53-string-and-ordinal). Each identity becomes one stored suppression `{fingerprint, kind: external, status: accepted, justification}`. The justification is written automatically: "tolerated when the `<checker>` checker started gating; frozen on 2026-10-15".

**Measured.** A parse of every entry with the patterns of the table (a scratch script of the drafting session) parsed all 2850 instances and left none unparsed. No two legacy entries map to one identity, so dropping the message and the severity merges nothing. 418 identities need ordinals, covering 2286 instances.

## 4. Entries that need manual mapping or review

- **The 32 `deprecated-symbol` entries (211 instances).** The matched expression is printed with `repr` (`'\\delta_{\\mathrm{ch}}'`), so the discriminator must be decoded, and the decoding compared with the new producer on these entries.
- **The 142 `undeclared-concept` entries.** They map automatically, but their locus is a list index (`knowledge.0`), so an insertion above them renames the finding. Either that renaming is accepted, or the locus is keyed by the concept before the freeze.
- **The 7 `unresolved-binding` entries.** The legacy locus is the pseudo-key `frontmatter`. The pointer `/<role>` is an assumption to be confirmed by the new producer.
- **The 5 `gloss-form` entries.** A dotted key path is ambiguous when a key holds a dot, so these 5 entries are checked by hand.
- **Every entry, at the migration commit.** Automatic mapping holds only where the new SARIF producer reproduces the components. The migration runs the new producers at the commit where the legacy run passes. It then compares the multiset of identities with the migrated suppressions, checker by checker. A suppression matching no result, or a result beyond the counts, is reviewed by hand.
- **The checkers to retire** (`check_links.py`, `build_indexes.py`, and the other duplicates of the inventory of the [decision on tool roles](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/tool-roles.md)). Their entries migrate onto the rules of the successor through the rename map, without SARIF output from the retired script.
