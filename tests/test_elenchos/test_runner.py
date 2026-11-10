"""Tests of the runner of the gate on planted checks: fake producers writing SARIF, a failing
check, invalid logs, partial and failed runs, suppressed, stale and unverified entries, and
blocking and non-blocking levels."""

import json
from pathlib import Path
import sys
from typing import Any

import pytest
from typer.testing import CliRunner

from elenchos.cli import EXIT_BLOCKED, EXIT_ERROR, EXIT_PASS, app
from elenchos.config import Configuration, load_configuration
from elenchos.runner import (
    CHECK_FAILED,
    CHECK_INCOMPLETE,
    CHECK_INVALID_LOG,
    CHECK_MISSING_LOG,
    SUPPRESSION_STALE,
    Report,
    judge,
    run_check,
)
from elenchos.sarif import FINGERPRINT_KEY
from elenchos.suppressions import load_suppressions

FIXTURES = Path(__file__).parents[1] / "fixtures" / "gate"
VECTORS = Path(__file__).parents[2] / "specs" / "vectors"
REJECTED_CASES = [vector["case"] for vector in json.loads((VECTORS / "rejected.json").read_text())]

LINKER = "linker|links/broken"
SUPPRESSED = f"{LINKER}|path:a.md|link:x.md"
UNSUPPRESSED = f"{LINKER}|path:a.md|link:y.md"
FIRST_OCCURRENCE = f"{LINKER}|path:b.md|link:z.md"
SECOND_OCCURRENCE = f"{LINKER}|path:b.md|link:z.md||2"
STALE = f"{LINKER}|path:gone.md|link:q.md"


def command(script: str, *arguments: str) -> str:
    """A TOML array running one fake check with the interpreter of the tests."""
    return json.dumps([sys.executable, str(FIXTURES / script), *arguments])


def checks_toml(*broken_modes: str, stopping: str | None = None) -> str:
    """The two fake producers, followed by one misbehaving check per mode, then the check of the
    tool `stopper` ending as `stopping` says, when given."""
    text = f"""
[checks.linker]
command = {command("linker_check.py", "logs/linker.sarif")}
log = "logs/linker.sarif"

[checks.terms]
command = {command("terms_check.py", "logs/terms.sarif")}
log = "logs/terms.sarif"
block = ["error", "warning"]
"""
    for index, mode in enumerate(broken_modes):
        text += f"""
[checks.broken-{index}]
command = {command("broken_check.py", mode, f"logs/broken-{index}.sarif")}
log = "logs/broken-{index}.sarif"
"""
    if stopping is not None:
        text += f"""
[checks.stopper]
command = {command("stopping_check.py", stopping, "logs/stopper.sarif")}
log = "logs/stopper.sarif"
"""
    return text


def consumer(
    root: Path,
    *broken_modes: str,
    entries: list[dict[str, Any]] | None = None,
    rules: str = '"terms|terms/advice" = []',
    stopping: str | None = None,
) -> Path:
    """Write a consumer under `root`: its configuration in `config/tools/`, and its suppressions."""
    if entries is None:
        entries = [
            {"identity": SUPPRESSED, "justification": "tolerated when the gate started"},
            {"identity": FIRST_OCCURRENCE, "justification": "counted once", "date": "2026-10-15"},
            {"identity": STALE, "justification": "fixed since", "author": "E. P."},
        ]
    (root / "specs").mkdir(parents=True, exist_ok=True)
    (root / "specs" / "suppressions.json").write_text(
        json.dumps({"version": 1, "suppressions": entries}), encoding="utf-8"
    )
    path = root / "config" / "tools" / "elenchos.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""version = 3
output = "build/gate.sarif"
suppressions = "specs/suppressions.json"

[policy]
block = ["error"]

[policy.rules]
{rules}
""" + checks_toml(*broken_modes, stopping=stopping),
        encoding="utf-8",
    )
    return path


def gate(path: Path) -> tuple[Configuration, Report]:
    """Run every check of a consumer and judge their outcomes, without the command line."""
    configuration = load_configuration(path, path.parents[2])
    assert configuration.suppressions is not None
    outcomes = [run_check(check, configuration.root) for check in configuration.checks]
    return configuration, judge(
        configuration, outcomes, load_suppressions(configuration.suppressions)
    )


def verdicts(report: Report) -> dict[str, tuple[bool, bool]]:
    """Map each identity to whether it is suppressed and whether it blocks."""
    return {f.identity: (f.suppressed, f.blocking) for f in report.findings}


def gate_rules(report: Report) -> list[str]:
    """Rule of each result of the run of the gate."""
    return [result["ruleId"] for result in report.log["runs"][-1]["results"]]


# --- Suppressions, ordinals and levels --------------------------------------------------------


def test_suppressed_and_unsuppressed_results(tmp_path: Path) -> None:
    """A suppressed error does not block; an unsuppressed error blocks."""
    _, report = gate(consumer(tmp_path))
    assert verdicts(report)[SUPPRESSED] == (True, False)
    assert verdicts(report)[UNSUPPRESSED] == (False, True)
    assert report.blocked


def test_identical_occurrences_are_suppressed_one_by_one(tmp_path: Path) -> None:
    """Two identical occurrences receive ordinals in line order; the suppression of the first
    leaves the second blocking."""
    _, report = gate(consumer(tmp_path))
    assert verdicts(report)[FIRST_OCCURRENCE] == (True, False)
    assert verdicts(report)[SECOND_OCCURRENCE] == (False, True)


def test_levels_block_by_rule_then_check_then_default(tmp_path: Path) -> None:
    """A warning does not block by default, blocks when its check declares it, and does not
    block when its rule declares no level; a note outside the levels of its check does not block."""
    _, report = gate(consumer(tmp_path))
    found = verdicts(report)
    assert found["linker|links/style|path:a.md"] == (False, False)
    assert found["terms|terms/forbidden|path:c.md|term:competition"] == (False, True)
    assert found["terms|terms/advice|path:c.md|term:rivalry"] == (False, False)
    assert found["terms|terms/hint|path:c.md"] == (False, False)


def test_suppression_carries_justification_date_and_author(tmp_path: Path) -> None:
    """A matched entry becomes an accepted external suppression with its justification."""
    _, report = gate(consumer(tmp_path))
    results = {
        r["fingerprints"][FINGERPRINT_KEY]: r for run in report.log["runs"] for r in run["results"]
    }
    assert results[FIRST_OCCURRENCE]["suppressions"] == [
        {
            "kind": "external",
            "status": "accepted",
            "justification": "counted once",
            "properties": {"elenchos/date": "2026-10-15"},
        }
    ]
    assert results[UNSUPPRESSED]["suppressions"] == []


# --- Stale suppressions -----------------------------------------------------------------------


def test_stale_suppression_is_reported_and_blocks(tmp_path: Path) -> None:
    """An entry matching no result yields a blocking result of the gate, carrying the entry."""
    _, report = gate(consumer(tmp_path))
    stale = (
        f"elenchos|{SUPPRESSION_STALE}|path:specs/suppressions.json||{STALE.replace('|', '%7C')}"
    )
    assert verdicts(report)[stale] == (False, True)
    assert gate_rules(report) == [SUPPRESSION_STALE]


def test_stale_suppression_follows_the_policy_of_its_rule(tmp_path: Path) -> None:
    """The consumer may declare the stale rule non-blocking; the entry is still reported."""
    path = consumer(tmp_path, rules='"terms|terms/advice" = []\n"elenchos|suppression/stale" = []')
    _, report = gate(path)
    assert gate_rules(report) == [SUPPRESSION_STALE]
    assert not any(f.blocking for f in report.findings if f.check is None)


def test_entry_of_a_tool_that_never_ran_is_stale_when_every_check_succeeds(tmp_path: Path) -> None:
    """A suppression of a tool absent from every valid run is stale when no check failed."""
    entries = [{"identity": "ghost|r/x|path:a.md", "justification": "removed tool"}]
    _, report = gate(consumer(tmp_path, entries=entries))
    assert gate_rules(report) == [SUPPRESSION_STALE]
    assert report.unverified == ()


def test_entry_of_a_failed_check_is_unverified_not_stale(tmp_path: Path) -> None:
    """When a check fails, a suppression whose tool yielded no valid run cannot be checked."""
    entries = [
        {"identity": "ghost|r/x|path:a.md", "justification": "held by the failed check"},
        {"identity": STALE, "justification": "linker ran, so this one is stale"},
    ]
    _, report = gate(consumer(tmp_path, "crash", entries=entries))
    assert gate_rules(report) == [CHECK_FAILED, SUPPRESSION_STALE]
    assert report.unverified == ("ghost|r/x|path:a.md",)


# --- Partial and failed runs ------------------------------------------------------------------

STOPPED = "stopper|stage/failed|path:s.md"
BEYOND_STOP = "stopper|stage/later|path:t.md"
STOPPER_DECLARATION = f"elenchos|{CHECK_INCOMPLETE}|path:config/tools/elenchos.toml|/checks/stopper"


def stopper_entries() -> list[dict[str, Any]]:
    """An entry matching the result of the stopper, one beyond its stop, and one stale entry."""
    return [
        {"identity": STOPPED, "justification": "tolerated first failure"},
        {"identity": BEYOND_STOP, "justification": "held by a later stage"},
        {"identity": STALE, "justification": "linker ran in full, so this one is stale"},
    ]


def test_entry_of_a_partial_run_is_unverified_not_stale(tmp_path: Path) -> None:
    """A run stopped by design keeps its results, which suppressions match; an unmatched entry of
    its tool is unverified, and the check is reported as incomplete, blocking."""
    path = consumer(tmp_path, entries=stopper_entries(), stopping="partial")
    _, report = gate(path)
    assert verdicts(report)[STOPPED] == (True, False)
    assert report.unverified == (BEYOND_STOP,)
    assert gate_rules(report) == [CHECK_INCOMPLETE, SUPPRESSION_STALE]
    assert verdicts(report)[STOPPER_DECLARATION] == (False, True)
    message = report.log["runs"][-1]["results"][0]["message"]["text"]
    assert message == (
        "check stopper: run of stopper is incomplete: "
        "stopped at the first failure; later stages skipped"
    )


def test_failed_run_without_results_is_reported_and_leaves_its_entries_unverified(
    tmp_path: Path,
) -> None:
    """A producer reporting its own crash omits its results; its run enters the merged log, the
    check is reported as incomplete, and every entry of its tool is unverified."""
    path = consumer(tmp_path, entries=stopper_entries(), stopping="failed")
    _, report = gate(path)
    assert report.unverified == (STOPPED, BEYOND_STOP)
    assert gate_rules(report) == [CHECK_INCOMPLETE, SUPPRESSION_STALE]
    assert "results" not in report.log["runs"][2]
    message = report.log["runs"][-1]["results"][0]["message"]["text"]
    assert message == "check stopper: run of stopper is incomplete: executionSuccessful is false"
    assert invoke(path).exit_code == EXIT_BLOCKED


def test_entry_of_a_run_declaring_success_is_stale(tmp_path: Path) -> None:
    """A run whose invocation succeeded is complete, so an unmatched entry of its tool is stale."""
    path = consumer(tmp_path, entries=stopper_entries()[1:], stopping="succeeded")
    _, report = gate(path)
    assert report.unverified == ()
    assert gate_rules(report) == [SUPPRESSION_STALE, SUPPRESSION_STALE]


# --- Failing checks and invalid logs ----------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "rule"),
    [
        ("crash", CHECK_FAILED),
        ("silent", CHECK_MISSING_LOG),
        ("garbage", CHECK_INVALID_LOG),
        ("level", CHECK_INVALID_LOG),
    ],
)
def test_misbehaving_check_is_reported_at_its_declaration(
    tmp_path: Path, mode: str, rule: str
) -> None:
    """A crash, a missing log or an invalid log yields one blocking result of the gate, located
    at the declaration of the check, and the other checks still report."""
    _, report = gate(consumer(tmp_path, mode, entries=[]))
    identity = f"elenchos|{rule}|path:config/tools/elenchos.toml|/checks/broken-0"
    assert verdicts(report)[identity] == (False, True)
    assert UNSUPPRESSED in verdicts(report)


@pytest.mark.parametrize("case", REJECTED_CASES)
def test_log_described_by_a_rejected_vector_is_invalid(tmp_path: Path, case: str) -> None:
    """A check writing the log of a rejected vector is reported as an invalid log."""
    _, report = gate(consumer(tmp_path, f"vector:{case}", entries=[]))
    assert gate_rules(report) == [CHECK_INVALID_LOG]
    assert len(report.log["runs"]) == 3


def test_failing_check_message_names_the_status_and_the_error(tmp_path: Path) -> None:
    """The message of a failed check holds its exit status and its last line of error output."""
    _, report = gate(consumer(tmp_path, "crash", entries=[]))
    message = report.log["runs"][-1]["results"][0]["message"]["text"]
    assert message == (
        "check broken-0: command exited with status 3: RuntimeError: the checker crashed"
    )


def test_log_of_an_earlier_run_is_never_read(tmp_path: Path) -> None:
    """A log left on disk by an earlier run is deleted before its check runs again."""
    path = consumer(tmp_path, "silent", entries=[])
    leftover = tmp_path / "logs" / "broken-0.sarif"
    leftover.parent.mkdir(parents=True)
    run = {"tool": {"driver": {"name": "old"}}, "results": []}
    leftover.write_text(json.dumps({"version": "2.1.0", "runs": [run]}))
    _, report = gate(path)
    assert gate_rules(report) == [CHECK_MISSING_LOG]
    assert not leftover.exists()


def test_log_path_that_cannot_be_deleted_is_a_failed_check(tmp_path: Path) -> None:
    """A declared log path holding a folder is reported, not raised."""
    path = consumer(tmp_path, "silent", entries=[])
    (tmp_path / "logs" / "broken-0.sarif").mkdir(parents=True)
    _, report = gate(path)
    assert gate_rules(report) == [CHECK_FAILED]


def test_command_that_cannot_start_is_a_failed_check(tmp_path: Path) -> None:
    """A command absent from the system is reported, not raised."""
    path = consumer(tmp_path, entries=[])
    path.write_text(
        path.read_text().replace(command("linker_check.py", "logs/linker.sarif"), '["no-such-x"]')
    )
    _, report = gate(path)
    assert gate_rules(report) == [CHECK_FAILED]


# --- Merged log -------------------------------------------------------------------------------


def test_merged_log_holds_one_run_per_producer_and_unaltered_tools(tmp_path: Path) -> None:
    """The merged log holds each producer run with its tool unchanged, then the run of the gate;
    every result of every run carries an identity and a suppressions array."""
    configuration, report = gate(consumer(tmp_path))
    names = [run["tool"]["driver"]["name"] for run in report.log["runs"]]
    assert names == ["linker", "terms", "elenchos"]
    written = json.loads((tmp_path / "logs" / "linker.sarif").read_text())
    assert report.log["runs"][0]["tool"] == written["runs"][0]["tool"]
    for run in report.log["runs"]:
        for result in run["results"]:
            assert FINGERPRINT_KEY in result["fingerprints"]
            assert isinstance(result["suppressions"], list)
    assert configuration.output == tmp_path / "build" / "gate.sarif"


# --- Command line and exit statuses -----------------------------------------------------------


def invoke(path: Path) -> Any:
    """Run `elenchos check` on the root of a consumer, which holds the configuration file."""
    return CliRunner().invoke(app, ["check", "--root", str(path.parents[2])])


def test_cli_exits_1_on_a_blocking_result_and_writes_the_log(tmp_path: Path) -> None:
    """An unsuppressed blocking result gives exit status 1, after the log is written."""
    outcome = invoke(consumer(tmp_path))
    assert outcome.exit_code == EXIT_BLOCKED
    assert "gate: fail" in outcome.output
    assert json.loads((tmp_path / "build" / "gate.sarif").read_text())["version"] == "2.1.0"


def test_cli_exits_0_when_every_blocking_result_is_suppressed(tmp_path: Path) -> None:
    """With every blocking result suppressed and no stale entry, the gate passes."""
    entries = [
        {"identity": identity, "justification": "accepted debt"}
        for identity in (
            SUPPRESSED,
            UNSUPPRESSED,
            FIRST_OCCURRENCE,
            SECOND_OCCURRENCE,
            "terms|terms/forbidden|path:c.md|term:competition",
        )
    ]
    outcome = invoke(consumer(tmp_path, entries=entries))
    assert outcome.exit_code == EXIT_PASS, outcome.output
    assert outcome.output.splitlines()[-1] == "gate: pass"


def test_cli_exits_2_on_an_invalid_suppressions_file(tmp_path: Path) -> None:
    """An entry without justification makes the gate refuse to run."""
    outcome = invoke(consumer(tmp_path, entries=[{"identity": SUPPRESSED}]))
    assert outcome.exit_code == EXIT_ERROR
    assert not (tmp_path / "build" / "gate.sarif").exists()


def test_cli_exits_2_on_a_missing_configuration(tmp_path: Path) -> None:
    """A file named by --config and absent, or a root holding no file, makes the gate refuse to
    run."""
    runner = CliRunner()
    named = ["check", "--root", str(tmp_path), "--config", str(tmp_path / "absent.toml")]
    assert runner.invoke(app, named).exit_code == EXIT_ERROR
    assert runner.invoke(app, ["check", "--root", str(tmp_path)]).exit_code == EXIT_ERROR


def test_cli_finds_the_root_from_a_subfolder(tmp_path: Path, monkeypatch: Any) -> None:
    """Without --root and ELENCHOS_ROOT, the root is the nearest ancestor holding the file."""
    consumer(tmp_path)
    (tmp_path / "docs").mkdir()
    monkeypatch.delenv("ELENCHOS_ROOT", raising=False)
    monkeypatch.chdir(tmp_path / "docs")
    outcome = CliRunner().invoke(app, ["check"])
    assert outcome.exit_code == EXIT_BLOCKED, outcome.output
    assert (tmp_path / "build" / "gate.sarif").is_file()


def test_cli_reads_the_root_from_the_environment(tmp_path: Path, monkeypatch: Any) -> None:
    """ELENCHOS_ROOT names the root when --root is absent; --root overrides it."""
    consumer(tmp_path / "consumer")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    monkeypatch.setenv("ELENCHOS_ROOT", str(tmp_path / "consumer"))
    runner = CliRunner()
    assert runner.invoke(app, ["check"]).exit_code == EXIT_BLOCKED
    overridden = runner.invoke(app, ["check", "--root", str(tmp_path / "elsewhere")])
    assert overridden.exit_code == EXIT_ERROR
    assert "no configuration file" in overridden.output
