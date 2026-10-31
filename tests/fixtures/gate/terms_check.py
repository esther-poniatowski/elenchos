"""Fake check of tool `terms`: a forbidden term and an advice, both warnings, and a note."""

from sarif_writer import result, write

write(
    "terms",
    [
        result("terms/forbidden", "warning", "path:c.md#term:competition", 4),
        result("terms/advice", "warning", "path:c.md#term:rivalry", 6),
        result("terms/hint", "note", "path:c.md"),
    ],
)
