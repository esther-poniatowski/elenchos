"""
Configuration of a consumer: its checks, its severity policy and its suppressions file.

The consumer declares every input of the gate in one TOML file, whose path it passes on the command
line. Elenchos discovers nothing on disk and holds no path of a consumer. The format is published as
the JSON Schema `specs/schemas/configuration.schema.json`, and specified in
`docs/configuration.md`.

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
load_configuration(path) -> Configuration
    Read and validate the configuration file of a consumer.
parse_configuration(data, path) -> Configuration
    Validate the parsed content of a configuration file.

Examples
--------
>>> from pathlib import Path
>>> configuration = parse_configuration(
...     {
...         "version": 1,
...         "output": "gate.sarif",
...         "policy": {"block": ["error"], "rules": {"geonexus|links/broken": ["warning"]}},
...         "checks": {"links": {"command": ["check-links"], "log": "links.sarif"}},
...     },
...     Path("/repo/elenchos.toml"),
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

FORMAT_VERSION = 2
"""Latest version of the configuration format read by this release."""

FORMAT_VERSIONS = frozenset({1, 2})
"""Versions read by this release: version 2 adds `renames` and the `scope` of a check."""

SCOPES = ("root", "paths")
"""Values of the `scope` of a check: it always checks the whole root, or it accepts paths."""

CHECK_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
"""Form of the name of a check; it excludes `/` and `~`, so that it is a JSON Pointer token."""

DEFAULT_EXIT_CODES = frozenset({0, 1})
"""Exit statuses meaning that a command ran to completion: 0 without findings, 1 with findings."""

_TOP_KEYS = frozenset({"version", "root", "output", "suppressions", "policy", "checks"})
_TOP_KEYS_V2 = _TOP_KEYS | {"renames"}
_POLICY_KEYS = frozenset({"block", "rules"})
_CHECK_KEYS = frozenset({"command", "log", "exit_codes", "block"})
_CHECK_KEYS_V2 = _CHECK_KEYS | {"scope"}
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
        Maps of rules and of resources applied to stored suppressions; empty in version 1.
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
        >>> configuration.relative(Path("/r/config/elenchos.toml"))
        'config/elenchos.toml'
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
            raise _fail(path, f"renames.{name}", f"renames {chained} again; map the first form to the last")
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


def _check(name: str, value: Any, path: Path, root: Path, version: int) -> Check:
    """Validate one table of `checks`."""
    location = f"checks.{name}"
    if not CHECK_NAME_PATTERN.fullmatch(name):
        raise _fail(path, location, f"name does not match {CHECK_NAME_PATTERN.pattern}")
    table = _table(value, path, location, _CHECK_KEYS_V2 if version >= 2 else _CHECK_KEYS)
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


def parse_configuration(data: Mapping[str, Any], path: Path) -> Configuration:
    """
    Validate the parsed content of a configuration file.

    Parameters
    ----------
    data : Mapping[str, Any]
        Content of the file, as returned by `tomllib`.
    path : Path
        Path of the file; relative paths of the file resolve against its directory.

    Returns
    -------
    Configuration
        The validated configuration.

    Raises
    ------
    ConfigurationError
        If a key is unknown or missing, a key of version 2 appears in version 1, a value breaks
        its form, two checks share a log, the output coincides with a log, the configuration or
        suppressions file lies outside the root, or a rename map renames a value again.
    """
    path = path.resolve()
    version = data.get("version") if isinstance(data, Mapping) else None
    if isinstance(version, bool) or version not in FORMAT_VERSIONS:
        raise _fail(path, "version", f"is not one of {sorted(FORMAT_VERSIONS)}")
    table = _table(data, path, "top level", _TOP_KEYS_V2 if version >= 2 else _TOP_KEYS)
    for key in ("output", "policy", "checks"):
        if key not in table:
            raise _fail(path, "top level", f"declares no `{key}`")
    root = (path.parent / _text(table.get("root", "."), path, "root")).resolve()
    if not path.is_relative_to(root):
        raise _fail(path, "root", f"{root} does not contain the configuration file")
    suppressions = None
    if "suppressions" in table:
        suppressions = (root / _text(table["suppressions"], path, "suppressions")).resolve()
        if not suppressions.is_relative_to(root):
            raise _fail(path, "suppressions", f"{suppressions} lies outside the root {root}")
    checks_table = _table(table["checks"], path, "checks", frozenset(table["checks"]))
    if not checks_table:
        raise _fail(path, "checks", "declares no check")
    checks = tuple(
        _check(name, value, path, root, version) for name, value in checks_table.items()
    )
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


def load_configuration(path: Path) -> Configuration:
    """
    Read and validate the configuration file of a consumer.

    Parameters
    ----------
    path : Path
        Path of the TOML configuration file.

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
    return parse_configuration(data, path)
