"""OCR integration tests for ``PdfInspectorParser``.

Routine tests never download an OCR model: the routing/forwarding tests use a
mock upstream result and the real-upstream test exercises ``mode="auto"`` on a
text-based fixture, which routes no page to OCR. The opt-in real-model test at
the end is skipped unless an operator explicitly provisions a model.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorParser


def _provenance(page: int, source: str = "ocr") -> SimpleNamespace:
    """Build a released-shape OCR provenance object for the fake result."""
    return SimpleNamespace(
        page_number=page,
        source=source,
        ocr_model=(
            None
            if source == "native"
            else SimpleNamespace(name="fixture-model", revision="rev-1")
        ),
        render_dpi=None if source == "native" else 150.0,
        ocr_confidence=None if source == "native" else 0.93,
        timings=SimpleNamespace(render_ms=1, ocr_ms=2, assembly_ms=3),
        warnings=[],
        hosted_recommended=False,
    )


def _ocr_result(
    page_numbers: list[int], *, source: str = "ocr", page_count: int = 3
) -> SimpleNamespace:
    """Build a released-shape ``OcrPdfResult`` for the fake upstream."""
    return SimpleNamespace(
        markdown="\n".join(f"ocr-page-{page}" for page in page_numbers),
        pages=[
            SimpleNamespace(
                page_number=page,
                markdown=f"ocr-page-{page}",
                provenance=_provenance(page, source),
            )
            for page in page_numbers
        ],
        page_count=page_count,
        pages_recommended_for_ocr=[],
        pages_routed_to_ocr=list(page_numbers),
        pages_recommending_hosted=[],
        ocr_reasons_by_page=[
            SimpleNamespace(page=page, reasons=[]) for page in page_numbers
        ],
        pages_with_tables=[],
        pages_with_columns=[],
        is_complex=False,
        processing_time_ms=10,
        render_time_ms=2,
        ocr_time_ms=8,
    )


class _CountingList(list[Any]):
    """A list that counts traversals."""

    def __init__(self, values: list[Any]) -> None:
        super().__init__(values)
        self.iterations = 0

    def __iter__(self) -> Any:
        self.iterations += 1
        return super().__iter__()


class _CountingPages(_CountingList):
    """A released-shape pages list that counts traversals."""


class _CountingOcrPage:
    """A released-shape OCR page that counts native field reads."""

    def __init__(self, page: int, source: str = "ocr") -> None:
        self._page_number = page
        self._provenance = _provenance(page, source)
        self.markdown = f"ocr-page-{page}"
        self.page_number_reads = 0
        self.provenance_reads = 0

    @property
    def page_number(self) -> int:
        self.page_number_reads += 1
        return self._page_number

    @property
    def provenance(self) -> SimpleNamespace:
        self.provenance_reads += 1
        return self._provenance


def _counting_ocr_result(
    page_numbers: list[int],
) -> tuple[SimpleNamespace, _CountingPages]:
    """Build a counting released-shape OCR result and expose its pages list."""
    pages = _CountingPages([_CountingOcrPage(page) for page in page_numbers])
    result = SimpleNamespace(
        markdown="\n".join(f"ocr-page-{page}" for page in page_numbers),
        pages=pages,
        page_count=len(page_numbers),
        pages_recommended_for_ocr=[],
        pages_routed_to_ocr=list(page_numbers),
        pages_recommending_hosted=[],
        ocr_reasons_by_page=[
            SimpleNamespace(page=page, reasons=[f"reason-{page}"])
            for page in page_numbers
        ],
        pages_with_tables=[],
        pages_with_columns=[],
        is_complex=False,
        processing_time_ms=10,
        render_time_ms=2,
        ocr_time_ms=8,
    )
    return result, pages


def _counting_detection_result(
    page_numbers: list[int],
) -> tuple[SimpleNamespace, list[_CountingList]]:
    """Build a released-shape detection result with counting page lists."""
    page_lists = [
        _CountingList(list(page_numbers)) for _ in ("needing_ocr", "tables", "columns")
    ]
    reasons = _CountingList(
        [SimpleNamespace(page=page, reasons=[]) for page in page_numbers]
    )
    result = SimpleNamespace(
        pdf_type="text_based",
        page_count=len(page_numbers),
        pages_needing_ocr=page_lists[0],
        ocr_reasons_by_page=reasons,
        pages_with_tables=page_lists[1],
        pages_with_columns=page_lists[2],
        confidence=0.9,
        is_complex_layout=False,
        has_encoding_issues=False,
        cmap_gaps=[
            SimpleNamespace(font="fixture-font", codes=1, interpolated=0, unmapped=0)
        ],
        title=None,
        author=None,
        subject=None,
        keywords=None,
        creator=None,
        producer=None,
        creation_date=None,
        mod_date=None,
    )
    return result, [*page_lists, reasons]


def _blob_from_pdf(pdf_path: Any) -> Blob:
    return Blob.from_path(str(pdf_path))


@pytest.mark.requires("pdf_inspector")
def test_ocr_forwards_options_and_translates_0_indexed_pages(
    plain_text_pdf: Any,
) -> None:
    """OCR forwards the released options and translates 0-indexed pages to 1-indexed."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 3], page_count=3),
    ) as mocked:
        parser = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[0, 2],
            ocr_mode="auto",
            offline=False,
            model_directory="/models/ocr",
            dpi=200.0,
            minimum_confidence=0.4,
            hosted_recommendation_confidence=0.7,
            password="secret",
        )
        docs = parser.parse(_blob_from_pdf(plain_text_pdf))

    kwargs = mocked.call_args.kwargs
    assert kwargs == {
        "mode": "auto",
        "page_numbers": [1, 3],
        "password": "secret",
        "dpi": 200.0,
        "minimum_confidence": 0.4,
        "hosted_recommendation_confidence": 0.7,
        "model_directory": "/models/ocr",
        "offline": False,
    }
    assert [doc.metadata["page"] for doc in docs] == [1, 3]
    assert [doc.page_content for doc in docs] == ["ocr-page-1", "ocr-page-3"]


@pytest.mark.requires("pdf_inspector")
def test_ocr_diagnostics_are_page_scoped_without_password(
    plain_text_pdf: Any,
) -> None:
    """OCR diagnostics remain independently page-scoped without a password."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 3], page_count=3),
    ):
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[0, 2],
            ocr_mode="auto",
            include_diagnostics=True,
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert [doc.metadata["page"] for doc in docs] == [1, 3]
    for doc in docs:
        diagnostics = doc.metadata["diagnostics"]["ocr"]
        assert diagnostics["pages"][0]["page_number"] == doc.metadata["page"]
        assert diagnostics["pages_routed_to_ocr"] == [doc.metadata["page"]]


@pytest.mark.requires("pdf_inspector")
def test_ocr_page_diagnostics_scan_result_once_for_many_documents(
    plain_text_pdf: Any,
) -> None:
    """Page diagnostics traverse each upstream page list once, not per document."""
    result, pages = _counting_ocr_result([1, 2, 3])
    detection, detection_lists = _counting_detection_result([1, 2, 3])
    with (
        mock.patch("pdf_inspector.detect_pdf_bytes", return_value=detection),
        mock.patch("pdf_inspector.process_pdf_with_ocr_bytes", return_value=result),
    ):
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[0, 1, 2, 0, 1, 2],
            ocr_mode="auto",
            include_diagnostics=True,
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert [doc.metadata["page"] for doc in docs] == [1, 2, 3, 1, 2, 3]
    assert pages.iterations <= 2
    assert sum(page.page_number_reads for page in pages) <= 2 * len(pages)
    assert sum(page.provenance_reads for page in pages) == len(pages)
    for values in detection_lists:
        assert values.iterations <= 2


@pytest.mark.requires("pdf_inspector")
def test_ocr_page_diagnostic_copies_are_independent_per_document(
    plain_text_pdf: Any,
) -> None:
    """Duplicate and distinct page documents never share mutable diagnostics."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2]),
    ):
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[0, 0, 1],
            ocr_mode="auto",
            include_diagnostics=True,
        ).parse(_blob_from_pdf(plain_text_pdf))

    first, duplicate, second = docs
    first_ocr = first.metadata["diagnostics"]["ocr"]
    duplicate_ocr = duplicate.metadata["diagnostics"]["ocr"]
    second_ocr = second.metadata["diagnostics"]["ocr"]

    assert first_ocr is not duplicate_ocr
    assert first_ocr["pages"] is not duplicate_ocr["pages"]
    assert first_ocr["pages"][0] is not duplicate_ocr["pages"][0]
    assert (
        first_ocr["ocr_reasons_by_page"][0]
        is not duplicate_ocr["ocr_reasons_by_page"][0]
    )

    first_ocr["pages"][0]["provenance"]["timings"]["render_ms"] = 999
    first_ocr["pages"][0]["provenance"]["warnings"].append("mutated")
    first_ocr["ocr_reasons_by_page"][0]["reasons"].append("mutated")

    assert duplicate_ocr["pages"][0]["provenance"]["timings"]["render_ms"] == 1
    assert duplicate_ocr["pages"][0]["provenance"]["warnings"] == []
    assert duplicate_ocr["ocr_reasons_by_page"][0]["reasons"] == []
    assert second_ocr["pages"][0]["page_number"] == 2
    assert second_ocr["ocr_reasons_by_page"][0]["reasons"] == []


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize(
    "groups",
    [
        {"include_structure": True},
        {"include_diagnostics": True},
        {"include_structure": True, "include_diagnostics": True},
    ],
)
def test_ocr_password_with_metadata_groups_rejected_before_upstream(
    plain_text_pdf: Any, groups: dict[str, bool]
) -> None:
    """A non-empty OCR password cannot combine with password-blind metadata APIs."""
    with (
        mock.patch("pdf_inspector.process_pdf_with_ocr_bytes") as ocr_mock,
        mock.patch("pdf_inspector.detect_pdf_bytes") as detect_mock,
        mock.patch("pdf_inspector.extract_structure_elements_bytes") as structure_mock,
        pytest.raises(ValueError, match="not password-aware") as exc_info,
    ):
        PdfInspectorParser(
            output="markdown",
            ocr_mode="auto",
            password="secret",
            **groups,
        ).parse(_blob_from_pdf(plain_text_pdf))

    message = str(exc_info.value)
    assert "detect_pdf_bytes" in message
    assert "extract_structure_elements_bytes" in message
    assert "decrypt" in message
    ocr_mock.assert_not_called()
    detect_mock.assert_not_called()
    structure_mock.assert_not_called()


@pytest.mark.requires("pdf_inspector")
def test_ocr_empty_password_with_metadata_groups_is_allowed(
    plain_text_pdf: Any,
) -> None:
    """An empty password is harmless and does not trigger the metadata restriction."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1], source="native", page_count=3),
    ) as mocked:
        docs = PdfInspectorParser(
            output="markdown",
            pages=[0],
            ocr_mode="auto",
            password="",
            include_structure=True,
            include_diagnostics=True,
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert mocked.call_args.kwargs["password"] == ""
    assert docs[0].metadata["structure"] == {"elements": []}
    assert "ocr" in docs[0].metadata["diagnostics"]


@pytest.mark.requires("pdf_inspector")
def test_ocr_defaults_to_offline(plain_text_pdf: Any) -> None:
    """Constructing enabled OCR without overriding the default keeps downloads prohibited."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2, 3]),
    ) as mocked:
        PdfInspectorParser(output="markdown", ocr_mode="auto").parse(
            _blob_from_pdf(plain_text_pdf)
        )

    assert mocked.call_args.kwargs["offline"] is True
    assert mocked.call_args.kwargs["model_directory"] is None


@pytest.mark.requires("pdf_inspector")
def test_ocr_page_mode_preserves_requested_order_and_duplicates(
    plain_text_pdf: Any,
) -> None:
    """OCR page mode yields the caller's requested order, duplicates included."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2, 3]),
    ):
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[2, 0, 2],
            ocr_mode="auto",
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert [doc.metadata["page"] for doc in docs] == [3, 1, 3]
    assert [doc.page_content for doc in docs] == [
        "ocr-page-3",
        "ocr-page-1",
        "ocr-page-3",
    ]


@pytest.mark.requires("pdf_inspector")
def test_ocr_single_mode_joins_requested_pages_with_page_delimiter(
    plain_text_pdf: Any,
) -> None:
    """Single-mode OCR joins requested page Markdown in requested order."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2, 3]),
    ):
        docs = PdfInspectorParser(
            output="markdown",
            pages=[2, 0],
            page_delimiter="<OCR-PAGE>",
            ocr_mode="auto",
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert len(docs) == 1
    assert docs[0].metadata["page"] == 1
    assert docs[0].page_content == "ocr-page-3<OCR-PAGE>ocr-page-1"


@pytest.mark.requires("pdf_inspector")
def test_ocr_single_mode_without_pages_joins_all_pages(plain_text_pdf: Any) -> None:
    """Without a ``pages`` selection, single-mode OCR joins upstream document order."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2, 3]),
    ):
        docs = PdfInspectorParser(
            output="markdown", page_delimiter="|", ocr_mode="auto"
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert docs[0].page_content == "ocr-page-1|ocr-page-2|ocr-page-3"


@pytest.mark.requires("pdf_inspector")
def test_ocr_page_mode_omits_nonexistent_pages(plain_text_pdf: Any) -> None:
    """Out-of-range pages are dropped using the detected page count."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([2], page_count=3),
    ) as mocked:
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[1, 99],
            ocr_mode="auto",
        ).parse(_blob_from_pdf(plain_text_pdf))

    assert [doc.metadata["page"] for doc in docs] == [2]
    assert mocked.call_args.kwargs["page_numbers"] == [2]


@pytest.mark.requires("pdf_inspector")
def test_ocr_disabled_never_calls_upstream(plain_text_pdf: Any) -> None:
    """The default ``ocr_mode="off"`` leaves the existing extraction path untouched."""
    with mock.patch("pdf_inspector.process_pdf_with_ocr_bytes") as mocked:
        docs = PdfInspectorParser().parse(_blob_from_pdf(plain_text_pdf))

    mocked.assert_not_called()
    assert "plaintextsentinel-foxtrot" in docs[0].page_content
    assert "positions" not in docs[0].metadata
    assert "structure" not in docs[0].metadata
    assert "diagnostics" not in docs[0].metadata


@pytest.mark.requires("pdf_inspector")
def test_ocr_auto_uses_released_native_path_without_models(
    plain_text_pdf: Any,
) -> None:
    """Actual upstream ``auto`` on a text-based PDF routes no page to OCR.

    This is the routine real-upstream coverage: it needs no OCR model and must
    never download one.
    """
    parser = PdfInspectorParser(
        output="markdown", ocr_mode="auto", include_diagnostics=True
    )
    docs = parser.parse(_blob_from_pdf(plain_text_pdf))

    assert len(docs) == 1
    assert "plaintextsentinel-foxtrot" in docs[0].page_content
    assert "plaintextsentinel-golf" in docs[0].page_content
    ocr = docs[0].metadata["diagnostics"]["ocr"]
    assert ocr["pages_routed_to_ocr"] == []
    assert ocr["pages_recommended_for_ocr"] == []
    assert [page["provenance"]["source"] for page in ocr["pages"]] == [
        "native",
        "native",
        "native",
    ]


@pytest.mark.requires("pdf_inspector")
def test_ocr_composes_with_structure_and_page_scoped_diagnostics(
    tagged_structure_pdf: Any,
) -> None:
    """OCR page documents can carry structure and page-scoped diagnostics."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2], source="native", page_count=2),
    ):
        docs = PdfInspectorParser(
            mode="page",
            output="markdown",
            pages=[0, 1],
            ocr_mode="auto",
            include_structure=True,
            include_diagnostics=True,
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
    for doc in docs:
        ocr = doc.metadata["diagnostics"]["ocr"]
        assert [page["page_number"] for page in ocr["pages"]] == [doc.metadata["page"]]


@pytest.mark.requires("pdf_inspector")
def test_ocr_metadata_is_json_serializable(plain_text_pdf: Any) -> None:
    """OCR diagnostics and provenance serialize as ordinary JSON values."""
    with mock.patch(
        "pdf_inspector.process_pdf_with_ocr_bytes",
        return_value=_ocr_result([1, 2, 3]),
    ):
        docs = PdfInspectorParser(
            output="markdown", ocr_mode="auto", include_diagnostics=True
        ).parse(_blob_from_pdf(plain_text_pdf))

    payload = json.loads(json.dumps(docs[0].metadata))
    assert payload["diagnostics"]["ocr"]["pages"][0]["provenance"]["source"] == "ocr"
    assert isinstance(payload["diagnostics"]["ocr"]["pages"][0]["provenance"], dict)


@pytest.mark.requires("pdf_inspector")
def test_ocr_missing_model_or_runtime_error_is_actionable_and_preserves_cause(
    plain_text_pdf: Any,
) -> None:
    """A missing model/runtime yields an actionable RuntimeError with its cause."""
    upstream_error = ValueError(
        "model file not found and offline mode prohibits downloading it"
    )
    with (
        mock.patch(
            "pdf_inspector.process_pdf_with_ocr_bytes", side_effect=upstream_error
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        PdfInspectorParser(
            output="markdown",
            ocr_mode="force",
            offline=True,
            model_directory="/models/missing",
        ).parse(_blob_from_pdf(plain_text_pdf))

    message = str(exc_info.value)
    assert "offline=True" in message
    assert "model_directory" in message
    assert "PDFIUM_LIB_PATH" in message
    assert "ORT_DYLIB_PATH" in message
    assert exc_info.value.__cause__ is upstream_error


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize(
    ("kwargs", "error_fragment"),
    [
        ({"ocr_mode": "sometimes"}, "ocr_mode must be either"),
        (
            {"ocr_mode": "auto"},
            "requires output='markdown'",
        ),
        (
            {"ocr_mode": "auto", "output": "markdown", "extract_positions": True},
            "does not support extract_positions",
        ),
        (
            {
                "ocr_mode": "auto",
                "output": "markdown",
                "extract_regions": True,
                "page_regions": [(0, [[0.0, 0.0, 1.0, 1.0]])],
            },
            "does not support extract_positions or extract_regions",
        ),
        (
            {
                "ocr_mode": "auto",
                "output": "markdown",
                "page_regions": [(0, [[0.0, 0.0, 1.0, 1.0]])],
            },
            "does not support page_regions",
        ),
        ({"offline": "yes"}, "offline must be a bool"),
        ({"model_directory": 123}, "model_directory must be"),
        ({"dpi": 0}, "dpi must be a positive"),
        ({"dpi": float("inf")}, "dpi must be a positive"),
        ({"minimum_confidence": 1.1}, "minimum_confidence must be"),
        (
            {"hosted_recommendation_confidence": -0.1},
            "hosted_recommendation_confidence must be",
        ),
        ({"password": 123}, "password must be"),
    ],
)
def test_ocr_invalid_options_raise_value_error(
    kwargs: dict[str, Any], error_fragment: str
) -> None:
    """Invalid OCR options and unsupported combinations raise clear errors."""
    with pytest.raises(ValueError, match=error_fragment):
        PdfInspectorParser(**kwargs)


# Opt-in real-model OCR integration test. Routine CI never sets these.
_REAL_OCR_ENABLED = os.environ.get("PDF_INSPECTOR_REAL_OCR") == "1"
_REAL_OCR_MODEL_DIR = os.environ.get("PDF_INSPECTOR_REAL_OCR_MODEL_DIR")


@pytest.mark.requires("pdf_inspector")
@pytest.mark.skipif(
    not (_REAL_OCR_ENABLED and _REAL_OCR_MODEL_DIR),
    reason=(
        "opt-in real-model OCR test: set PDF_INSPECTOR_REAL_OCR=1 and "
        "PDF_INSPECTOR_REAL_OCR_MODEL_DIR to a provisioned model directory"
    ),
)
def test_ocr_force_with_real_provisioned_model(plain_text_pdf: Any) -> None:
    """Exercise real OCR with an explicitly provisioned, offline model.

    This test is intentionally skipped in routine CI. It requires compatible
    PDFium and ONNX Runtime shared libraries plus a model directory produced by
    the upstream provisioning flow; it never permits a download.
    """
    parser = PdfInspectorParser(
        output="markdown",
        ocr_mode="force",
        offline=True,
        model_directory=_REAL_OCR_MODEL_DIR,
        include_diagnostics=True,
    )
    docs = parser.parse(_blob_from_pdf(plain_text_pdf))

    assert docs
    assert "plaintextsentinel-foxtrot" in docs[0].page_content
    ocr = docs[0].metadata["diagnostics"]["ocr"]
    assert ocr["pages_routed_to_ocr"]
    assert all(
        page["provenance"]["source"] in {"ocr", "fused"} for page in ocr["pages"]
    )
