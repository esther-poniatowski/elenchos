"""Fake check of tool `linker`: two distinct broken links, one link broken twice, one warning.

It exits 1, as a producer does when it reports findings.
"""

from sarif_writer import result, write

write(
    "linker",
    [
        result("links/broken", "error", "path:a.md#link:x.md", 3),
        result("links/broken", "error", "path:a.md#link:y.md", 5),
        result("links/broken", "error", "path:b.md#link:z.md", 9),
        result("links/broken", "error", "path:b.md#link:z.md", 2),
        result("links/style", "warning", "path:a.md"),
    ],
    status=1,
)
