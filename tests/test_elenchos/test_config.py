"""Tests of the configuration and suppressions formats, and of their agreement with the published
JSON Schemas."""

import copy
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from elenchos.config import (
    DEFAULT_EXIT_CODES,
    Check,
    find_root,
    locate_configuration,
    parse_configuration,
)
from elenchos.errors import ConfigurationError, ProfileError
from elenchos.sarif import check_log
from elenchos.suppressions import parse_suppressions, write_suppressions

SPECS = Path(__file__).parents[2] / "specs"
ROOT = Path("/consumer")
CONFIG_PATH = ROOT / "config" / "tools" / "elenchos.toml"

VALID_CONFIGURATION: dict[str, Any] = {
    "_schema": "elenchos:configuration@3",
    "output": "build/gate.sarif",
    "suppressions": "specs/suppressions.json",
    "policy": {"block": ["error"], "rules": {"terms|terms/advice": []}},
    "checks": {
        "links": {"command": ["check-links"], "log": "logs/links.sarif"},
        "terms": {
            "command": ["check-terms", "--sarif"],
            "log": "logs/terms.sarif",
            "exit_codes": [0],
            "block": ["error", "warning"],
        },
    },
}

VALID_SUPPRESSIONS: dict[str, Any] = {
    "_schema": "elenchos:suppressions@1",
    "suppressions": [
        {
            "identity": "geonexus|links/broken|path:a.md|link:b.md",
            "justification": "tolerated when the gate started",
            "date": "2026-10-15",
            "author": "Esther Poniatowski",
        },
        {"identity": "geonexus|links/broken|path:a.md|link:b.md||2", "justification": "twice"},
    ],
}


def edited(base: dict[str, Any], edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """A deep copy of a document after one edit."""
    document = copy.deepcopy(base)
    edit(document)
    return document


# Each edit breaks a rule that both the loader and the published schema state.
CONFIGURATION_EDITS: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown-key": lambda d: d.update(extra=1),
    "version-2": lambda d: d.update(version=2),
    "retired-root": lambda d: d.update(root=".."),
    "old-key": lambda d: (d.pop("_schema"), d.update(version=3)),
    "no-schema": lambda d: d.pop("_schema"),
    "wrong-schema": lambda d: d.update(_schema="elenchos:configuration@2"),
    "other-tool-schema": lambda d: d.update(_schema="ktisma:configuration@2"),
    "unknown-scope": lambda d: d["checks"]["links"].update(scope="all"),
    "bad-rename-rule": lambda d: d.update(renames={"rules": {"a|b": "c"}}),
    "bad-rename-resource": lambda d: d.update(
        renames={"resources": {"docs/a.md": "path:docs/b.md"}}
    ),
    "no-policy-block": lambda d: d["policy"].pop("block"),
    "unknown-level": lambda d: d["policy"].update(block=["fatal"]),
    "repeated-level": lambda d: d["policy"].update(block=["error", "error"]),
    "bad-rule-key": lambda d: d["policy"]["rules"].update({"terms/advice": []}),
    "no-check": lambda d: d.update(checks={}),
    "bad-check-name": lambda d: d["checks"].update({"Links": d["checks"]["links"]}),
    "empty-command": lambda d: d["checks"]["links"].update(command=[]),
    "boolean-exit-code": lambda d: d["checks"]["links"].update(exit_codes=[True]),
    "unknown-check-key": lambda d: d["checks"]["links"].update(shell=True),
}

SUPPRESSION_EDITS: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown-key": lambda d: d.update(extra=1),
    "version-2": lambda d: d.update(version=2),
    "old-key": lambda d: (d.pop("_schema"), d.update(version=1)),
    "no-schema": lambda d: d.pop("_schema"),
    "wrong-schema": lambda d: d.update(_schema="elenchos:suppressions@9"),
    "other-tool-schema": lambda d: d.update(_schema="elenchos:configuration@3"),
    "no-justification": lambda d: d["suppressions"][0].pop("justification"),
    "blank-justification": lambda d: d["suppressions"][0].update(justification="  "),
    "bad-date": lambda d: d["suppressions"][0].update(date="15/10/2026"),
    "unknown-entry-key": lambda d: d["suppressions"][0].update(reason="x"),
}


# --- Configuration ----------------------------------------------------------------------------


def test_valid_configuration_resolves_paths_against_the_root() -> None:
    """Relative paths resolve against the root, not against the folder of the file."""
    configuration = parse_configuration(VALID_CONFIGURATION, CONFIG_PATH, ROOT)
    root = ROOT.resolve()
    assert configuration.root == root
    assert configuration.output == root / "build" / "gate.sarif"
    assert configuration.checks[0].log == root / "logs" / "links.sarif"
    assert configuration.checks[0].exit_codes == DEFAULT_EXIT_CODES
    assert configuration.relative(configuration.path) == "config/tools/elenchos.toml"


def test_output_and_logs_default_to_the_build_folder_of_the_tool() -> None:
    """Without `output` and `log`, the results go to `build/elenchos/`, one log per check name."""

    def edit(document: dict[str, Any]) -> None:
        document.pop("output")
        document["checks"]["links"].pop("log")

    configuration = parse_configuration(edited(VALID_CONFIGURATION, edit), CONFIG_PATH, ROOT)
    root = ROOT.resolve()
    assert configuration.output == root / "build" / "elenchos" / "gate.sarif"
    assert configuration.checks[0].log == root / "build" / "elenchos" / "links.sarif"
    assert configuration.checks[1].log == root / "logs" / "terms.sarif"


def test_the_placeholder_names_the_log_in_each_argument() -> None:
    """`{log}` is replaced by the absolute path of the log, inside any argument of the command."""
    check = Check("links", ("check-links", "--output={log}", "{log}", "--root"), Path("/r/l.sarif"))
    assert check.arguments == ("check-links", "--output=/r/l.sarif", "/r/l.sarif", "--root")
    assert check.command == ("check-links", "--output={log}", "{log}", "--root")


def test_checks_keep_the_order_of_the_file() -> None:
    """Checks run in the order in which the file declares them."""
    configuration = parse_configuration(VALID_CONFIGURATION, CONFIG_PATH, ROOT)
    assert [check.name for check in configuration.checks] == ["links", "terms"]


@pytest.mark.parametrize("case", sorted(CONFIGURATION_EDITS))
def test_invalid_configuration_is_rejected(case: str) -> None:
    """Each planted breach of the format is rejected by the loader."""
    with pytest.raises(ConfigurationError):
        parse_configuration(
            edited(VALID_CONFIGURATION, CONFIGURATION_EDITS[case]), CONFIG_PATH, ROOT
        )


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(suppressions="../outside.json"),
        lambda d: d["checks"]["terms"].update(log="logs/links.sarif"),
        lambda d: d.update(output="logs/links.sarif"),
        lambda d: (d.pop("output"), d["checks"].update(gate={"command": ["check-gate"]})),
        lambda d: (
            d["checks"]["links"].pop("log"),
            d["checks"]["terms"].update(log="build/elenchos/links.sarif"),
        ),
    ],
    ids=["suppressions-outside", "shared-log", "output-is-a-log", "default-output-is-a-default-log",
         "log-is-a-default-log"],
)
def test_path_rules_beyond_the_schema_are_rejected(edit: Callable[[dict[str, Any]], None]) -> None:
    """The loader rejects the path rules that a JSON Schema cannot state."""
    with pytest.raises(ConfigurationError):
        parse_configuration(edited(VALID_CONFIGURATION, edit), CONFIG_PATH, ROOT)


def test_a_root_that_excludes_the_configuration_file_is_rejected() -> None:
    """The gate names the configuration file as a resource under the root, so it lies there."""
    with pytest.raises(ConfigurationError, match="does not contain"):
        parse_configuration(VALID_CONFIGURATION, CONFIG_PATH, ROOT / "sub")


# --- Root and place of the configuration file -------------------------------------------------


def test_the_root_is_the_nearest_ancestor_holding_a_configuration_file(tmp_path: Path) -> None:
    """The search stops at the nearest folder holding the file, in `config/tools/` or at its
    level, and falls back to the start folder."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    (outer / "config" / "tools").mkdir(parents=True)
    (outer / "config" / "tools" / "elenchos.toml").write_text("")
    (inner / "docs").mkdir(parents=True)
    (inner / "elenchos.toml").write_text("")
    assert find_root(inner / "docs") == inner.resolve()
    assert find_root(outer / "config") == outer.resolve()
    assert find_root(tmp_path) == tmp_path.resolve()


def test_the_configuration_is_found_in_either_place(tmp_path: Path) -> None:
    """Without --config, the file is `config/tools/elenchos.toml` or `elenchos.toml`."""
    (tmp_path / "elenchos.toml").write_text("")
    assert locate_configuration(tmp_path, None) == tmp_path / "elenchos.toml"
    (tmp_path / "elenchos.toml").unlink()
    (tmp_path / "config" / "tools").mkdir(parents=True)
    (tmp_path / "config" / "tools" / "elenchos.toml").write_text("")
    assert locate_configuration(tmp_path, None) == tmp_path / "config" / "tools" / "elenchos.toml"


def test_two_competing_configuration_files_are_rejected(tmp_path: Path) -> None:
    """Both places holding a file is an error naming both."""
    (tmp_path / "config" / "tools").mkdir(parents=True)
    (tmp_path / "config" / "tools" / "elenchos.toml").write_text("")
    (tmp_path / "elenchos.toml").write_text("")
    with pytest.raises(ConfigurationError) as error:
        locate_configuration(tmp_path, None)
    assert "config/tools/elenchos.toml" in str(error.value)
    assert str(tmp_path / "elenchos.toml") in str(error.value)


@pytest.mark.parametrize(
    "name", [".elenchos.toml", "config/elenchos.toml"], ids=["dotted", "config-folder"]
)
def test_a_configuration_file_elsewhere_is_not_read(tmp_path: Path, name: str) -> None:
    """Only the two conventional places are searched; a former place is not a fallback."""
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_text("")
    with pytest.raises(ConfigurationError, match="no configuration file"):
        locate_configuration(tmp_path, None)


def test_an_absent_file_named_by_config_is_rejected(tmp_path: Path) -> None:
    """A file named by --config and absent is an error, even when a default file exists."""
    (tmp_path / "elenchos.toml").write_text("")
    with pytest.raises(ConfigurationError, match="does not exist"):
        locate_configuration(tmp_path, tmp_path / "missing.toml")


# --- Suppressions -----------------------------------------------------------------------------


def test_valid_suppressions_are_keyed_by_identity() -> None:
    """Entries are keyed by identity, in the order of the file."""
    entries = parse_suppressions(VALID_SUPPRESSIONS, Path("s.json"))
    assert list(entries) == [entry["identity"] for entry in VALID_SUPPRESSIONS["suppressions"]]


@pytest.mark.parametrize("case", sorted(SUPPRESSION_EDITS))
def test_invalid_suppressions_are_rejected(case: str) -> None:
    """Each planted breach of the format is rejected by the loader."""
    with pytest.raises(ConfigurationError):
        parse_suppressions(edited(VALID_SUPPRESSIONS, SUPPRESSION_EDITS[case]), Path("s.json"))


@pytest.mark.parametrize(
    "identity",
    [
        "geonexus|links/broken|path:a.md|link:b.md|",
        "geonexus|links/broken|path:a.md|||1",
        "geonexus|links/broken|a.md",
    ],
)
def test_non_canonical_identity_is_rejected(identity: str) -> None:
    """An identity that is not the canonical string of an identity is rejected."""
    document = edited(VALID_SUPPRESSIONS, lambda d: d["suppressions"][0].update(identity=identity))
    with pytest.raises(ConfigurationError):
        parse_suppressions(document, Path("s.json"))


def test_repeated_identity_is_rejected() -> None:
    """Two entries naming one identity are rejected."""
    document = edited(
        VALID_SUPPRESSIONS,
        lambda d: d["suppressions"][1].update(identity=d["suppressions"][0]["identity"]),
    )
    with pytest.raises(ConfigurationError):
        parse_suppressions(document, Path("s.json"))


# --- Agreement with the published schemas -----------------------------------------------------


def schema_accepts(name: str, document: dict[str, Any]) -> bool:
    """Whether the published JSON Schema `name` accepts a document."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((SPECS / "schemas" / name).read_text())
    return bool(jsonschema.Draft202012Validator(schema).is_valid(document))


def test_configuration_schema_accepts_the_default_places() -> None:
    """The published configuration schema accepts a file without `output` and without `log`."""

    def edit(document: dict[str, Any]) -> None:
        document.pop("output")
        document["checks"]["links"].pop("log")
        document["checks"]["links"]["command"] = ["check-links", "--output", "{log}"]

    assert schema_accepts("configuration.schema.json", edited(VALID_CONFIGURATION, edit))


def test_schemas_accept_the_valid_documents() -> None:
    """The published schemas accept the documents that the loaders accept."""
    assert schema_accepts("configuration.schema.json", VALID_CONFIGURATION)
    assert schema_accepts("suppressions.schema.json", VALID_SUPPRESSIONS)


@pytest.mark.parametrize("case", sorted(CONFIGURATION_EDITS))
def test_configuration_schema_rejects_what_the_loader_rejects(case: str) -> None:
    """The published configuration schema rejects each planted breach."""
    document = edited(VALID_CONFIGURATION, CONFIGURATION_EDITS[case])
    assert not schema_accepts("configuration.schema.json", document)


@pytest.mark.parametrize("case", sorted(SUPPRESSION_EDITS))
def test_suppressions_schema_rejects_what_the_loader_rejects(case: str) -> None:
    """The published suppressions schema rejects each planted breach."""
    document = edited(VALID_SUPPRESSIONS, SUPPRESSION_EDITS[case])
    assert not schema_accepts("suppressions.schema.json", document)


# --- Log validation ---------------------------------------------------------------------------


def test_identity_vectors_satisfy_the_log_validation() -> None:
    """Every identity vector, a conforming log, passes the validation of the runner."""
    for vector in json.loads((SPECS / "vectors" / "identity.json").read_text()):
        check_log(vector["log"])


def conforming_log() -> dict[str, Any]:
    """A log of one run holding one conforming result."""
    result = {
        "ruleId": "links/broken",
        "level": "error",
        "message": {"text": "broken"},
        "locations": [{"logicalLocations": [{"name": "path:a.md#link:b.md"}]}],
    }
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "t"}}, "results": [result]}]}


LOG_EDITS: dict[str, Callable[[dict[str, Any]], None]] = {
    "version-2.0.0": lambda d: d.update(version="2.0.0"),
    "no-runs": lambda d: d.update(runs=[]),
    "no-results": lambda d: d["runs"][0].pop("results"),
    "gate-driver": lambda d: d["runs"][0]["tool"]["driver"].update(name="elenchos"),
    "uppercase-driver": lambda d: d["runs"][0]["tool"]["driver"].update(name="Tool"),
    "level-none": lambda d: d["runs"][0]["results"][0].update(level="none"),
    "no-level": lambda d: d["runs"][0]["results"][0].pop("level"),
    "no-message-text": lambda d: d["runs"][0]["results"][0].update(message={"id": "m"}),
    "producer-suppressions": lambda d: d["runs"][0]["results"][0].update(suppressions=[]),
    "producer-identity": lambda d: d["runs"][0]["results"][0].update(
        fingerprints={"elenchos/v1": "t|links/broken|path:a.md"}
    ),
}


def test_conforming_log_passes() -> None:
    """The planted conforming log passes the validation."""
    check_log(conforming_log())


@pytest.mark.parametrize("case", sorted(LOG_EDITS))
def test_log_breaking_a_rule_of_the_verdict_is_rejected(case: str) -> None:
    """A log without version 2.1.0, runs, results, an admitted level or a message text, or
    holding an object that only the gate writes, is rejected."""
    with pytest.raises(ProfileError):
        check_log(edited(conforming_log(), LOG_EDITS[case]))


# --- The `_schema` key ------------------------------------------------------------------------


def test_configuration_declares_its_identifier_as_the_first_key() -> None:
    """The accepted form names the format in `_schema`, first in the document."""
    configuration = parse_configuration(VALID_CONFIGURATION, CONFIG_PATH, ROOT)
    assert configuration.path == CONFIG_PATH.resolve()
    assert next(iter(VALID_CONFIGURATION)) == "_schema"


@pytest.mark.parametrize(
    ("edit", "name"),
    [
        (lambda d: d.pop("_schema"), "absent"),
        (lambda d: d.update(_schema="elenchos:configuration@2"), "wrong"),
    ],
    ids=["absent", "wrong"],
)
def test_configuration_names_the_expected_identifier(
    edit: Callable[[dict[str, Any]], None], name: str
) -> None:
    """An absent or a wrong `_schema` stops the run and names the expected value."""
    with pytest.raises(ConfigurationError, match="_schema") as excinfo:
        parse_configuration(edited(VALID_CONFIGURATION, edit), CONFIG_PATH, ROOT)
    assert "elenchos:configuration@3" in str(excinfo.value), name


def test_configuration_with_the_old_key_names_the_value_to_write() -> None:
    """The former key `version` is rejected with the assignment that replaces it."""
    document = edited(VALID_CONFIGURATION, lambda d: (d.pop("_schema"), d.update(version=3)))
    with pytest.raises(ConfigurationError, match='_schema = "elenchos:configuration@3"'):
        parse_configuration(document, CONFIG_PATH, ROOT)


@pytest.mark.parametrize(
    ("edit", "name"),
    [
        (lambda d: d.pop("_schema"), "absent"),
        (lambda d: d.update(_schema="elenchos:suppressions@9"), "wrong"),
    ],
    ids=["absent", "wrong"],
)
def test_suppressions_name_the_expected_identifier(
    edit: Callable[[dict[str, Any]], None], name: str
) -> None:
    """An absent or a wrong `_schema` stops the run and names the expected value."""
    with pytest.raises(ConfigurationError, match="_schema") as excinfo:
        parse_suppressions(edited(VALID_SUPPRESSIONS, edit), Path("s.json"))
    assert "elenchos:suppressions@1" in str(excinfo.value), name


def test_suppressions_with_the_old_key_name_the_value_to_write() -> None:
    """A suppressions file cannot be regenerated, so the old key is rejected with the fix."""
    document = edited(VALID_SUPPRESSIONS, lambda d: (d.pop("_schema"), d.update(version=1)))
    with pytest.raises(ConfigurationError, match='"_schema": "elenchos:suppressions@1"'):
        parse_suppressions(document, Path("s.json"))


def test_written_suppressions_declare_the_identifier_first(tmp_path: Path) -> None:
    """The writer of the format writes `_schema` as the first key."""
    target = tmp_path / "suppressions.json"
    write_suppressions(parse_suppressions(VALID_SUPPRESSIONS, target).values(), target)
    document = json.loads(target.read_text(encoding="utf-8"))
    assert next(iter(document)) == "_schema"
    assert document["_schema"] == "elenchos:suppressions@1"
    assert "version" not in document
