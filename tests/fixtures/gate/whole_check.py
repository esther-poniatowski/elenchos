"""Fake check of tool `scoper`, of scope `root`: it evaluates the rule `headings/missing` on the
whole root, and finds nothing. Its driver lists that rule alone."""

import sys
from pathlib import Path

from sarif_writer import write

write("scoper", [], target=Path(sys.argv[1]), rules=["headings/missing"])
