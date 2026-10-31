---
tags:
  - decision
status: proposed
created: 2026-10-31
revised: 2026-10-31
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Runner and suppressions decision
---
# Runner and suppressions

> [!QUESTION] Goal: how does a consumer declare its checks, its severity policy and its tolerated findings, and how does `elenchos check` turn the logs of the checks into one verdict?

The [decision on tool roles](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/tool-roles.md) of Geonexus assigns to Elenchos the runner of the checks declared by the consumer, and the baselines and suppressions. It leaves to the consumer the selection of tools, the severities, the baselines and the hook that invokes the gate. The [findings profile](../profile.md) fixes what a log holds and how a baseline entry enters it, as an external suppression with status `accepted`. The present record decides the files of the consumer and the behaviour of the runner. The [gate configuration](../configuration.md) states the result normatively.

## Decision

**Explicit configuration.** The consumer passes the path of one TOML configuration on the command line. The configuration names the root, the output, the suppressions file, the severity policy and each check; Elenchos discovers no file. ^configuration

**Checks keyed by name.** Each check is a table `checks.<name>` holding an argument vector run without a shell, the path of its log, and the exit statuses meaning that it ran to completion (`[0, 1]` by default). The gate deletes the log before the command runs. ^checks

**Levels by scope.** The levels that block are declared by default, per check, and per rule keyed by `tool|ruleId`; the most specific declaration wins. The gate never rewrites the level of a result. ^policy

**Suppressions in JSON.** The suppressions file is a JSON file of entries, each holding a canonical identity, a required justification, and optionally a date and an author. Each matched entry becomes an accepted external suppression, the date and the author going to its properties. ^suppressions

**Failures as results of the gate.** A check that cannot start, exits with an undeclared status, writes no log or writes an invalid log yields a result of the run of the gate, located at its declaration, and its runs are discarded. ^failures

**Incomplete runs enter the log.** A valid log holding a partial or failed run enters the merged log with the results it holds, and the gate adds a result of rule `check/incomplete` at the declaration of the check. ^incomplete

**Stale entries block.** An entry matching no result yields a result of rule `suppression/stale` at level `error`, judged by the policy like any result. An entry whose tool yielded an incomplete run, or yielded no run while a check failed, is unverified, not stale. ^stale

**Exit status.** `elenchos check` exits 0 when no result blocks, 1 when an unsuppressed result blocks, and 2 when the configuration or the suppressions file is invalid or the log cannot be written. ^exit

## Constraints that decide the form

- **Consumers declare their inputs.** The tool roles assign the configuration of the checks to the consumer. Therefore, Elenchos holds no consumer path and looks up no default file.
- **A small dependency set.** The gate runs at each commit, and the tool roles weigh robustness by the size of its dependencies. The standard library of Python 3.12 reads TOML and reads and writes JSON; YAML and JSON Schema validation require third-party packages.
- **A baseline only shrinks.** A tolerated finding that disappears must leave the suppressions file, or the entry would tolerate the same finding again when it returns.
- **A ruleId is scoped to its tool** (profile, section 4.1). Therefore, a rule of the policy is keyed by the tool and the `ruleId`.
- **Producers exit 1 on findings.** The runner of Geonexus, Ekthesis and Anagraphe exit with status 1 when a run reports findings; the runner of Geonexus treats any other non-zero status as a crash.
- **A run may stop by design.** Kleisis stops at its first failure, since each stage consumes the output of the previous one. The profile declares such a run, and a crash that the producer reports itself, as a failed run.
- **Every result of the gate carries an identity.** The gate builds identities from a resource and a semantic locus, so its own results need a stable locus too.

## Options weighed

**Format of the configuration.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| YAML, as `config/checks.yaml` of Geonexus | Matches the policy files of the consumer and the files rendered by Ekphrasis | Requires a YAML package at each commit; implicit typing turns `no` into a boolean and an unquoted date into a date object. It would win if the configuration had to be bound to a schema and rendered by Ekphrasis |
| JSON | Standard library; the format of SARIF | No comments, whereas each check deserves its gloss |
| A table of `pyproject.toml` | No extra file for a Python library | Elenchos would read a file of the consumer by convention, and a vault holds no `pyproject.toml` |
| **TOML, at a path given on the command line** | Standard library (`tomllib`); comments; typed values | Taken |

**Format of the suppressions file.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| TOML | One format with the configuration | The standard library cannot write TOML, and a converter of legacy baselines or a shrinking command must write the file |
| YAML | Readable for thousands of entries | Requires a package to read and write, and writing drops the comments |
| A table of the configuration | One file | The configuration changes with the selection of checks, the suppressions with the debts; Geonexus would hold about 2850 entries in its configuration |
| **JSON** | Standard library reads and writes it; the format of SARIF and of the current baselines; a justification field replaces comments | Taken |

**Validation of the two files.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| Validation by the published JSON Schema at run time | One source for the rules | Adds `jsonschema` and its dependencies to each commit; the path rules (root containment, unique logs) need code anyway |
| **Validation in code, and a test that the published schemas reject every planted breach that the code rejects** | No dependency at run time; the test catches a drift between schema and code | Taken |

**Representation of the checks.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| An array of tables with a `name` key | The order is explicit | A result of the gate located at `/checks/2` changes identity when a check is inserted above |
| **A table keyed by name** | The pointer `/checks/<name>` is a stable locus for a failed check; names are unique by construction; TOML keeps the order of the file | Taken |

**Detection of a failed command.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| Any non-zero exit status fails | No declaration | Every producer that exits 1 on findings would fail |
| The exit status ignored; the log alone decides | No declaration | A producer crashing after it wrote part of its log would pass, with findings missing |
| **Declared exit statuses, `[0, 1]` by default** | Matches the convention of the current producers; a crash is detected even when a log exists | Taken |

**Report of a failed check.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| `invocations[].toolExecutionNotifications` in the run of the gate | A field of SARIF made for tool failures | A notification is not a result: it carries no identity and no level of the policy, so the verdict would need a second channel |
| The exit status alone | Simple | A viewer of the log cannot see which check failed |
| **A result of the run of the gate, at the declaration of the check** | One channel for every verdict; visible in the log; the consumer can relax it by a rule of the policy | Taken |

**Handling of an incomplete run.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| Discard its runs, as for a failed check | One treatment for every failure | Drops genuine findings, and the suppressions that match them would turn unverified for nothing |
| Keep its runs, and add no result of the gate | No extra result | A producer reporting its own crash with a declared exit status, and no result, would pass the gate |
| **Keep its runs, add `check/incomplete`, and leave the unmatched entries of its tool unverified** | The findings stay visible; a self-reported crash blocks; no entry turns stale on a run that did not reach its finding | Taken. A consumer relaxing `elenchos\|check/incomplete` relaxes it for every tool, the self-reported crashes included |

**Policy of a stale entry.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| A warning only, as the runner of Geonexus reports resolved instances | No friction when a finding is fixed | The entry stays a permission, and silently tolerates the finding when it returns; the file only shrinks if someone remembers to shrink it |
| A dedicated switch of the configuration | Explicit | A second mechanism beside the policy of levels, which already expresses it |
| **A result at level `error`, judged by the policy** | The commit that fixes a finding removes its entry; the consumer may relax the rule `elenchos\|suppression/stale` during a migration | Taken |

**Policy of the levels.**

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| A threshold (`--fail-on warning`) | One value | Cannot keep one rule of warnings non-blocking while another blocks |
| Rewriting `level` in the merged log | The log shows the verdict | The profile leaves the level to the producer, and a viewer would lose the default level |
| **Levels declared by default, per check and per rule, the most specific winning** | Expresses a non-gating check and a non-gating rule; the level stays the producer's | Taken |

## Consequences

- **Findings profile.** Section 1 and section 5.6 add the rules of the verdict to the rejected input: a `level` among the three admitted values, a `message.text`, an array of results unless the run failed, well-formed invocations, and no object written by the gate only. Section 3 describes incomplete runs, and the run of the gate with its five rules; section 4.7 refers to the suppressions file and its properties; the open point on a crash of a producer is settled.
- **Decision on tool roles.** Its section "Findings" and item 5 of "Roles" hold as written. The hook of Geonexus invokes `elenchos check --config <path>` once its producers write the profile; its configuration replaces `config/checks.yaml` under `baselines` and `gating`. The baselines of `specs/baselines/` convert into one suppressions file through the ordinal.
- **Scoped runs.** The runner of Geonexus checks the files changed since the last commit. `elenchos check` always runs every check in full, since a scoped run would report the entries of unscanned files as stale. A scoped run takes a later decision.
- **Rename maps.** The maps of profile section 5.5 are not yet keys of the configuration; they take version 2 of the format.
- **Shrinking.** No command shrinks the suppressions file or converts a legacy baseline. A stale entry is removed by hand, guided by the report.
