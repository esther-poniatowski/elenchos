# elenchos

[![Maintenance](https://img.shields.io/maintenance/yes/2026)]()
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)](https://www.python.org/)
[![License: GPL](https://img.shields.io/badge/License-GPL--3.0-yellow.svg)](https://opensource.org/licenses/GPL-3.0)

Gates a repository on the findings of its checks: a profile of SARIF 2.1.0, stable finding identities and baselines.

---

## Overview

A repository runs checks from several tools, and each tool reports its findings in a format of its own. `elenchos` fixes one profile of SARIF 2.1.0 that every producer of findings writes. It gives each finding an identity that survives textual edits, runs the checks that the consumer declares, and decides from the configuration of the consumer which findings block a commit.

### Motivation

Two limitations are observed when each checker reports and tolerates findings on its own terms:

- a baseline keyed by a message or a line number breaks on the next edit, and a baseline keyed by a rule alone merges distinct findings;
- the findings of several tools cannot be merged, compared or suppressed by one mechanism.

`elenchos` answers both: its profile states the fields of a finding, and its identity names each finding by its tool, rule, resource and semantic locus.

### Status

Pre-alpha. The package provides the identity builder of the profile and the runner of the gate. The identity builder builds the canonical identity of a finding from its components, numbers identical occurrences, and parses an identity back. The runner executes the checks declared by a consumer, merges their logs into one SARIF log, applies the suppressions of the consumer, and exits non-zero on an unsuppressed blocking result. No command yet converts the legacy count baselines into suppressions.

### Usage

A consumer declares its checks, its severity policy and its suppressions file in one TOML configuration, and passes its path:

```sh
elenchos check --config config/elenchos.toml
```

The exit status is 0 when no result blocks, 1 when an unsuppressed result blocks, and 2 when an input is invalid. The [gate configuration](docs/configuration.md) specifies both files and the behaviour of the runner.

---

## Documentation

The [documentation index](docs/_index.md) is the entry point.

---

## Contributing

Contributions follow the [contribution guidelines](CONTRIBUTING.md).

---

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
