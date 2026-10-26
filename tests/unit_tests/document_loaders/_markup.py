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

_WHITESPACE = re.compile(r"\s+")
_EMPTY_CELLS = re.compile(r"\|{2,}")


def normalize_table_markup(text: str) -> str:
    """Strip whitespace and collapse empty cells in markdown table text.

    Renderers differ in how they pad pipe-delimited rows and whether they emit
    an empty cell for a visually blank column, so assertions compare the
    normalized form (for example ``|widget|3active|``) instead of an exact row.
    """
    return _EMPTY_CELLS.sub("|", _WHITESPACE.sub("", text))


def has_list_item(content: str, item_text: str) -> bool:
    """Return whether ``item_text`` shares a line with an unordered list marker.

    Nested items may be emitted inline after their parent item, so the marker
    only has to appear before the text on the same line.
    """
    for line in content.splitlines():
        index = line.find(item_text)
        if index != -1 and any(marker in line[:index] for marker in BULLET_MARKERS):
            return True
    return False
