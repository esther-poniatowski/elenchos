"""Tests of the rename maps of the configuration: rename maps applied to stored suppressions, scoped runs
on the paths of a check of scope `paths`, the listing of changed files, and the command `update`
that prunes, accepts and rewrites the entries of a suppressions file."""

import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
from typer.testing import CliRunner

from elenchos.cli import EXIT_BLOCKED, EXIT_PASS, app
from elenchos.config import Renames, load_configuration
from elenchos.errors import ConfigurationError
from elenchos.runner import changed_paths, judge, run_check
from elenchos.suppressions import Suppression, apply_renames, load_suppressions

FIXTURES = Path(__file__).parents[1] / "fixtures" / "gate"

IN_A = "scoper|links/broken|path:a.md|link:x.md"
IN_B = "scoper|links/broken|path:b.md|link:y.md"
GONE = "scoper|links/broken|path:a.md|link:gone.md"


def command(script: str, *arguments: str) -> str:
    """A TOML array running one fake check with the interpreter of the tests."""
    return json.dumps([sys.executable, str(FIXTURES / script), *arguments])


def consumer(root: Path, entries: list[dict[str, Any]], renames: str = "") -> Path:
    """Write a consumer whose single check accepts paths, its configuration at the root."""
    (root / "suppressions.json").write_text(
        json.dumps({"version": 1, "suppressions": entries}), encoding="utf-8"
    )
    path = root / "elenchos.toml"
    path.write_text(
        f"""version = 3
output = "build/gate.sarif"
suppressions = "suppressions.json"

[policy]
block = ["error"]
{renames}
[checks.scoper]
command = {command("scoped_check.py", "logs/scoper.sarif")}
log = "logs/scoper.sarif"
scope = "paths"
""",
        encoding="utf-8",
    )
    return path


def gate(path: Path, scope: list[str] | None = None):
    """Run the check of a consumer, its stored suppressions renamed, and judge the outcome."""
    configuration = load_configuration(path, path.parent)
    assert configuration.suppressions is not None
    entries = apply_renames(
        load_suppressions(configuration.suppressions),
        configuration.renames,
        configuration.suppressions,
    )
    outcomes = [run_check(check, configuration.root, scope) for check in configuration.checks]
    return judge(configuration, outcomes, entries)


def entry(identity: str) -> dict[str, str]:
    return {"identity": identity, "justification": "tolerated"}


# --- Rename maps ---------------------------------------------------------------------------------


def test_a_renamed_rule_and_resource_still_suppress_their_finding(tmp_path: Path) -> None:
    """An entry written under the former tool, rule and resource suppresses the current finding,
    and the suppression records the identity written in the file."""
    old = "linker|links/missing|path:old/a.md|link:x.md"
    path = consumer(
        tmp_path,
        [entry(old), entry(IN_B)],
        renames='\n[renames.rules]\n"linker|links/missing" = "scoper|links/broken"\n'
        '\n[renames.resources]\n"path:old/a.md" = "path:a.md"\n',
    )
    report = gate(path)
    assert not report.blocked and not report.stale
    result = report.log["runs"][0]["results"][0]
    assert result["suppressions"][0]["properties"]["elenchos/renamed-from"] == old


def test_two_entries_renamed_onto_one_identity_are_rejected() -> None:
    renames = Renames(rules={"linker|links/missing": "scoper|links/broken"})
    old = "linker|links/missing|path:a.md|link:x.md"
    entries = {text: Suppression(text, "t") for text in (old, IN_A)}
    with pytest.raises(ConfigurationError, match="both become"):
        apply_renames(entries, renames, Path("s.json"))


def test_a_rename_map_that_renames_a_value_again_is_rejected(tmp_path: Path) -> None:
    path = consumer(
        tmp_path,
        [],
        renames='\n[renames.rules]\n"a|r" = "b|r"\n"b|r" = "c|r"\n',
    )
    with pytest.raises(ConfigurationError, match="again"):
        load_configuration(path, path.parent)


# --- Scoped runs ---------------------------------------------------------------------------------


def test_a_scoped_run_checks_its_paths_and_leaves_other_entries_unverified(
    tmp_path: Path,
) -> None:
    """The check receives the scope: the entry of a file outside it is unverified, while an
    unmatched entry of a file inside it is stale."""
    report = gate(consumer(tmp_path, [entry(IN_B), entry(GONE)]), scope=["a.md"])
    assert [finding.identity for finding in report.findings if finding.check] == [IN_A]
    assert report.unverified == (IN_B,)
    assert report.stale == (GONE,)


def test_a_folder_in_the_scope_covers_the_files_below_it(tmp_path: Path) -> None:
    report = gate(consumer(tmp_path, [entry(GONE)]), scope=["."])
    assert report.stale == (GONE,)


def test_a_scoped_run_without_paths_skips_the_check(tmp_path: Path) -> None:
    report = gate(consumer(tmp_path, [entry(IN_A)]), scope=[])
    assert report.skipped == ("scoper",)
    assert report.unverified == (IN_A,) and not report.stale and not report.blocked


def test_changed_paths_lists_modified_and_untracked_files(tmp_path: Path) -> None:
    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "T")
    for name in ("kept.md", "edited.md", "deleted.md"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "start")
    (tmp_path / "edited.md").write_text("y\n", encoding="utf-8")
    (tmp_path / "deleted.md").unlink()
    (tmp_path / "new.md").write_text("z\n", encoding="utf-8")
    (tmp_path / "ignored.md").write_text("z\n", encoding="utf-8")
    assert changed_paths(tmp_path) == ["edited.md", "new.md"]


# --- Command update ------------------------------------------------------------------------------


def test_update_prunes_accepts_and_rewrites_then_the_gate_passes(tmp_path: Path) -> None:
    old = "linker|links/missing|path:a.md|link:x.md"
    path = consumer(
        tmp_path,
        [entry(old), entry(GONE)],
        renames='\n[renames.rules]\n"linker|links/missing" = "scoper|links/broken"\n',
    )
    runner = CliRunner()
    assert runner.invoke(app, ["check", "--root", str(tmp_path)]).exit_code == EXIT_BLOCKED
    updated = runner.invoke(
        app,
        ["update", "--root", str(tmp_path), "--prune", "--accept", "frozen", "--author", "E. P."],
    )
    assert updated.exit_code == EXIT_PASS, updated.output
    assert "1 renamed, 1 pruned, 1 added" in updated.output
    stored = json.loads((tmp_path / "suppressions.json").read_text(encoding="utf-8"))
    assert stored["suppressions"] == [
        entry(IN_A),
        {
            "identity": IN_B,
            "justification": "frozen",
            "date": datetime.date.today().isoformat(),
            "author": "E. P.",
        },
    ]
    assert runner.invoke(app, ["check", "--root", str(tmp_path)]).exit_code == EXIT_PASS


def test_update_keeps_unverified_entries(tmp_path: Path) -> None:
    path = consumer(tmp_path, [entry(IN_B)])
    arguments = ["update", "-r", str(tmp_path), "-c", str(path), "--prune", str(tmp_path / "a.md")]
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == EXIT_PASS, result.output
    stored = json.loads((tmp_path / "suppressions.json").read_text(encoding="utf-8"))
    assert [item["identity"] for item in stored["suppressions"]] == [IN_B]


def test_update_accepts_only_the_results_of_the_named_checks(tmp_path: Path) -> None:
    consumer(tmp_path, [])
    runner = CliRunner()
    unknown = runner.invoke(
        app, ["update", "--root", str(tmp_path), "--accept", "x", "--only", "nope"]
    )
    assert unknown.exit_code == 2
    none = runner.invoke(
        app, ["update", "--root", str(tmp_path), "--accept", "x", "--only", "scoper"]
    )
    assert none.exit_code == EXIT_PASS and "2 added" in none.output


def test_update_no_longer_reads_the_retired_check_filter(tmp_path: Path) -> None:
    """`--check` is reserved for a run that writes nothing; the filter is `--only`, without
    alias."""
    consumer(tmp_path, [])
    retired = CliRunner().invoke(
        app, ["update", "--root", str(tmp_path), "--accept", "x", "--check", "scoper"]
    )
    assert retired.exit_code == 2
    assert not (tmp_path / "build" / "gate.sarif").exists()
