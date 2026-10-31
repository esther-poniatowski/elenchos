---
tags:
  - index
aliases:
  - Elenchos documentation
---
# Elenchos documentation

Orients a reader toward the specification, the decisions and the migration plan of the quality gate of a repository.

- [Findings profile](profile.md): specifies what a producer of findings writes in SARIF and how the gate identifies each finding
- [Gate configuration](configuration.md): specifies what a consumer declares to the gate, and how `elenchos check` reaches its verdict
- [Producer and baseline migration](producer-migration.md): maps the current output of each producer and each current baseline entry onto the profile
- [Architecture decisions](adr/_index.md): records the decisions that later work on `elenchos` must respect
