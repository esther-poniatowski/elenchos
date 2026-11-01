"""Fake check of tool `scoper`, of scope `paths`: one broken link in `a.md` and one in `b.md`.

Given paths after the log path, it reports only the findings in those files, as a producer does
in a scoped run. It exits 1 when it reports a finding, 0 otherwise.
"""

import sys
from pathlib import Path

from sarif_writer import result, write

FINDINGS = {
    "a.md": result("links/broken", "error", "path:a.md#link:x.md", 3),
    "b.md": result("links/broken", "error", "path:b.md#link:y.md", 4),
}
paths = sys.argv[2:]
selected = [finding for path, finding in FINDINGS.items() if not paths or path in paths]
write("scoper", selected, status=1 if selected else 0, target=Path(sys.argv[1]))
