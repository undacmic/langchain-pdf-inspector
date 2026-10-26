"""Tests for opt-in positioned, structure, and diagnostics metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

import pytest
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorParser

TEXT_ITEM_FIELDS = {
    "text",
    "x",
    "y",
    "width",
    "height",
    "rotation",
    "advance_known",
    "font",
    "font_tag",
    "font_size",
    "page",
    "is_bold",
    "is_italic",
    "font_weight",
    "bold_source",
    "fixed_pitch",
    "fill_color",
    "stroke_color",
    "render_mode",
    "is_underline",
    "is_strikeout",
    "baseline_shift",
    "item_type",
    "mcid",
}


def _blob_from_pdf(pdf_path: Path) -> Blob:
    return Blob.from_path(str(pdf_path))


def _pdf_object_bodies(pdf_path: Path) -> dict[int, bytes]:
    """Parse the uncompressed fixture's numbered object bodies from raw bytes."""
    data = pdf_path.read_bytes()
    return {
        int(match.group(1)): match.group(2)
        for match in re.finditer(
            rb"(?m)^(\d+) 0 obj\n(.*?)\nendobj\n", data, flags=re.DOTALL
        )
    }


@pytest.mark.requires("pdf_inspector")
def test_default_metadata_has_no_opt_in_groups(plain_text_pdf: Path) -> None:
    """Defaults keep the existing metadata shape: no rich groups appear."""
    metadata = PdfInspectorParser().parse(_blob_from_pdf(plain_text_pdf))[0].metadata
    assert not {"positions", "structure", "diagnostics"} & metadata.keys()


@pytest.mark.requires("pdf_inspector")
def test_position_metadata_contains_released_fields_and_serializes(
    plain_text_pdf: Path,
) -> None:
    """``include_position_metadata`` emits every released item field as JSON."""
    docs = PdfInspectorParser(
        extract_positions=True, include_position_metadata=True
    ).parse(_blob_from_pdf(plain_text_pdf))

    positions = docs[0].metadata["positions"]
    assert isinstance(positions["items"], list)
    assert positions["items"]
    item = positions["items"][0]
    assert set(item) == TEXT_ITEM_FIELDS
    assert item["page"] == 1
    assert item["mcid"] is None
    assert isinstance(item["fill_color"], list)
    assert isinstance(positions["page_rotations"], list)
    json.loads(json.dumps(docs[0].metadata))


@pytest.mark.requires("pdf_inspector")
def test_position_metadata_does_not_change_positional_content(
    plain_text_pdf: Path,
) -> None:
    """The opt-in group is additive: content and page selection are unchanged."""
    blob = _blob_from_pdf(plain_text_pdf)
    plain = PdfInspectorParser(extract_positions=True).parse(blob)[0]
    enriched = PdfInspectorParser(
        extract_positions=True, include_position_metadata=True
    ).parse(blob)[0]

    assert enriched.page_content == plain.page_content
    assert enriched.metadata["page"] == plain.metadata["page"]
    assert "positions" not in plain.metadata
    assert "positions" in enriched.metadata


@pytest.mark.requires("pdf_inspector")
def test_position_metadata_page_mode_is_scoped_to_page(
    plain_text_pdf: Path,
) -> None:
    """Page-mode position metadata only contains the corresponding page's items."""
    docs = PdfInspectorParser(
        mode="page",
        output="text",
        extract_positions=True,
        include_position_metadata=True,
        pages=[1],
    ).parse(_blob_from_pdf(plain_text_pdf))

    assert len(docs) == 1
    assert docs[0].metadata["page"] == 2
    positions = docs[0].metadata["positions"]
    assert positions["items"]
    assert {item["page"] for item in positions["items"]} == {2}
    assert "plaintextsentinel-foxtrot" in docs[0].page_content


@pytest.mark.requires("pdf_inspector")
def test_rotated_fixture_reports_page_rotation_frame_and_fields(
    rotated_text_pdf: Path,
) -> None:
    """Actual rotated text is normalized and its turned frame is reported."""
    docs = PdfInspectorParser(
        extract_positions=True, include_position_metadata=True
    ).parse(_blob_from_pdf(rotated_text_pdf))

    positions = docs[0].metadata["positions"]
    assert positions["page_rotations"] == [{"page": 1, "rotation": "ccw"}]
    assert {item["page"] for item in positions["items"]} == {1}
    assert "rotatedsentinel-oscar" in docs[0].page_content
    assert "rotatedsentinel-papa" in docs[0].page_content
    for item in positions["items"]:
        assert {"x", "y", "width", "height", "rotation"} <= item.keys()
    json.loads(json.dumps(docs[0].metadata))


@pytest.mark.requires("pdf_inspector")
def test_position_metadata_page_mode_scopes_rotation(rotated_text_pdf: Path) -> None:
    """A page-mode rotated document reports only its own rotated frame."""
    docs = PdfInspectorParser(
        mode="page",
        output="text",
        extract_positions=True,
        include_position_metadata=True,
        pages=[0],
    ).parse(_blob_from_pdf(rotated_text_pdf))

    assert docs[0].metadata["positions"]["page_rotations"] == [
        {"page": 1, "rotation": "ccw"}
    ]


@pytest.mark.requires("pdf_inspector")
def test_position_metadata_requires_positions_and_text_output() -> None:
    """Unsupported position-metadata combinations are rejected explicitly."""
    with pytest.raises(ValueError, match="requires extract_positions=True"):
        PdfInspectorParser(include_position_metadata=True)
    with pytest.raises(ValueError, match="requires output='text'"):
        PdfInspectorParser(
            output="markdown",
            extract_positions=True,
            include_position_metadata=True,
        )


@pytest.mark.requires("pdf_inspector")
def test_tagged_structure_roles_and_mcid_join(tagged_structure_pdf: Path) -> None:
    """Actual tagged PDF roles join to positioned items by (page, mcid)."""
    docs = PdfInspectorParser(
        extract_positions=True,
        include_position_metadata=True,
        include_structure=True,
    ).parse(_blob_from_pdf(tagged_structure_pdf))

    doc = docs[0]
    assert doc.metadata["structure"] == {
        "elements": [
            {"page": 1, "mcid": 0, "role": "H1"},
            {"page": 1, "mcid": 1, "role": "P"},
            {"page": 1, "mcid": 2, "role": "Code"},
            {"page": 1, "mcid": 3, "role": "P"},
            {"page": 2, "mcid": 0, "role": "P"},
        ]
    }
    roles = {
        (element["page"], element["mcid"]): element["role"]
        for element in doc.metadata["structure"]["elements"]
    }
    heading = " ".join(
        item["text"]
        for item in doc.metadata["positions"]["items"]
        if roles.get((item["page"], item["mcid"])) == "H1"
    )
    assert heading == "Tagged Structure Fixture"
    assert "taggedsentinel-page-two" in doc.page_content
    json.loads(json.dumps(doc.metadata))


@pytest.mark.requires("pdf_inspector")
def test_structure_page_mode_is_scoped_to_page(tagged_structure_pdf: Path) -> None:
    """Page-mode structure metadata only contains the corresponding page."""
    docs = PdfInspectorParser(
        mode="page",
        output="markdown",
        pages=[0, 1],
        include_structure=True,
    ).parse(_blob_from_pdf(tagged_structure_pdf))

    assert [doc.metadata["page"] for doc in docs] == [1, 2]
    assert docs[0].metadata["structure"]["elements"] == [
        {"page": 1, "mcid": 0, "role": "H1"},
        {"page": 1, "mcid": 1, "role": "P"},
        {"page": 1, "mcid": 2, "role": "Code"},
        {"page": 1, "mcid": 3, "role": "P"},
    ]
    assert docs[1].metadata["structure"]["elements"] == [
        {"page": 2, "mcid": 0, "role": "P"}
    ]


@pytest.mark.requires("pdf_inspector")
def test_region_page_structure_follows_page_regions_not_pages(
    tagged_structure_pdf: Path,
) -> None:
    """Page-mode region structure uses `page_regions`, matching content pages."""
    blob = _blob_from_pdf(tagged_structure_pdf)
    common = {
        "mode": "page",
        "output": "text",
        "pages": [0],
        "extract_regions": True,
        "page_regions": [(1, [[0.0, 0.0, 612.0, 792.0]])],
    }
    baseline = PdfInspectorParser(**common).parse(blob)[0]
    enriched = PdfInspectorParser(**common, include_structure=True).parse(blob)[0]

    assert baseline.metadata["page"] == 2
    assert "taggedsentinel-page-two" in baseline.page_content
    assert enriched.page_content == baseline.page_content
    assert enriched.metadata["page"] == baseline.metadata["page"]
    assert {
        key: value for key, value in enriched.metadata.items() if key != "structure"
    } == (baseline.metadata)
    assert enriched.metadata["structure"] == {
        "elements": [{"page": 2, "mcid": 0, "role": "P"}]
    }


@pytest.mark.requires("pdf_inspector")
def test_region_option_markdown_structure_uses_pages_not_page_regions(
    tagged_structure_pdf: Path,
) -> None:
    """Markdown output ignores regions, so structure selection must use `pages`."""
    docs = PdfInspectorParser(
        mode="page",
        output="markdown",
        pages=[0],
        extract_regions=True,
        page_regions=[(1, [[0.0, 0.0, 612.0, 792.0]])],
        include_structure=True,
    ).parse(_blob_from_pdf(tagged_structure_pdf))

    assert len(docs) == 1
    assert docs[0].metadata["page"] == 1
    assert "Tagged Structure Fixture" in docs[0].page_content
    assert docs[0].metadata["structure"]["elements"] == [
        {"page": 1, "mcid": 0, "role": "H1"},
        {"page": 1, "mcid": 1, "role": "P"},
        {"page": 1, "mcid": 2, "role": "Code"},
        {"page": 1, "mcid": 3, "role": "P"},
    ]


def test_tagged_fixture_parent_tree_reverse_associations(
    tagged_structure_pdf: Path,
) -> None:
    """The tagged fixture maps each page's StructParents to its immediate parents.

    This inspects the uncompressed checked-in bytes directly, independently of
    ``pdf-inspector`` forward extraction: page 0's ParentTree entry must list
    the four page-1 StructElems (MCIDs 0-3) and page 1's entry must list the
    page-2 StructElem (MCID 0). The root Document element is not an immediate
    parent.
    """
    objects = _pdf_object_bodies(tagged_structure_pdf)

    assert b"/StructParents 0" in objects[3]
    assert b"/StructParents 1" in objects[4]
    assert b"/K [10 0 R 11 0 R 12 0 R 13 0 R 14 0 R]" in objects[9]
    parent_tree = objects[15]
    assert b"/Nums [0 [10 0 R 11 0 R 12 0 R 13 0 R] 1 [14 0 R]]" in parent_tree

    # Reverse association: each ParentTree immediate parent points back to the
    # same page object and carries the matching MCID.
    expected: dict[int, list[tuple[int, int]]] = {
        3: [(10, 0), (11, 1), (12, 2), (13, 3)],
        4: [(14, 0)],
    }
    for page_object, entries in expected.items():
        for struct_object, mcid in entries:
            body = objects[struct_object]
            assert f"/Pg {page_object} 0 R".encode() in body
            assert f"/K {mcid} >>".encode() in body
            assert b"/P 9 0 R" in body


@pytest.mark.requires("pdf_inspector")
def test_untagged_pdf_has_empty_structure_elements(plain_text_pdf: Path) -> None:
    """Untagged PDFs expose the opt-in group with an empty element list."""
    metadata = (
        PdfInspectorParser(include_structure=True)
        .parse(_blob_from_pdf(plain_text_pdf))[0]
        .metadata
    )
    assert metadata["structure"] == {"elements": []}


@pytest.mark.requires("pdf_inspector")
def test_structure_does_not_rewrite_content(tagged_structure_pdf: Path) -> None:
    """Enabling structure leaves the existing content path unchanged."""
    blob = _blob_from_pdf(tagged_structure_pdf)
    plain = PdfInspectorParser(output="markdown").parse(blob)[0]
    enriched = PdfInspectorParser(output="markdown", include_structure=True).parse(
        blob
    )[0]
    assert enriched.page_content == plain.page_content
    assert "structure" not in plain.metadata
    assert "structure" in enriched.metadata


@pytest.mark.requires("pdf_inspector")
def test_diagnostics_are_json_serializable_and_scoped(
    tables_pdf: Path,
) -> None:
    """Diagnostics serialize and page-mode page lists are scoped to the page."""
    docs = PdfInspectorParser(
        mode="page",
        output="markdown",
        pages=[0, 1],
        include_diagnostics=True,
    ).parse(_blob_from_pdf(tables_pdf))

    for doc in docs:
        diagnostics = doc.metadata["diagnostics"]
        page = doc.metadata["page"]
        assert "confidence" in diagnostics
        assert "has_encoding_issues" in diagnostics
        assert "cmap_gaps" in diagnostics
        assert all(value == page for value in diagnostics["pages_with_tables"])
        assert all(value == page for value in diagnostics["pages_with_columns"])
        assert all(value == page for value in diagnostics["pages_needing_ocr"])
        assert all(
            reason["page"] == page for reason in diagnostics["ocr_reasons_by_page"]
        )
        json.loads(json.dumps(doc.metadata))


@pytest.mark.requires("pdf_inspector")
def test_diagnostics_single_mode_keeps_page_associations(
    tables_pdf: Path,
) -> None:
    """Single-mode diagnostics retain the document-wide 1-indexed page lists."""
    metadata = (
        PdfInspectorParser(output="markdown", include_diagnostics=True)
        .parse(_blob_from_pdf(tables_pdf))[0]
        .metadata
    )
    diagnostics = metadata["diagnostics"]
    assert diagnostics["pdf_type"] == "text_based"
    assert 1 in diagnostics["pages_with_tables"]
    assert all(isinstance(page, int) for page in diagnostics["pages_with_tables"])


@pytest.mark.requires("pdf_inspector")
def test_diagnostics_detection_failure_is_not_silently_swallowed(
    plain_text_pdf: Path,
) -> None:
    """Opt-in diagnostics surface detection failures; the default fallback remains."""
    blob = _blob_from_pdf(plain_text_pdf)
    with mock.patch(
        "pdf_inspector.detect_pdf_bytes", side_effect=RuntimeError("detect failed")
    ):
        # The historical default still falls back to base metadata.
        with pytest.raises(RuntimeError, match="detection diagnostics"):
            PdfInspectorParser(include_diagnostics=True).parse(blob)
        assert PdfInspectorParser().parse(blob)[0].metadata["source"]


@pytest.mark.requires("pdf_inspector")
def test_structure_extraction_failure_is_not_silently_swallowed(
    plain_text_pdf: Path,
) -> None:
    """Opt-in structure extraction surfaces failures with the original cause."""
    upstream_error = ValueError("bad structure tree")
    with (
        mock.patch(
            "pdf_inspector.extract_structure_elements_bytes", side_effect=upstream_error
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        PdfInspectorParser(include_structure=True).parse(_blob_from_pdf(plain_text_pdf))

    assert "structure metadata" in str(exc_info.value)
    assert exc_info.value.__cause__ is upstream_error


@pytest.mark.requires("pdf_inspector")
def test_all_opt_in_groups_serialize_together(tagged_structure_pdf: Path) -> None:
    """Every opt-in group composes and remains ordinary JSON."""
    docs = PdfInspectorParser(
        extract_positions=True,
        include_position_metadata=True,
        include_structure=True,
        include_diagnostics=True,
    ).parse(_blob_from_pdf(tagged_structure_pdf))
    payload = json.loads(json.dumps(docs[0].metadata))
    assert {"positions", "structure", "diagnostics"} <= payload.keys()
    assert "ocr" not in payload["diagnostics"]


@pytest.mark.requires("pdf_inspector")
def test_structure_metadata_type_is_plain_dict(tagged_structure_pdf: Path) -> None:
    """Metadata never contains upstream native extension result objects."""
    metadata = (
        PdfInspectorParser(include_structure=True)
        .parse(_blob_from_pdf(tagged_structure_pdf))[0]
        .metadata
    )
    assert type(metadata["structure"]["elements"][0]) is dict
