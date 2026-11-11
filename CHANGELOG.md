# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The placeholder `{log}` in the command of a check: before running the command, Elenchos replaces
  it, in each argument, by the absolute path of the log of the check. A command names its log once,
  instead of repeating the path of `log`.

### Changed

- The key `output` and the key `log` of each check are optional. The merged log goes by default to
  `build/elenchos/gate.sarif`, and the log of a check to `build/elenchos/<name>.sarif`, below the
  root. A check that declares no `log` and holds no placeholder is read at the default place; when
  its command writes no log there, it fails with `check/missing-log`, and the message names the
  placeholder. The defaults obey the rule of unique logs, so a check named `gate` without `log`
  conflicts with the default output. A configuration that declares both keys is read as before,
  unless an argument of a command holds the text `{log}`, which is now replaced; no configuration
  of the workspace holds it, and the format stays `elenchos:configuration@3`, unreleased.

- The configuration file is found without `--config`: Elenchos reads `config/tools/elenchos.toml`
  or `elenchos.toml` below the root, and stops with exit status 2 when both exist or neither does.
  `-c`, `--config` remains to name another file; an absent named file exits 2.
- The root comes from the new option `-r`, `--root`, then from the environment variable
  `ELENCHOS_ROOT`, then from the nearest ancestor of the current folder that holds the
  configuration file, then from the current folder.
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
