"""
The check `elenchos validate`: each record against the schema that its binding names.

A record names its contract under the binding key of the consumer, `_schema` by default. The check
reads the records of the consumer, their binding key and the place of their schema registry through
`anagraphe-read`, and reads the registry through the public reader of Kleisis. It then validates
each bound record against the schema of its contract, and writes a findings log in the profile of
Elenchos, under the driver `elenchos-validate`. The specification is `docs/validation.md`.

Functions
---------
validate_repository(root, scope=None) -> Outcome
    Validate every bound record of the repository at `root`.
sarif_log(outcome) -> dict
    Write the findings log of a validation.
text_lines(outcome) -> list[str]
    Write the text report of a validation.

Classes
-------
Finding
    One record, or one node of a record, that breaks the rule of the check.
Outcome
    The findings of a validation, or the reason that stopped it.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import yaml  # type: ignore[import-untyped]
from anagraphe_read import ConfigurationError as AnagrapheConfigurationError
from anagraphe_read import RecordFile, open_repository
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from kleisis.contracts import is_contract_identifier
from kleisis.registry import RegistryError, read_registry
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from . import __version__
from .ecma import ecma_pattern, python_schema
from .errors import ConfigurationError
from .profile import EntryKeys, keyed_validation, pointer
from .runner import SARIF_SCHEMA
from .sarif import DISCRIMINATOR_KEY, location_name

TOOL = "elenchos-validate"
"""Driver name of the log of the check; `elenchos` names the run of the gate alone."""

MALFORMED = "binding/malformed"
UNREGISTERED = "binding/unregistered"
INVALID = "record/invalid"

RULES: dict[str, str] = {
    MALFORMED: "The binding key of a record holds no contract identifier.",
    UNREGISTERED: "The binding key of a record names a contract absent from the schema registry.",
    INVALID: "A record breaks the schema of the contract that its binding names.",
}
"""Each rule of the check, with its description; every finding has the level `error`."""

_PROPERTY_KEYWORDS = ("additionalProperties",)
"""Keywords whose failure is reported at each offending property, rather than at its object."""


@dataclass(frozen=True)
class Finding:
    """
    One record, or one node of a record, that breaks the rule of the check.

    Attributes
    ----------
    rule : str
        The rule broken, a key of `RULES`.
    path : str
        The path of the file of the record, relative to the root.
    resource : str
        The resource of the finding, `id:<identifier>` or `path:<path>`.
    locus : str
        The JSON Pointer of the node, with keyed tokens; empty for the whole record.
    discriminator : str
        The keyword of JSON Schema that fails, or the offending binding value.
    message : str
        The explanation.
    position : tuple[int, int] | None
        The line and the column where the node is written, or None for the whole file.
    """

    rule: str
    path: str
    resource: str
    locus: str
    discriminator: str
    message: str
    position: tuple[int, int] | None = None


@dataclass
class Outcome:
    """
    The findings of a validation, or the reason that stopped it.

    Attributes
    ----------
    findings : list[Finding]
        The findings, in the order of the walk of the records.
    stopped : str | None
        Why the validation could not run, None when it ran to completion.
    """

    findings: list[Finding] = field(default_factory=list)
    stopped: str | None = None


def _load(path: Path) -> Any:
    """Read a JSON or YAML file; raise `ConfigurationError` when it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
        raise ConfigurationError(f"{path}: the schema cannot be read: {error}") from error


@dataclass
class _Schemas:
    """The schemas of a registry, each read once, and the resources of their closure."""

    root: Path
    contracts: Mapping[str, PurePosixPath]
    registry: Registry = field(default_factory=Registry)
    loaded: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def read(cls, root: Path, registry_path: Path) -> "_Schemas":
        """Read the registry at `registry_path` and the resources that it lists."""
        try:
            registry = read_registry(registry_path)
        except RegistryError as error:
            raise ConfigurationError(f"{registry_path}: {error}") from error
        resources = [
            (
                identifier,
                Resource.from_contents(
                    python_schema(_load(root / rel)), default_specification=DRAFT202012
                ),
            )
            for identifier, rel in registry.resources.items()
        ]
        return cls(root, registry.schemas, Registry().with_resources(resources))

    def schema(self, contract: str) -> Any:
        """Return the schema of a registered contract, its patterns rewritten for Python."""
        if contract not in self.loaded:
            self.loaded[contract] = python_schema(_load(self.root / self.contracts[contract]))
        return self.loaded[contract]


def _resource(record: RecordFile) -> str:
    """Return the resource of a record: its declared identifier, else its path."""
    return f"id:{record.identifier}" if record.identifier else f"path:{record.path}"


def _in_scope(path: str, scope: Sequence[str] | None) -> bool:
    """Whether a repository-relative path lies in a scope of files or folders."""
    if scope is None:
        return True
    return any(
        item in (".", "") or path == item or path.startswith(item.rstrip("/") + "/")
        for item in scope
    )


def _record_findings(record: RecordFile, binding: str, schemas: _Schemas) -> list[Finding]:
    """Return the findings of one record whose binding key holds a value."""
    value = record.data.get(binding)
    resource = _resource(record)
    place = record.position([binding])
    if not is_contract_identifier(value):
        return [
            Finding(
                MALFORMED,
                record.path,
                resource,
                pointer([binding]),
                str(value),
                f"{binding} holds {value!r}, which is no contract identifier",
                place,
            )
        ]
    if value not in schemas.contracts:
        return [
            Finding(
                UNREGISTERED,
                record.path,
                resource,
                pointer([binding]),
                str(value),
                f"{binding} names {value}, which the schema registry does not hold",
                place,
            )
        ]
    contract = str(value)
    try:
        keys, errors = keyed_validation(
            dict(record.data), schemas.schema(contract), schemas.registry
        )
    except SchemaError as error:
        raise ConfigurationError(f"the schema of {contract} is invalid: {error.message}") from error
    return [
        finding for error in errors for finding in _error_findings(record, resource, keys, error)
    ]


def _error_findings(
    record: RecordFile, resource: str, keys: EntryKeys, error: Any
) -> list[Finding]:
    """Return the findings of one error of the validator, one per offending property when the
    error names several."""
    path = list(error.absolute_path)
    keyword = str(error.validator)
    instance = error.instance
    if keyword == "required" and isinstance(instance, Mapping):
        # The validator reports each missing property in its own error, whose message opens on
        # the repr of the property.
        missing = [name for name in error.validator_value if name not in instance]
        name = next((name for name in missing if error.message.startswith(repr(name))), None)
        if name is not None:
            return [
                Finding(
                    INVALID,
                    record.path,
                    resource,
                    keys.locus([*path, name]),
                    keyword,
                    f"{name!r} is a required property",
                    record.position(path),
                )
            ]
    if keyword in _PROPERTY_KEYWORDS and error.validator_value is False:
        extras = _additional(instance, error.schema)
        if extras:
            return [
                Finding(
                    INVALID,
                    record.path,
                    resource,
                    keys.locus([*path, name]),
                    keyword,
                    f"{name!r} is not a property of the schema",
                    record.position([*path, name]),
                )
                for name in extras
            ]
    message = str(error.message)
    if keyword == "pattern" and isinstance(error.validator_value, str):
        message = f"{instance!r} does not match {ecma_pattern(error.validator_value)!r}"
    return [
        Finding(
            INVALID,
            record.path,
            resource,
            keys.locus(path),
            keyword,
            message,
            record.position(path),
        )
    ]


def _additional(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    """Return the properties of an object that neither `properties` nor `patternProperties`
    declare, in the order of the object."""
    if not isinstance(instance, Mapping):
        return []
    declared = schema.get("properties", {})
    patterns = list(schema.get("patternProperties", {}))
    return [
        name
        for name in instance
        if name not in declared and not any(re.search(pattern, name) for pattern in patterns)
    ]


def validate_repository(root: Path, scope: Sequence[str] | None = None) -> Outcome:
    """
    Validate every bound record of the repository at `root`.

    Parameters
    ----------
    root : Path
        The root of the consumer.
    scope : Sequence[str], optional
        Repository-relative files or folders; only the records below them are reported.

    Returns
    -------
    Outcome
        The findings, or the reason that stopped the validation: an invalid configuration of
        Anagraphe, a configuration without schema registry, an unreadable registry or schema, or
        an invalid schema.
    """
    try:
        repository = open_repository(root)
        registry_path = repository.schema_registry
        if registry_path is None:
            raise ConfigurationError(
                "the configuration of Anagraphe declares no schema registry under targets.records"
            )
        records = repository.records()
        schemas = _Schemas.read(repository.root, registry_path)
        findings: list[Finding] = []
        for record in records:
            if record.problem is not None or not _in_scope(record.path, scope):
                continue
            if record.data.get(repository.binding) is None:
                continue
            findings += _record_findings(record, repository.binding, schemas)
    except (AnagrapheConfigurationError, ConfigurationError) as error:
        return Outcome(stopped=str(error))
    return Outcome(findings)


def _result(finding: Finding) -> dict[str, Any]:
    """Write one finding as a SARIF result of the profile."""
    physical: dict[str, Any] = {
        "artifactLocation": {"uri": quote(finding.path), "uriBaseId": "SRCROOT"}
    }
    if finding.position is not None:
        physical["region"] = {"startLine": finding.position[0], "startColumn": finding.position[1]}
    result: dict[str, Any] = {
        "ruleId": finding.rule,
        "level": "error",
        "message": {"text": finding.message},
        "locations": [
            {
                "physicalLocation": physical,
                "logicalLocations": [{"name": location_name(finding.resource, finding.locus)}],
            }
        ],
    }
    if finding.discriminator:
        result["partialFingerprints"] = {DISCRIMINATOR_KEY: finding.discriminator}
    return result


def sarif_log(outcome: Outcome) -> dict[str, Any]:
    """
    Write the findings log of a validation, in the profile of Elenchos.

    A stopped validation writes a failed run, whose notification of level `error` states why, and
    no results.

    Parameters
    ----------
    outcome : Outcome
        The outcome of `validate_repository`.

    Returns
    -------
    dict[str, Any]
        A SARIF 2.1.0 log of one run, of driver `elenchos-validate`.
    """
    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": TOOL,
                "version": __version__,
                "isComprehensive": True,
                "rules": [
                    {
                        "id": rule,
                        "shortDescription": {"text": description},
                        "defaultConfiguration": {"level": "error"},
                    }
                    for rule, description in RULES.items()
                ],
            }
        },
        "columnKind": "unicodeCodePoints",
    }
    if outcome.stopped is not None:
        run["invocations"] = [
            {
                "executionSuccessful": False,
                "toolExecutionNotifications": [
                    {"level": "error", "message": {"text": outcome.stopped}}
                ],
            }
        ]
    else:
        run["results"] = [_result(finding) for finding in outcome.findings]
    return {"version": "2.1.0", "$schema": SARIF_SCHEMA, "runs": [run]}


def text_lines(outcome: Outcome) -> list[str]:
    """
    Write the text report of a validation: one line per finding, then a summary.

    Examples
    --------
    >>> finding = Finding(
    ...     INVALID, "a.yml", "path:a.yml", "/title", "type", "1 is not a string", (2, 8)
    ... )
    >>> text_lines(Outcome([finding]))
    ['a.yml:2:8: record/invalid: /title: 1 is not a string', '1 findings']
    """
    if outcome.stopped is not None:
        return [f"elenchos validate: {outcome.stopped}"]
    lines = []
    for finding in outcome.findings:
        place = f":{finding.position[0]}:{finding.position[1]}" if finding.position else ""
        where = f" {finding.locus}:" if finding.locus else ""
        lines.append(f"{finding.path}{place}: {finding.rule}:{where} {finding.message}")
    lines.append(f"{len(outcome.findings)} findings")
    return lines
