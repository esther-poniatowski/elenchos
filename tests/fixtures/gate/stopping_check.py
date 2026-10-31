"""Fake check of tool `stopper`, whose run ends as its first argument says, written to the path of
its second.

- `partial`: stops by design at its first failure, declares a failed invocation with a notification
  of level `error`, and holds the one result detected before the stop;
- `failed`: crashes before its analysis begins, declares a failed invocation, and omits `results`;
- `succeeded`: declares a successful invocation and holds no result.
"""

import sys

from sarif_writer import result, write

STOP = {
    "executionSuccessful": False,
    "toolExecutionNotifications": [
        {
            "level": "error",
            "message": {"text": "stopped at the first failure; later stages skipped"},
        }
    ],
}

mode = sys.argv[1]
if mode == "partial":
    write("stopper", [result("stage/failed", "error", "path:s.md")], status=1, invocation=STOP)
elif mode == "failed":
    write("stopper", None, status=1, invocation={"executionSuccessful": False})
elif mode == "succeeded":
    write("stopper", [], invocation={"executionSuccessful": True})
