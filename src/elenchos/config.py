"""
Configuration of a consumer: its checks, its severity policy and its suppressions file.

The consumer declares every input of the gate in one TOML file, `elenchos.toml`, read from
`config/tools/elenchos.toml` or `elenchos.toml` below the root of the consumer, or from the path
given by `--config`. The root is given by `--root`, by the environment variable `ELENCHOS_ROOT`, or
found as the nearest ancestor of the current folder that holds the file; every path written in the
file resolves against it. The format is published as the JSON Schema
`specs/schemas/configuration.schema.json`, and specified in `docs/configuration.md`.

Classes
-------
Check
    One declared check: the command that writes one SARIF log, and where the log is read.
Renames
    The declared maps of rules and of resources, applied to stored suppressions.
Policy
    The levels that block, by default and for each rule.
Configuration
    The validated configuration of a consumer, with every path resolved.

Functions
---------
find_root(start) -> Path
    Return the nearest ancestor of a folder that holds a configuration file, or the folder itself.
locate_configuration(root, config) -> Path
    Return the configuration file named on the command line, or the one found below the root.
load_configuration(path, root) -> Configuration
    Read and validate the configuration file of a consumer.
parse_configuration(data, path, root) -> Configuration
    Validate the parsed content of a configuration file.

Examples
--------
>>> from pathlib import Path
>>> configuration = parse_configuration(
...     {
...         "version": 3,
...         "output": "gate.sarif",
...         "policy": {"block": ["error"], "rules": {"geonexus|links/broken": ["warning"]}},
...         "checks": {"links": {"command": ["check-links"], "log": "links.sarif"}},
...     },
...     Path("/repo/elenchos.toml"),
...     Path("/repo"),
... )
>>> [check.name for check in configuration.checks]
['links']
>>> sorted(configuration.policy.blocking_levels("geonexus", "links/broken", configuration.checks[0]))
['warning']
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from .errors import ConfigurationError, ProfileError
from .identity import RULE_PATTERN, TOOL_PATTERN, check_resource
from .sarif import LEVELS

FORMAT_VERSION = 3
"""Version of the configuration format read by this release.

Version 3 retires the key `root`: the root comes from the command line, and every path of the file
resolves against it. Versions 1 and 2, whose paths resolved against the folder of the file, are no
longer read.
"""

SETTINGS_NAME = "elenchos.toml"
"""Name of the configuration file, below the root or in its folder `config/tools/`."""

SETTINGS_PLACES = (Path("config") / "tools" / SETTINGS_NAME, Path(SETTINGS_NAME))
"""Places of the configuration file relative to the root, searched without `--config`."""

ROOT_VARIABLE = "ELENCHOS_ROOT"
"""Environment variable naming the root when `--root` is absent."""

SCOPES = ("root", "paths")
"""Values of the `scope` of a check: it always checks the whole root, or it accepts paths."""

CHECK_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
"""Form of the name of a check; it excludes `/` and `~`, so that it is a JSON Pointer token."""

DEFAULT_EXIT_CODES = frozenset({0, 1})
"""Exit statuses meaning that a command ran to completion: 0 without findings, 1 with findings."""

_TOP_KEYS = frozenset({"version", "output", "suppressions", "policy", "checks", "renames"})
_POLICY_KEYS = frozenset({"block", "rules"})
_CHECK_KEYS = frozenset({"command", "log", "exit_codes", "block", "scope"})
_RENAMES_KEYS = frozenset({"rules", "resources"})


@dataclass(frozen=True)
class Check:
    """
    One declared check: the command that writes one SARIF log, and where the log is read.

    Attributes
    ----------
    name : str
        Name of the check, unique in the configuration.
    command : tuple[str, ...]
        Argument vector of the command, run without a shell in the root of the consumer.
    log : Path
        Absolute path of the SARIF log written by the command.
    exit_codes : frozenset[int]
        Exit statuses meaning that the command ran to completion.
    block : frozenset[str] | None
        Levels that block for the results of this check, or None to apply the default of the
        policy.
    scope : str, default "root"
        `root` when the command always checks the whole root; `paths` when it accepts paths
        appended to its argument vector, so that a scoped run checks only those paths.
    """

    name: str
    command: tuple[str, ...]
    log: Path
    exit_codes: frozenset[int] = DEFAULT_EXIT_CODES
    block: frozenset[str] | None = None
    scope: str = "root"


@dataclass(frozen=True)
class Renames:
    """
    The declared maps of rules and of resources, applied to stored suppressions.

    Attributes
    ----------
    rules : Mapping[str, str]
        New `tool|ruleId` of each renamed or moved rule, keyed by its former `tool|ruleId`.
    resources : Mapping[str, str]
        New resource of each moved or newly identified resource, keyed by its former resource.
    """

    rules: Mapping[str, str] = field(default_factory=dict)
    resources: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Policy:
    """
    The levels that block, by default and for each rule.

    Attributes
    ----------
    block : frozenset[str]
        Levels that block when neither the rule nor the check declares its own.
    rules : Mapping[str, frozenset[str]]
        Levels that block for one rule, keyed by `tool|ruleId`.
    """

    block: frozenset[str]
    rules: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def blocking_levels(self, tool: str, rule_id: str, check: Check | None) -> frozenset[str]:
        """
        Return the levels that block for one rule, the most specific declaration winning.

        Parameters
        ----------
        tool : str
            Name of the driver of the run holding the result.
        rule_id : str
            `ruleId` of the result.
        check : Check | None
            Check whose log holds the result, or None for a result of the gate itself.

        Returns
        -------
        frozenset[str]
            The levels of the rule declaration when one exists, otherwise those of the check
            when it declares some, otherwise the default of the policy.
        """
        rule = self.rules.get(f"{tool}|{rule_id}")
        if rule is not None:
            return rule
        if check is not None and check.block is not None:
            return check.block
        return self.block


@dataclass(frozen=True)
class Configuration:
    """
    The validated configuration of a consumer, with every path resolved.

    Attributes
    ----------
    path : Path
        Absolute path of the configuration file.
    root : Path
        Absolute path of the root of the consumer, against which relative paths resolve and in
        which the commands run.
    output : Path
        Absolute path where the merged log is written.
    suppressions : Path | None
        Absolute path of the suppressions file, or None when the consumer declares none.
    policy : Policy
        Levels that block.
    checks : tuple[Check, ...]
        Declared checks, in the order of the file.
    renames : Renames
        Maps of rules and of resources applied to stored suppressions; empty when undeclared.
    """

    path: Path
    root: Path
    output: Path
    suppressions: Path | None
    policy: Policy
    checks: tuple[Check, ...]
    renames: Renames = field(default_factory=Renames)

    def relative(self, path: Path) -> str:
        """
        Return a path under the root as a repository-relative POSIX path.

        Examples
        --------
        >>> configuration = Configuration(
        ...     Path("/r/c.toml"), Path("/r"), Path("/r/o"), None, Policy(frozenset()), ()
        ... )
        >>> configuration.relative(Path("/r/config/tools/elenchos.toml"))
        'config/tools/elenchos.toml'
        """
        return path.relative_to(self.root).as_posix()


def _fail(path: Path, location: str, problem: str) -> ConfigurationError:
    """Build the error naming the file, the key and the problem."""
    return ConfigurationError(f"{path}: {location}: {problem}")


def _table(value: Any, path: Path, location: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    """Return a table after checking that it holds only the allowed keys."""
    if not isinstance(value, Mapping):
        raise _fail(path, location, "is not a table")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _fail(path, location, f"holds unknown keys {unknown}")
    return value


def _text(value: Any, path: Path, location: str) -> str:
    """Return a non-empty string, or raise."""
    if not isinstance(value, str) or not value:
        raise _fail(path, location, "is not a non-empty string")
    return value


def _levels(value: Any, path: Path, location: str) -> frozenset[str]:
    """Return a list of distinct levels as a set, or raise."""
    if not isinstance(value, list) or any(level not in LEVELS for level in value):
        raise _fail(path, location, f"is not a list of levels among {list(LEVELS)}")
    if len(set(value)) != len(value):
        raise _fail(path, location, "repeats a level")
    return frozenset(value)


def _exit_codes(value: Any, path: Path, location: str) -> frozenset[int]:
    """Return a non-empty list of distinct integers as a set, or raise."""
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(code, bool) or not isinstance(code, int) for code in value)
    ):
        raise _fail(path, location, "is not a non-empty list of integers")
    if len(set(value)) != len(value):
        raise _fail(path, location, "repeats an exit status")
    return frozenset(value)


def _rule_key(key: str, path: Path, location: str) -> str:
    """Return a rule key `tool|ruleId` after checking both components, or raise."""
    tool, separator, rule_id = key.partition("|")
    if not separator or not TOOL_PATTERN.fullmatch(tool) or not RULE_PATTERN.fullmatch(rule_id):
        raise _fail(path, location, f"key {key!r} is not `tool|ruleId`")
    return key


def _renames(value: Any, path: Path) -> Renames:
    """Validate the table `renames`: keys and values of rules are `tool|ruleId`, those of
    resources are resources of the profile, and no value is renamed again."""
    table = _table(value, path, "renames", _RENAMES_KEYS)
    rules_table = table.get("rules", {})
    rules = {
        _rule_key(key, path, "renames.rules"): _rule_key(
            _text(new, path, f"renames.rules.{key!r}"), path, f"renames.rules.{key!r}"
        )
        for key, new in _table(rules_table, path, "renames.rules", frozenset(rules_table)).items()
    }
    resources_table = table.get("resources", {})
    resources: dict[str, str] = {}
    for key, new in _table(
        resources_table, path, "renames.resources", frozenset(resources_table)
    ).items():
        location = f"renames.resources.{key!r}"
        try:
            check_resource(key)
            check_resource(_text(new, path, location))
        except ProfileError as error:
            raise _fail(path, location, str(error)) from error
        resources[key] = new
    for name, mapping in (("rules", rules), ("resources", resources)):
        chained = sorted(set(mapping) & set(mapping.values()))
        if chained:
            raise _fail(
                path, f"renames.{name}", f"renames {chained} again; map the first form to the last"
            )
    return Renames(rules, resources)


def _policy(value: Any, path: Path) -> Policy:
    """Validate the table `policy`."""
    table = _table(value, path, "policy", _POLICY_KEYS)
    if "block" not in table:
        raise _fail(path, "policy", "declares no `block`")
    rules = _table(table.get("rules", {}), path, "policy.rules", frozenset(table.get("rules", {})))
    return Policy(
        _levels(table["block"], path, "policy.block"),
        {
            _rule_key(key, path, "policy.rules"): _levels(levels, path, f"policy.rules.{key!r}")
            for key, levels in rules.items()
        },
    )


def _check(name: str, value: Any, path: Path, root: Path) -> Check:
    """Validate one table of `checks`."""
    location = f"checks.{name}"
    if not CHECK_NAME_PATTERN.fullmatch(name):
        raise _fail(path, location, f"name does not match {CHECK_NAME_PATTERN.pattern}")
    table = _table(value, path, location, _CHECK_KEYS)
    for key in ("command", "log"):
        if key not in table:
            raise _fail(path, location, f"declares no `{key}`")
    command = table["command"]
    if not isinstance(command, list) or not command:
        raise _fail(path, f"{location}.command", "is not a non-empty list of strings")
    arguments = tuple(_text(item, path, f"{location}.command") for item in command)
    block = table.get("block")
    scope = table.get("scope", "root")
    if scope not in SCOPES:
        raise _fail(path, f"{location}.scope", f"is not one of {list(SCOPES)}")
    return Check(
        name,
        arguments,
        (root / _text(table["log"], path, f"{location}.log")).resolve(),
        _exit_codes(table.get("exit_codes", [0, 1]), path, f"{location}.exit_codes"),
        None if block is None else _levels(block, path, f"{location}.block"),
        scope,
    )


def parse_configuration(data: Mapping[str, Any], path: Path, root: Path) -> Configuration:
    """
    Validate the parsed content of a configuration file.

    Parameters
    ----------
    data : Mapping[str, Any]
        Content of the file, as returned by `tomllib`.
    path : Path
        Path of the file.
    root : Path
        Root of the consumer; relative paths of the file resolve against it.

    Returns
    -------
    Configuration
        The validated configuration.

    Raises
    ------
    ConfigurationError
        If a key is unknown or missing, the version is not the one read by this release, a value
        breaks its form, two checks share a log, the output coincides with a log, the
        configuration or suppressions file lies outside the root, or a rename map renames a value
        again.
    """
    path = path.resolve()
    root = root.resolve()
    version = data.get("version") if isinstance(data, Mapping) else None
    if isinstance(version, bool) or version != FORMAT_VERSION:
        raise _fail(
            path,
            "version",
            f"is not {FORMAT_VERSION}; version 3 retires the key `root`, and resolves every path "
            "against the root",
        )
    table = _table(data, path, "top level", _TOP_KEYS)
    for key in ("output", "policy", "checks"):
        if key not in table:
            raise _fail(path, "top level", f"declares no `{key}`")
    if not path.is_relative_to(root):
        raise _fail(path, "top level", f"the root {root} does not contain the configuration file")
    suppressions = None
    if "suppressions" in table:
        suppressions = (root / _text(table["suppressions"], path, "suppressions")).resolve()
        if not suppressions.is_relative_to(root):
            raise _fail(path, "suppressions", f"{suppressions} lies outside the root {root}")
    checks_table = _table(table["checks"], path, "checks", frozenset(table["checks"]))
    if not checks_table:
        raise _fail(path, "checks", "declares no check")
    checks = tuple(_check(name, value, path, root) for name, value in checks_table.items())
    output = (root / _text(table["output"], path, "output")).resolve()
    logs = [check.log for check in checks]
    if len(set(logs)) != len(logs):
        raise _fail(path, "checks", "two checks declare one log")
    if output in logs:
        raise _fail(path, "output", "coincides with the log of a check")
    renames = _renames(table["renames"], path) if "renames" in table else Renames()
    return Configuration(
        path, root, output, suppressions, _policy(table["policy"], path), checks, renames
    )


def find_root(start: Path) -> Path:
    """
    Return the nearest ancestor of a folder that holds a configuration file, or the folder itself.

    Parameters
    ----------
    start : Path
        Folder from which the search starts, normally the current folder.

    Returns
    -------
    Path
        The nearest folder, `start` included, holding `config/tools/elenchos.toml` or
        `elenchos.toml`; `start` itself when no ancestor holds one.

    Examples
    --------
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as folder:
    ...     root = Path(folder).resolve()
    ...     (root / "config" / "tools").mkdir(parents=True)
    ...     _ = (root / "config" / "tools" / "elenchos.toml").write_text("")
    ...     (root / "docs" / "notes").mkdir(parents=True)
    ...     find_root(root / "docs" / "notes") == root
    True
    """
    start = start.resolve()
    for folder in (start, *start.parents):
        if any((folder / place).is_file() for place in SETTINGS_PLACES):
            return folder
    return start


def locate_configuration(root: Path, config: Path | None) -> Path:
    """
    Return the configuration file named on the command line, or the one found below the root.

    Parameters
    ----------
    root : Path
        Root of the consumer.
    config : Path | None
        Path given by `--config`, relative to the current folder, or None.

    Returns
    -------
    Path
        The path given by `--config`, or the single existing place of `SETTINGS_PLACES`.

    Raises
    ------
    ConfigurationError
        If the file named by `--config` does not exist, if both places hold a file, or if neither
        does: the gate has no built-in checks to run without a configuration.
    """
    if config is not None:
        if not config.is_file():
            raise ConfigurationError(
                f"{config}: the configuration file named by --config does not exist"
            )
        return config
    found = [root / place for place in SETTINGS_PLACES if (root / place).is_file()]
    if len(found) > 1:
        raise ConfigurationError(
            f"two configuration files compete: {found[0]} and {found[1]}; keep one of them"
        )
    if not found:
        places = " or ".join(str(root / place) for place in SETTINGS_PLACES)
        raise ConfigurationError(f"no configuration file: expected {places}, or --config")
    return found[0]


def load_configuration(path: Path, root: Path) -> Configuration:
    """
    Read and validate the configuration file of a consumer.

    Parameters
    ----------
    path : Path
        Path of the TOML configuration file.
    root : Path
        Root of the consumer, against which the paths of the file resolve.

    Returns
    -------
    Configuration
        The validated configuration.

    Raises
    ------
    ConfigurationError
        If the file cannot be read, is not TOML, or breaks the format (see
        `parse_configuration`).
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"{path}: cannot be read as TOML: {error}") from error
    return parse_configuration(data, path, root)
