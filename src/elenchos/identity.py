"""
Canonical identity of a finding, as defined by the findings profile.

The identity of a finding is the string `tool|ruleId|resource|locus|discriminator[|ordinal]`. Each
component is normalized to Unicode NFC, then escaped, so that the string splits back into its
components without ambiguity. The specification is section "Identity string" of
`docs/profile.md`.

Classes
-------
Identity
    Components of the identity of one finding, with its canonical string.

Functions
---------
escape(component) -> str
    Escape the characters of a component that the identity string reserves.
unescape(text) -> str
    Invert `escape`, rejecting any text that `escape` does not produce.
number_occurrences(occurrences) -> list[Identity]
    Assign ordinals to the identical occurrences of a set of findings.

Notes
-----
The components are NFC before escaping, but the identity string as a whole is not guaranteed to
be NFC: the escape `%7C` ends with `C`, which composes with a following combining mark. An identity
string is therefore compared code point by code point, and never normalized again.

Examples
--------
>>> identity = Identity("anagraphe", "references/broken", "path:docs/a.md", "link:b.md")
>>> str(identity)
'anagraphe|references/broken|path:docs/a.md|link:b.md'
>>> Identity.parse(str(identity)) == identity
True
"""

from dataclasses import dataclass, replace
import re
import unicodedata
from typing import Sequence

from .errors import ProfileError

SEPARATOR = "|"
"""Separator of the components of an identity string."""

FIELD_COUNT = 5
"""Number of components before the ordinal: tool, rule, resource, locus, discriminator."""

TOOL_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
"""Form of a tool name, equal to `run.tool.driver.name`."""

RULE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*")
"""Form of a `ruleId`: lowercase components separated by `/`."""

RESOURCE_PREFIXES = ("id:", "path:")
"""Prefixes of the two forms of a resource: a record identifier or a repository-relative path."""

LOCUS_TYPES = frozenset({"link", "task", "slot", "term", "symbol"})
"""Types of a typed locus `<type>:<value>`; a new type takes a new version of the profile."""

ORDINAL_PATTERN = re.compile(r"[1-9][0-9]*")
"""Form of a written ordinal: a decimal integer without leading zero."""

OrderKey = tuple[int, int, str]
"""Key ordering identical occurrences: start line, start column, message text."""


def _is_reserved(character: str) -> bool:
    """Whether `escape` replaces this character: `%`, `|`, a C0 control character or DEL."""
    code = ord(character)
    return character in "%|" or code < 0x20 or code == 0x7F


def escape(component: str) -> str:
    """
    Escape the characters of a component that the identity string reserves.

    Parameters
    ----------
    component : str
        Component of an identity, already normalized to NFC.

    Returns
    -------
    str
        The component with `%`, `|`, each C0 control character and DEL written as `%XX`, in
        uppercase hexadecimal.

    Examples
    --------
    >>> escape("link:foo|bar%.md")
    'link:foo%7Cbar%25.md'
    """
    return "".join(f"%{ord(char):02X}" if _is_reserved(char) else char for char in component)


def unescape(text: str) -> str:
    """
    Invert `escape`, rejecting any text that `escape` does not produce.

    Parameters
    ----------
    text : str
        Escaped component, read from an identity string.

    Returns
    -------
    str
        The component before escaping.

    Raises
    ------
    ProfileError
        If the text holds a raw reserved character, or a `%` not followed by the uppercase
        hexadecimal code of a reserved character.

    Examples
    --------
    >>> unescape("link:foo%7Cbar.md")
    'link:foo|bar.md'
    """
    characters: list[str] = []
    position = 0
    while position < len(text):
        char = text[position]
        if char == "%":
            code = text[position + 1 : position + 3]
            if not re.fullmatch(r"[0-9A-F]{2}", code) or not _is_reserved(chr(int(code, 16))):
                raise ProfileError(f"invalid escape {text[position:position + 3]!r} in {text!r}")
            characters.append(chr(int(code, 16)))
            position += 3
        elif _is_reserved(char):
            raise ProfileError(f"unescaped reserved character {char!r} in {text!r}")
        else:
            characters.append(char)
            position += 1
    return "".join(characters)


def check_resource(resource: str) -> None:
    """Raise `ProfileError` unless the resource is `id:<identifier>` or a normalized `path:`."""
    prefix = next((p for p in RESOURCE_PREFIXES if resource.startswith(p)), None)
    if prefix is None or resource == prefix:
        raise ProfileError(f"resource {resource!r} is neither `id:<identifier>` nor `path:<path>`")
    if prefix == "path:":
        path = resource.removeprefix(prefix)
        if path == "./":
            return
        segments = path.removesuffix("/").split("/")
        if path.startswith("/") or any(segment in ("", ".", "..") for segment in segments):
            raise ProfileError(f"path {path!r} is not a normalized repository-relative POSIX path")


def _check_locus(locus: str) -> None:
    """Raise `ProfileError` unless the locus is empty, a JSON Pointer or a typed locus."""
    if not locus:
        return
    if locus.startswith("/"):
        if re.search(r"~(?![01])", locus):
            raise ProfileError(f"JSON Pointer {locus!r} holds a `~` not followed by 0 or 1")
        return
    kind, colon, _ = locus.partition(":")
    if not colon or kind not in LOCUS_TYPES:
        raise ProfileError(
            f"locus {locus!r} is neither a JSON Pointer nor a typed locus of "
            f"{sorted(LOCUS_TYPES)}"
        )


@dataclass(frozen=True)
class Identity:
    """
    Components of the identity of one finding, with its canonical string.

    Each text component is normalized to NFC on construction, then checked against the form that
    the profile requires.

    Attributes
    ----------
    tool : str
        Name of the producer, equal to `run.tool.driver.name`.
    rule_id : str
        Identifier of the rule within its tool, equal to `result.ruleId`.
    resource : str
        Affected resource, `id:<identifier>` or `path:<repository-relative path>`.
    locus : str, default ""
        Semantic locus within the resource: a JSON Pointer, a typed locus `<type>:<value>`, or the
        empty string for the whole resource.
    discriminator : str, default ""
        Normalized offending content separating two findings at one locus, or the empty string.
    ordinal : int, default 1
        Rank of the finding among the identical occurrences of one tool; 1 is never written.

    Raises
    ------
    ProfileError
        If a component breaks the form that the profile requires.
    """

    tool: str
    rule_id: str
    resource: str
    locus: str = ""
    discriminator: str = ""
    ordinal: int = 1

    def __post_init__(self) -> None:
        for name in ("tool", "rule_id", "resource", "locus", "discriminator"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ProfileError(f"component {name} is not a string: {value!r}")
            object.__setattr__(self, name, unicodedata.normalize("NFC", value))
        if not TOOL_PATTERN.fullmatch(self.tool):
            raise ProfileError(f"tool name {self.tool!r} does not match {TOOL_PATTERN.pattern}")
        if not RULE_PATTERN.fullmatch(self.rule_id):
            raise ProfileError(f"ruleId {self.rule_id!r} does not match {RULE_PATTERN.pattern}")
        check_resource(self.resource)
        _check_locus(self.locus)
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise ProfileError(f"ordinal {self.ordinal!r} is not an integer of at least 1")

    @property
    def base(self) -> "Identity":
        """The identity without its ordinal, shared by every identical occurrence."""
        return replace(self, ordinal=1)

    def __str__(self) -> str:
        """
        Build the canonical identity string.

        Trailing empty components are removed. An ordinal of 2 or more pads the string to five
        components, then appends `|<ordinal>`.
        """
        fields = [
            escape(component)
            for component in (
                self.tool,
                self.rule_id,
                self.resource,
                self.locus,
                self.discriminator,
            )
        ]
        if self.ordinal > 1:
            fields.append(str(self.ordinal))
        else:
            while not fields[-1]:
                fields.pop()
        return SEPARATOR.join(fields)

    @classmethod
    def parse(cls, text: str) -> "Identity":
        """
        Parse a canonical identity string back into its components.

        Parameters
        ----------
        text : str
            Identity string, as written in `fingerprints["elenchos/v1"]`.

        Returns
        -------
        Identity
            The components of the string.

        Raises
        ------
        ProfileError
            If the string is not the canonical string of any identity: a wrong number of
            components, a trailing empty component, an ordinal below 2 or with a leading zero, an
            invalid escape, or a component not in NFC.
        """
        fields = text.split(SEPARATOR)
        if not 3 <= len(fields) <= FIELD_COUNT + 1:
            raise ProfileError(f"identity {text!r} holds {len(fields)} components, not 3 to 6")
        ordinal = 1
        if len(fields) == FIELD_COUNT + 1:
            written = fields.pop()
            if not ORDINAL_PATTERN.fullmatch(written) or int(written) < 2:
                raise ProfileError(
                    f"ordinal {written!r} of {text!r} is not an integer of 2 or more"
                )
            ordinal = int(written)
        elif not fields[-1]:
            raise ProfileError(f"identity {text!r} ends with an empty component")
        components = [unescape(field) for field in fields]
        components += [""] * (FIELD_COUNT - len(components))
        for component in components:
            if unicodedata.normalize("NFC", component) != component:
                raise ProfileError(f"component {component!r} of {text!r} is not in NFC")
        tool, rule_id, resource, locus, discriminator = components
        return cls(tool, rule_id, resource, locus, discriminator, ordinal)


def number_occurrences(occurrences: Sequence[tuple[Identity, OrderKey]]) -> list[Identity]:
    """
    Assign ordinals to the identical occurrences of a set of findings.

    Occurrences sharing one identity are sorted by their order key, then by their position in the
    input. The first keeps ordinal 1; the k-th receives ordinal k.

    Parameters
    ----------
    occurrences : Sequence[tuple[Identity, OrderKey]]
        Identity without ordinal of each finding, with the key ordering identical occurrences.
        The identity holds the tool, so findings of two tools never share one.

    Returns
    -------
    list[Identity]
        The identity of each finding, with its ordinal, in the order of the input.

    Raises
    ------
    ProfileError
        If an input identity already carries an ordinal.

    Examples
    --------
    >>> base = Identity("geonexus", "links/broken", "path:r.md", "link:o.md")
    >>> numbered = number_occurrences([(base, (30, 1, "")), (base, (12, 1, ""))])
    >>> [str(identity) for identity in numbered]
    ['geonexus|links/broken|path:r.md|link:o.md||2', 'geonexus|links/broken|path:r.md|link:o.md']
    """
    for identity, _ in occurrences:
        if identity.ordinal != 1:
            raise ProfileError(f"identity {identity} already carries an ordinal")
    ranked = sorted(range(len(occurrences)), key=lambda i: (occurrences[i][1], i))
    numbered: list[Identity | None] = [None] * len(occurrences)
    counts: dict[Identity, int] = {}
    for index in ranked:
        identity = occurrences[index][0]
        counts[identity] = counts.get(identity, 0) + 1
        numbered[index] = replace(identity, ordinal=counts[identity])
    return [identity for identity in numbered if identity is not None]
