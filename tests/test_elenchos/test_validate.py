"""Tests of the check `elenchos validate` on a consumer holding records of each kind."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from elenchos.cli import app
from elenchos.profile import identities, violations
from elenchos.validate import (
    INVALID,
    MALFORMED,
    TOOL,
    UNREGISTERED,
    Outcome,
    sarif_log,
    validate_repository,
)

ITEM = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.org/schemas/item.schema.json",
    "type": "object",
    "required": ["_schema", "title"],
    "additionalProperties": False,
    "properties": {
        "_schema": {"const": "test:item@1"},
        "title": {"type": "string"},
        "tag": {"type": "string", "pattern": "^[a-z]+$"},
        "variables": {
            "type": "array",
            "x-entry-key": "symbol",
            "items": {"$ref": "https://example.org/schemas/common.schema.json#/$defs/variable"},
        },
    },
}
COMMON = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.org/schemas/common.schema.json",
    "$defs": {
        "variable": {
            "type": "object",
            "required": ["symbol"],
            "properties": {"symbol": {"type": "string"}, "rank": {"type": "integer"}},
        }
    },
}
REGISTRY = """\
_schema: kleisis:schema-registry@2
schemas:
  "test:item@1": "specs/schemas/item.schema.json"
resources:
  "https://example.org/schemas/item.schema.json": "specs/schemas/item.schema.json"
  "https://example.org/schemas/common.schema.json": "specs/schemas/common.schema.json"
"""
ANAGRAPHE = """\
_schema: anagraphe:configuration@3
targets:
  records:
    registry: specs/schema-registry.yml
exclude:
  paths:
    - /specs/
"""
RECORDS = {
    "good.yml": "_schema: test:item@1\ntitle: Good\nvariables:\n  - symbol: u\n    rank: 1\n",
    "bad.yml": (
        "_schema: test:item@1\nextra: 1\nvariables:\n  - symbol: v\n  - symbol: u\n"
        "    rank: high\n"
    ),
    "malformed.yml": "_schema: Not A Contract\n",
    "unregistered.yml": "_schema: test:other@1\ntitle: Other\n",
    "unbound.yml": "title: no binding\n",
    "newline.json": '{"_schema": "test:item@1", "title": "T", "tag": "abc\\n"}\n',
    "notes/note.md": "---\n_schema: test:item@1\ntitle: 3\n---\nbody\n",
}


def consumer(root: Path, anagraphe: str = ANAGRAPHE) -> Path:
    """Write a consumer whose records break each rule of the check."""
    files = {
        "anagraphe.yml": anagraphe,
        "specs/schema-registry.yml": REGISTRY,
        "specs/schemas/item.schema.json": json.dumps(ITEM),
        "specs/schemas/common.schema.json": json.dumps(COMMON),
        **RECORDS,
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def summary(outcome: Outcome) -> list[tuple[str, str, str, str, tuple[int, int] | None]]:
    """The rule, resource, locus, discriminator and position of each finding."""
    return [
        (finding.rule, finding.resource, finding.locus, finding.discriminator, finding.position)
        for finding in outcome.findings
    ]


def test_each_record_is_validated_against_its_bound_schema(tmp_path: Path) -> None:
    """Each bound record yields the findings of its schema, located at its nodes."""
    outcome = validate_repository(consumer(tmp_path))
    assert outcome.stopped is None
    assert summary(outcome) == [
        (UNREGISTERED, "path:anagraphe.yml", "/_schema", "anagraphe:configuration@3", (1, 10)),
        (INVALID, "path:bad.yml", "/title", "required", None),
        (INVALID, "path:bad.yml", "/extra", "additionalProperties", (2, 8)),
        (INVALID, "path:bad.yml", "/variables/symbol=u/rank", "type", (6, 11)),
        (MALFORMED, "path:malformed.yml", "/_schema", "Not A Contract", (1, 10)),
        (INVALID, "path:newline.json", "/tag", "pattern", (1, 49)),
        (UNREGISTERED, "path:unregistered.yml", "/_schema", "test:other@1", (1, 10)),
        (INVALID, "path:notes/note.md", "/title", "type", (3, 8)),
    ]
    assert outcome.findings[5].message == "'abc\\n' does not match '^[a-z]+$'"


def test_a_missing_field_is_located_at_its_own_pointer(tmp_path: Path) -> None:
    """The locus of a missing field names the field, and its message names it too."""
    outcome = validate_repository(consumer(tmp_path))
    missing = outcome.findings[1]
    assert missing.locus == "/title" and missing.message == "'title' is a required property"


def test_the_log_conforms_to_the_profile(tmp_path: Path) -> None:
    """The log of the check is a producer log of the profile, and yields stable identities."""
    log = sarif_log(validate_repository(consumer(tmp_path)))
    assert violations(log) == []
    assert log["runs"][0]["tool"]["driver"]["name"] == TOOL
    assert "elenchos-validate|record/invalid|path:bad.yml|/variables/symbol=u/rank|type" in (
        identities(log)
    )


def test_a_scope_restricts_the_report(tmp_path: Path) -> None:
    """Only the records below the scope are reported."""
    outcome = validate_repository(consumer(tmp_path), ["notes"])
    assert [finding.path for finding in outcome.findings] == ["notes/note.md"]


def test_a_consumer_without_registry_stops_with_a_failed_run(tmp_path: Path) -> None:
    """Without a schema registry, the check stops, and its log declares the failure."""
    outcome = validate_repository(consumer(tmp_path, "_schema: anagraphe:configuration@3\n"))
    assert outcome.stopped is not None and "targets" in outcome.stopped
    log = sarif_log(outcome)
    assert violations(log) == []
    assert log["runs"][0]["invocations"][0]["executionSuccessful"] is False


@pytest.mark.parametrize(
    ("anagraphe", "status"),
    [(ANAGRAPHE, 1), ("_schema: anagraphe:configuration@3\n", 2)],
    ids=["findings", "stopped"],
)
def test_exit_status(tmp_path: Path, anagraphe: str, status: int) -> None:
    """The command exits 1 on findings and 2 when it cannot run, and writes its log."""
    root = consumer(tmp_path, anagraphe)
    log = tmp_path / "build" / "validate.sarif"
    result = CliRunner().invoke(
        app, ["validate", "--root", str(root), "--format", "sarif", "--output", str(log)]
    )
    assert result.exit_code == status, result.output
    assert violations(json.loads(log.read_text(encoding="utf-8"))) == []


def test_a_valid_consumer_passes(tmp_path: Path) -> None:
    """A consumer whose records all conform exits 0."""
    root = consumer(tmp_path, ANAGRAPHE + "    - /anagraphe.yml\n")
    for rel in RECORDS:
        if rel != "good.yml":
            (root / rel).unlink()
    result = CliRunner().invoke(app, ["validate", "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "0 findings"


OUTSIDE = "config/anagraphe/anagraphe.yml"
"""A place of the configuration of Anagraphe outside the places that Hodegos searches: a subfolder
of `config/`, which is not searched."""


def consumer_outside(root: Path) -> Path:
    """Write a consumer whose configuration of Anagraphe lies at `OUTSIDE`."""
    consumer(root)
    (root / OUTSIDE).parent.mkdir(parents=True)
    (root / "anagraphe.yml").rename(root / OUTSIDE)
    return root


def sarif_run(root: Path, *options: str) -> tuple[int, dict]:
    """Run the command with a SARIF report; return its status and the run of its log."""
    log = root / "build" / "validate.sarif"
    result = CliRunner().invoke(
        app,
        ["validate", "--root", str(root), *options, "--format", "sarif", "--output", str(log)],
    )
    document = json.loads(log.read_text(encoding="utf-8"))
    assert violations(document) == []
    return result.exit_code, document["runs"][0]


def test_the_option_names_a_configuration_outside_the_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--anagraphe-config`, read from the current folder, gives the registry and the bindings."""
    root = consumer_outside(tmp_path / "outside")
    monkeypatch.chdir(root)
    status, run = sarif_run(root, "--anagraphe-config", OUTSIDE)
    assert status == 1
    assert ("record/invalid", "bad.yml") in {
        (result["ruleId"], result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"])
        for result in run["results"]
    }
    outcome = validate_repository(root, config=Path(OUTSIDE))
    assert outcome.stopped is None
    plain = validate_repository(consumer(tmp_path / "plain"))
    assert {item for item in summary(outcome) if item[1] != f"path:{OUTSIDE}"} == {
        item for item in summary(plain) if item[1] != "path:anagraphe.yml"
    }


def test_without_the_option_no_registry_is_declared(tmp_path: Path) -> None:
    """Without the option, the configuration outside the places is not read."""
    status, run = sarif_run(consumer_outside(tmp_path))
    assert status == 2
    notification = run["invocations"][0]["toolExecutionNotifications"][0]["message"]["text"]
    assert "declares no schema registry" in notification


def test_an_absent_file_named_by_the_option_stops_the_check(tmp_path: Path) -> None:
    """A missing file stops the check as an invalid configuration of Anagraphe does."""
    root = consumer(tmp_path)
    status, run = sarif_run(root, "--anagraphe-config", str(root / "config/absent.yml"))
    assert status == 2
    invocation = run["invocations"][0]
    assert invocation["executionSuccessful"] is False and "results" not in run
    assert "config/absent.yml" in invocation["toolExecutionNotifications"][0]["message"]["text"]
