---
tags:
  - specification
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Gate configuration
---
# Gate configuration

This specification fixes the two files through which a consumer declares the inputs of the gate: the configuration, listing the checks and the severity policy, and the suppressions file, listing the tolerated findings. It also fixes how `elenchos check` runs the checks and decides its exit status. The grounds of each choice, and the options weighed, are recorded in the [decision on the runner and the suppressions](adr/runner-and-suppressions.md). The SARIF objects that the gate reads and writes follow the [findings profile](profile.md).

Elenchos discovers nothing on disk and holds no path of a consumer. The consumer passes the path of its configuration on the command line, and the configuration names every other path:

```sh
elenchos check --config config/elenchos.toml
```

## 1. Configuration

The configuration is a TOML file, published as the JSON Schema [configuration.schema.json](../specs/schemas/configuration.schema.json). The commands of the example are illustrative: they assume producers that write the profile.

```toml
version = 1
root = ".."
output = "build/elenchos/gate.sarif"
suppressions = "specs/suppressions.json"

[policy]
block = ["error"]

[policy.rules]
"geonexus|glossary/undeclared-concept" = []

[checks.links]
command = ["python", "utils/scripts/check_links.py", "--sarif", "build/elenchos/links.sarif"]
log = "build/elenchos/links.sarif"

[checks.glossary]
command = ["python", "utils/scripts/check_glossary.py", "--sarif", "build/elenchos/glossary.sarif"]
log = "build/elenchos/glossary.sarif"
exit_codes = [0, 1]
block = ["error", "warning"]
```

| Key | Status | Content |
| --- | --- | --- |
| `version` | required | `1`, the version of the format |
| `root` | optional | the root of the consumer, relative to the directory of the configuration file; `"."` when absent. The root contains the configuration file |
| `output` | required | the path where the merged log is written |
| `suppressions` | optional | the path of the suppressions file, under the root; absent when the consumer tolerates no finding. A declared file must exist |
| `policy.block` | required | the levels that block by default, among `error`, `warning` and `note` |
| `policy.rules` | optional | the levels that block for one rule, keyed by `tool|ruleId` |
| `checks.<name>` | at least one | one check, named by `[a-z][a-z0-9-]*`; the checks run in the order of the file |
| `checks.<name>.command` | required | the argument vector of the command that writes one SARIF log; it runs without a shell, in the root |
| `checks.<name>.log` | required | the path of the log written by the command; unique among the checks, and distinct from `output` |
| `checks.<name>.exit_codes` | optional | the exit statuses meaning that the command ran to completion; `[0, 1]` when absent |
| `checks.<name>.block` | optional | the levels that block for the results of this check, in place of `policy.block` |

**Paths.** Every relative path resolves against the root. The configuration file and the suppressions file lie under the root, since the gate names them as resources (`path:`) in its own results. Logs and the output may lie anywhere.

**Severity policy.** A result of a producer carries the default level written by its producer, and the gate does not rewrite it ([profile, section 4.2](profile.md#42-level)). The levels that block for a result are taken from the most specific declaration:

1. the entry of `policy.rules` for the tool and the `ruleId` of the result;
2. the `block` of the check whose log holds the result;
3. `policy.block`.

An empty list declares that no level blocks. A key of `policy.rules` holds the tool, since a `ruleId` is scoped to its tool ([profile, section 4.1](profile.md#41-ruleid)). The results of the gate itself belong to no check, so only steps 1 and 3 apply to them.

## 2. Suppressions file

The suppressions file is a JSON file, published as the JSON Schema [suppressions.schema.json](../specs/schemas/suppressions.schema.json). Version 1 holds identities of the profile key `elenchos/v1`.

```json
{
  "version": 1,
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

1. read and validate the configuration and the suppressions file;
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

A check is **incomplete** when its log is valid but holds an incomplete run: a partial run, stopped by design, or a failed run, by which a crashed producer reports itself ([profile, section 3](profile.md#3-log-and-run)). The runs of an incomplete check enter the merged log, since their results are genuine findings. The gate also reports the check as a result of rule `check/incomplete`, located at its declaration, whose message names the tool of each incomplete run and the reasons that its notifications state. Without that result, a producer that reports its own crash and exits with a declared status would pass the gate.

**Exit status.**

| Status | Meaning |
| --- | --- |
| 0 | no result blocks |
| 1 | at least one unsuppressed result blocks: a finding of a producer, a failed or incomplete check, or a stale suppression |
| 2 | the gate cannot run: the configuration or the suppressions file is invalid, or the merged log cannot be written |

## 4. Stale suppressions

A suppression is **stale** when it matches no result of the merged log. The gate reports each stale entry as a result of rule `suppression/stale`, located at the suppressions file, with the stale identity as discriminator. The result has level `error`, so a stale entry blocks under any policy whose default blocks errors. The consumer may declare `"elenchos|suppression/stale" = []` under `policy.rules`, for instance during a migration; the entry is then reported without blocking.

A stale entry blocks because it is a standing permission: if the finding it named comes back, the entry would tolerate it again without review. Blocking keeps the suppressions file equal to the debts that exist, so that the file only shrinks.

Two cases leave the gate unable to tell whether the finding of an entry persists:

- the tool of the entry yielded an incomplete run, which may have stopped before reaching the finding;
- the tool of the entry yielded no run while a check failed, and the failed check may have been that of the tool.

An unmatched entry in either case is **unverified**: the gate counts it in its summary, and does not report it as stale. Every other unmatched entry is stale. The failed or incomplete check already yields a result of the gate, judged by the policy.

The results of the gate are never suppressed: their `suppressions` array is always empty.

## 5. Open points

- The rename maps of [profile, section 5.5](profile.md#55-renames), a map of rules and a map of resources applied to stored suppressions, are not yet keys of the configuration. They take version 2 of the format.
- No command shrinks the suppressions file or converts a legacy count baseline into entries. A stale entry is removed by hand, guided by the report.
