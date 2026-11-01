"""
Runner of the gate: run the declared checks, merge their logs, apply suppressions and judge.

The runner executes each check of a configuration, reads the SARIF log that the check writes, and
validates it against the findings profile. It merges the valid runs into one log, builds the
identity of every result, applies the suppressions of the consumer, and adds one run of its own,
of driver `elenchos`, holding a result for each check that failed, for each check whose log holds
an incomplete run, and for each stale suppression.
A result blocks when it is unsuppressed and its level is blocking under the policy of the consumer.
The behaviour is specified in `docs/configuration.md`.

Classes
-------
Failure
    The reason for which one check yields no valid log, or an incomplete one.
CheckOutcome
    The valid runs of one check, or its failure.
Finding
    The verdict on one result of the merged log.
Report
    The merged log and the verdict on each of its results.

Functions
---------
run_check(check, root, scope) -> CheckOutcome
    Run one check, on the paths of a scoped run when it accepts paths, and read its log.
changed_paths(root) -> list[str]
    List the files changed since the last commit, and the untracked files, under a root.
judge(configuration, outcomes, suppressions) -> Report
    Merge the outcomes of the checks into one log, and decide which results block.
write_log(log, path) -> None
    Write a SARIF log as JSON.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from . import __version__
from .config import Check, Configuration, Policy
from .errors import ProfileError
from .identity import Identity
from .sarif import (
    FINGERPRINT_KEY,
    GATE_TOOL,
    SARIF_VERSION,
    JsonObject,
    check_log,
    fingerprint_log,
    location_name,
    run_complete,
    stop_reasons,
    write_identity,
)
from .suppressions import Suppression

SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)
"""Schema URI of SARIF 2.1.0 errata 01, written in `sarifLog.$schema`."""

CHECK_FAILED = "check/failed"
"""Rule of the gate: the earlier log of a check could not be deleted, or its command could not start
or exited with an undeclared status."""

CHECK_MISSING_LOG = "check/missing-log"
"""Rule of the gate: the command of a check ran to completion, but wrote no log."""

CHECK_INVALID_LOG = "check/invalid-log"
"""Rule of the gate: the log of a check is not JSON, or breaks the findings profile."""

CHECK_INCOMPLETE = "check/incomplete"
"""Rule of the gate: the valid log of a check holds a run declaring that its analysis is partial or
failed."""

SUPPRESSION_STALE = "suppression/stale"
"""Rule of the gate: a suppression matches no result of the merged log."""

GATE_RULES = {
    CHECK_FAILED: (
        "The earlier log of a check could not be deleted, or its command could not start or "
        "exited with an undeclared status."
    ),
    CHECK_MISSING_LOG: "The command of a check ran to completion, but wrote no log.",
    CHECK_INVALID_LOG: "The log of a check is not JSON, or breaks the findings profile.",
    CHECK_INCOMPLETE: (
        "The log of a check holds a run declaring that its analysis is partial or failed, so its "
        "results may be incomplete."
    ),
    SUPPRESSION_STALE: "A suppression matches no result, so the suppressions file must shrink.",
}
"""Short description of each rule of the gate, written in the descriptors of its run."""

GATE_LEVEL = "error"
"""Level of every result of the gate."""


@dataclass(frozen=True)
class Failure:
    """
    The reason for which one check yields no valid log, or a valid log holding an incomplete run.

    Attributes
    ----------
    rule_id : str
        Rule of the gate that the failure breaks.
    message : str
        Explanation of the failure.
    """

    rule_id: str
    message: str


@dataclass(frozen=True)
class CheckOutcome:
    """
    The valid runs of one check, or its failure.

    Attributes
    ----------
    check : Check
        The declared check.
    runs : tuple[JsonObject, ...]
        Runs of the log of the check, empty when the check failed or was skipped.
    failure : Failure | None
        Reason for which the check yields no valid log, or None.
    scope : frozenset[str] | None, default None
        Repository-relative paths that the check received in a scoped run, or None when it
        checked the whole root.
    skipped : bool, default False
        Whether the check did not run, since it accepts paths and the scoped run holds none.
    """

    check: Check
    runs: tuple[JsonObject, ...] = ()
    failure: Failure | None = None
    scope: frozenset[str] | None = None
    skipped: bool = False


@dataclass(frozen=True)
class Finding:
    """
    The verdict on one result of the merged log.

    Attributes
    ----------
    check : str | None
        Name of the check whose log holds the result, or None for a result of the gate.
    identity : str
        Identity of the result.
    level : str
        Level of the result.
    message : str
        Text of the message of the result.
    suppressed : bool
        Whether a suppression of the consumer matches the result.
    blocking : bool
        Whether the result is unsuppressed and its level blocks under the policy.
    """

    check: str | None
    identity: str
    level: str
    message: str
    suppressed: bool
    blocking: bool


@dataclass(frozen=True)
class Report:
    """
    The merged log and the verdict on each of its results.

    Attributes
    ----------
    log : JsonObject
        Merged SARIF log: one run per producer run, then the run of the gate.
    findings : tuple[Finding, ...]
        Verdict on each result, in the order of the log.
    unverified : tuple[str, ...]
        Identities of the unmatched suppressions that could not be checked: their tool yielded an
        incomplete run, no run while a check failed or was skipped, or a scoped run that did not
        cover their resource.
    stale : tuple[str, ...]
        Identities of the stale suppressions, each reported by a result of the gate.
    skipped : tuple[str, ...]
        Names of the checks skipped by a scoped run that holds no path.
    entries : tuple[Suppression, ...]
        Suppressions of the consumer under their current identity, in the order of the file.
    """

    log: JsonObject
    findings: tuple[Finding, ...]
    unverified: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    entries: tuple[Suppression, ...] = ()

    @property
    def blocked(self) -> bool:
        """Whether at least one result blocks."""
        return any(finding.blocking for finding in self.findings)


def _display(path: Path, root: Path) -> str:
    """Return a path relative to the root when it lies under it, and absolute otherwise."""
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _last_line(*outputs: str) -> str:
    """Return the last non-empty line of the first output that holds one."""
    for output in outputs:
        lines = [line for line in output.splitlines() if line.strip()]
        if lines:
            return lines[-1].strip()
    return "no output"


def changed_paths(root: Path) -> list[str]:
    """
    List the files changed since the last commit, and the untracked files, under a root.

    Parameters
    ----------
    root : Path
        Root of the consumer, inside a Git work tree.

    Returns
    -------
    list[str]
        Repository-relative POSIX paths of the existing files that differ from `HEAD` or are
        untracked and not ignored, sorted. A deleted file is left out, since no check can read it.

    Raises
    ------
    OSError
        If Git cannot run, or the root lies outside a work tree.
    """
    found: set[str] = set()
    for arguments in (
        ["diff", "--name-only", "--relative", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        completed = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
        )
        if completed.returncode != 0:
            raise OSError(f"git {arguments[0]} failed: {_last_line(completed.stderr)}")
        found.update(line for line in completed.stdout.splitlines() if line)
    return sorted(path for path in found if (root / path).is_file())


def run_check(check: Check, root: Path, scope: Sequence[str] | None = None) -> CheckOutcome:
    """
    Run one check, on the paths of a scoped run when it accepts paths, and read its log.

    The log declared by the check is deleted before the command runs, so that a log left by an
    earlier run is never read. The command runs without a shell, in the root of the consumer.
    In a scoped run, a check of scope `paths` receives the paths appended to its command, and is
    skipped when the run holds no path; a check of scope `root` checks the whole root.

    Parameters
    ----------
    check : Check
        The declared check.
    root : Path
        Root of the consumer, the working directory of the command.
    scope : Sequence[str] | None, default None
        Repository-relative paths of a scoped run, or None for a run on the whole root.

    Returns
    -------
    CheckOutcome
        The runs of the log when the command exits with a declared status and writes a log that
        satisfies the profile; otherwise the failure, and no run.
    """
    scoped = scope is not None and check.scope == "paths"
    if scoped and not scope:
        return CheckOutcome(check, skipped=True)
    arguments = [*check.command, *(scope or [])] if scoped else list(check.command)
    paths = frozenset(scope or []) if scoped else None
    try:
        check.log.unlink(missing_ok=True)
    except OSError as error:
        message = f"earlier log {_display(check.log, root)} cannot be deleted: {error}"
        return CheckOutcome(check, failure=Failure(CHECK_FAILED, message), scope=paths)
    try:
        completed = subprocess.run(
            arguments, cwd=root, capture_output=True, text=True, check=False
        )
    except OSError as error:
        return CheckOutcome(
            check, failure=Failure(CHECK_FAILED, f"command cannot start: {error}"), scope=paths
        )
    if completed.returncode not in check.exit_codes:
        tail = _last_line(completed.stderr, completed.stdout)
        message = f"command exited with status {completed.returncode}: {tail}"
        return CheckOutcome(check, failure=Failure(CHECK_FAILED, message), scope=paths)
    if not check.log.is_file():
        message = f"command wrote no log at {_display(check.log, root)}"
        return CheckOutcome(check, failure=Failure(CHECK_MISSING_LOG, message), scope=paths)
    try:
        log = json.loads(check.log.read_text(encoding="utf-8"))
        check_log(log)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ProfileError) as error:
        message = f"log {_display(check.log, root)} is invalid: {error}"
        return CheckOutcome(check, failure=Failure(CHECK_INVALID_LOG, message), scope=paths)
    return CheckOutcome(check, runs=tuple(log["runs"]), scope=paths)


def _gate_result(identity: Identity, message: str, uri: str) -> JsonObject:
    """Build one result of the run of the gate, about a file of the consumer."""
    result: JsonObject = {
        "ruleId": identity.rule_id,
        "level": GATE_LEVEL,
        "message": {"text": message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": quote(uri), "uriBaseId": "SRCROOT"}
                },
                "logicalLocations": [{"name": location_name(identity.resource, identity.locus)}],
            }
        ],
    }
    write_identity(result, identity)
    result["suppressions"] = []
    return result


def _gate_run(results: list[JsonObject]) -> JsonObject:
    """Build the run of the gate, holding its own results."""
    return {
        "tool": {
            "driver": {
                "name": GATE_TOOL,
                "version": __version__,
                "rules": [
                    {
                        "id": rule_id,
                        "shortDescription": {"text": text},
                        "defaultConfiguration": {"level": GATE_LEVEL},
                    }
                    for rule_id, text in GATE_RULES.items()
                ],
            }
        },
        "columnKind": "unicodeCodePoints",
        "results": results,
    }


def _covers(scope: frozenset[str], resource: str) -> bool:
    """Whether a scoped run covers a resource: a `path:` equal to a path of the scope, or below a
    folder of the scope.

    Examples
    --------
    >>> _covers(frozenset({"docs/a.md", "notes"}), "path:notes/b.md")
    True
    >>> _covers(frozenset({"docs/a.md"}), "id:quest.x")
    False
    >>> _covers(frozenset({"."}), "path:docs/a.md")
    True
    """
    if not resource.startswith("path:"):
        return False
    path = resource.removeprefix("path:").removesuffix("/")
    folders = {item.rstrip("/") for item in scope}
    return "." in folders or any(path == item or path.startswith(item + "/") for item in folders)


def _stale(
    suppressions: Mapping[str, Suppression],
    matched: set[str],
    outcomes: Sequence[CheckOutcome],
    runs: Sequence[JsonObject],
) -> tuple[list[str], list[str]]:
    """
    Split the unmatched suppressions into stale and unverified entries.

    An unmatched entry is unverified when its tool yielded an incomplete run, since the finding may
    lie beyond the point where the run stopped. An entry whose tool yielded no run while a check
    failed or was skipped is unverified, since that check may have held its finding. An entry
    whose tool ran only on the paths of a scoped run is unverified unless the scope covers its
    resource. Every other unmatched entry is stale.
    """
    tools = {run["tool"]["driver"]["name"] for run in runs}
    incomplete = {run["tool"]["driver"]["name"] for run in runs if not run_complete(run)}
    whole = {
        run["tool"]["driver"]["name"]
        for outcome in outcomes
        if outcome.scope is None
        for run in outcome.runs
    }
    scopes: dict[str, frozenset[str]] = {}
    for outcome in outcomes:
        if outcome.scope is not None:
            for run in outcome.runs:
                name = run["tool"]["driver"]["name"]
                scopes[name] = scopes.get(name, frozenset()) | outcome.scope
    all_ran = all(outcome.failure is None and not outcome.skipped for outcome in outcomes)
    stale: list[str] = []
    unverified: list[str] = []
    for text in suppressions:
        if text in matched:
            continue
        identity = Identity.parse(text)
        tool = identity.tool
        if tool in incomplete or not (all_ran or tool in tools):
            unverified.append(text)
        elif tool in scopes and tool not in whole and not _covers(scopes[tool], identity.resource):
            unverified.append(text)
        else:
            stale.append(text)
    return stale, unverified


def _verdict(
    result: JsonObject,
    tool: str,
    check: Check | None,
    policy: Policy,
    suppression: Suppression | None,
) -> Finding:
    """
    Write the `suppressions` array of one result, and decide whether the result blocks.

    The result blocks when no suppression matches it and its level is blocking under the policy,
    for the rule of the result and the check whose log holds it.
    """
    result["suppressions"] = [] if suppression is None else [suppression.sarif()]
    levels = policy.blocking_levels(tool, result["ruleId"], check)
    return Finding(
        None if check is None else check.name,
        result["fingerprints"][FINGERPRINT_KEY],
        result["level"],
        result["message"]["text"],
        suppression is not None,
        suppression is None and result["level"] in levels,
    )


def _incompleteness(outcome: CheckOutcome) -> Failure | None:
    """
    Return the incompleteness of the valid log of a check, or None when every run is complete.

    The message names the tool of each incomplete run, followed by the messages of its
    notifications of level `error`.
    """
    parts: list[str] = []
    for run in outcome.runs:
        if not run_complete(run):
            tool = run["tool"]["driver"]["name"]
            reasons = "; ".join(stop_reasons(run)) or "executionSuccessful is false"
            parts.append(f"run of {tool} is incomplete: {reasons}")
    return Failure(CHECK_INCOMPLETE, "; ".join(parts)) if parts else None


def _gate_results(
    configuration: Configuration, outcomes: Sequence[CheckOutcome], stale: Sequence[str]
) -> list[JsonObject]:
    """
    Build the results of the gate: one per failed or incomplete check, then one per stale
    suppression.

    A failed or incomplete check is located at its declaration, the pointer `/checks/<name>` of
    the configuration file. A stale suppression is located at the suppressions file, with its
    identity as discriminator.
    """
    results: list[JsonObject] = []
    config_uri = configuration.relative(configuration.path)
    for outcome in outcomes:
        failure = outcome.failure or _incompleteness(outcome)
        if failure is not None:
            identity = Identity(
                GATE_TOOL,
                failure.rule_id,
                f"path:{config_uri}",
                f"/checks/{outcome.check.name}",
            )
            message = f"check {outcome.check.name}: {failure.message}"
            results.append(_gate_result(identity, message, config_uri))
    if stale and configuration.suppressions is not None:
        suppressions_uri = configuration.relative(configuration.suppressions)
        for text in stale:
            identity = Identity(
                GATE_TOOL, SUPPRESSION_STALE, f"path:{suppressions_uri}", discriminator=text
            )
            message = f"the suppression of {text} matches no result"
            results.append(_gate_result(identity, message, suppressions_uri))
    return results


def judge(
    configuration: Configuration,
    outcomes: Sequence[CheckOutcome],
    suppressions: Mapping[str, Suppression],
) -> Report:
    """
    Merge the outcomes of the checks into one log, and decide which results block.

    Parameters
    ----------
    configuration : Configuration
        Configuration of the consumer, giving the policy and the paths named by gate results.
    outcomes : Sequence[CheckOutcome]
        Outcome of each check, in the order of the configuration.
    suppressions : Mapping[str, Suppression]
        Suppressions of the consumer, keyed by identity.

    Returns
    -------
    Report
        The merged log, with the identity and the `suppressions` array of every result, and the
        verdict on each result. Identical occurrences are numbered across every run of one tool.
        The `tool` object of each producer run is left unchanged, and an incomplete run enters
        the log with the results it holds. The results of the gate are never suppressed, and are
        judged by the default and rule levels of the policy.
    """
    owners = [outcome.check for outcome in outcomes for _ in outcome.runs]
    runs: list[JsonObject] = fingerprint_log(
        {"runs": [run for outcome in outcomes for run in outcome.runs]}
    )["runs"]
    findings = [
        _verdict(
            result,
            run["tool"]["driver"]["name"],
            check,
            configuration.policy,
            suppressions.get(result["fingerprints"][FINGERPRINT_KEY]),
        )
        for check, run in zip(owners, runs)
        for result in run.get("results") or []
    ]
    stale, unverified = _stale(
        suppressions,
        {finding.identity for finding in findings if finding.suppressed},
        outcomes,
        runs,
    )
    gate_results = _gate_results(configuration, outcomes, stale)
    findings += [
        _verdict(result, GATE_TOOL, None, configuration.policy, None) for result in gate_results
    ]
    log: JsonObject = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [*runs, _gate_run(gate_results)],
    }
    return Report(
        log,
        tuple(findings),
        tuple(unverified),
        tuple(stale),
        tuple(outcome.check.name for outcome in outcomes if outcome.skipped),
        tuple(suppressions.values()),
    )


def write_log(log: Mapping[str, Any], path: Path) -> None:
    """
    Write a SARIF log as JSON, creating the parent folders.

    Parameters
    ----------
    log : Mapping[str, Any]
        SARIF log to write.
    path : Path
        Destination of the log.

    Raises
    ------
    OSError
        If the folder or the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
