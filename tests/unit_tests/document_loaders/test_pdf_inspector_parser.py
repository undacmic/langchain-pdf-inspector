"""Unit tests for the ``PdfInspectorParser`` blob parser."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorParser

from ._markup import has_list_item, normalize_table_markup

# ---------------------------------------------------------------------------
# Fixture facts (verified against the LaTeX sources and `detect_pdf_bytes`)
# ---------------------------------------------------------------------------

# Physical page count of every built fixture PDF, read from the `.tex` sources
# (explicit page breaks / multi-page layout) and confirmed against the parser
# output so the "one Document per page" assertions stay truthful. The generic
# single-document and page-count tests are parametrized over this mapping, so
# every fixture (including the cross-cutting `cropbox_offset` and
# `document_info` ones) gets the standard sanity checks.
FIXTURE_PAGE_COUNTS: dict[str, int] = {
    "plain_text": 3,
    "headings": 1,
    "lists": 1,
    "two_column": 1,
    "tables": 2,
    "complex_layout": 2,
    "cropbox_offset": 1,
    "document_info": 1,
    "tagged_structure": 2,
    "rotated_text": 1,
}

ALL_FIXTURES: list[str] = sorted(FIXTURE_PAGE_COUNTS)

# The (page, [[x0, y0, x1, y1], ...]) region that crops the line carrying the
# `plaintextsentinel-foxtrot` marker on the *second* page (0-indexed page 1)
# of `plain_text.pdf`. Region coordinates use the top-left origin with y
# increasing downward, which is the coordinate space consumed by
# `extract_text_in_regions` (verified empirically).
FOXTROT_REGION: tuple[int, list[list[float]]] = (1, [[130.0, 140.0, 490.0, 165.0]])


def _blob_from_pdf(pdf_path: Path) -> Blob:
    """Wrap a conftest fixture PDF path in a ``Blob`` for the parser."""
    return Blob.from_path(str(pdf_path))


# ---------------------------------------------------------------------------
# Single mode: length, metadata, and content
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_single_mode_yields_exactly_one_document(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """Single mode produces exactly one ``Document`` for the whole PDF."""
    pdf_path = request.getfixturevalue(f"{fixture_name}_pdf")
    blob = _blob_from_pdf(pdf_path)
    docs = PdfInspectorParser().parse(blob)
    assert len(docs) == 1
    assert isinstance(docs[0], Document)


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_single_mode_metadata_is_sane(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """Every single-mode ``Document`` carries ``source``, ``page``, and detection metadata."""
    pdf_path = request.getfixturevalue(f"{fixture_name}_pdf")
    name = pdf_path.stem
    blob = _blob_from_pdf(pdf_path)
    doc = PdfInspectorParser().parse(blob)[0]

    assert isinstance(doc.page_content, str)
    assert doc.page_content, "single-mode content should be non-empty"

    metadata = doc.metadata
    # `source` points at the fixture PDF (Blob.from_path resolves the path).
    assert metadata["source"].endswith(f"{name}.pdf")
    # Single mode is always one joined document, tagged as page 1.
    assert metadata["page"] == 1
    # Detection metadata is attached for every text-based fixture.
    assert "pdf_type" in metadata
    assert "total_pages" in metadata
    assert metadata["pdf_type"] == "text_based"
    assert metadata["total_pages"] == FIXTURE_PAGE_COUNTS[name]


@pytest.mark.requires("pdf_inspector")
def test_plain_text_content_matches_tex_source(plain_text_pdf: Path) -> None:
    """Plain-text extraction returns the prose with the sentinel markers intact."""
    blob = _blob_from_pdf(plain_text_pdf)
    content = PdfInspectorParser().parse(blob)[0].page_content

    # Sentinels from plain_text.tex appear verbatim in the extracted text.
    assert "plaintextsentinel-foxtrot" in content
    assert "plaintextsentinel-golf" in content
    # Ordinary prose from the opening paragraph is captured too.
    assert "northbound migration of the quokka population" in content


@pytest.mark.requires("pdf_inspector")
def test_plain_text_contains_no_markdown_artifacts(plain_text_pdf: Path) -> None:
    """Plain text output is prose: no heading or table markup."""
    blob = _blob_from_pdf(plain_text_pdf)
    content = PdfInspectorParser().parse(blob)[0].page_content

    assert "|" not in content
    assert not any(line.lstrip().startswith("#") for line in content.splitlines())


# ---------------------------------------------------------------------------
# Markdown output: headings, lists, tables
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_markdown_preserves_headings(headings_pdf: Path) -> None:
    """Markdown keeps the document title and section/subsection headings."""
    blob = _blob_from_pdf(headings_pdf)
    docs = PdfInspectorParser(output="markdown").parse(blob)
    assert len(docs) == 1
    content = docs[0].page_content

    assert "# Incremental Heading Fixture" in content
    for heading in (
        "## 1 Introduction",
        "## 2 Core Findings",
        "### 2.1 Methodology",
        "### 2.2 Results",
        "## 3 Conclusion",
    ):
        assert heading in content
    # Body text under the headings is preserved alongside the structure.
    assert "headingfixture-zephyr" in content


@pytest.mark.requires("pdf_inspector")
def test_markdown_preserves_lists(lists_pdf: Path) -> None:
    """Markdown keeps bulleted and numbered list content from lists.tex."""
    blob = _blob_from_pdf(lists_pdf)
    content = PdfInspectorParser(output="markdown").parse(blob)[0].page_content

    # Bullet glyphs are renderer-dependent, so assert list structure through
    # any common unordered marker instead of the exact U+2022 / U+2013 glyphs.
    assert has_list_item(content, "listsentinel-quark")  # top-level bullet
    assert has_list_item(content, "listsentinel-nested")  # nested bullet
    # A hyphen in ordinary prose is not a list marker: the marker must lead the
    # line, so this must not be treated as a bulleted item.
    assert not has_list_item(
        "well-known facts about listsentinel-quark", "listsentinel-quark"
    )
    for marker in ("1.", "2.", "3.", "(a)"):
        assert marker in content
    # All three sentinel markers survive into the markdown output.
    for sentinel in (
        "listsentinel-quark",
        "listsentinel-nested",
        "listsentinel-neutrino",
    ):
        assert sentinel in content


@pytest.mark.requires("pdf_inspector")
def test_markdown_preserves_tables(tables_pdf: Path) -> None:
    """Markdown emits pipe-separated table rows for the tabular fixtures."""
    blob = _blob_from_pdf(tables_pdf)
    content = PdfInspectorParser(output="markdown").parse(blob)[0].page_content

    assert "|" in content
    assert "|tablesentinel-beta|<empty>|7 active|" in normalize_table_markup(content)
    for sentinel in (
        "tablesentinel-alpha",
        "tablesentinel-beta",
        "tablesentinel-gamma",
    ):
        assert sentinel in content
    assert "Metric / Value" in content


@pytest.mark.requires("pdf_inspector")
def test_markdown_preserves_table_in_complex_layout(complex_layout_pdf: Path) -> None:
    """The complex-layout fixture keeps its summary table in markdown."""
    blob = _blob_from_pdf(complex_layout_pdf)
    content = PdfInspectorParser(output="markdown").parse(blob)[0].page_content

    assert "|" in content
    assert "|layoutsentinel-table|128|active|" in normalize_table_markup(content)
    for sentinel in (
        "layoutsentinel-intro",
        "layoutsentinel-wrap",
        "layoutsentinel-multicol",
        "layoutsentinel-table",
        "layoutsentinel-conclusion",
    ):
        assert sentinel in content


# ---------------------------------------------------------------------------
# Region extraction and delimiters
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_region_extraction_crops_known_area(plain_text_pdf: Path) -> None:
    """``extract_regions=True`` returns text cropped to the requested bounding box."""
    blob = _blob_from_pdf(plain_text_pdf)
    parser = PdfInspectorParser(
        extract_regions=True,
        page_regions=[FOXTROT_REGION],
    )
    docs = parser.parse(blob)
    assert len(docs) == 1
    # The crop covers the foxtrot line, which is on 0-indexed page 1.
    assert "plaintextsentinel-foxtrot" in docs[0].page_content
    # The cropped text is a strict subset: it must not include the marker from
    # the third page, which sits outside the requested region.
    assert "plaintextsentinel-golf" not in docs[0].page_content


@pytest.mark.requires("pdf_inspector")
def test_region_coordinates_are_relative_to_visible_page_box(
    cropbox_offset_pdf: Path,
) -> None:
    """Region coordinates use a top-left origin relative to the visible page box.

    ``cropbox_offset.pdf`` pins its MediaBox to ``[0 0 612 792]`` and sets a
    CropBox whose lower-left is ``(36, 54)``, so the visible page box (CropBox
    intersected with MediaBox) is ``[36 54 576 756]``: 540 x 702 points, with
    its top edge 36 points below the MediaBox top edge. The sentinel line sits
    at visible ``y`` 86-102.

    The first region is the tight band around that line in visible-page-box
    coordinates. A MediaBox-relative implementation would read it 36 points too
    high and miss the sentinel. The second region is the *same physical band*
    expressed in MediaBox coordinates (``y + 36``); under the correct
    visible-box interpretation it falls below the text, which is the negative
    half of the contract.
    """
    blob = _blob_from_pdf(cropbox_offset_pdf)

    visible_doc = PdfInspectorParser(
        extract_regions=True,
        page_regions=[(0, [[0.0, 80.0, 540.0, 110.0]])],
    ).parse(blob)[0]
    assert "cropboxsentinel-tango" in visible_doc.page_content

    mediabox_relative_doc = PdfInspectorParser(
        extract_regions=True,
        page_regions=[(0, [[0.0, 116.0, 540.0, 146.0]])],
    ).parse(blob)[0]
    assert "cropboxsentinel-tango" not in mediabox_relative_doc.page_content


@pytest.mark.requires("pdf_inspector")
def test_region_delimiter_joins_regions_in_single_mode(plain_text_pdf: Path) -> None:
    """Regions inside one page entry are joined with ``region_delimiter``."""
    blob = _blob_from_pdf(plain_text_pdf)
    # Two non-empty regions on the same page (0-indexed page 0), split top vs.
    # bottom of the text block.
    page_regions = [(0, [[0.0, 0.0, 612.0, 150.0], [0.0, 150.0, 612.0, 300.0]])]
    parser = PdfInspectorParser(
        extract_regions=True,
        page_regions=page_regions,
        region_delimiter="<REG>",
    )
    doc = parser.parse(blob)[0]
    # Two region texts joined by the custom delimiter.
    assert doc.page_content.count("<REG>") == 1
    assert "This is the opening paragraph of the plain text fixture" in doc.page_content


@pytest.mark.requires("pdf_inspector")
def test_region_delimiter_joins_regions_in_page_mode(plain_text_pdf: Path) -> None:
    """Page-mode region text uses ``region_delimiter`` for regions on one page."""
    blob = _blob_from_pdf(plain_text_pdf)
    page_regions = [(0, [[0.0, 0.0, 612.0, 150.0], [0.0, 150.0, 612.0, 300.0]])]
    parser = PdfInspectorParser(
        mode="page",
        output="text",
        extract_regions=True,
        page_regions=page_regions,
        pages=[0],
        region_delimiter="<REG>",
    )
    docs = parser.parse(blob)
    # Both regions live on the same page, so page mode yields one `Document`.
    assert len(docs) == 1
    assert docs[0].metadata["page"] == 1
    assert docs[0].page_content.count("<REG>") == 1


@pytest.mark.requires("pdf_inspector")
def test_page_delimiter_joins_pages_in_positional_single_mode(
    plain_text_pdf: Path,
) -> None:
    """Single-mode positional text joins pages with ``page_delimiter``."""
    blob = _blob_from_pdf(plain_text_pdf)
    parser = PdfInspectorParser(extract_positions=True, page_delimiter="<PAGE>")
    doc = parser.parse(blob)[0]
    # plain_text.pdf has three pages -> two delimiter joins.
    assert doc.page_content.count("<PAGE>") == 2
    assert "plaintextsentinel-foxtrot" in doc.page_content
    assert "plaintextsentinel-golf" in doc.page_content


@pytest.mark.requires("pdf_inspector")
def test_page_delimiter_joins_pages_in_region_single_mode(plain_text_pdf: Path) -> None:
    """Single-mode region text from separate page entries joins with ``page_delimiter``."""
    blob = _blob_from_pdf(plain_text_pdf)
    # One region on page 0 and one on page 1 -> two page entries.
    page_regions = [
        (0, [[0.0, 0.0, 612.0, 150.0]]),
        FOXTROT_REGION,
    ]
    parser = PdfInspectorParser(
        extract_regions=True,
        page_regions=page_regions,
        page_delimiter="<PAGE>",
    )
    doc = parser.parse(blob)[0]
    assert doc.page_content.count("<PAGE>") == 1
    assert "This is the opening paragraph of the plain text fixture" in doc.page_content
    assert "plaintextsentinel-foxtrot" in doc.page_content


@pytest.mark.requires("pdf_inspector")
def test_single_mode_positions_joins_all_pages(plain_text_pdf: Path) -> None:
    """Single-mode positional extraction returns one joined document with all pages."""
    blob = _blob_from_pdf(plain_text_pdf)
    docs = PdfInspectorParser(extract_positions=True).parse(blob)
    assert len(docs) == 1
    assert docs[0].metadata["page"] == 1
    assert "plaintextsentinel-foxtrot" in docs[0].page_content
    assert "plaintextsentinel-golf" in docs[0].page_content


# ---------------------------------------------------------------------------
# Page mode: one Document per page
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize("fixture_name", ALL_FIXTURES)
def test_page_mode_markdown_one_document_per_page(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """Page-mode markdown yields one ``Document`` per requested page (1-indexed)."""
    pdf_path = request.getfixturevalue(f"{fixture_name}_pdf")
    name = pdf_path.stem
    page_count = FIXTURE_PAGE_COUNTS[name]
    blob = _blob_from_pdf(pdf_path)

    parser = PdfInspectorParser(
        mode="page",
        output="markdown",
        pages=list(range(page_count)),
    )
    docs = parser.parse(blob)

    assert len(docs) == page_count
    assert [doc.metadata["page"] for doc in docs] == list(range(1, page_count + 1))
    for doc in docs:
        assert isinstance(doc, Document)
        assert isinstance(doc.page_content, str)
        assert doc.metadata["source"].endswith(f"{name}.pdf")
        # Per-page markdown layout flags are always present and boolean.
        for flag in ("needs_ocr", "has_tables", "has_multicolumn_layout"):
            assert flag in doc.metadata
            assert isinstance(doc.metadata[flag], bool)


@pytest.mark.requires("pdf_inspector")
def test_page_mode_markdown_layout_flags_tables(tables_pdf: Path) -> None:
    """Page 1 of tables.pdf is flagged as containing tables."""
    blob = _blob_from_pdf(tables_pdf)
    docs = PdfInspectorParser(mode="page", output="markdown", pages=[0, 1]).parse(blob)

    assert len(docs) == 2
    tables_page = docs[0]
    assert tables_page.metadata["page"] == 1
    assert tables_page.metadata["has_tables"] is True
    assert "|" in tables_page.page_content


@pytest.mark.requires("pdf_inspector")
def test_page_mode_markdown_layout_flags_complex(complex_layout_pdf: Path) -> None:
    """The complex-layout fixture flags its table + multi-column page."""
    blob = _blob_from_pdf(complex_layout_pdf)
    docs = PdfInspectorParser(mode="page", output="markdown", pages=[0, 1]).parse(blob)

    assert len(docs) == 2
    # The summary table and the two-column region flow onto page 2 of the
    # fixture, which is where the library reports them.
    table_page = docs[1]
    assert table_page.metadata["page"] == 2
    assert table_page.metadata["has_tables"] is True
    assert table_page.metadata["has_multicolumn_layout"] is True
    assert "|" in table_page.page_content


@pytest.mark.requires("pdf_inspector")
def test_page_mode_text_positions(plain_text_pdf: Path) -> None:
    """Page-mode positional text yields one ``Document`` per requested page."""
    # ``pages`` is 0-indexed, so ``[0, 1, 2]`` selects all three pages of the
    # fixture and the parser translates them to upstream's 1-indexed argument.
    blob = _blob_from_pdf(plain_text_pdf)
    docs = PdfInspectorParser(
        mode="page", output="text", extract_positions=True, pages=[0, 1, 2]
    ).parse(blob)

    assert [doc.metadata["page"] for doc in docs] == [1, 2, 3]
    for doc in docs:
        assert isinstance(doc.page_content, str)
        assert doc.page_content
    # The foxtrot marker lives on the second physical page.
    foxtrot_doc = next(doc for doc in docs if doc.metadata["page"] == 2)
    assert "plaintextsentinel-foxtrot" in foxtrot_doc.page_content


# Unique sentinel on each physical page of ``plain_text.pdf`` (1-indexed).
PAGE_SENTINELS: dict[int, str] = {
    1: "quokka",
    2: "plaintextsentinel-foxtrot",
    3: "plaintextsentinel-golf",
}


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize("pages", [[0, 1, 2], [1, 2, 99]])
def test_page_mode_positions_and_markdown_select_same_pages(
    plain_text_pdf: Path, pages: list[int]
) -> None:
    """The same 0-indexed ``pages`` selection means the same pages in both paths.

    The second case includes an out-of-range index (``99``); both paths omit
    it, so page 100 is never emitted.
    """
    blob = _blob_from_pdf(plain_text_pdf)

    positions_docs = PdfInspectorParser(
        mode="page", output="text", extract_positions=True, pages=pages
    ).parse(blob)
    markdown_docs = PdfInspectorParser(
        mode="page", output="markdown", pages=pages
    ).parse(blob)

    positions_pages = [doc.metadata["page"] for doc in positions_docs]
    markdown_pages = [doc.metadata["page"] for doc in markdown_docs]
    assert sorted(positions_pages) == sorted(markdown_pages)
    assert all(page <= 3 for page in positions_pages)

    positions_by_page = {
        doc.metadata["page"]: doc.page_content for doc in positions_docs
    }
    markdown_by_page = {doc.metadata["page"]: doc.page_content for doc in markdown_docs}
    # The same page number must carry the same page's content in both paths.
    for page in positions_pages:
        sentinel = PAGE_SENTINELS[page]
        assert sentinel in positions_by_page[page]
        assert sentinel in markdown_by_page[page]


@pytest.mark.requires("pdf_inspector")
def test_page_mode_regions(plain_text_pdf: Path) -> None:
    """Page-mode region extraction yields one ``Document`` per region entry."""
    blob = _blob_from_pdf(plain_text_pdf)
    page_regions = [
        (0, [[0.0, 0.0, 612.0, 150.0]]),
        FOXTROT_REGION,
    ]
    docs = PdfInspectorParser(
        mode="page",
        output="text",
        extract_regions=True,
        page_regions=page_regions,
        pages=[0, 1],
    ).parse(blob)

    assert len(docs) == 2
    assert [doc.metadata["page"] for doc in docs] == [1, 2]
    assert "This is the opening paragraph" in docs[0].page_content
    assert "plaintextsentinel-foxtrot" in docs[1].page_content


# ---------------------------------------------------------------------------
# Lazy vs. eager parsing
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_lazy_parse_matches_parse(plain_text_pdf: Path) -> None:
    """``list(lazy_parse(blob))`` equals ``parse(blob)`` across every extraction path."""
    blob = _blob_from_pdf(plain_text_pdf)
    configs = [
        PdfInspectorParser(),
        PdfInspectorParser(output="markdown"),
        PdfInspectorParser(extract_positions=True),
        PdfInspectorParser(extract_regions=True, page_regions=[FOXTROT_REGION]),
        PdfInspectorParser(mode="page", output="markdown", pages=[0, 1, 2]),
        PdfInspectorParser(
            mode="page", output="text", extract_positions=True, pages=[0, 1, 2]
        ),
    ]
    for parser in configs:
        eager = parser.parse(blob)
        lazy = list(parser.lazy_parse(blob))
        assert len(eager) == len(lazy)
        for eager_doc, lazy_doc in zip(eager, lazy, strict=True):
            assert eager_doc.page_content == lazy_doc.page_content
            assert eager_doc.metadata == lazy_doc.metadata


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize(
    ("kwargs", "error_fragment"),
    [
        ({"mode": "chunk"}, "mode must be either"),
        ({"output": "html"}, "output must be either"),
        ({"mode": "page"}, "pages is required when mode='page'"),
        ({"mode": "page", "pages": []}, "pages is required when mode='page'"),
        ({"pages": [-1]}, "non-negative"),
        ({"pages": [0, -2]}, "non-negative"),
        ({"extract_positions": True, "extract_regions": True}, "mutually exclusive"),
        ({"extract_regions": True}, "page_regions is required"),
        (
            {"mode": "page", "output": "text", "pages": [0]},
            "page mode with output='text' requires",
        ),
        ({"region_delimiter": 123}, "region_delimiter must be a string"),
        ({"page_delimiter": object()}, "page_delimiter must be a string"),
    ],
)
def test_invalid_arguments_raise_value_error(
    kwargs: dict[str, Any], error_fragment: str
) -> None:
    """Invalid constructor arguments are rejected with a clear ``ValueError``."""
    with pytest.raises(ValueError, match=error_fragment):
        PdfInspectorParser(**kwargs)


# ---------------------------------------------------------------------------
# Upstream failures and metadata fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_missing_pdf_inspector_raises_import_error(plain_text_pdf: Path) -> None:
    """A missing ``pdf_inspector`` package raises a friendly ``ImportError``."""
    with (
        mock.patch.dict(sys.modules, {"pdf_inspector": None}),
        pytest.raises(ImportError, match="pdf_inspector.*not found"),
    ):
        PdfInspectorParser().parse(_blob_from_pdf(plain_text_pdf))


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize(
    ("parser_kwargs", "upstream_name", "message"),
    [
        ({}, "extract_text_bytes", "plain text"),
        (
            {"extract_positions": True},
            "extract_text_with_positions_bytes",
            "text with positions",
        ),
        (
            {"extract_positions": True, "include_position_metadata": True},
            "extract_text_with_positions_and_rotations_bytes",
            "text with positions",
        ),
        (
            {"extract_regions": True, "page_regions": [FOXTROT_REGION]},
            "extract_text_in_regions_bytes",
            "page regions",
        ),
        ({"output": "markdown"}, "extract_pages_markdown_bytes", "per-page markdown"),
    ],
)
def test_upstream_extraction_failures_preserve_cause(
    plain_text_pdf: Path,
    parser_kwargs: dict[str, Any],
    upstream_name: str,
    message: str,
) -> None:
    """Each extraction path wraps upstream failures and keeps the original cause."""
    upstream_error = ValueError("upstream extraction failed")
    with (
        mock.patch(f"pdf_inspector.{upstream_name}", side_effect=upstream_error),
        pytest.raises(RuntimeError) as exc_info,
    ):
        PdfInspectorParser(**parser_kwargs).parse(_blob_from_pdf(plain_text_pdf))

    assert message in str(exc_info.value)
    assert exc_info.value.__cause__ is upstream_error


@pytest.mark.requires("pdf_inspector")
def test_detection_metadata_omits_missing_values(plain_text_pdf: Path) -> None:
    """Successful detection with missing fields omits them instead of emitting nulls."""
    detection = SimpleNamespace(
        pdf_type=None,
        page_count=None,
        title=None,
        author=None,
        subject=None,
        keywords=None,
        creator=None,
        producer=None,
        creation_date=None,
        mod_date=None,
    )
    with mock.patch("pdf_inspector.detect_pdf_bytes", return_value=detection):
        metadata = (
            PdfInspectorParser().parse(_blob_from_pdf(plain_text_pdf))[0].metadata
        )

    assert metadata["source"].endswith("plain_text.pdf")
    assert metadata["page"] == 1
    assert {"pdf_type", "total_pages", "title"} & metadata.keys() == set()


# ---------------------------------------------------------------------------
# Document info metadata
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_document_info_metadata_is_surfaced(
    document_info_pdf: Path, plain_text_pdf: Path
) -> None:
    """PDF document info fields are merged into metadata, and absent ones omitted."""
    metadata = PdfInspectorParser().parse(_blob_from_pdf(document_info_pdf))[0].metadata

    expected: dict[str, str] = {
        "title": "Document Info Fixture",
        "author": "Ada Lovelace",
        "subject": "Metadata extraction",
        "keywords": "alpha, beta, gamma",
        "creator": "pdfinfo-probe",
        "producer": "pdfinfo-probe producer",
        "creation_date": "D:20240115103000+01'00'",
        "mod_date": "D:20240220120000+01'00'",
    }
    for key, value in expected.items():
        assert metadata[key] == value
        assert isinstance(metadata[key], str)

    # A PDF without those entries omits them instead of emitting None. (The
    # plain-text fixture still carries pdfTeX's own creator/producer/dates.)
    plain_metadata = (
        PdfInspectorParser().parse(_blob_from_pdf(plain_text_pdf))[0].metadata
    )
    for key in ("title", "author", "subject", "keywords"):
        assert key not in plain_metadata


# ---------------------------------------------------------------------------
# Two-column fixture sanity
# ---------------------------------------------------------------------------


@pytest.mark.requires("pdf_inspector")
def test_two_column_content_contains_both_columns(two_column_pdf: Path) -> None:
    """Plain text from the two-column fixture keeps both column sentinels."""
    blob = _blob_from_pdf(two_column_pdf)
    content = PdfInspectorParser().parse(blob)[0].page_content
    assert "columnsentinel-left" in content
    assert "columnsentinel-right" in content
