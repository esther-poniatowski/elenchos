"""Shared writer of the fake checks: one SARIF log of one run, written to the path given."""

import json
import sys
from pathlib import Path
from typing import Any


def result(
    rule_id: str, level: str, name: str, line: int | None = None, message: str = "finding"
) -> dict[str, Any]:
    """A result of the profile at a logical location, with an optional line."""
    location: dict[str, Any] = {"logicalLocations": [{"name": name}]}
    if line is not None:
        path = name.removeprefix("path:").split("#", 1)[0]
        location["physicalLocation"] = {
            "artifactLocation": {"uri": path, "uriBaseId": "SRCROOT"},
            "region": {"startLine": line, "startColumn": 1},
        }
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [location],
    }


def write(tool: str, results: list[dict[str, Any]], status: int = 0) -> None:
    """Write a log of one run of `tool` to the path given as first argument, then exit."""
    log = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": tool, "version": "1.0.0"}},
                "columnKind": "unicodeCodePoints",
                "results": results,
            }
        ],
    }
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(log), encoding="utf-8")
    sys.exit(status)
