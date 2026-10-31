"""
Suppressions file of a consumer: the identities of tolerated findings, each with its reason.

A suppressions file lists the findings that a consumer accepts as debts. Each entry names one
identity of the findings profile and states its justification. The gate applies each entry as an
external suppression with status `accepted`, and reports an entry matching no result as stale, so
that the file may only shrink. The format is published as the JSON Schema
`specs/schemas/suppressions.schema.json`, and specified in `docs/configuration.md`.

Classes
-------
Suppression
    One entry of a suppressions file.

Functions
---------
load_suppressions(path) -> dict[str, Suppression]
    Read and validate a suppressions file.
parse_suppressions(data, path) -> dict[str, Suppression]
    Validate the parsed content of a suppressions file.

Examples
--------
>>> from pathlib import Path
>>> entries = parse_suppressions(
...     {
...         "version": 1,
...         "suppressions": [
...             {"identity": "geonexus|links/broken|path:a.md|link:b.md", "justification": "old"}
...         ],
...     },
...     Path("suppressions.json"),
... )
>>> entries["geonexus|links/broken|path:a.md|link:b.md"].sarif()
{'kind': 'external', 'status': 'accepted', 'justification': 'old'}
"""

from dataclasses import dataclass
import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .errors import ConfigurationError, ProfileError
from .identity import Identity
from .sarif import GATE_TOOL, JsonObject

FORMAT_VERSION = 1
"""Version of the suppressions format read by this release; its identities are `elenchos/v1`."""

DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
"""Form of the date of an entry: an ISO 8601 calendar date."""

_TOP_KEYS = frozenset({"version", "suppressions"})
_ENTRY_KEYS = frozenset({"identity", "justification", "date", "author"})


@dataclass(frozen=True)
class Suppression:
    """
    One entry of a suppressions file.

    Attributes
    ----------
    identity : str
        Canonical identity string of the suppressed finding.
    justification : str
        Reason for which the finding is tolerated.
    date : str | None, default None
        ISO 8601 date on which the entry was written.
    author : str | None, default None
        Author of the entry.
    """

    identity: str
    justification: str
    date: str | None = None
    author: str | None = None

    def sarif(self) -> JsonObject:
        """
        Build the SARIF `suppression` object of this entry.

        Returns
        -------
        JsonObject
            An external suppression with status `accepted` and the justification of the entry.
            The date and the author, when present, go to the properties `elenchos/date` and
            `elenchos/author`.
        """
        suppression: JsonObject = {
            "kind": "external",
            "status": "accepted",
            "justification": self.justification,
        }
        properties = {
            f"{GATE_TOOL}/{key}": value
            for key, value in (("date", self.date), ("author", self.author))
            if value is not None
        }
        if properties:
            suppression["properties"] = properties
        return suppression


def _fail(path: Path, location: str, problem: str) -> ConfigurationError:
    """Build the error naming the file, the entry and the problem."""
    return ConfigurationError(f"{path}: {location}: {problem}")


def _entry(value: Any, path: Path, location: str) -> Suppression:
    """Validate one entry of the array `suppressions`."""
    if not isinstance(value, Mapping):
        raise _fail(path, location, "is not an object")
    unknown = sorted(set(value) - _ENTRY_KEYS)
    if unknown:
        raise _fail(path, location, f"holds unknown keys {unknown}")
    identity = value.get("identity")
    if not isinstance(identity, str):
        raise _fail(path, location, "holds no identity")
    try:
        Identity.parse(identity)
    except ProfileError as error:
        raise _fail(path, location, f"identity is not canonical: {error}") from error
    justification = value.get("justification")
    if not isinstance(justification, str) or not justification.strip():
        raise _fail(path, location, "holds no justification")
    date = value.get("date")
    if date is not None:
        try:
            if not isinstance(date, str) or not DATE_PATTERN.fullmatch(date):
                raise ValueError(date)
            datetime.date.fromisoformat(date)
        except ValueError as error:
            raise _fail(path, location, f"date {date!r} is not YYYY-MM-DD") from error
    author = value.get("author")
    if author is not None and (not isinstance(author, str) or not author.strip()):
        raise _fail(path, location, "author is not a non-empty string")
    return Suppression(identity, justification, date, author)


def parse_suppressions(data: Any, path: Path) -> dict[str, Suppression]:
    """
    Validate the parsed content of a suppressions file.

    Parameters
    ----------
    data : Any
        Content of the file, as returned by `json.load`.
    path : Path
        Path of the file, named in error messages.

    Returns
    -------
    dict[str, Suppression]
        The entries keyed by identity, in the order of the file.

    Raises
    ------
    ConfigurationError
        If a key is unknown or missing, an identity is not canonical, a justification is empty, a
        date or an author breaks its form, or two entries name one identity.
    """
    if not isinstance(data, Mapping):
        raise _fail(path, "top level", "is not an object")
    unknown = sorted(set(data) - _TOP_KEYS)
    if unknown:
        raise _fail(path, "top level", f"holds unknown keys {unknown}")
    version = data.get("version")
    if isinstance(version, bool) or version != FORMAT_VERSION:
        raise _fail(path, "version", f"is not {FORMAT_VERSION}")
    array = data.get("suppressions")
    if not isinstance(array, list):
        raise _fail(path, "suppressions", "is not an array")
    entries: dict[str, Suppression] = {}
    for index, value in enumerate(array):
        entry = _entry(value, path, f"suppressions[{index}]")
        if entry.identity in entries:
            raise _fail(path, f"suppressions[{index}]", f"repeats the identity {entry.identity!r}")
        entries[entry.identity] = entry
    return entries


def load_suppressions(path: Path) -> dict[str, Suppression]:
    """
    Read and validate a suppressions file.

    Parameters
    ----------
    path : Path
        Path of the JSON suppressions file.

    Returns
    -------
    dict[str, Suppression]
        The entries keyed by identity, in the order of the file.

    Raises
    ------
    ConfigurationError
        If the file cannot be read, is not JSON, or breaks the format (see
        `parse_suppressions`).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"{path}: cannot be read as JSON: {error}") from error
    return parse_suppressions(data, path)
