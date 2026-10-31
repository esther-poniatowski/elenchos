# elenchos

[![Maintenance](https://img.shields.io/maintenance/yes/2026)]()
[![Python](https://img.shields.io/badge/python-%E2%89%A53.12-blue)](https://www.python.org/)
[![License: GPL](https://img.shields.io/badge/License-GPL--3.0-yellow.svg)](https://opensource.org/licenses/GPL-3.0)

Gates a repository on the findings of its checks: a profile of SARIF 2.1.0, stable finding identities and baselines.

---

## Overview

A repository runs checks from several tools, and each tool reports its findings in a format of its own. `elenchos` fixes one profile of SARIF 2.1.0 that every producer of findings writes. It gives each finding an identity that survives textual edits, and it decides from the configuration of the consumer which findings block a commit.

### Motivation

Two limitations are observed when each checker reports and tolerates findings on its own terms:

- a baseline keyed by a message or a line number breaks on the next edit, and a baseline keyed by a rule alone merges distinct findings;
- the findings of several tools cannot be merged, compared or suppressed by one mechanism.

`elenchos` answers both: its profile states the fields of a finding, and its identity names each finding by its tool, rule, resource and semantic locus.

### Status

Pre-alpha. The package provides the identity builder of the profile: it builds the canonical identity of a finding from its components, numbers identical occurrences, parses an identity back, and writes the identity on SARIF results held as plain dictionaries. The runner of the checks and the baselines come later.

---

## Documentation

The [documentation index](docs/_index.md) is the entry point.

---

## Contributing

Contributions follow the [contribution guidelines](CONTRIBUTING.md).

---

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
