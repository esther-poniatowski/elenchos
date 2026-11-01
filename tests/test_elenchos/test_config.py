"""Tests of the configuration and suppressions formats, and of their agreement with the published
JSON Schemas."""

import copy
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from elenchos.config import DEFAULT_EXIT_CODES, parse_configuration
from elenchos.errors import ConfigurationError, ProfileError
from elenchos.sarif import check_log
from elenchos.suppressions import parse_suppressions

SPECS = Path(__file__).parents[2] / "specs"
CONFIG_PATH = Path("/consumer/config/elenchos.toml")

VALID_CONFIGURATION: dict[str, Any] = {
    "version": 1,
    "root": "..",
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
    "version": 1,
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
    "version-3": lambda d: d.update(version=3),
    "renames-in-version-1": lambda d: d.update(renames={"rules": {}}),
    "scope-in-version-1": lambda d: d["checks"]["links"].update(scope="paths"),
    "unknown-scope": lambda d: (d.update(version=2), d["checks"]["links"].update(scope="all")),
    "bad-rename-rule": lambda d: d.update(version=2, renames={"rules": {"a|b": "c"}}),
    "bad-rename-resource": lambda d: d.update(
        version=2, renames={"resources": {"docs/a.md": "path:docs/b.md"}}
    ),
    "no-output": lambda d: d.pop("output"),
    "no-policy-block": lambda d: d["policy"].pop("block"),
    "unknown-level": lambda d: d["policy"].update(block=["fatal"]),
    "repeated-level": lambda d: d["policy"].update(block=["error", "error"]),
    "bad-rule-key": lambda d: d["policy"]["rules"].update({"terms/advice": []}),
    "no-check": lambda d: d.update(checks={}),
    "bad-check-name": lambda d: d["checks"].update({"Links": d["checks"]["links"]}),
    "empty-command": lambda d: d["checks"]["links"].update(command=[]),
    "no-log": lambda d: d["checks"]["links"].pop("log"),
    "boolean-exit-code": lambda d: d["checks"]["links"].update(exit_codes=[True]),
    "unknown-check-key": lambda d: d["checks"]["links"].update(shell=True),
}

SUPPRESSION_EDITS: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown-key": lambda d: d.update(extra=1),
    "version-2": lambda d: d.update(version=2),
    "no-justification": lambda d: d["suppressions"][0].pop("justification"),
    "blank-justification": lambda d: d["suppressions"][0].update(justification="  "),
    "bad-date": lambda d: d["suppressions"][0].update(date="15/10/2026"),
    "unknown-entry-key": lambda d: d["suppressions"][0].update(reason="x"),
}


# --- Configuration ----------------------------------------------------------------------------


def test_valid_configuration_resolves_paths_against_the_root() -> None:
    """Relative paths resolve against the root, itself relative to the configuration file."""
    configuration = parse_configuration(VALID_CONFIGURATION, CONFIG_PATH)
    root = Path("/consumer").resolve()
    assert configuration.root == root
    assert configuration.output == root / "build" / "gate.sarif"
    assert configuration.checks[0].log == root / "logs" / "links.sarif"
    assert configuration.checks[0].exit_codes == DEFAULT_EXIT_CODES
    assert configuration.relative(configuration.path) == "config/elenchos.toml"


def test_checks_keep_the_order_of_the_file() -> None:
    """Checks run in the order in which the file declares them."""
    configuration = parse_configuration(VALID_CONFIGURATION, CONFIG_PATH)
    assert [check.name for check in configuration.checks] == ["links", "terms"]


@pytest.mark.parametrize("case", sorted(CONFIGURATION_EDITS))
def test_invalid_configuration_is_rejected(case: str) -> None:
    """Each planted breach of the format is rejected by the loader."""
    with pytest.raises(ConfigurationError):
        parse_configuration(edited(VALID_CONFIGURATION, CONFIGURATION_EDITS[case]), CONFIG_PATH)


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(root="sub"),
        lambda d: d.update(suppressions="../outside.json"),
        lambda d: d["checks"]["terms"].update(log="logs/links.sarif"),
        lambda d: d.update(output="logs/links.sarif"),
    ],
    ids=["root-excludes-config", "suppressions-outside", "shared-log", "output-is-a-log"],
)
def test_path_rules_beyond_the_schema_are_rejected(edit: Callable[[dict[str, Any]], None]) -> None:
    """The loader rejects the path rules that a JSON Schema cannot state."""
    with pytest.raises(ConfigurationError):
        parse_configuration(edited(VALID_CONFIGURATION, edit), CONFIG_PATH)


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
