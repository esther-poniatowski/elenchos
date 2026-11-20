"""
Command-line interface for the `elenchos` package.

Defines commands available via `python -m elenchos` or `elenchos` if installed as a script.

Commands
--------
info : Display diagnostic information.
check : Run the checks declared by a consumer, write the merged log, and gate on its results.
update : Run the checks, then rewrite the suppressions file: renamed identities, stale entries
    pruned, current findings accepted.
validate : Validate each record against the schema that its binding names, as a check of its own.

See Also
--------
typer.Typer
    Library for building CLI applications: https://typer.tiangolo.com/
"""

import datetime
import json
from pathlib import Path
from typing import Optional

import typer

from . import info, __version__
from .config import Configuration, discover_configuration, discover_root, load_configuration
from .errors import ConfigurationError
from .runner import Report, changed_paths, judge, run_check, write_log
from .sarif import GATE_TOOL
from .suppressions import Suppression, apply_renames, load_suppressions, write_suppressions

EXIT_PASS = 0
"""Exit status of `check` when no result blocks."""

EXIT_BLOCKED = 1
"""Exit status of `check` when at least one unsuppressed result blocks."""

EXIT_ERROR = 2
"""Exit status of `check` when the gate cannot run: an invalid input, or an unwritable log."""

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("info")
def cli_info() -> None:
    """Display version and platform diagnostics."""
    typer.echo(info())


def render(report: Report, configuration: Configuration) -> list[str]:
    """
    Format the verdict of a run of the gate as lines of text.

    Parameters
    ----------
    report : Report
        Merged log and verdicts.
    configuration : Configuration
        Configuration of the consumer, giving the order of the checks and the output path.

    Returns
    -------
    list[str]
        One summary line per check and for the gate, then each blocking result, then the count of
        unverified suppressions, then the path of the log and the verdict.
    """
    lines: list[str] = []
    skipped = set(report.skipped)
    for name in [check.name for check in configuration.checks] + [None]:
        if name in skipped:
            lines.append(f"{name}: skipped, since the scoped run holds no path")
            continue
        own = [finding for finding in report.findings if finding.check == name]
        suppressed = sum(finding.suppressed for finding in own)
        blocking = sum(finding.blocking for finding in own)
        lines.append(
            f"{name or GATE_TOOL}: {len(own)} results, {suppressed} suppressed, "
            f"{blocking} blocking"
        )
    blocking_findings = [finding for finding in report.findings if finding.blocking]
    if blocking_findings:
        lines.append("blocking results:")
        lines.extend(
            f"  {finding.identity}: {finding.level}: {finding.message}"
            for finding in blocking_findings
        )
    if report.unverified:
        lines.append(
            f"{len(report.unverified)} suppressions unverified, since their tool yielded an "
            "incomplete run, no run while a check failed or was skipped, or a scoped run that "
            "did not cover their resource"
        )
    lines.append(f"log written to {configuration.output}")
    lines.append("gate: fail" if report.blocked else "gate: pass")
    return lines


CONFIG_OPTION = typer.Option(
    None,
    "--config",
    "-c",
    help=(
        "Configuration file of the consumer, declaring its checks, policy and suppressions, "
        "relative to the current folder; by default elenchos.toml at the root, in .config/, or in "
        "config/."
    ),
)
ROOT_OPTION = typer.Option(
    None,
    "--root",
    "-r",
    help=(
        "Root of the consumer, against which the paths of the configuration resolve; by default "
        "the folder of ELENCHOS_ROOT, else the nearest folder, from the current one upwards, "
        "holding a configuration, else the current folder."
    ),
)
CHANGED_OPTION = typer.Option(
    False,
    "--changed",
    help="Scope the run to the files changed since the last commit and the untracked files.",
)
ANAGRAPHE_CONFIG_OPTION = typer.Option(
    None,
    "--anagraphe-config",
    help=(
        "Configuration file of Anagraphe, declaring the records, their binding key and their "
        "schema registry, relative to the current folder; by default anagraphe.yml at the root, "
        "in .config/, or in config/."
    ),
)
PATHS_ARGUMENT = typer.Argument(
    None, help="Scope the run to these files or folders, under the root of the consumer."
)


def _scope(
    configuration: Configuration, changed: bool, paths: list[Path] | None
) -> list[str] | None:
    """Return the repository-relative paths of a scoped run, or None for a run on the whole root.

    Raises
    ------
    ConfigurationError
        If both `--changed` and paths are given, a path lies outside the root, or Git cannot list
        the changed files.
    """
    if changed and paths:
        raise ConfigurationError("--changed and explicit paths exclude each other")
    if changed:
        try:
            return changed_paths(configuration.root)
        except OSError as error:
            raise ConfigurationError(f"cannot list the changed files: {error}") from error
    if not paths:
        return None
    scope = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(configuration.root):
            raise ConfigurationError(f"{path} lies outside the root {configuration.root}")
        scope.append(configuration.relative(resolved) or ".")
    return scope


def _gate(
    root: Path | None, config: Path | None, changed: bool, paths: list[Path] | None
) -> tuple[Configuration, Report]:
    """Load the inputs, run the checks, judge them and write the merged log; exit 2 on an error."""
    try:
        resolved, path = discover_configuration(root, config)
        configuration = load_configuration(path, resolved)
        entries = (
            {}
            if configuration.suppressions is None
            else apply_renames(
                load_suppressions(configuration.suppressions),
                configuration.renames,
                configuration.suppressions,
            )
        )
        scope = _scope(configuration, changed, paths)
    except ConfigurationError as error:
        typer.echo(f"elenchos: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    outcomes = [run_check(check, configuration.root, scope) for check in configuration.checks]
    report = judge(configuration, outcomes, entries)
    try:
        write_log(report.log, configuration.output)
    except OSError as error:
        typer.echo(f"elenchos: cannot write {configuration.output}: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    return configuration, report


@app.command("check")
def cli_check(
    root: Optional[Path] = ROOT_OPTION,
    config: Optional[Path] = CONFIG_OPTION,
    changed: bool = CHANGED_OPTION,
    paths: Optional[list[Path]] = PATHS_ARGUMENT,
) -> None:
    """
    Run the declared checks, write the merged log, and exit 1 on an unsuppressed blocking result.

    A scoped run passes its paths to the checks of scope `paths`, and skips them when it holds no
    path; the checks of scope `root` check the whole root. The exit status is 0 when no result
    blocks, 1 when at least one unsuppressed result blocks (a failed or incomplete check and a
    stale suppression included), and 2 when an input is invalid, or the merged log cannot be
    written.
    """
    configuration, report = _gate(root, config, changed, paths)
    typer.echo("\n".join(render(report, configuration)))
    raise typer.Exit(EXIT_BLOCKED if report.blocked else EXIT_PASS)


# Typer takes one parameter per option of the command.
@app.command("update")
def cli_update(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    root: Optional[Path] = ROOT_OPTION,
    config: Optional[Path] = CONFIG_OPTION,
    prune: bool = typer.Option(False, "--prune", help="Remove the stale entries."),
    accept: Optional[str] = typer.Option(
        None,
        "--accept",
        help="Add an entry, with this justification, for every unsuppressed result of a producer.",
    ),
    author: Optional[str] = typer.Option(None, "--author", help="Author of the added entries."),
    only: Optional[list[str]] = typer.Option(
        None, "--only", help="Accept only the results of this check; repeatable."
    ),
    changed: bool = CHANGED_OPTION,
    paths: Optional[list[Path]] = PATHS_ARGUMENT,
) -> None:
    """
    Run the declared checks, then rewrite the suppressions file.

    Every entry is written under its current identity, so a renamed identity is settled. With
    `--prune`, the stale entries are removed; an unverified entry is kept. With `--accept`, every
    unsuppressed result of a producer receives an entry dated today, appended in the order of the
    log; the results of the gate are never accepted. `--only` restricts the accepted results to the
    named checks, so that each check receives its own justification. The exit status is 0 once the
    file is written, and 2 when an input is invalid, the configuration declares no suppressions
    file, or a file cannot be written.
    """
    configuration, report = _gate(root, config, changed, paths)
    if configuration.suppressions is None:
        typer.echo("elenchos: the configuration declares no suppressions file", err=True)
        raise typer.Exit(EXIT_ERROR)
    if accept is not None and not accept.strip():
        typer.echo("elenchos: --accept needs a justification that is not blank", err=True)
        raise typer.Exit(EXIT_ERROR)
    unknown = sorted(set(only or []) - {check.name for check in configuration.checks})
    if unknown:
        typer.echo(f"elenchos: --only names no declared check: {unknown}", err=True)
        raise typer.Exit(EXIT_ERROR)
    stale = set(report.stale) if prune else set()
    kept = [entry for entry in report.entries if entry.identity not in stale]
    added: list[Suppression] = []
    if accept is not None:
        today = datetime.date.today().isoformat()
        added = [
            Suppression(finding.identity, accept, today, author)
            for finding in report.findings
            if finding.check is not None
            and not finding.suppressed
            and (not only or finding.check in only)
        ]
    try:
        write_suppressions([*kept, *added], configuration.suppressions)
    except OSError as error:
        typer.echo(f"elenchos: cannot write {configuration.suppressions}: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    renamed = sum(entry.renamed_from is not None for entry in kept)
    typer.echo(
        f"{configuration.relative(configuration.suppressions)}: {len(kept) + len(added)} entries; "
        f"{renamed} renamed, {len(report.entries) - len(kept)} pruned, {len(added)} added"
    )
    raise typer.Exit(EXIT_PASS)


def _relative_scope(root: Path, paths: list[Path] | None) -> list[str] | None:
    """Return the repository-relative form of the paths of a scoped run, None without paths.

    Raises
    ------
    ConfigurationError
        If a path lies outside the root.
    """
    if not paths:
        return None
    scope = []
    for path in paths:
        full = path.resolve()
        if not full.is_relative_to(root):
            raise ConfigurationError(f"{path} lies outside the root {root}")
        scope.append(full.relative_to(root).as_posix() or ".")
    return scope


def _emit(report: str, output: Path | None) -> None:
    """Write a report to its file, or to the standard output; exit 2 when the file cannot be
    written."""
    try:
        if output is None:
            typer.echo(report, nl=False)
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8")
    except OSError as error:
        typer.echo(f"elenchos: cannot write {output}: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error


@app.command("validate")
def cli_validate(
    root: Optional[Path] = ROOT_OPTION,
    anagraphe_config: Optional[Path] = ANAGRAPHE_CONFIG_OPTION,
    output_format: str = typer.Option(
        "text", "--format", help="Report format: `text`, or `sarif` for a findings log."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="File of the report; standard output by default."
    ),
    paths: Optional[list[Path]] = PATHS_ARGUMENT,
) -> None:
    """
    Validate each record against the schema that its binding names.

    The records, their binding key and their schema registry are those that the configuration of
    Anagraphe declares: the file named by `--anagraphe-config`, else anagraphe.yml at the root, in
    .config/, or in config/. Paths restrict the report to the records below them. The exit status
    is 0 when no record breaks its schema, 1 when one does, and 2 when the check cannot run, a file
    named by `--anagraphe-config` and absent included; with `--format sarif`, the log then holds a
    failed run that states why.
    """
    try:
        # The check needs the extra `validate`, which the gate alone does not.
        # pylint: disable-next=import-outside-toplevel
        from .validate import sarif_log, text_lines, validate_repository
    except ImportError as error:
        typer.echo(f"elenchos: validate needs the extra elenchos[validate]: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    if output_format not in ("text", "sarif"):
        typer.echo(f"elenchos: --format takes text or sarif, not {output_format}", err=True)
        raise typer.Exit(EXIT_ERROR)
    try:
        resolved = discover_root(root)
        scope = _relative_scope(resolved, paths)
    except ConfigurationError as error:
        typer.echo(f"elenchos: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    outcome = validate_repository(resolved, scope, anagraphe_config)
    if output_format == "sarif":
        report = json.dumps(sarif_log(outcome), indent=2, ensure_ascii=False) + "\n"
    else:
        report = "\n".join(text_lines(outcome)) + "\n"
    _emit(report, output)
    if outcome.stopped is not None:
        if output is not None or output_format == "sarif":
            typer.echo(f"elenchos validate: {outcome.stopped}", err=True)
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(EXIT_BLOCKED if outcome.findings else EXIT_PASS)


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show the package version and exit."
    )
) -> None:
    """Root command for the package command-line interface."""
    if version:
        typer.echo(__version__)
        raise typer.Exit()
