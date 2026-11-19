"""
Public interface of the findings profile: the check of a producer log, its identities, and loci.

A producer of findings checks its log with this module, and copies no rule of the profile. The
schema of a producer log holds every rule of sections 3 and 4 of `docs/profile.md` that JSON Schema
expresses; `violations` adds the four rules that relate two members of a log. A reader of a log
resolves the locus of a finding against its document with `resolve_locus`, and a producer builds
the locus of a node with `entry_keys`, which reads the keys that a schema declares by
`x-entry-key`.

Functions
---------
profile_schema() -> dict
    Return the schema of a producer log.
violations(log) -> list[Violation]
    Return every rule of the profile that a producer log breaks.
identities(log) -> list[str]
    Return the identity of each result of a log, in the order of its runs and results.
pointer(path) -> str
    Write a positional path as a JSON Pointer.
resolve_locus(document, locus) -> Resolution | None
    Resolve the locus of a finding against its document.
entry_keys(document, schema, registry=None) -> EntryKeys
    Read the lists of a document whose schema declares the key of their entries.

Classes
-------
Violation
    One rule of the profile broken at one node of a log.
Resolution
    The node of a document that a locus names, or its closest existing ancestor.
EntryKeys
    The keyed lists of one document, which write the locus of each of its nodes.
"""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any, Mapping, Sequence
from urllib.parse import unquote_to_bytes

from jsonschema import validators  # type: ignore[import-untyped]
from jsonschema.protocols import Validator  # type: ignore[import-untyped]
from referencing import Registry

from .ecma import ecma_pattern, python_schema
from .errors import ProfileError
from .sarif import FINGERPRINT_KEY, check_log, fingerprint_log, location_name, split_location_name

__all__ = [
    "ENTRY_KEY",
    "PROFILE_SCHEMA_ID",
    "EntryKeys",
    "ProfileError",
    "Resolution",
    "Violation",
    "entry_keys",
    "identities",
    "location_name",
    "pointer",
    "profile_schema",
    "resolve_locus",
    "split_location_name",
    "violations",
]

PROFILE_SCHEMA_ID = (
    "https://github.com/esther-poniatowski/elenchos/specs/schemas/findings-profile.schema.json"
)
"""Absolute `$id` of the schema of a producer log."""

ENTRY_KEY = "x-entry-key"
"""Keyword by which the schema of a list declares the properties keying its entries."""

_INDEX = re.compile(r"0|[1-9][0-9]*")
"""Form of an index token under an array (RFC 6901)."""

_MALFORMED_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
"""A `%` that opens no percent-encoded octet (RFC 3986)."""

Segment = str | int
"""One step of a positional path: a property name, or an index of an array."""


@dataclass(frozen=True)
class Violation:
    """
    One rule of the profile broken at one node of a log.

    Attributes
    ----------
    pointer : str
        JSON Pointer of the node of the log at which the rule fails.
    message : str
        The rule broken, in words.
    """

    pointer: str
    message: str


@dataclass(frozen=True)
class Resolution:
    """
    The node of a document that a locus names, or its closest existing ancestor.

    Attributes
    ----------
    path : tuple[str | int, ...]
        Positional path of the deepest node reached, empty for the whole document.
    unresolved : tuple[str, ...]
        The decoded tokens of the locus below that node, empty when the locus names an existing
        node. A field absent from the record leaves its name here.
    """

    path: tuple[Segment, ...]
    unresolved: tuple[str, ...] = ()


@cache
def _schema_text() -> str:
    """Return the text of the packaged schema of a producer log, read once."""
    return files("elenchos").joinpath("schemas/findings-profile.schema.json").read_text("utf-8")


def profile_schema() -> dict[str, Any]:
    """
    Return the schema of a producer log, `findings-profile.schema.json`.

    Returns
    -------
    dict[str, Any]
        A fresh copy of the schema, whose `$id` is `PROFILE_SCHEMA_ID`.
    """
    schema: dict[str, Any] = json.loads(_schema_text())
    return schema


@cache
def _profile_validator() -> Validator:
    """Return the validator of the schema of a producer log, its patterns read as ECMA-262."""
    schema = python_schema(profile_schema())
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    validator: Validator = cls(schema)
    return validator


def pointer(path: Sequence[Segment]) -> str:
    """
    Write a positional path as a JSON Pointer (RFC 6901).

    Examples
    --------
    >>> pointer(["runs", 0, "a/b", "c~d"])
    '/runs/0/a~1b/c~0d'
    >>> pointer([])
    ''
    """
    return "".join("/" + str(step).replace("~", "~0").replace("/", "~1") for step in path)


def _members(node: Any, key: str) -> list[tuple[int, Any]]:
    """Return the indexed elements of `node[key]` when it is an array, none otherwise."""
    value = node.get(key) if isinstance(node, Mapping) else None
    return list(enumerate(value)) if isinstance(value, list) else []


def _decoded(uri: str) -> str | None:
    """Return the percent-decoded URI, or None when an escape is malformed or not UTF-8."""
    if _MALFORMED_ESCAPE.search(uri):
        return None
    try:
        return unquote_to_bytes(uri).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _result_violations(
    result: Any, here: str, driver: Any, rule_ids: set[str] | None
) -> list[Violation]:
    """Return the violations of the rules relating a result to its run, or to its own members."""
    if not isinstance(result, Mapping):
        return []
    found: list[Violation] = []
    rule_id = result.get("ruleId")
    if rule_ids is not None and isinstance(rule_id, str) and rule_id not in rule_ids:
        found.append(Violation(f"{here}/ruleId", f"ruleId {rule_id!r} names no rule of the driver"))
    payload = result.get("properties")
    if isinstance(driver, str) and isinstance(payload, Mapping):
        for name in payload:
            if not str(name).startswith(f"{driver}/"):
                found.append(
                    Violation(f"{here}/properties", f"property {name!r} does not open on {driver}/")
                )
    for index, location in _members(result, "locations"):
        found += _location_violations(location, f"{here}/locations/{index}")
    return found


def _location_violations(location: Any, here: str) -> list[Violation]:
    """Return the violations of the rules relating the logical and the physical location."""
    logical = _members(location, "logicalLocations")
    if len(logical) != 1 or not isinstance(logical[0][1], Mapping):
        return []
    name = logical[0][1].get("name")
    if not isinstance(name, str):
        return []
    found: list[Violation] = []
    qualified = logical[0][1].get("fullyQualifiedName")
    if qualified is not None and qualified != name:
        found.append(
            Violation(
                f"{here}/logicalLocations/0/fullyQualifiedName",
                "fullyQualifiedName differs from name",
            )
        )
    try:
        resource, _ = split_location_name(name)
    except ProfileError:
        return found
    physical = location.get("physicalLocation") if isinstance(location, Mapping) else None
    artifact = physical.get("artifactLocation") if isinstance(physical, Mapping) else None
    uri = artifact.get("uri") if isinstance(artifact, Mapping) else None
    if resource.startswith("path:") and isinstance(uri, str):
        path = resource.removeprefix("path:")
        if _decoded(uri) != path:
            found.append(
                Violation(
                    f"{here}/physicalLocation/artifactLocation/uri",
                    f"artifact URI {uri!r} does not encode the resource path {path!r}",
                )
            )
    return found


def _relation_violations(log: Any) -> list[Violation]:
    """Return the violations of the four rules that relate two members of a log."""
    found: list[Violation] = []
    for run_index, run in _members(log, "runs"):
        tool = run.get("tool") if isinstance(run, Mapping) else None
        driver = tool.get("driver") if isinstance(tool, Mapping) else None
        name = driver.get("name") if isinstance(driver, Mapping) else None
        rules = driver.get("rules") if isinstance(driver, Mapping) else None
        rule_ids = (
            {
                rule["id"]
                for rule in rules
                if isinstance(rule, Mapping) and isinstance(rule.get("id"), str)
            }
            if isinstance(rules, list)
            else None
        )
        for index, result in _members(run, "results"):
            found += _result_violations(
                result, f"/runs/{run_index}/results/{index}", name, rule_ids
            )
    return found


def violations(log: Any) -> list[Violation]:
    """
    Return every rule of the profile that a producer log breaks.

    The schema of a producer log checks the rules of sections 3 and 4 of the profile that JSON
    Schema expresses. Four rules relate two members of a log, and are checked here: each `ruleId`
    names a rule of the driver, each property of a result opens on the driver name and `/`, a
    `fullyQualifiedName` equals the `name` of its logical location, and the URI of the artifact of
    a `path:` resource decodes to its path.

    Parameters
    ----------
    log : Any
        Content of a log file, as returned by `json.load`.

    Returns
    -------
    list[Violation]
        The violations, empty when the log conforms. The violations of the schema come first, in
        the order of the validator.

    Examples
    --------
    >>> violations({"version": "2.1.0", "runs": []})[0].pointer
    '/runs'
    """
    found = [
        Violation(pointer(list(error.absolute_path)), _message(error))
        for error in _profile_validator().iter_errors(log)
    ]
    return found + _relation_violations(log)


def _message(error: Any) -> str:
    """Return the message of a violation of the schema, read from the rule that the schema states.

    A failed `not` or `anyOf` names no member, and a failed `pattern` prints the whole pattern, so
    the description of the subschema holding the keyword states the rule when it has one.
    """
    description = error.schema.get("description") if isinstance(error.schema, Mapping) else None
    if not isinstance(description, str):
        if error.validator == "pattern" and isinstance(error.validator_value, str):
            return f"{error.instance!r} does not match {ecma_pattern(error.validator_value)!r}"
        return str(error.message)
    if error.validator == "pattern":
        return f"{error.instance!r} breaks the form of {description}"
    if error.validator in ("not", "anyOf"):
        return description
    return str(error.message)


def identities(log: Mapping[str, Any]) -> list[str]:
    """
    Return the identity of each result of a log, in the order of its runs and results.

    The identities are those that the gate writes in `fingerprints["elenchos/v1"]`, ordinals
    included, so that a producer can state the identity of each of its findings in its tests.

    Parameters
    ----------
    log : Mapping[str, Any]
        A log that the gate accepts.

    Returns
    -------
    list[str]
        The canonical identity strings.

    Raises
    ------
    ProfileError
        If the gate rejects the log.
    """
    check_log(log)
    stamped = fingerprint_log(log)
    return [
        result["fingerprints"][FINGERPRINT_KEY]
        for run in stamped["runs"]
        for result in run.get("results") or []
    ]


def _tokens(locus: str) -> list[str]:
    """Return the decoded reference tokens of a JSON Pointer, or raise `ValueError`."""
    if re.search(r"~(?![01])", locus):
        raise ValueError(f"pointer {locus!r} holds a '~' followed by neither 0 nor 1")
    return [token.replace("~1", "/").replace("~0", "~") for token in locus.split("/")[1:]]


def _step(node: Any, token: str) -> tuple[bool, Segment]:
    """Return whether `token` names a child of `node`, and the positional segment of that child."""
    if isinstance(node, Mapping):
        return token in node, token
    if not isinstance(node, list):
        return False, token
    if _INDEX.fullmatch(token):
        return int(token) < len(node), int(token)
    name, separator, value = token.partition("=")
    if not separator:
        return False, token
    holders = [
        index
        for index, item in enumerate(node)
        if isinstance(item, Mapping) and item.get(name) == value
    ]
    return (True, holders[0]) if len(holders) == 1 else (False, token)


def resolve_locus(document: Any, locus: str) -> Resolution | None:
    """
    Resolve the locus of a finding against its document.

    The locus is a JSON Pointer, whose tokens descend from the root. Under an object, a token names
    a property. Under an array, a token of decimal digits without leading zero names an index, and
    a keyed token `<property>=<value>` names the one entry that holds the value under the property.
    The resolution stops at the first token that names no node.

    Parameters
    ----------
    document : Any
        The structured content that the locus addresses, as returned by a JSON or YAML loader.
    locus : str
        The locus of the finding, read from its logical location.

    Returns
    -------
    Resolution | None
        The deepest node reached, with the tokens left below it; None for a typed locus, which
        names no node of a document.

    Raises
    ------
    ValueError
        If the locus is a pointer holding a `~` followed by neither `0` nor `1`.

    Examples
    --------
    >>> document = {"variables": [{"symbol": "v"}, {"symbol": "u", "signature": ["a", "b"]}]}
    >>> resolve_locus(document, "/variables/symbol=u/signature/1")
    Resolution(path=('variables', 1, 'signature', 1), unresolved=())
    >>> resolve_locus(document, "/variables/symbol=u/title")
    Resolution(path=('variables', 1), unresolved=('title',))
    """
    if locus and not locus.startswith("/"):
        return None
    tokens = _tokens(locus)
    node = document
    path: list[Segment] = []
    for position, token in enumerate(tokens):
        found, segment = _step(node, token)
        if not found:
            return Resolution(tuple(path), tuple(tokens[position:]))
        node = node[segment]
        path.append(segment)
    return Resolution(tuple(path))


@dataclass
class EntryKeys:
    """
    The keyed lists of one document, which write the locus of each of its nodes.

    Attributes
    ----------
    document : Any
        The document, kept so that each list stays the object whose keys were read.
    keys : dict[int, tuple[str, ...]]
        The properties keying the entries of each keyed list, by identity of the list object.
    """

    document: Any
    keys: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def locus(self, path: Sequence[Segment]) -> str:
        """
        Write the locus of the node at a positional path of the document.

        An entry of a keyed list is written by the token `<property>=<value>` of the first listed
        property whose value in the entry is a non-empty string that no other entry holds under
        that property; another entry keeps its index. A path that leaves the document, such as the
        path of a missing field, is written positionally from the first missing step.

        Parameters
        ----------
        path : Sequence[str | int]
            Positional path of the node, from the root of the document.

        Returns
        -------
        str
            The JSON Pointer of the node, with keyed tokens.

        Examples
        --------
        >>> document = {"variables": [{"symbol": "u", "signature": ["a", "b"]}]}
        >>> keys = EntryKeys(document, {id(document["variables"]): ("symbol",)})
        >>> keys.locus(["variables", 0, "signature", 1])
        '/variables/symbol=u/signature/1'
        """
        steps: list[Segment] = []
        node = self.document
        for step in path:
            written: Segment = step
            if isinstance(node, list) and isinstance(step, int):
                written = self._entry_token(node, step)
            steps.append(written)
            try:
                node = node[step]
            except (KeyError, IndexError, TypeError):
                node = None
        return pointer(steps)

    def _entry_token(self, entries: list[Any], index: int) -> Segment:
        """Return the keyed token of one entry of a list, or its index."""
        if index >= len(entries) or not isinstance(entries[index], Mapping):
            return index
        for name in self.keys.get(id(entries), ()):
            value = entries[index].get(name)
            if not isinstance(value, str) or not value or "=" in name:
                continue
            holders = sum(
                1 for item in entries if isinstance(item, Mapping) and item.get(name) == value
            )
            if holders == 1:
                return f"{name}={value}"
        return index


def entry_keys(
    document: Any, schema: Mapping[str, Any], registry: Registry | None = None
) -> EntryKeys:
    """
    Read the lists of a document whose schema declares the key of their entries.

    The schema of a list declares the key by `x-entry-key`, whose value is one property name or a
    list of property names in order of preference. A list matched by several subschemas takes the
    first declaration that the validator reaches.

    Parameters
    ----------
    document : Any
        The document, as returned by a JSON or YAML loader.
    schema : Mapping[str, Any]
        The schema of the document.
    registry : referencing.Registry, optional
        The resources that the references of the schema reach.

    Returns
    -------
    EntryKeys
        The keyed lists of the document.

    Examples
    --------
    >>> schema = {"properties": {"variables": {"type": "array", "x-entry-key": "symbol"}}}
    >>> document = {"variables": [{"symbol": "u"}]}
    >>> entry_keys(document, schema).locus(["variables", 0])
    '/variables/symbol=u'
    """
    keys, _ = keyed_validation(document, schema, registry)
    return keys


def _key_names(value: Any) -> tuple[str, ...]:
    """Return the property names that a value of `x-entry-key` declares, in order."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(name for name in value if isinstance(name, str))
    return ()


def keyed_validation(
    document: Any, schema: Mapping[str, Any], registry: Registry | None = None
) -> tuple[EntryKeys, list[Any]]:
    """
    Validate a document against its schema, and read its keyed lists in the same pass.

    Parameters
    ----------
    document : Any
        The document, as returned by a JSON or YAML loader.
    schema : Mapping[str, Any]
        The schema of the document; its patterns are read as ECMA-262 patterns.
    registry : referencing.Registry, optional
        The resources that the references of the schema reach, their patterns already rewritten
        by `elenchos.ecma.python_schema`.

    Returns
    -------
    tuple[EntryKeys, list[jsonschema.ValidationError]]
        The keyed lists of the document, and the errors of the validator at the top level.

    Raises
    ------
    jsonschema.exceptions.SchemaError
        If the schema is not a valid schema of its dialect.
    """
    found = EntryKeys(document)

    def collect(_validator: Any, value: Any, instance: Any, _schema: Any) -> Any:
        if isinstance(instance, list):
            found.keys.setdefault(id(instance), _key_names(value))
        return iter(())

    converted = python_schema(dict(schema))
    base = validators.validator_for(converted)
    base.check_schema(converted)
    cls = validators.extend(base, {ENTRY_KEY: collect})
    validator = cls(converted, registry=registry) if registry is not None else cls(converted)
    errors = list(validator.iter_errors(document))
    return found, errors
