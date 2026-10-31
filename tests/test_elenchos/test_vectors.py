"""Tests of the identity builder on the test vectors of the findings profile."""

import json
from pathlib import Path
from typing import Any

import pytest

from elenchos.errors import ProfileError
from elenchos.identity import Identity
from elenchos.sarif import FINGERPRINT_KEY, check_log, fingerprint_log

VECTORS = Path(__file__).parents[2] / "specs" / "vectors"
IDENTITY_VECTORS: list[dict[str, Any]] = json.loads((VECTORS / "identity.json").read_text())
REJECTED_VECTORS: list[dict[str, Any]] = json.loads((VECTORS / "rejected.json").read_text())


def fingerprints(log: dict[str, Any]) -> list[str]:
    """Identity of every result of a log, in the order of its runs and results."""
    return [
        result["fingerprints"][FINGERPRINT_KEY]
        for run in log["runs"]
        for result in run.get("results", [])
    ]


@pytest.mark.parametrize("vector", IDENTITY_VECTORS, ids=lambda vector: vector["case"])
def test_vector_yields_expected_identities(vector: dict[str, Any]) -> None:
    """Each vector log yields the identities that the profile states for it."""
    assert fingerprints(fingerprint_log(vector["log"])) == vector["expected"]


@pytest.mark.parametrize("vector", IDENTITY_VECTORS, ids=lambda vector: vector["case"])
def test_vector_identities_round_trip(vector: dict[str, Any]) -> None:
    """Each expected identity parses into components that build the same string."""
    for text in vector["expected"]:
        assert str(Identity.parse(text)) == text


@pytest.mark.parametrize("vector", REJECTED_VECTORS, ids=lambda vector: vector["case"])
def test_rejected_vector_raises(vector: dict[str, Any]) -> None:
    """Each negative vector breaks the profile, and the gate rejects it."""
    with pytest.raises(ProfileError):
        check_log(vector["log"])


@pytest.mark.parametrize("vector", IDENTITY_VECTORS, ids=lambda vector: vector["case"])
def test_identity_vector_is_accepted(vector: dict[str, Any]) -> None:
    """Each identity vector satisfies the profile, so the gate accepts it."""
    check_log(vector["log"])


def test_moved_line_keeps_the_identity() -> None:
    """A finding whose line, message and level change keeps its identity."""
    cases = {vector["case"]: vector["expected"] for vector in IDENTITY_VECTORS}
    assert cases["file-region"] == cases["line-moved"]
