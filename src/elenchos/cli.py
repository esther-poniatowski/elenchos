"""
Command-line interface for the `elenchos` package.

Defines commands available via `python -m elenchos` or `elenchos` if installed as a script.

Commands
--------
info : Display diagnostic information.
check : Run the checks declared by a consumer, write the merged log, and gate on its results.

See Also
--------
typer.Typer
    Library for building CLI applications: https://typer.tiangolo.com/
"""

from pathlib import Path

import typer

from . import info, __version__
from .config import Configuration, load_configuration
from .errors import ConfigurationError
from .runner import Report, judge, run_check, write_log
from .sarif import GATE_TOOL
from .suppressions import load_suppressions

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
    for name in [check.name for check in configuration.checks] + [None]:
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
            "incomplete run, or no run while a check failed"
        )
    lines.append(f"log written to {configuration.output}")
    lines.append("gate: fail" if report.blocked else "gate: pass")
    return lines


@app.command("check")
def cli_check(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Configuration file of the consumer, declaring its checks, policy and suppressions.",
    )
) -> None:
    """
    Run the declared checks, write the merged log, and exit 1 on an unsuppressed blocking result.

    The exit status is 0 when no result blocks, 1 when at least one unsuppressed result blocks
    (a failed or incomplete check and a stale suppression included), and 2 when the configuration
    or the suppressions file is invalid, or the merged log cannot be written.
    """
    try:
        configuration = load_configuration(config)
        suppressions = (
            {}
            if configuration.suppressions is None
            else load_suppressions(configuration.suppressions)
        )
    except ConfigurationError as error:
        typer.echo(f"elenchos: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    outcomes = [run_check(check, configuration.root) for check in configuration.checks]
    report = judge(configuration, outcomes, suppressions)
    try:
        write_log(report.log, configuration.output)
    except OSError as error:
        typer.echo(f"elenchos: cannot write {configuration.output}: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from error
    typer.echo("\n".join(render(report, configuration)))
    raise typer.Exit(EXIT_BLOCKED if report.blocked else EXIT_PASS)


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
