"""Fake check that misbehaves as its first argument says, writing to the path of its second.

- `crash`: prints a traceback line and exits 3, an undeclared status;
- `silent`: exits 0 and writes no log;
- `garbage`: writes a log that is not JSON;
- `vector:<case>`: writes the log of a rejected vector of the profile;
- `level`: writes a log whose result has the level `none`.
"""

import json
import sys
from pathlib import Path

mode, target = sys.argv[1], Path(sys.argv[2])
if mode == "crash":
    print("RuntimeError: the checker crashed", file=sys.stderr)
    sys.exit(3)
if mode == "silent":
    sys.exit(0)
if mode == "garbage":
    target.write_text("not a SARIF log", encoding="utf-8")
elif mode.startswith("vector:"):
    vectors = Path(__file__).parents[3] / "specs" / "vectors" / "rejected.json"
    case = mode.removeprefix("vector:")
    log = next(v["log"] for v in json.loads(vectors.read_text()) if v["case"] == case)
    target.write_text(json.dumps(log), encoding="utf-8")
elif mode == "level":
    result = {
        "ruleId": "x/y",
        "level": "none",
        "message": {"text": "m"},
        "locations": [{"logicalLocations": [{"name": "path:a.md"}]}],
    }
    log = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "odd"}}, "results": [result]}]}
    target.write_text(json.dumps(log), encoding="utf-8")
