"""Tests of the identity builder on planted cases: escaping, NFC, ordinals and parsing."""

import copy
import unicodedata
from typing import Any

import pytest

from elenchos.errors import ProfileError
from elenchos.identity import Identity, escape, number_occurrences, unescape
from elenchos.sarif import (
    DISCRIMINATOR_KEY,
    FINGERPRINT_KEY,
    fingerprint_log,
    identity_of,
    location_name,
    order_key,
    split_location_name,
    write_identity,
)


def result(name: str, line: int | None = None, discriminator: str | None = None) -> dict[str, Any]:
    """A SARIF result of the rule `links/broken`, at a logical location and an optional line."""
    location: dict[str, Any] = {"logicalLocations": [{"name": name}]}
    if line is not None:
        location["physicalLocation"] = {
            "artifactLocation": {"uri": "a.md", "uriBaseId": "SRCROOT"},
            "region": {"startLine": line, "startColumn": 1},
        }
    planted: dict[str, Any] = {
        "ruleId": "links/broken",
        "level": "error",
        "message": {"text": "broken link"},
        "locations": [location],
    }
    if discriminator is not None:
        planted["partialFingerprints"] = {DISCRIMINATOR_KEY: discriminator}
    return planted


def log(*runs: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """A SARIF log holding one run per pair of a tool name and its results."""
    return {
        "version": "2.1.0",
        "runs": [
            {"tool": {"driver": {"name": tool}}, "columnKind": "unicodeCodePoints", "results": rs}
            for tool, rs in runs
        ],
    }


def stamped(sarif_log: dict[str, Any]) -> list[str]:
    """Identity of every result of a fingerprinted log, in order."""
    return [
        r["fingerprints"][FINGERPRINT_KEY]
        for run in fingerprint_log(sarif_log)["runs"]
        for r in run["results"]
    ]


# --- Escaping ---------------------------------------------------------------------------------


def test_pipe_and_percent_are_escaped() -> None:
    """`|` and `%` inside a component are written `%7C` and `%25`, and parse back."""
    identity = Identity("geonexus", "links/broken", "path:100%.md", "link:a|b.md", "x%7Cy")
    text = str(identity)
    assert text == "geonexus|links/broken|path:100%25.md|link:a%7Cb.md|x%257Cy"
    assert Identity.parse(text) == identity


def test_control_characters_are_escaped() -> None:
    """A tab, a newline and DEL are written in uppercase hexadecimal."""
    assert escape("a\tb\nc\x7f") == "a%09b%0Ac%7F"
    assert unescape("a%09b%0Ac%7F") == "a\tb\nc\x7f"


@pytest.mark.parametrize("text", ["%41", "%7c", "%2", "%", "a|b", "a\tb"])
def test_unescape_rejects_text_that_escape_never_writes(text: str) -> None:
    """An escape of an unreserved character, a lowercase or truncated escape, or a raw reserved
    character is rejected, so that one component has one escaped form."""
    with pytest.raises(ProfileError):
        unescape(text)


# --- Unicode normalization --------------------------------------------------------------------


def test_decomposed_and_composed_components_give_one_identity() -> None:
    """A decomposed accent and its composed form yield one identity, written in NFC."""
    decomposed = Identity("geonexus", "example/nfc", "path:docs/café.md")
    composed = Identity("geonexus", "example/nfc", "path:docs/café.md")
    assert decomposed == composed
    assert str(decomposed) == "geonexus|example/nfc|path:docs/café.md"


def test_parse_rejects_a_component_not_in_nfc() -> None:
    """A string holding a decomposed component is not the canonical string of any identity."""
    with pytest.raises(ProfileError):
        Identity.parse("geonexus|example/nfc|path:docs/café.md")


def test_identity_string_is_not_normalized_again() -> None:
    """The escape `%7C` followed by a combining mark is not NFC as a whole string; the identity
    keeps it unchanged, and parses back to its components."""
    identity = Identity("geonexus", "example/nfc", "path:a.md", "link:a|̧b")
    text = str(identity)
    assert text.endswith("link:a%7Çb")
    assert unicodedata.normalize("NFC", text) != text
    assert Identity.parse(text) == identity


# --- Distinct tools and resources -------------------------------------------------------------


def test_two_tools_with_one_rule_at_one_locus_stay_distinct() -> None:
    """Two tools emitting one ruleId at one locus receive two identities, without ordinal."""
    name = "id:arg-ab12#/relations/2/target"
    identities = stamped(log(("ekthesis", [result(name, 3)]), ("gnomon", [result(name, 3)])))
    assert identities == [
        "ekthesis|links/broken|id:arg-ab12|/relations/2/target",
        "gnomon|links/broken|id:arg-ab12|/relations/2/target",
    ]


def test_finding_of_the_vault_without_region() -> None:
    """A folder of the vault without physical location yields the resource alone, ordered first."""
    planted = result("path:projects/x/")
    assert str(identity_of(planted, "geonexus")) == "geonexus|links/broken|path:projects/x/"
    assert order_key(planted) == (0, 0, "broken link")


# --- Ordinals ---------------------------------------------------------------------------------


def test_identical_occurrences_receive_ordinals_in_line_order() -> None:
    """Three identical occurrences are numbered by line, whatever their order in the log."""
    name = "path:r.md#link:o.md"
    base = "geonexus|links/broken|path:r.md|link:o.md"
    identities = stamped(log(("geonexus", [result(name, 30), result(name, 5), result(name, 12)])))
    assert identities == [f"{base}||3", base, f"{base}||2"]


def test_ordinals_run_across_the_runs_of_one_tool() -> None:
    """Identical occurrences in two runs of one tool share one numbering."""
    name = "path:r.md#link:o.md"
    base = "geonexus|links/broken|path:r.md|link:o.md"
    identities = stamped(log(("geonexus", [result(name, 9)]), ("geonexus", [result(name, 2)])))
    assert identities == [f"{base}||2", base]


def test_equal_keys_fall_back_to_input_order() -> None:
    """Occurrences with equal lines, columns and messages are numbered in input order."""
    base = Identity("geonexus", "links/broken", "path:r.md", "link:o.md")
    numbered = number_occurrences([(base, (0, 0, "")), (base, (0, 0, ""))])
    assert [identity.ordinal for identity in numbered] == [1, 2]


def test_number_occurrences_rejects_a_numbered_identity() -> None:
    """An input identity that already carries an ordinal is rejected."""
    numbered = Identity("geonexus", "links/broken", "path:r.md", ordinal=2)
    with pytest.raises(ProfileError):
        number_occurrences([(numbered, (0, 0, ""))])


def test_moved_findings_keep_distinct_and_stable_identities() -> None:
    """Two findings of one rule keep distinct identities when their source lines move, as the
    decision on stable checker finding identities requires."""
    before = log(("geonexus", [result("path:a.md#link:x.md", 3), result("path:a.md#link:y.md", 7)]))
    after = log(("geonexus", [result("path:a.md#link:x.md", 40), result("path:a.md#link:y.md", 2)]))
    assert stamped(before) == stamped(after)
    assert len(set(stamped(before))) == 2


# --- Parsing and building ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity",
    [
        Identity("geonexus", "links/broken", "path:./"),
        Identity("geonexus", "links/broken", "path:a.md", discriminator="d"),
        Identity("geonexus", "links/broken", "path:a.md", ordinal=12),
        Identity("geonexus", "links/broken", "path:a.md", "task:t-1", "d", ordinal=2),
        Identity("anagraphe", "a/b/c", "id:x%y", "slot:s|t", "é\u0000"),
    ],
)
def test_parse_inverts_build(identity: Identity) -> None:
    """Parsing the canonical string of an identity returns the identity."""
    assert Identity.parse(str(identity)) == identity


@pytest.mark.parametrize(
    "text",
    [
        "geonexus|links/broken",
        "geonexus|links/broken|path:a.md|link:b.md|d|2|3",
        "geonexus|links/broken|path:a.md|",
        "geonexus|links/broken|path:a.md|link:b.md|",
        "geonexus|links/broken|path:a.md|||1",
        "geonexus|links/broken|path:a.md|||02",
        "geonexus|links/broken|path:a.md|||x",
    ],
)
def test_parse_rejects_non_canonical_strings(text: str) -> None:
    """A wrong count of components, a trailing empty component, or an ordinal below 2 or with a
    leading zero is rejected, so that each identity has one string."""
    with pytest.raises(ProfileError):
        Identity.parse(text)


@pytest.mark.parametrize(
    ("tool", "rule_id", "resource", "locus"),
    [
        ("Geonexus", "links/broken", "path:a.md", ""),
        ("geonexus", "Links/Broken", "path:a.md", ""),
        ("geonexus", "links//broken", "path:a.md", ""),
        ("geonexus", "links/broken", "a.md", ""),
        ("geonexus", "links/broken", "path:", ""),
        ("geonexus", "links/broken", "path:./a.md", ""),
        ("geonexus", "links/broken", "path:../a.md", ""),
        ("geonexus", "links/broken", "path:/abs.md", ""),
        ("geonexus", "links/broken", "path:a//b.md", ""),
        ("geonexus", "links/broken", "path:a.md", "section:intro"),
        ("geonexus", "links/broken", "path:a.md", "intro"),
        ("geonexus", "links/broken", "path:a.yml", "/a~2b"),
    ],
)
def test_component_breaking_the_profile_is_rejected(
    tool: str, rule_id: str, resource: str, locus: str
) -> None:
    """A tool name, a ruleId, a resource or a locus outside the forms of the profile is rejected."""
    with pytest.raises(ProfileError):
        Identity(tool, rule_id, resource, locus)


# --- Logical location and SARIF writing -------------------------------------------------------


@pytest.mark.parametrize(
    ("resource", "locus"),
    [("path:docs/notes#old.md", "link:a#b"), ("id:x%23y", ""), ("path:a.md", "/k")],
)
def test_location_name_round_trip(resource: str, locus: str) -> None:
    """The name of a logical location splits back into its resource and its locus."""
    assert split_location_name(location_name(resource, locus)) == (resource, locus)


@pytest.mark.parametrize("name", ["path:a.md#", "path:a%41.md", "path:a%2", "id:x%#/k"])
def test_split_location_name_rejects_names_never_written(name: str) -> None:
    """A trailing `#`, or an escape other than `%25` and `%23` in the resource, is rejected."""
    with pytest.raises(ProfileError):
        split_location_name(name)


def test_write_identity_sets_both_keys() -> None:
    """The identity goes to `fingerprints`, the discriminator to `partialFingerprints`."""
    planted = result("path:n.md#term:competition", 3)
    identity = Identity("geonexus", "links/broken", "path:n.md", "term:competition", "Competition")
    write_identity(planted, identity)
    assert planted["fingerprints"] == {FINGERPRINT_KEY: str(identity)}
    assert planted["partialFingerprints"] == {DISCRIMINATOR_KEY: "Competition"}


def test_write_identity_omits_an_empty_discriminator() -> None:
    """A result without discriminator receives no `partialFingerprints`."""
    planted = result("path:a.md", 1)
    write_identity(planted, Identity("geonexus", "links/broken", "path:a.md"))
    assert "partialFingerprints" not in planted


def test_fingerprint_log_leaves_its_input_unchanged() -> None:
    """The gate returns a fingerprinted copy, and keeps the tool and partial fingerprints."""
    original = log(("geonexus", [result("path:a.md#link:b.md", 1, discriminator="café")]))
    snapshot = copy.deepcopy(original)
    stamped_log = fingerprint_log(original)
    assert original == snapshot
    stamped_run, original_run = stamped_log["runs"][0], snapshot["runs"][0]
    assert stamped_run["tool"] == original_run["tool"]
    stamped_result = stamped_run["results"][0]
    assert stamped_result["partialFingerprints"] == {DISCRIMINATOR_KEY: "café"}
    assert stamped_result["fingerprints"][FINGERPRINT_KEY].endswith("|café")


def test_run_without_driver_name_is_rejected() -> None:
    """A run whose tool names no driver cannot give the first component of an identity."""
    with pytest.raises(ProfileError):
        fingerprint_log({"version": "2.1.0", "runs": [{"tool": {}, "results": []}]})
