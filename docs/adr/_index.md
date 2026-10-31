---
tags:
  - index
index: "[Elenchos documentation](docs/_index.md)"
aliases:
  - Architecture decisions
---
# Architecture decisions

Records the decisions that later work on `elenchos` must respect, so that a reader can judge whether a changed constraint reopens one of them.

## Findings

- [Findings profile](findings-profile.md): decides how SARIF carries the components of a finding identity, how they join into one string, and how baselines enter a log

## Gate

- [Runner and suppressions](runner-and-suppressions.md): decides how a consumer declares the inputs of the gate, and how the runner reaches its verdict
