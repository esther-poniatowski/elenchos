---
tags:
  - specification
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Gate configuration
---
# Gate configuration

This specification fixes the two files through which a consumer declares the inputs of the gate: the configuration, listing the checks and the severity policy, and the suppressions file, listing the tolerated findings. It also fixes how `elenchos check` runs the checks and decides its exit status. The grounds of each choice, and the options weighed, are recorded in the [decision on the runner and the suppressions](adr/runner-and-suppressions.md). The SARIF objects that the gate reads and writes follow the [findings profile](profile.md).

The configuration names every path of the consumer. Elenchos itself locates only the root of the consumer and the configuration file:

```sh
elenchos check                                        # from the root or any folder below it
elenchos check --root PATH --config FILE              # both named explicitly
```

**Root.** The root is the folder in which the checks run and against which every path of the configuration resolves. Elenchos takes the first answer among:

1. the option `-r`, `--root`;
2. the environment variable `ELENCHOS_ROOT`;
3. the nearest ancestor of the current folder, the current folder included, that holds `config/tools/elenchos.toml` or `elenchos.toml`;
4. the current folder.

**Configuration file.** The configuration file is named `elenchos.toml`. Without `-c`, `--config`, Elenchos reads `config/tools/elenchos.toml` or `elenchos.toml` below the root. When both exist, the gate refuses to run and names both. When neither exists, the gate also refuses to run, since it has no built-in checks. A file named by `--config` and absent is an error. A path given on the command line, to `--root`, `--config` or as a scope, is read from the current folder.

## 1. Configuration

The configuration is a TOML file, published as the JSON Schema [configuration.schema.json](../specs/schemas/configuration.schema.json). The commands of the example are illustrative: they assume producers that write the profile.

```toml
_schema = "elenchos:configuration@3"
output = "build/elenchos/gate.sarif"
suppressions = "specs/suppressions.json"

[policy]
block = ["error"]

[policy.rules]
"geonexus|glossary/undeclared-concept" = []

[renames.rules]
"geonexus|links/broken" = "anagraphe|references/broken"

[checks.links]
command = ["python", "utils/scripts/check_links.py", "--format", "sarif", "--output", "build/elenchos/links.sarif"]
log = "build/elenchos/links.sarif"
scope = "paths"

[checks.glossary]
command = ["python", "utils/scripts/check_glossary.py", "--format", "sarif", "--output", "build/elenchos/glossary.sarif"]
log = "build/elenchos/glossary.sarif"
exit_codes = [0, 1]
block = ["error", "warning"]
```

| Key | Status | Content |
| --- | --- | --- |
| `_schema` | required | `elenchos:configuration@3`, the first key of the file. Earlier formats are no longer read: they held a key `root`, and resolved the paths of the file against their folder. A file that still carries the former key `version` stops with status 2, and the message names the value to write |
| `output` | required | the path where the merged log is written |
| `suppressions` | optional | the path of the suppressions file, under the root; absent when the consumer tolerates no finding. A declared file must exist |
| `policy.block` | required | the levels that block by default, among `error`, `warning` and `note` |
| `policy.rules` | optional | the levels that block for one rule, keyed by `tool|ruleId` |
| `checks.<name>` | at least one | one check, named by `[a-z][a-z0-9-]*`; the checks run in the order of the file |
| `checks.<name>.command` | required | the argument vector of the command that writes one SARIF log; it runs without a shell, in the root |
| `checks.<name>.log` | required | the path of the log written by the command; unique among the checks, and distinct from `output` |
| `checks.<name>.exit_codes` | optional | the exit statuses meaning that the command ran to completion; `[0, 1]` when absent |
| `checks.<name>.block` | optional | the levels that block for the results of this check, in place of `policy.block` |
| `checks.<name>.scope` | optional | `paths` when the command accepts paths appended to its argument vector, so that a scoped run checks only those paths; `root`, the default, when it always checks the whole root |
| `renames.rules` | optional | the new `tool|ruleId` of a renamed or moved rule, keyed by its former `tool|ruleId` |
| `renames.resources` | optional | the new resource of a moved or newly identified resource, keyed by its former resource (`path:<path>` or `id:<identifier>`) |

**Paths.** Every relative path of the file resolves against the root, never against the folder of the file, so the file moves between the root and `config/tools/` without an edit. The configuration file and the suppressions file lie under the root, since the gate names them as resources (`path:`) in its own results. Logs and the output may lie anywhere.

**Severity policy.** A result of a producer carries the default level written by its producer, and the gate does not rewrite it ([profile, section 4.2](profile.md#42-level)). The levels that block for a result are taken from the most specific declaration:

1. the entry of `policy.rules` for the tool and the `ruleId` of the result;
2. the `block` of the check whose log holds the result;
3. `policy.block`.

**Renames.** Before matching, the gate rewrites each stored suppression through the two maps of `renames`, as the [profile, section 5.5](profile.md#55-renames) states:

- the map of rules replaces the tool and the `ruleId` together;
- the map of resources replaces the resource;
- the locus, the discriminator and the ordinal stay unchanged.

No value of a map may be a key of the same map. Therefore, a chain of renames is declared by its first and last forms. When two entries take one identity after the rewrite, the gate rejects the suppressions file. A suppression matched after a rename records, in the property `elenchos/renamed-from`, the identity written in the file. The command `elenchos update` then writes the entry under its new identity.

An empty list declares that no level blocks. A key of `policy.rules` holds the tool, since a `ruleId` is scoped to its tool ([profile, section 4.1](profile.md#41-ruleid)). The results of the gate itself belong to no check, so only steps 1 and 3 apply to them.

## 2. Suppressions file

The suppressions file is a JSON file, published as the JSON Schema [suppressions.schema.json](../specs/schemas/suppressions.schema.json). The key `_schema`, first in the file, is `elenchos:suppressions@1`; this format holds identities of the profile key `elenchos/v1`. The file cannot be regenerated, since it holds justifications written by a person, so a file that still carries the former key `version` stops with status 2, and the message names the value to write.

```json
{
  "_schema": "elenchos:suppressions@1",
  "suppressions": [
    {
      "identity": "geonexus|links/broken|path:docs/a.md|link:b.md",
      "justification": "tolerated when the links checker started gating",
      "date": "2026-10-15",
      "author": "Esther Poniatowski"
    }
  ]
}
```

| Key | Status | Content |
| --- | --- | --- |
| `identity` | required | a canonical identity string ([profile, section 5.4](profile.md#54-parsing)); each identity occurs at most once in the file |
| `justification` | required | the reason for which the finding is tolerated; not blank |
| `date` | optional | the ISO 8601 date on which the entry was written, `YYYY-MM-DD` |
| `author` | optional | the author of the entry; not blank |

An entry suppresses the one result whose identity equals its own, compared code point by code point. An identity carrying an ordinal suppresses one occurrence among identical ones, so a baseline counting *c* occurrences becomes *c* entries.

Each matched entry becomes the SARIF suppression `{"kind": "external", "status": "accepted", "justification": …}` of its result ([profile, section 4.7](profile.md#47-suppressions)). The date and the author, when present, go to the properties `elenchos/date` and `elenchos/author` of the suppression.

## 3. Runner

`elenchos check` proceeds in six steps:

1. read and validate the configuration and the suppressions file, and apply the rename maps to the suppressions;
2. for each check, delete its log, run its command, and read the log that the command wrote. A log left by an earlier run is therefore never read;
3. validate each log against the profile ([profile, section 5.6](profile.md#56-rejected-input)). A log that the rejected vectors describe is rejected;
4. merge the runs of the valid logs into one log, one run per producer run with its `tool` object unaltered, incomplete runs included. Build the identity of every result, numbering identical occurrences across every run of one tool;
5. apply the suppressions, then add the run of the gate, of driver `elenchos`, holding one result for each failed or incomplete check and for each stale suppression;
6. write the merged log at `output`, print one summary line per check and every blocking result, and exit.

A check **fails** in three cases, each reported as a result of the gate, located at the declaration of the check (`path:<configuration>#/checks/<name>`):

| Rule | Case |
| --- | --- |
| `check/failed` | the earlier log cannot be deleted, or the command cannot start or exits with a status outside `exit_codes` |
| `check/missing-log` | the command exits with a declared status, but writes no log |
| `check/invalid-log` | the log is not JSON, or breaks the profile |

The runs of a failed check do not enter the merged log, since its log is absent, left by a crashed command, or unreadable.

**Scoped runs.** Two forms scope a run:

- `elenchos check --changed` scopes it to the files changed since the last commit, and to the untracked files outside the ignore rules of Git;
- `elenchos check PATH...` scopes it to the given files or folders, under the root.

A check of scope `paths` receives the repository-relative paths, appended to its command. When the scope holds no path, the gate skips that check. A check of scope `root` checks the whole root, as in a full run. The gate judges the results of a scoped run as those of a full run; only the staleness of suppressions changes, as section 4 states.

A check is **incomplete** when its log is valid but holds an incomplete run: a partial run, stopped by design, or a failed run, by which a crashed producer reports itself ([profile, section 3](profile.md#3-log-and-run)). The runs of an incomplete check enter the merged log, since their results are genuine findings. The gate also reports the check as a result of rule `check/incomplete`, located at its declaration, whose message names the tool of each incomplete run and the reasons that its notifications state. Without that result, a producer that reports its own crash and exits with a declared status would pass the gate.

**Exit status.**

| Status | Meaning |
| --- | --- |
| 0 | no result blocks |
| 1 | at least one unsuppressed result blocks: a finding of a producer, a failed or incomplete check, or a stale suppression |
| 2 | the gate cannot run: the configuration file is absent, competes with a second one, or is invalid, the suppressions file is invalid, or the merged log cannot be written |

## 4. Stale suppressions

A suppression is **stale** when it matches no result of the merged log. The gate reports each stale entry as a result of rule `suppression/stale`, located at the suppressions file, with the stale identity as discriminator. The result has level `error`, so a stale entry blocks under any policy whose default blocks errors. The consumer may declare `"elenchos|suppression/stale" = []` under `policy.rules`, for instance during a migration; the entry is then reported without blocking.

A stale entry blocks because it is a standing permission: if the finding it named comes back, the entry would tolerate it again without review. Blocking keeps the suppressions file equal to the debts that exist, so that the file only shrinks.

Three cases leave the gate unable to tell whether the finding of an entry persists:

- the tool of the entry yielded an incomplete run, which may have stopped before reaching the finding;
- the tool of the entry yielded no run while a check failed or was skipped, and that check may have been the check of the tool;
- the tool of the entry ran only in scoped checks, and the scope covers no path of the resource of the entry: a `path:` resource equal to a path of the scope or below one of its folders. An `id:` resource is never covered.

An unmatched entry in either case is **unverified**: the gate counts it in its summary, and does not report it as stale. Every other unmatched entry is stale. The failed or incomplete check already yields a result of the gate, judged by the policy.

The results of the gate are never suppressed: their `suppressions` array is always empty.

## 5. Updating the suppressions file

`elenchos update` runs the checks as `check` does, with the same root, configuration and scope options, and then rewrites the suppressions file:

- every entry is written under its current identity, so an identity renamed by the maps is settled in the file;
- with `--prune`, every stale entry is removed. An unverified entry is kept, since its finding may persist;
- with `--accept TEXT`, every unsuppressed result of a producer receives an entry justified by `TEXT`, dated today, and authored by `--author NAME` when given. `--only NAME`, repeatable, restricts the accepted results to the named checks, so that each check receives its own justification. The results of the gate are never accepted.

The command exits 0 once the file is written, and 2 when an input is invalid, the configuration declares no suppressions file, or a file cannot be written. A legacy count baseline is converted by accepting, once, every finding that it tolerates: when the run holds no finding beyond the baseline, `update --accept` writes one entry per tolerated instance, its ordinal reproducing the count.
