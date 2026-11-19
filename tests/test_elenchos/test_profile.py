"""Tests of the public interface of the findings profile on the vectors of the profile."""

import json
from pathlib import Path
from typing import Any

import pytest

from elenchos.ecma import python_pattern
from elenchos.profile import (
    PROFILE_SCHEMA_ID,
    Resolution,
    entry_keys,
    identities,
    profile_schema,
    resolve_locus,
    violations,
)

VECTORS = Path(__file__).parents[2] / "specs" / "vectors"


def load(name: str) -> list[dict[str, Any]]:
    """Read one file of vectors of the profile."""
    vectors: list[dict[str, Any]] = json.loads((VECTORS / name).read_text(encoding="utf-8"))
    return vectors


IDENTITY = load("identity.json")
REJECTED = load("rejected.json")
NONCONFORMING = load("nonconforming.json")
LOCI = load("loci.json")


def test_schema_carries_its_identifier() -> None:
    """The packaged schema is the published resource named by its absolute `$id`."""
    assert profile_schema()["$id"] == PROFILE_SCHEMA_ID


@pytest.mark.parametrize("vector", IDENTITY, ids=lambda vector: vector["case"])
def test_identity_vector_conforms(vector: dict[str, Any]) -> None:
    """Each identity vector is a log that a producer may write."""
    assert violations(vector["log"]) == []


@pytest.mark.parametrize("vector", IDENTITY, ids=lambda vector: vector["case"])
def test_identities_of_identity_vector(vector: dict[str, Any]) -> None:
    """The interface yields the identities that the profile states for each vector."""
    assert identities(vector["log"]) == vector["expected"]


@pytest.mark.parametrize("vector", REJECTED, ids=lambda vector: vector["case"])
def test_rejected_vector_breaks_the_profile(vector: dict[str, Any]) -> None:
    """Each log that the gate rejects also breaks the rules of a producer."""
    assert violations(vector["log"]) != []


@pytest.mark.parametrize("vector", NONCONFORMING, ids=lambda vector: vector["case"])
def test_nonconforming_vector_is_reported_at_its_node(vector: dict[str, Any]) -> None:
    """Each nonconforming vector breaks one rule, reported at the node that the vector names."""
    pointers = [violation.pointer for violation in violations(vector["log"])]
    if vector["pointer"] is None:
        assert pointers == []
    else:
        assert vector["pointer"] in pointers


@pytest.mark.parametrize("vector", LOCI, ids=lambda vector: vector["case"])
def test_locus_resolves_to_its_node(vector: dict[str, Any]) -> None:
    """Each locus resolves to the node, and the tokens left, that the vector states."""
    expected = vector["resolution"]
    resolution = resolve_locus(vector["document"], vector["locus"])
    if expected is None:
        assert resolution is None
    else:
        assert resolution == Resolution(tuple(expected["path"]), tuple(expected["unresolved"]))


@pytest.mark.parametrize(
    "vector", [vector for vector in LOCI if "path" in vector], ids=lambda vector: vector["case"]
)
def test_locus_is_built_from_its_path(vector: dict[str, Any]) -> None:
    """A producer that reads the keys of the schema writes the locus that the vector states."""
    keys = entry_keys(vector["document"], vector["schema"])
    assert keys.locus(vector["path"]) == vector["locus"]


def test_pattern_anchor_matches_only_at_the_end() -> None:
    """The anchor `$` of a pattern rejects a final newline, as ECMA-262 reads it."""
    log = next(vector for vector in NONCONFORMING if vector["case"] == "conforming")["log"]
    edited = json.loads(json.dumps(log))
    edited["runs"][0]["tool"]["driver"]["name"] = "anagraphe\n"
    assert "/runs/0/tool/driver/name" in [violation.pointer for violation in violations(edited)]
    assert python_pattern("[$]a$") == "[$]a\\Z"
