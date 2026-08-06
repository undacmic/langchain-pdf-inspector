"""Unit tests for the ``PdfInspectorLoader`` document loader."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorLoader
from langchain_pdf_inspector.pdf_inspector_loader import BasePDFLoader

# Conftest fixture names that resolve to the absolute path of each built PDF
# (skipping the test with an actionable message when the PDF is absent).
FIXTURE_NAMES = [
    "plain_text_pdf",
    "headings_pdf",
    "lists_pdf",
    "two_column_pdf",
    "tables_pdf",
    "complex_layout_pdf",
]

# Multi-page fixtures with the 0-indexed page lists used in ``mode="page"``.
# Verified page counts: plain_text = 3, tables = 2, complex_layout = 2.
MULTI_PAGE_CASES = [
    ("plain_text_pdf", [0, 1, 2]),
    ("tables_pdf", [0, 1]),
    ("complex_layout_pdf", [0, 1]),
]


class _FakeParser:
    """Deterministic stand-in for ``PdfInspectorParser`` used by the blob tests."""

    def __init__(self, **_: Any) -> None:
        """Accept (and ignore) every option the loader forwards to the parser."""

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        """Yield one fixed ``Document`` regardless of the supplied blob."""
        yield Document(page_content="fake-page-content", metadata={"source": "fake"})

    def parse(self, blob: Blob) -> list[Document]:
        """Return the fixed ``Document`` list (``lazy_load`` calls ``parse``)."""
        return list(self.lazy_parse(blob))


@pytest.mark.requires("pdf_inspector")
class TestSingleMode:
    """Default ``mode="single"`` behaviour: one whole-file ``Document``."""

    @pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
    def test_single_mode_returns_one_document_with_base_metadata(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """Every fixture collapses into exactly one ``Document`` with base metadata."""
        path = request.getfixturevalue(fixture_name)
        docs = PdfInspectorLoader(str(path)).load()

        assert len(docs) == 1
        doc = docs[0]
        assert isinstance(doc, Document)
        assert isinstance(doc.page_content, str)
        assert doc.page_content.strip() != ""
        assert doc.metadata["source"] == str(path)
        assert Path(doc.metadata["source"]).name == Path(path).name
        assert doc.metadata["page"] == 1
        assert "pdf_type" in doc.metadata
        assert "total_pages" in doc.metadata

    def test_single_mode_reports_the_fixture_page_count(
        self, plain_text_pdf: Path
    ) -> None:
        """``total_pages`` reflects the real page count of the fixture."""
        doc = PdfInspectorLoader(str(plain_text_pdf)).load()[0]
        assert doc.metadata["total_pages"] == 3

    def test_single_mode_plain_text_is_full_prose(self, plain_text_pdf: Path) -> None:
        """Plain-text output contains prose from every page of the fixture."""
        content = PdfInspectorLoader(str(plain_text_pdf)).load()[0].page_content
        # Note: "fixture" is extracted with the ``fi`` ligature (U+FB01), so the
        # prose assertion stops before that word.
        assert "This is the opening paragraph of the plain text" in content
        assert "plaintextsentinel-foxtrot" in content
        assert "plaintextsentinel-golf" in content

    def test_single_mode_headings_content(self, headings_pdf: Path) -> None:
        """Heading fixture content includes the title, sections and sentinel."""
        content = PdfInspectorLoader(str(headings_pdf)).load()[0].page_content
        assert "Incremental Heading Fixture" in content
        assert "Introduction" in content
        assert "headingfixture-zephyr" in content

    def test_single_mode_lists_content(self, lists_pdf: Path) -> None:
        """Bulleted and numbered list content is extracted."""
        content = PdfInspectorLoader(str(lists_pdf)).load()[0].page_content
        assert "listsentinel-quark" in content
        assert "listsentinel-nested" in content
        assert "listsentinel-neutrino" in content

    def test_single_mode_two_column_content(self, two_column_pdf: Path) -> None:
        """Content from both columns of the two-column layout is extracted."""
        content = PdfInspectorLoader(str(two_column_pdf)).load()[0].page_content
        assert "columnsentinel-left" in content
        assert "columnsentinel-right" in content

    def test_single_mode_tables_content(self, tables_pdf: Path) -> None:
        """Table cell content from every table is extracted."""
        content = PdfInspectorLoader(str(tables_pdf)).load()[0].page_content
        assert "tablesentinel-alpha" in content
        assert "tablesentinel-beta" in content
        assert "tablesentinel-gamma" in content

    def test_single_mode_complex_layout_content(self, complex_layout_pdf: Path) -> None:
        """Complex-layout content spans the title, columns, table and conclusion."""
        content = PdfInspectorLoader(str(complex_layout_pdf)).load()[0].page_content
        assert "layoutsentinel-intro" in content
        assert "layoutsentinel-wrap" in content
        assert "layoutsentinel-multicol" in content
        assert "layoutsentinel-multicol-2" in content
        assert "layoutsentinel-table" in content
        assert "layoutsentinel-conclusion" in content


@pytest.mark.requires("pdf_inspector")
class TestPageMode:
    """``mode="page"`` yields one ``Document`` per requested page."""

    @pytest.mark.parametrize(("fixture_name", "pages"), MULTI_PAGE_CASES)
    def test_page_mode_markdown_yields_one_document_per_requested_page(
        self, fixture_name: str, pages: list[int], request: pytest.FixtureRequest
    ) -> None:
        """One ``Document`` per requested page, 1-indexed, with layout flags."""
        path = request.getfixturevalue(fixture_name)
        loader = PdfInspectorLoader(
            str(path), mode="page", pages=pages, output="markdown"
        )
        docs = loader.load()

        assert len(docs) == len(pages)
        assert [doc.metadata["page"] for doc in docs] == list(range(1, len(pages) + 1))
        for doc in docs:
            assert isinstance(doc, Document)
            assert isinstance(doc.page_content, str)
            assert doc.page_content.strip() != ""
            assert doc.metadata["source"] == str(path)
            assert "pdf_type" in doc.metadata
            assert "total_pages" in doc.metadata
            # Page-mode markdown attaches per-page layout flags.
            for key in ("needs_ocr", "has_tables", "has_multicolumn_layout"):
                assert key in doc.metadata
                assert isinstance(doc.metadata[key], bool)

    def test_page_mode_markdown_flags_tables_pages(self, tables_pdf: Path) -> None:
        """The table-bearing page is flagged with ``has_tables=True``."""
        loader = PdfInspectorLoader(
            str(tables_pdf), mode="page", pages=[0, 1], output="markdown"
        )
        page_one = loader.load()[0]
        assert page_one.metadata["has_tables"] is True
        assert page_one.metadata["has_multicolumn_layout"] is True

    def test_page_mode_text_with_positions_yields_per_page_documents(
        self, plain_text_pdf: Path
    ) -> None:
        """Positional text in page mode yields per-page, non-empty documents."""
        loader = PdfInspectorLoader(
            str(plain_text_pdf),
            mode="page",
            pages=[0, 1, 2],
            extract_positions=True,
        )
        docs = loader.load()

        assert docs
        for doc in docs:
            assert doc.metadata["page"] >= 1
            assert doc.page_content.strip() != ""
            assert doc.metadata["source"] == str(plain_text_pdf)
        assert docs[0].metadata["page"] == 1
        assert "opening paragraph" in docs[0].page_content


@pytest.mark.requires("pdf_inspector")
class TestMarkdownOutput:
    """``output="markdown"`` preserves headings, list markers and table rows."""

    def test_markdown_preserves_heading_markers(self, headings_pdf: Path) -> None:
        """Section headings survive as ``#``-prefixed markdown headings."""
        content = (
            PdfInspectorLoader(str(headings_pdf), output="markdown")
            .load()[0]
            .page_content
        )
        assert "# Incremental Heading Fixture" in content
        assert "## 1 Introduction" in content
        assert "headingfixture-zephyr" in content

    def test_markdown_preserves_list_markers(self, lists_pdf: Path) -> None:
        """Bulleted list content keeps its bullet marker in markdown output."""
        content = (
            PdfInspectorLoader(str(lists_pdf), output="markdown").load()[0].page_content
        )
        assert "# 1 Shopping and Tasks" in content
        assert "\u2022" in content  # pdf-inspector emits U+2022 bullets, not "-" or "*"
        assert "listsentinel-quark" in content
        assert "listsentinel-nested" in content

    def test_markdown_preserves_table_rows(self, tables_pdf: Path) -> None:
        """Table rows are rendered as pipe-delimited markdown table lines."""
        content = (
            PdfInspectorLoader(str(tables_pdf), output="markdown")
            .load()[0]
            .page_content
        )
        assert "|tablesentinel-beta|" in content
        assert "|widget|3 active|" in content
        assert "Metric" in content
        assert "tablesentinel-alpha" in content
        assert "tablesentinel-gamma" in content

    def test_markdown_preserves_complex_layout_table(
        self, complex_layout_pdf: Path
    ) -> None:
        """The booktabs table in the complex fixture becomes markdown rows."""
        content = (
            PdfInspectorLoader(str(complex_layout_pdf), output="markdown")
            .load()[0]
            .page_content
        )
        assert "|Region|Recordings|Flag|" in content
        assert "|layoutsentinel-table|128|active|" in content


@pytest.mark.requires("pdf_inspector")
class TestRegionExtraction:
    """``extract_regions=True`` crops text to ``page_regions``."""

    def test_single_mode_regions_returns_cropped_text(
        self, plain_text_pdf: Path
    ) -> None:
        """A region crop returns only the text within the cropped area."""
        full_region = (
            PdfInspectorLoader(
                str(plain_text_pdf),
                extract_regions=True,
                page_regions=[(0, [[0.0, 0.0, 612.0, 792.0]])],
            )
            .load()[0]
            .page_content
        )
        cropped = (
            PdfInspectorLoader(
                str(plain_text_pdf),
                extract_regions=True,
                page_regions=[(0, [[0.0, 0.0, 612.0, 150.0]])],
            )
            .load()[0]
            .page_content
        )

        assert isinstance(cropped, str)
        assert cropped.strip() != ""
        assert "opening paragraph" in cropped
        assert "Filler words" not in cropped
        assert len(cropped) < len(full_region)

    def test_page_mode_regions_yields_one_document_per_page(
        self, plain_text_pdf: Path
    ) -> None:
        """Per-page region cropping yields one ``Document`` per page."""
        page_regions = [
            (0, [[0.0, 0.0, 612.0, 792.0]]),
            (1, [[0.0, 0.0, 612.0, 792.0]]),
            (2, [[0.0, 0.0, 612.0, 792.0]]),
        ]
        loader = PdfInspectorLoader(
            str(plain_text_pdf),
            mode="page",
            pages=[0, 1, 2],
            extract_regions=True,
            page_regions=page_regions,
        )
        docs = loader.load()

        assert len(docs) == 3
        assert [doc.metadata["page"] for doc in docs] == [1, 2, 3]
        assert all(doc.page_content.strip() != "" for doc in docs)
        assert "plaintextsentinel-foxtrot" in docs[1].page_content
        assert "plaintextsentinel-golf" in docs[2].page_content


@pytest.mark.requires("pdf_inspector")
class TestMetadataMerging:
    """Caller-supplied ``metadata`` is merged on top of parsed metadata."""

    def test_caller_metadata_is_merged_onto_every_document(
        self, plain_text_pdf: Path
    ) -> None:
        """Every returned ``Document`` carries the caller-supplied metadata."""
        loader = PdfInspectorLoader(
            str(plain_text_pdf), metadata={"tenant": "acme", "region": "eu"}
        )
        assert loader.metadata == {"tenant": "acme", "region": "eu"}

        for doc in loader.load():
            assert doc.metadata["tenant"] == "acme"
            assert doc.metadata["region"] == "eu"
            # Parser-produced keys are preserved alongside the caller keys.
            assert doc.metadata["source"] == str(plain_text_pdf)
            assert "total_pages" in doc.metadata

    def test_caller_metadata_wins_on_key_conflict(self, plain_text_pdf: Path) -> None:
        """A caller value overrides a parser key (``page``) on conflict."""
        loader = PdfInspectorLoader(
            str(plain_text_pdf),
            mode="page",
            pages=[0, 1, 2],
            output="markdown",
            metadata={"page": 99},
        )
        for doc in loader.load():
            assert doc.metadata["page"] == 99


@pytest.mark.requires("pdf_inspector")
class TestArgumentValidation:
    """Invalid options raise from the loader constructor."""

    def test_extract_images_true_raises_not_implemented(
        self, plain_text_pdf: Path
    ) -> None:
        """``extract_images=True`` is not implemented and raises."""
        with pytest.raises(NotImplementedError, match="extract_images"):
            PdfInspectorLoader(str(plain_text_pdf), extract_images=True)

    def test_invalid_mode_raises_value_error(self, plain_text_pdf: Path) -> None:
        """An unknown ``mode`` raises ``ValueError``."""
        with pytest.raises(ValueError, match="mode must be either"):
            PdfInspectorLoader(str(plain_text_pdf), mode="bogus")

    def test_invalid_output_raises_value_error(self, plain_text_pdf: Path) -> None:
        """An unknown ``output`` raises ``ValueError``."""
        with pytest.raises(ValueError, match="output must be either"):
            PdfInspectorLoader(str(plain_text_pdf), output="bogus")

    @pytest.mark.parametrize("pages", [None, []])
    def test_page_mode_without_pages_raises_value_error(
        self, plain_text_pdf: Path, pages: list[int] | None
    ) -> None:
        """``mode="page"`` requires a non-empty ``pages`` list."""
        with pytest.raises(ValueError, match="pages is required when mode='page'"):
            PdfInspectorLoader(str(plain_text_pdf), mode="page", pages=pages)

    def test_positions_and_regions_together_raise_value_error(
        self, plain_text_pdf: Path
    ) -> None:
        """``extract_positions`` and ``extract_regions`` are mutually exclusive."""
        with pytest.raises(ValueError, match="mutually exclusive"):
            PdfInspectorLoader(
                str(plain_text_pdf),
                extract_positions=True,
                extract_regions=True,
            )

    def test_extract_regions_without_page_regions_raises_value_error(
        self, plain_text_pdf: Path
    ) -> None:
        """``extract_regions=True`` requires ``page_regions``."""
        with pytest.raises(ValueError, match="page_regions is required"):
            PdfInspectorLoader(str(plain_text_pdf), extract_regions=True)

    def test_page_mode_text_without_positions_or_regions_raises_value_error(
        self, plain_text_pdf: Path
    ) -> None:
        """Page mode with ``output="text"`` needs positions or regions."""
        with pytest.raises(ValueError, match="page mode with output='text' requires"):
            PdfInspectorLoader(str(plain_text_pdf), mode="page", pages=[0, 1])

    def test_missing_pdf_inspector_raises_import_error(
        self, plain_text_pdf: Path
    ) -> None:
        """A missing ``pdf_inspector`` package raises a friendly ``ImportError``."""
        with (
            mock.patch.dict(sys.modules, {"pdf_inspector": None}),
            pytest.raises(ImportError, match="pdf_inspector.*not found"),
        ):
            PdfInspectorLoader(str(plain_text_pdf))


@pytest.mark.requires("pdf_inspector")
class TestPathResolution:
    """Local, web and S3 path resolution in ``BasePDFLoader``."""

    def test_web_url_is_downloaded_and_loaded(self, plain_text_pdf: Path) -> None:
        """A web URL is downloaded via ``requests.get`` and then parsed."""
        pdf_bytes = Path(plain_text_pdf).read_bytes()
        response = mock.MagicMock()
        response.status_code = 200
        response.content = pdf_bytes
        url = "https://example.com/files/report.pdf"
        headers = {"Authorization": "Bearer test-token"}

        with mock.patch(
            "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
            return_value=response,
        ) as mocked_get:
            loader = PdfInspectorLoader(url, headers=headers)

            assert loader.web_path == url
            assert loader.source == url
            assert loader.file_path != url
            mocked_get.assert_called_once_with(url, headers=headers)

            docs = loader.load()
        assert len(docs) == 1
        assert docs[0].metadata["source"] == url
        assert "plaintextsentinel-golf" in docs[0].page_content

    def test_web_url_http_error_raises_value_error(self) -> None:
        """A non-200 web response raises ``ValueError`` during construction."""
        response = mock.MagicMock()
        response.status_code = 404
        with (
            mock.patch(
                "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
                return_value=response,
            ),
            pytest.raises(ValueError, match="status code 404"),
        ):
            PdfInspectorLoader("https://example.com/missing.pdf")

    def test_s3_scheme_url_is_not_downloaded(self) -> None:
        """A plain ``s3://`` URL is detected without a download in ``__init__``."""
        url = "s3://my-bucket/docs/report.pdf"
        with mock.patch(
            "langchain_pdf_inspector.pdf_inspector_loader.requests.get"
        ) as mocked_get:
            loader = PdfInspectorLoader(url)

            assert loader.web_path == url
            assert loader.file_path == url
            mocked_get.assert_not_called()

    def test_presigned_s3_url_is_downloaded(self, plain_text_pdf: Path) -> None:
        """A presigned S3 URL is downloaded like a regular web URL."""
        pdf_bytes = Path(plain_text_pdf).read_bytes()
        response = mock.MagicMock()
        response.status_code = 200
        response.content = pdf_bytes
        url = "https://my-bucket.s3.amazonaws.com/report.pdf?X-Amz-Signature=abc123"

        with mock.patch(
            "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
            return_value=response,
        ) as mocked_get:
            loader = PdfInspectorLoader(url)

            assert loader.web_path == url
            assert loader.file_path != url
            mocked_get.assert_called_once()

    def test_nonexistent_local_path_raises_value_error(self, tmp_path: Path) -> None:
        """A nonexistent local path raises ``ValueError``."""
        missing = tmp_path / "does-not-exist.pdf"
        with pytest.raises(ValueError, match="is not a valid file or url"):
            PdfInspectorLoader(str(missing))

    def test_non_url_string_raises_value_error(self) -> None:
        """A string that is neither a file nor a URL raises ``ValueError``."""
        with pytest.raises(ValueError, match="is not a valid file or url"):
            PdfInspectorLoader("this is not a url or a file")

    def test_tilde_path_is_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``~``-prefixed path is expanded through ``os.path.expanduser``."""
        dummy = tmp_path / "dummy.pdf"
        dummy.write_bytes(b"%PDF-1.4 dummy")
        monkeypatch.setattr(
            "langchain_pdf_inspector.pdf_inspector_loader.os.path.expanduser",
            lambda path: str(dummy),
        )
        loader = PdfInspectorLoader("~/reports/report.pdf")
        assert loader.file_path == str(dummy)


class TestBaseLoaderHelpers:
    """URL/S3 classification helpers on ``BasePDFLoader``."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://example.test/file.pdf", True),
            ("s3://bucket/key.pdf", True),
            ("not-a-url", False),
            ("/tmp/file.pdf", False),
        ],
    )
    def test_url_validation_helper(self, url: str, expected: bool) -> None:
        """``_is_valid_url`` requires a scheme and a netloc."""
        assert BasePDFLoader._is_valid_url(url) is expected

    @pytest.mark.parametrize(
        ("url", "is_s3", "is_presigned"),
        [
            ("s3://bucket/key.pdf", True, False),
            (
                "https://bucket.s3.amazonaws.com/key.pdf?X-Amz-Signature=test",
                False,
                True,
            ),
            ("https://example.test/file.pdf", False, False),
        ],
    )
    def test_s3_helpers(self, url: str, is_s3: bool, is_presigned: bool) -> None:
        """``_is_s3_url`` and ``_is_s3_presigned_url`` classify S3 paths."""
        assert BasePDFLoader._is_s3_url(url) is is_s3
        assert BasePDFLoader._is_s3_presigned_url(url) is is_presigned

    @pytest.mark.requires("pdf_inspector")
    def test_base_loader_rejects_invalid_file_path(self) -> None:
        """Invalid paths raise a clear ``ValueError`` at construction."""
        with pytest.raises(ValueError, match="is not a valid file or url"):
            PdfInspectorLoader(file_path="definitely-not-a-real-file.pdf")


@pytest.mark.requires("pdf_inspector")
class TestBlobWrapping:
    """``lazy_load`` wraps local vs. web paths in the matching ``Blob``."""

    def test_loader_uses_blob_from_path_for_local_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local files are wrapped via ``Blob.from_path`` before parsing."""
        local_pdf = tmp_path / "local.pdf"
        local_pdf.write_bytes(b"%PDF-1.4 dummy")

        from_path = mock.Mock(return_value=Blob.from_path(str(local_pdf)))
        monkeypatch.setattr(
            "langchain_pdf_inspector.pdf_inspector_loader.Blob.from_path", from_path
        )
        monkeypatch.setattr(
            "langchain_pdf_inspector.pdf_inspector_loader.PdfInspectorParser",
            _FakeParser,
        )

        loader = PdfInspectorLoader(str(local_pdf))
        docs = list(loader.lazy_load())

        assert loader.web_path is None
        from_path.assert_called_once_with(str(local_pdf))
        assert docs[0].page_content == "fake-page-content"

    def test_loader_uses_blob_from_data_for_web_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Web sources are wrapped via ``Blob.from_data`` with the web path."""
        url = "https://example.test/report.pdf"
        from_data = mock.Mock()
        monkeypatch.setattr(
            "langchain_pdf_inspector.pdf_inspector_loader.Blob.from_data", from_data
        )
        monkeypatch.setattr(
            "langchain_pdf_inspector.pdf_inspector_loader.PdfInspectorParser",
            _FakeParser,
        )

        response = mock.MagicMock()
        response.status_code = 200
        response.content = b"%PDF-1.4 dummy"
        with mock.patch(
            "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
            return_value=response,
        ):
            loader = PdfInspectorLoader(url)

        docs = list(loader.lazy_load())

        assert loader.web_path == url
        from_data.assert_called_once()
        assert from_data.call_args.kwargs["path"] == url
        assert docs[0].page_content == "fake-page-content"


@pytest.mark.requires("pdf_inspector")
class TestLazyLoading:
    """``lazy_load`` yields the same documents as ``load``."""

    def test_lazy_load_matches_load(self, plain_text_pdf: Path) -> None:
        """``lazy_load`` yields the same documents as ``load``."""
        loader = PdfInspectorLoader(str(plain_text_pdf))
        lazy_docs = list(loader.lazy_load())
        loaded_docs = loader.load()

        assert [doc.page_content for doc in lazy_docs] == [
            doc.page_content for doc in loaded_docs
        ]
        assert [doc.metadata for doc in lazy_docs] == [
            doc.metadata for doc in loaded_docs
        ]
