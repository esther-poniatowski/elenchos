---
tags:
  - decision
status: accepted
created: 2026-11-19
index: "[Architecture decisions](docs/adr/_index.md)"
aliases:
  - Record validation decision
---
# Record validation

> [!QUESTION] Goal: in which form does Elenchos validate each file against the schema named by its binding, and from which owners does it read the records and the schemas?

The [decision on tool roles](https://github.com/esther-poniatowski/geonexus/blob/main/docs/_decisions/tool-roles.md) of Geonexus gives Elenchos the validation of each file against the schema that its binding names, as a check of its own. The [record validation](../validation.md) states the check normatively.

## Decision

**A command with its own driver.** The check is the command `elenchos validate`. A consumer declares it in its gate configuration as any other check. Its log names the driver `elenchos-validate`. ^command

**Owners of the inputs.** The check reads the records, their binding key and the place of their registry through `anagraphe-read`, and the registry through the public reader of Kleisis. Elenchos reads no configuration of these tools itself. ^owners

**An extra of the distribution.** The dependencies of the check form the extra `validate`, so that a producer that checks its logs with `elenchos.profile` installs Elenchos without `anagraphe-read` and Kleisis. ^extra

## Constraints that decide the form

- **The driver `elenchos` names the run of the gate.** The profile forbids a producer to write it, and the gate rejects a log of that driver.
- **The gate runs the checks of the consumer.** A check declared like the others receives the scope of a run, the severity policy and the suppressions without a rule of its own.
- **Anagraphe owns the records and their binding.** Its configuration declares the files that are records, their exemptions, the binding key and the schema registry, so a second declaration in Elenchos would repeat them.
- **Anagraphe tests with Elenchos.** The tests of Anagraphe will check its logs with `elenchos.profile`. If the distribution `elenchos` required `anagraphe-read`, installing it beside the editable read package of Anagraphe would pull a second copy of that package.

## Options weighed

| Option | Benefit | Reason it is not taken |
| ------ | ------- | ---------------------- |
| A section of the gate configuration, whose results join the run of driver `elenchos` | No log file of its own | The run of the gate then mixes findings on the gate with findings on the content, and the scope and the policy need a rule of their own |
| A list of files in the configuration of Elenchos | No dependency on Anagraphe | Repeats the declaration of the records and their exemptions, owned by Anagraphe |
| The dependencies of the check required by the distribution | One installation | Each producer checking its logs installs the read package of Anagraphe, and Anagraphe installs it twice |
| **A command of driver `elenchos-validate`, reading its inputs through their owners, behind an extra** | Uniform with the other checks; one declaration of each input; a light profile interface | Taken |

## Consequences

- **Consumers.** A consumer validating its records declares the check in its gate configuration. The consumer also declares, as dependencies of Kleisis, the owners of the contracts named by its records, such as the configurations of its tools.
- **Anagraphe.** The distribution `anagraphe-read` exposes the records of a repository, their binding key and the place of their registry, from its version 0.2.0.
- **Conda.** The extra installs through pip only, until `anagraphe-read` has a conda recipe of its own.
