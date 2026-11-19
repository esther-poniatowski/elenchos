"""
Patterns of JSON Schema read with the semantics of ECMA-262 by the regular expressions of Python.

JSON Schema writes its patterns in the dialect of ECMA-262, where `$` matches at the end of the
string only. In Python, `$` also matches before a final newline, so `re.search("^a$", "a\\n")`
succeeds where ECMA-262 fails. This module rewrites each `$` anchor as `\\Z` in a copy of a schema,
so that a validator in Python and one in JavaScript give one verdict on one instance.

Functions
---------
python_pattern(pattern) -> str
    Rewrite the `$` anchors of an ECMA-262 pattern for the module `re`.
ecma_pattern(pattern) -> str
    Return the ECMA-262 pattern that `python_pattern` rewrote into a pattern.
python_schema(schema) -> Any
    Copy a schema with every pattern rewritten by `python_pattern`.
"""

from typing import Any

_ORIGINALS: dict[str, str] = {}
"""The ECMA-262 pattern of each pattern rewritten by `python_pattern`, for the messages."""

_SCHEMA_VALUED = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
"""Keywords whose value is one schema, or a list of schemas for `items` in early drafts."""

_SCHEMA_LISTS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
"""Keywords whose value is a list of schemas."""

_SCHEMA_MAPS = frozenset({"$defs", "definitions", "dependentSchemas", "dependencies", "properties"})
"""Keywords whose value maps names to schemas; `dependencies` may also map names to lists."""


def python_pattern(pattern: str) -> str:
    """
    Rewrite the `$` anchors of an ECMA-262 pattern for the module `re`.

    A `$` outside a character class and not escaped becomes `\\Z`, which matches at the end of the
    string only, as `$` does in ECMA-262 without the flag `m`.

    Parameters
    ----------
    pattern : str
        A pattern of JSON Schema.

    Returns
    -------
    str
        The same pattern, for `re.search`.

    Examples
    --------
    >>> python_pattern(r"^a(?:#|$)[$]\\$$")
    '^a(?:#|\\\\Z)[$]\\\\$\\\\Z'
    """
    out: list[str] = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            out.append(pattern[index : index + 2])
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "$":
            char = "\\Z"
        out.append(char)
        index += 1
    rewritten = "".join(out)
    _ORIGINALS.setdefault(rewritten, pattern)
    return rewritten


def ecma_pattern(pattern: str) -> str:
    """
    Return the ECMA-262 pattern that `python_pattern` rewrote into `pattern`, for a message.

    Examples
    --------
    >>> ecma_pattern(python_pattern("^a$")), ecma_pattern("never rewritten")
    ('^a$', 'never rewritten')
    """
    return _ORIGINALS.get(pattern, pattern)


def python_schema(schema: Any) -> Any:
    """
    Copy a schema with every pattern rewritten by `python_pattern`.

    The rewrite reaches the value of `pattern` and the keys of `patternProperties` at each position
    of a schema. The value of a keyword outside JSON Schema, such as `const` or an `x-` keyword, is
    data, and is copied unchanged.

    Parameters
    ----------
    schema : Any
        A JSON Schema, as a mapping or a boolean.

    Returns
    -------
    Any
        A copy of the schema.

    Examples
    --------
    >>> python_schema({"properties": {"a": {"pattern": "^x$"}}, "const": {"pattern": "^x$"}})
    {'properties': {'a': {'pattern': '^x\\\\Z'}}, 'const': {'pattern': '^x$'}}
    """
    if not isinstance(schema, dict):
        return schema
    copied: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "pattern" and isinstance(value, str):
            copied[key] = python_pattern(value)
        elif key == "patternProperties" and isinstance(value, dict):
            copied[key] = {
                python_pattern(name): python_schema(item) for name, item in value.items()
            }
        elif key in _SCHEMA_VALUED:
            copied[key] = (
                [python_schema(item) for item in value]
                if isinstance(value, list)
                else python_schema(value)
            )
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            copied[key] = [python_schema(item) for item in value]
        elif key in _SCHEMA_MAPS and isinstance(value, dict):
            copied[key] = {name: python_schema(item) for name, item in value.items()}
        else:
            copied[key] = value
    return copied
