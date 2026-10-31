"""
Reading and writing of finding identities on SARIF 2.1.0 objects held as plain dictionaries.

A producer writes the resource and the locus of a finding in `logicalLocations[0].name`, and its
discriminator in `partialFingerprints["discriminator/v1"]`. The gate reads them, numbers the
identical occurrences of the log, and writes the identity in `fingerprints["elenchos/v1"]`. The
specification is `docs/profile.md`.

Functions
---------
location_name(resource, locus) -> str
    Write the name of the logical location of a finding.
split_location_name(name) -> tuple[str, str]
    Read the resource and the locus back from the name of a logical location.
identity_of(result, tool) -> Identity
    Read the identity without ordinal of one result of a run of `tool`.
order_key(result) -> OrderKey
    Read the key ordering identical occurrences of one result.
write_fingerprint(result, identity) -> None
    Write the identity of a result in `fingerprints["elenchos/v1"]`.
write_identity(result, identity) -> None
    Write the identity and the discriminator of a result.
run_complete(run) -> bool
    Whether a run declares that its analysis covered every rule on every target.
stop_reasons(run) -> list[str]
    Messages of the notifications of level `error` by which a run declares that it failed.
check_log(log) -> None
    Check that a log written by a producer satisfies the profile.
fingerprint_log(log) -> dict
    Return a copy of a log whose every result carries its identity.
"""

import copy
import re
from typing import Any, Mapping

from .errors import ProfileError
from .identity import TOOL_PATTERN, Identity, OrderKey, number_occurrences

FINGERPRINT_KEY = "elenchos/v1"
"""Key of the identity in `result.fingerprints`."""

DISCRIMINATOR_KEY = "discriminator/v1"
"""Key of the discriminator in `result.partialFingerprints`."""

VERSIONED_KEY = re.compile(r"[^/]+(?:/[^/]+)*/v[0-9]+")
"""Form of a versioned hierarchical string (SARIF §3.5.4.2), with non-empty components."""

SARIF_VERSION = "2.1.0"
"""Value of `sarifLog.version`."""

LEVELS = ("error", "warning", "note")
"""Values of `result.level` admitted by the profile."""

NOTIFICATION_LEVELS = ("none", "note", "warning", "error")
"""Values of `notification.level` admitted by SARIF; an absent level defaults to `warning`."""

GATE_TOOL = "elenchos"
"""Driver name of the run that the gate adds to the log; a producer never writes it."""

JsonObject = dict[str, Any]
"""A JSON object of a SARIF log, read with `json.load`."""

_NAME_ESCAPES = {"%25": "%", "%23": "#"}
"""Escapes of the resource in the name of a logical location, mapped to their characters."""


def location_name(resource: str, locus: str = "") -> str:
    """
    Write the name of the logical location of a finding.

    Parameters
    ----------
    resource : str
        Affected resource, `id:<identifier>` or `path:<path>`.
    locus : str, default ""
        Semantic locus within the resource, or the empty string for the whole resource.

    Returns
    -------
    str
        `<resource>` or `<resource>#<locus>`, with `%` and `#` of the resource written `%25` and
        `%23`. The locus is written as is, since the name splits at its first `#`.

    Examples
    --------
    >>> location_name("path:docs/notes#old.md", "link:a#b")
    'path:docs/notes%23old.md#link:a#b'
    """
    escaped = resource.replace("%", "%25").replace("#", "%23")
    return f"{escaped}#{locus}" if locus else escaped


def split_location_name(name: str) -> tuple[str, str]:
    """
    Read the resource and the locus back from the name of a logical location.

    Parameters
    ----------
    name : str
        Value of `logicalLocations[0].name`.

    Returns
    -------
    tuple[str, str]
        The resource, decoded, and the locus, empty for the whole resource.

    Raises
    ------
    ProfileError
        If the name ends with `#`, or if its resource holds a `%` other than `%25` or `%23`. Such a
        name is not produced by `location_name`, and accepting it would map two names onto one
        identity.
    """
    escaped, separator, locus = name.partition("#")
    if separator and not locus:
        raise ProfileError(f"logical location {name!r} ends with `#` and an empty locus")
    pieces = re.split(r"(%..)", escaped)
    for piece in pieces[1::2]:
        if piece not in _NAME_ESCAPES:
            raise ProfileError(f"invalid escape {piece!r} in the resource of {name!r}")
    if "%" in "".join(pieces[0::2]):
        raise ProfileError(f"truncated escape in the resource of {name!r}")
    resource = "".join(_NAME_ESCAPES.get(piece, piece) for piece in pieces)
    return resource, locus


def _check_keys(result: Mapping[str, Any], member: str) -> Mapping[str, Any]:
    """Return `result[member]`, after checking that it maps versioned keys to strings."""
    value = result.get(member, {})
    if not isinstance(value, Mapping):
        raise ProfileError(f"{member} is not an object")
    for key, item in value.items():
        if not VERSIONED_KEY.fullmatch(key):
            raise ProfileError(f"{member} key {key!r} is not a versioned hierarchical string")
        if not isinstance(item, str):
            raise ProfileError(f"{member}[{key!r}] is not a string")
    return value


def _only_element(container: Mapping[str, Any], member: str) -> Mapping[str, Any]:
    """Return the single element of the array `container[member]`, or raise `ProfileError`."""
    array = container.get(member)
    if not isinstance(array, list) or len(array) != 1 or not isinstance(array[0], Mapping):
        count = len(array) if isinstance(array, list) else "no"
        raise ProfileError(f"{member} must hold exactly one object, not {count}")
    element: Mapping[str, Any] = array[0]
    return element


def identity_of(result: Mapping[str, Any], tool: str) -> Identity:
    """
    Read the identity without ordinal of one result of a run of `tool`.

    Parameters
    ----------
    result : Mapping[str, Any]
        SARIF `result` object.
    tool : str
        Value of `run.tool.driver.name` of the run holding the result.

    Returns
    -------
    Identity
        The identity of the result, with ordinal 1.

    Raises
    ------
    ProfileError
        If the result holds no `ruleId`, not exactly one location, not exactly one logical
        location with a `name`, or a fingerprint key that is not a versioned hierarchical string.
    """
    rule_id = result.get("ruleId")
    if not isinstance(rule_id, str):
        raise ProfileError("result holds no ruleId")
    location = _only_element(result, "locations")
    name = _only_element(location, "logicalLocations").get("name")
    if not isinstance(name, str):
        raise ProfileError("logical location holds no name")
    _check_keys(result, "fingerprints")
    discriminator = _check_keys(result, "partialFingerprints").get(DISCRIMINATOR_KEY, "")
    resource, locus = split_location_name(name)
    return Identity(tool, rule_id, resource, locus, discriminator)


def order_key(result: Mapping[str, Any]) -> OrderKey:
    """
    Read the key ordering identical occurrences of one result.

    Parameters
    ----------
    result : Mapping[str, Any]
        SARIF `result` object, already accepted by `identity_of`.

    Returns
    -------
    OrderKey
        `region.startLine` and `region.startColumn` of the physical location, each 0 when absent,
        and `message.text`, empty when absent.
    """
    location = result["locations"][0]
    region = location.get("physicalLocation", {}).get("region", {})
    message = result.get("message", {}).get("text", "")
    return (int(region.get("startLine", 0)), int(region.get("startColumn", 0)), str(message))


def write_fingerprint(result: JsonObject, identity: Identity) -> None:
    """Write the identity of a result in `fingerprints["elenchos/v1"]`, keeping other keys."""
    result.setdefault("fingerprints", {})[FINGERPRINT_KEY] = str(identity)


def write_identity(result: JsonObject, identity: Identity) -> None:
    """
    Write the identity and the discriminator of a result.

    The discriminator goes to `partialFingerprints["discriminator/v1"]` when it is non-empty. This
    serves a result built from its components, such as a finding of the gate itself.

    Parameters
    ----------
    result : JsonObject
        SARIF `result` object, modified in place.
    identity : Identity
        Identity of the result, with its ordinal.
    """
    write_fingerprint(result, identity)
    if identity.discriminator:
        result.setdefault("partialFingerprints", {})[DISCRIMINATOR_KEY] = identity.discriminator


def _invocations(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """
    Return the invocations of a run, after checking the members on which the verdict depends.

    Raises
    ------
    ProfileError
        If `invocations` is not an array of objects each holding a boolean `executionSuccessful`,
        or if `toolExecutionNotifications` is not an array of objects whose `level`, when present,
        is a level of SARIF.
    """
    invocations = run.get("invocations", [])
    if not isinstance(invocations, list):
        raise ProfileError("run invocations is not an array")
    for invocation in invocations:
        if not isinstance(invocation, Mapping):
            raise ProfileError("invocation is not an object")
        if not isinstance(invocation.get("executionSuccessful"), bool):
            raise ProfileError("invocation holds no boolean executionSuccessful")
        notifications = invocation.get("toolExecutionNotifications", [])
        if not isinstance(notifications, list):
            raise ProfileError("invocation toolExecutionNotifications is not an array")
        for notification in notifications:
            if not isinstance(notification, Mapping):
                raise ProfileError("tool execution notification is not an object")
            level = notification.get("level", "warning")
            if level not in NOTIFICATION_LEVELS:
                raise ProfileError(
                    f"notification level {level!r} is not one of {list(NOTIFICATION_LEVELS)}"
                )
    return invocations


def _error_notifications(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the tool execution notifications of level `error` of every invocation of a run."""
    return [
        notification
        for invocation in _invocations(run)
        for notification in invocation.get("toolExecutionNotifications", [])
        if notification.get("level", "warning") == "error"
    ]


def run_complete(run: Mapping[str, Any]) -> bool:
    """
    Whether a run declares that its analysis covered every rule on every target.

    SARIF expresses an incomplete analysis only as a failed run (§3.20.21): a run is incomplete
    when one of its invocations holds `executionSuccessful` false, or a tool execution
    notification of level `error`. A run holding no invocation is complete.

    Parameters
    ----------
    run : Mapping[str, Any]
        SARIF `run` object.

    Returns
    -------
    bool
        False for a partial run, stopped by design, and for a failed run; True otherwise.

    Raises
    ------
    ProfileError
        If the invocations of the run break the profile.

    Examples
    --------
    >>> run_complete({"results": []})
    True
    >>> run_complete({"invocations": [{"executionSuccessful": False}]})
    False
    >>> notification = {"level": "error", "message": {"text": "stopped"}}
    >>> run_complete(
    ...     {"invocations": [{"executionSuccessful": True,
    ...                       "toolExecutionNotifications": [notification]}]}
    ... )
    False
    """
    if any(not invocation["executionSuccessful"] for invocation in _invocations(run)):
        return False
    return not _error_notifications(run)


def stop_reasons(run: Mapping[str, Any]) -> list[str]:
    """
    Return the messages of the notifications of level `error` by which a run declares a failure.

    Parameters
    ----------
    run : Mapping[str, Any]
        SARIF `run` object.

    Returns
    -------
    list[str]
        The `message.text` of each tool execution notification of level `error`, in the order of
        the invocations; a notification without text is skipped.
    """
    reasons: list[str] = []
    for notification in _error_notifications(run):
        message = notification.get("message")
        text = message.get("text") if isinstance(message, Mapping) else None
        if isinstance(text, str):
            reasons.append(text)
    return reasons


def _check_result(result: Any, tool: str) -> None:
    """Raise `ProfileError` unless a producer result satisfies the profile."""
    if not isinstance(result, Mapping):
        raise ProfileError("result is not an object")
    identity_of(result, tool)
    level = result.get("level")
    if level not in LEVELS:
        raise ProfileError(f"result level {level!r} is not one of {list(LEVELS)}")
    message = result.get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("text"), str):
        raise ProfileError("result holds no message.text")
    if "suppressions" in result:
        raise ProfileError("result holds suppressions, which only the gate writes")
    if FINGERPRINT_KEY in result.get("fingerprints", {}):
        raise ProfileError(
            f"result holds fingerprints[{FINGERPRINT_KEY!r}], written by the gate only"
        )


def check_log(log: Any) -> None:
    """
    Check that a log written by a producer satisfies the profile.

    The rules checked are those on which the identity depends, and those on which the verdict of
    the gate depends: the level of each result, the absence of every object written by the gate
    only, and the invocations by which a run declares that it is incomplete. A failed run may omit
    `results`, since its analysis may never have begun (SARIF §3.14.23).

    Parameters
    ----------
    log : Any
        Content of a log file, as returned by `json.load`.

    Raises
    ------
    ProfileError
        If the log is not an object of version `2.1.0` holding a non-empty array of runs; if a run
        names no driver matching the tool form, names the driver of the gate, holds malformed
        invocations (see `run_complete`), or holds no array of results while declaring no failure;
        or if a result breaks the profile (see `identity_of`), carries no admitted `level`, no
        `message.text`, or a `suppressions` array or identity written by the producer.
    """
    if not isinstance(log, Mapping):
        raise ProfileError("log is not an object")
    version = log.get("version")
    if version != SARIF_VERSION:
        raise ProfileError(f"log version {version!r} is not {SARIF_VERSION!r}")
    runs = log.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ProfileError("log holds no array of runs")
    for run in runs:
        if not isinstance(run, Mapping):
            raise ProfileError("run is not an object")
        tool = _driver_name(run)
        if not TOOL_PATTERN.fullmatch(tool):
            raise ProfileError(f"run driver name {tool!r} does not match {TOOL_PATTERN.pattern}")
        if tool == GATE_TOOL:
            raise ProfileError(f"run names the driver {GATE_TOOL!r} of the gate")
        complete = run_complete(run)
        if "results" not in run and not complete:
            continue
        results = run.get("results")
        if not isinstance(results, list):
            raise ProfileError("run holds no array of results, and declares no failure")
        for result in results:
            _check_result(result, tool)


def _driver_name(run: Mapping[str, Any]) -> str:
    """Return `run.tool.driver.name`, or raise `ProfileError` when the run names no driver."""
    tool = run.get("tool")
    driver = tool.get("driver") if isinstance(tool, Mapping) else None
    name = driver.get("name") if isinstance(driver, Mapping) else None
    if not isinstance(name, str):
        raise ProfileError("run holds no tool.driver.name")
    return name


def fingerprint_log(log: Mapping[str, Any]) -> JsonObject:
    """
    Return a copy of a log whose every result carries its identity.

    Identical occurrences are numbered across every run of one tool in the log. The `tool` object
    and the `partialFingerprints` of each result are left unchanged.

    Parameters
    ----------
    log : Mapping[str, Any]
        SARIF `sarifLog` object; it is not modified.

    Returns
    -------
    JsonObject
        A deep copy of the log, with `fingerprints["elenchos/v1"]` on every result.

    Raises
    ------
    ProfileError
        If a run names no driver, or if a result breaks the profile (see `identity_of`).
    """
    stamped: JsonObject = copy.deepcopy(dict(log))
    occurrences: list[tuple[Identity, OrderKey]] = []
    results: list[JsonObject] = []
    for run in stamped.get("runs", []):
        tool = run.get("tool", {}).get("driver", {}).get("name")
        if not isinstance(tool, str):
            raise ProfileError("run holds no tool.driver.name")
        for result in run.get("results") or []:
            occurrences.append((identity_of(result, tool), order_key(result)))
            results.append(result)
    for result, identity in zip(results, number_occurrences(occurrences)):
        write_fingerprint(result, identity)
    return stamped
