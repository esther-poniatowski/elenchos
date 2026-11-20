# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The schema of a producer log, `findings-profile.schema.json`, published under its absolute `$id`
  and listed as a resource of the registry of Elenchos. The schema holds every rule of sections 3
  and 4 of the profile expressible in JSON Schema.
- The module `elenchos.profile`, the Python interface of the profile:
  - `violations` checks a log against the schema and the four rules relating two members of a log;
  - `identities` returns the identities written by the gate;
  - `resolve_locus` and `entry_keys` read and write loci.
- The TypeScript package `@elenchos/profile`, in `packages/profile`, which checks a log, splits
  location names and resolves loci. A release attaches its tarball.
- The keyed entry of a list in the locus of a finding: the schema of a list declares the key of its
  entries by `x-entry-key`, and the pointer writes the entry as `<property>=<value>`. Version 1 of
  the profile takes it in place, since every valid log stays valid and every identity unchanged.
- The vectors `nonconforming.json` and `loci.json`, and the vector `keyed-entry` of the identity
  vectors. The identity and rejected vectors list the rules of their drivers, so that each vector
  breaks exactly one rule.
- The command `elenchos validate` validates each record against the schema named by its binding,
  and writes its findings under the driver `elenchos-validate`. The command reads the records
  through `anagraphe-read` and the registry through Kleisis, both in the new extra `validate`.
- The configuration of Kleisis, `config/kleisis.yml`, and its registry `specs/schema-registry.yml`.
  The registry exports `elenchos:configuration@3` and `elenchos:suppressions@1`, and declares the
  keyword `x-entry-key`.

- The placeholder `{log}` in the command of a check: before running the command, Elenchos replaces
  it, in each argument, by the absolute path of the log of the check. A command names its log once,
  instead of repeating the path of `log`.

### Fixed

- A scoped run no longer reports as stale the entry of a scoped check outside its scope when the
  same tool also runs on the whole root. An unmatched entry is judged by the runs whose driver
  lists its rule, and by every run of its tool only when none lists it.

### Changed

- **Breaking:** Elenchos requires Hodegos at commit `a151a28`. Therefore, Elenchos searches
  `config/elenchos.toml`, and no longer searches a folder that a file `hodegos.yml` lists. A file
  `hodegos.yml` left at the root is ignored, so an invalid one no longer stops `check`, `update`
  or `validate`. A root that holds both `config/elenchos.toml` and another place of the file stops
  the command with status 2.
- **Breaking:** The extra `validate` pins Kleisis at `b098f5e` and `anagraphe-read` 0.5.0 at
  `107a80b`, which share Hodegos `a151a28`. The command `validate` reads `anagraphe.yml` at the
  root, in `.config/` or in `config/`, and no longer in `config/tools/`. The extra installs
  Merismos, which `anagraphe-read` requires.
- **Breaking:** Hodegos resolves the root of a command and locates `elenchos.toml`, as its
  [specification](https://github.com/esther-poniatowski/hodegos/blob/main/docs/specification.md)
  states. The file lies at the root, in its subfolder `.config/`, or in its subfolder `config/`.
  Elenchos no longer reads `config/tools/elenchos.toml`: the option `--config` names a file kept in
  that folder or in any other folder. `discover_root` and `discover_configuration` replace
  `find_root` and `locate_configuration`, and the constants `SETTINGS_PLACES` and `ROOT_VARIABLE`
  are removed. The distribution requires `hodegos`. The command `validate` stops with status 2 when
  two places of the root hold `elenchos.toml`.
- The schemas move from `specs/schemas/` to `src/elenchos/schemas/`, so that the Python package
  ships them; their `$id`s are unchanged.
- The distribution requires `jsonschema` and `referencing`.

- The key `output` and the key `log` of each check are optional. The merged log goes by default to
  `build/elenchos/gate.sarif`, and the log of a check to `build/elenchos/<name>.sarif`, below the
  root. A check that declares no `log` and holds no placeholder is read at the default place; when
  its command writes no log there, it fails with `check/missing-log`, and the message names the
  placeholder. The defaults obey the rule of unique logs, so a check named `gate` without `log`
  conflicts with the default output. A configuration that declares both keys is read as before,
  unless an argument of a command holds the text `{log}`, which is now replaced; no configuration
  of the workspace holds it, and the format stays `elenchos:configuration@3`, unreleased.

- The configuration file is found without `--config`: Elenchos reads `elenchos.toml` at the one
  place of the root that holds it, and stops with exit status 2 when two places hold it or none
  does.
  `-c`, `--config` remains to name another file; an absent named file exits 2.
- The root comes from the new option `-r`, `--root`, then from the environment variable
  `ELENCHOS_ROOT`, then from the nearest folder, from the current one upwards, that holds the
  configuration file at one of its places, then from the current folder.
- The configuration format is version 3. Every path of the file resolves against the root, never
  against the folder of the file. Versions 1 and 2 are no longer read.
- The configuration file and the suppressions file declare their format as their first key:
  `_schema = "elenchos:configuration@3"` and `"_schema": "elenchos:suppressions@1"`. The key
  replaces `version`, without an alias. A file with an absent or another identifier stops with
  status 2 and a message that names the expected value. A file that still carries `version`
  receives the value to write; the suppressions file holds justifications written by a person, so
  it is rewritten by hand. `elenchos update` writes `_schema`.

### Removed

- The key `root` of the configuration file, replaced by the option `--root` and the variable
  `ELENCHOS_ROOT`.
- The option `elenchos update --check NAME`, replaced by `--only NAME`, since `--check` is reserved
  for a run that writes nothing.
