"""Formatting-insensitive helpers for renderer-dependent markdown assertions.

``pdf-inspector`` renders markdown itself, so its exact output is not part of
this package's contract: pipe padding, empty table cells, and list bullet
glyphs can change between releases. These helpers compare the meaningful
content (table cells, list items) without depending on that cosmetic
formatting.
"""

from __future__ import annotations

import re

# Unordered list markers emitted by the renderers we support: U+2022 bullet,
# U+2013 en dash, U+25E6 white bullet, U+25AA black small square, and ASCII.
BULLET_MARKERS: tuple[str, ...] = (
    "\u2022",
    "\u2013",
    "\u25e6",
    "\u25aa",
    "-",
    "*",
    "+",
)

# A list marker must be the first non-space character on the line; the
# renderers may or may not emit a space after it (``•item`` and ``- item``).
_LIST_MARKER = re.compile(rf"^\s*(?:{'|'.join(map(re.escape, BULLET_MARKERS))})\s*")

_WHITESPACE = re.compile(r"\s+")

# Token for an interior empty table cell, so a dropped column is still visible
# instead of being silently collapsed away.
EMPTY_CELL = "<empty>"


def normalize_table_markup(text: str) -> str:
    """Normalize pipe padding and interior empty cells in markdown table rows.

    Renderers differ in how they pad pipe-delimited rows and whether they emit
    an empty cell for a visually blank column. Cell *contents* are preserved
    (whitespace runs inside a cell collapse to a single space) so that a real
    content change still fails an assertion. Interior empty cells become
    ``<empty>`` rather than being deleted, so a dropped column is detectable.
    Non-table lines are ignored.

    For example, ``| widget |  | 3 active |`` normalizes to
    ``|widget|<empty>|3 active|``.
    """
    rows: list[str] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [_WHITESPACE.sub(" ", cell).strip() for cell in line.split("|")]
        # The first and last entries are the empty boundaries around the row.
        inner = [cell or EMPTY_CELL for cell in cells[1:-1]]
        rows.append("|" + "|".join(inner) + "|")
    return "\n".join(rows)


def has_list_item(content: str, item_text: str) -> bool:
    """Return whether ``item_text`` shares a line with a leading list marker.

    Nested items may be emitted inline after their parent item, so the marker
    only has to lead the line; ``item_text`` may then appear anywhere after it.
    A hyphen or asterisk in ordinary prose does not count as a list marker.
    """
    for line in content.splitlines():
        match = _LIST_MARKER.match(line)
        if match is not None and item_text in line[match.end() :]:
            return True
    return False
