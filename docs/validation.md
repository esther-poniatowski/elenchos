---
tags:
  - specification
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Record validation
---
# Record validation

The check `elenchos validate` validates each record of a consumer against the schema of the contract that the record names. The check writes its findings in the [findings profile](profile.md), under the driver `elenchos-validate`, and the gate runs it as any other check of the [gate configuration](configuration.md). The grounds of its form are recorded in the [decision on record validation](adr/record-validation.md).

## 1. Inputs

The check reads three inputs of the consumer, each through the tool that owns it:

- the **records**, read through `anagraphe-read` from the configuration of Anagraphe of the consumer. A record is the frontmatter of a note, or the top-level mapping of a JSON or YAML document, or of a TOML document declared with a `toml` source by the configuration. The walk skips the files that the configuration exempts, the record registry, and the files of nested repositories;
- the **binding key**, read from the same configuration: the property naming the contract of a record, `_schema` by default;
- the **schema registry**, named by the key `targets.records.registry` of the same configuration, and read through the public reader of Kleisis. The registry gives the schema of each contract, and the file of each absolute `$id` reached by a reference.

The check skips a record whose binding key holds no value. The check also skips an unreadable or unparsable record, since `anagraphe targets check` reports it as `unreadable-record`.

## 2. Rules

Every result has the level `error`. Its resource is `id:<identifier>` when the schema of the record declares its identifier by `x-identifier` and the record holds a string there, and `path:<path>` otherwise.

| `ruleId` | Case | Locus | Discriminator |
| --- | --- | --- | --- |
| `binding/malformed` | the binding key holds no contract identifier of Kleisis | the pointer of the binding key | the value held |
| `binding/unregistered` | the binding key names a contract absent from the schema registry | the pointer of the binding key | the contract |
| `record/invalid` | the record breaks the schema of its contract | the pointer of the offending node | the keyword of JSON Schema that fails |

The locus of a `record/invalid` result follows the profile:

- the pointer writes a keyed token for each entry of a list whose schema declares `x-entry-key` ([profile, section 4.5](profile.md#45-logical-location-resource-and-locus));
- a missing required property has the pointer of the missing property as locus, and the region of its closest existing ancestor ([profile, section 4.4](profile.md#44-physical-location));
- each property excluded by `additionalProperties: false` gives one result, at the pointer of that property;
- any other failure gives one result, at the pointer of the node at which the validator reports the failure.

The patterns of a schema follow ECMA-262, as JSON Schema states: `$` matches only at the end of the string, also in Python.

Once the registry of the consumer holds the contract, the check also covers a record naming a contract of another tool, such as the configuration of that tool. The consumer then declares that tool as a dependency in its configuration of Kleisis, and selects the contract. Without that declaration, the record yields `binding/unregistered`.

## 3. Command

```sh
elenchos validate
elenchos validate --format sarif --output build/elenchos/records.sarif
elenchos validate notes/ specs/model.yml
```

The root comes from `--root`, from the environment variable `ELENCHOS_ROOT`, or from the search of the gate configuration ([gate configuration](configuration.md)). Paths given after the options restrict the report to the records below them. The option `--format` takes `text`, the default, or `sarif`; the option `--output` names the file of the report. Without `--output`, the report goes to standard output.

The exit status is 0 when no record breaks its schema, 1 when a record does, and 2 when the check cannot run. The check cannot run in four cases:

- the configuration of Anagraphe is invalid;
- the configuration lacks the section `targets`, or the schema registry in it;
- the registry, a schema or a resource cannot be read;
- a schema is invalid.

With `--format sarif`, the log then holds a failed run, whose notification states the reason, and no results.

A consumer declares the check in its gate configuration:

```toml
[checks.records]
command = ["elenchos", "validate", "--format", "sarif", "--output", "{log}"]
scope = "paths"
```

## 4. Installation

The check needs the extra `validate`: `pip install "elenchos[validate]"`. The extra installs `anagraphe-read`, Kleisis and PyYAML. The gate and the module `elenchos.profile` need none of these packages. The extra installs through pip only, since no conda channel serves `anagraphe-read`.

## 5. Open points

- The frontmatter of a note names no contract. Its validation against the metadata schema of the consumer, named by `indexes.metadata_schema` in the configuration of Anagraphe, is not yet part of the check.
