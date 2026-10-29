"""PDF failure handling, empty content, metadata fallback, and page selection."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pdf_inspector
import pytest
import requests
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorLoader, PdfInspectorParser
from langchain_pdf_inspector.pdf_inspector_loader import BasePDFLoader


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({}, "Failed to extract plain text"),
        ({"extract_positions": True}, "Failed to extract text with positions"),
        (
            {
                "extract_regions": True,
                "page_regions": [(0, [[0.0, 0.0, 100.0, 100.0]])],
            },
            "Failed to extract text in the requested page regions",
        ),
        ({"output": "markdown"}, "Failed to extract per-page markdown"),
    ],
)
@pytest.mark.parametrize("data", [b"not a PDF", b"%PDF-1.7\ntruncated"])
def test_invalid_pdf_reports_extraction_failure(
    options: dict, message: str, data: bytes
):
    """Reject non-PDF uploads and truncated downloads without hiding the cause."""
    blob = Blob.from_data(data, path="broken.pdf")
    with pytest.raises(RuntimeError, match=message) as error:
        PdfInspectorParser(**options).parse(blob)
    assert isinstance(error.value.__cause__, ValueError)
    assert "PDF" in str(error.value.__cause__)


def test_missing_pdf_backend_has_install_hint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "pdf_inspector", None)
    with pytest.raises(ImportError, match="pip install pdf-inspector") as error:
        PdfInspectorParser().parse(Blob.from_data(b"%PDF-1.7"))
    assert isinstance(error.value.__cause__, ImportError)


def test_metadata_detection_failure_does_not_discard_text(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
):
    """A detection failure must not prevent independent text extraction."""
    monkeypatch.setattr(
        pdf_inspector, "detect_pdf_bytes", Mock(side_effect=ValueError("bad PDF info"))
    )
    doc = PdfInspectorParser().parse(Blob.from_path(plain_text_pdf))[0]
    assert "plaintextsentinel-foxtrot" in doc.page_content
    assert doc.metadata == {"source": str(plain_text_pdf), "page": 1}


@pytest.mark.parametrize("output", ["text", "markdown"])
def test_missing_detection_fields_preserve_pdf_content(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch, output: str
):
    """Accept partial backend metadata without inventing a page count or title."""
    detection = SimpleNamespace(
        pdf_type=None,
        page_count=None,
        title="",
        author=None,
        subject=None,
        keywords="",
        creator=None,
        producer=None,
        creation_date=None,
        mod_date=None,
    )
    monkeypatch.setattr(pdf_inspector, "detect_pdf_bytes", lambda **_: detection)
    options = {"mode": "page", "pages": [1]} if output == "markdown" else {}
    doc = PdfInspectorParser(output=output, **options).parse(
        Blob.from_path(plain_text_pdf)
    )[0]
    assert "plaintextsentinel-foxtrot" in doc.page_content
    assert doc.metadata["source"] == str(plain_text_pdf)
    assert doc.metadata["page"] == (2 if output == "markdown" else 1)
    assert not {"pdf_type", "total_pages", "title", "author"} & doc.metadata.keys()


def test_blank_page_is_omitted_from_positional_text(empty_pages_pdf: Path):
    docs = PdfInspectorParser(mode="page", pages=[0, 1], extract_positions=True).parse(
        Blob.from_path(empty_pages_pdf)
    )
    assert len(docs) == 1
    assert "emptypage-sentinel" in docs[0].page_content
    assert docs[0].metadata["page"] == 1
    assert docs[0].metadata["total_pages"] == 3


def test_selecting_only_blank_page_returns_no_positional_documents(
    empty_pages_pdf: Path,
):
    assert (
        PdfInspectorParser(mode="page", pages=[1], extract_positions=True).parse(
            Blob.from_path(empty_pages_pdf)
        )
        == []
    )


def test_markdown_retains_blank_and_image_pages_with_ocr_flags(empty_pages_pdf: Path):
    """Image-only pages are flagged for OCR, not silently presented as extracted text."""
    docs = PdfInspectorParser(mode="page", output="markdown", pages=[0, 1, 2]).parse(
        Blob.from_path(empty_pages_pdf)
    )
    assert [doc.metadata["page"] for doc in docs] == [1, 2, 3]
    assert "emptypage-sentinel" in docs[0].page_content
    assert docs[0].metadata["needs_ocr"] is False
    for doc in docs[1:]:
        assert doc.page_content == ""
        assert doc.metadata["needs_ocr"] is True
        assert doc.metadata["has_tables"] is False
        assert doc.metadata["has_multicolumn_layout"] is False


@pytest.mark.parametrize("mode", ["single", "page"])
def test_crop_outside_text_returns_empty_content(plain_text_pdf: Path, mode: str):
    """A valid crop in the page margin is not an extraction error."""
    docs = PdfInspectorParser(
        mode=mode,
        pages=[0],
        extract_regions=True,
        page_regions=[(0, [[0.0, 0.0, 10.0, 10.0]])],
    ).parse(Blob.from_path(plain_text_pdf))
    assert len(docs) == 1
    assert docs[0].page_content == ""
    assert docs[0].metadata["page"] == 1


@pytest.mark.parametrize("output", ["text", "markdown"])
def test_nonexistent_page_is_not_emitted(plain_text_pdf: Path, output: str):
    docs = PdfInspectorParser(
        mode="page", output=output, pages=[99], extract_positions=output == "text"
    ).parse(Blob.from_path(plain_text_pdf))
    assert docs == []


@pytest.mark.parametrize("output", ["text", "markdown"])
def test_duplicate_page_requests_follow_extraction_contract(
    plain_text_pdf: Path, output: str
):
    docs = PdfInspectorParser(
        mode="page", output=output, pages=[1, 1], extract_positions=output == "text"
    ).parse(Blob.from_path(plain_text_pdf))
    assert len(docs) == (2 if output == "markdown" else 1)
    for doc in docs:
        assert doc.metadata["page"] == 2
        assert "plaintextsentinel-foxtrot" in doc.page_content
        assert "plaintextsentinel-golf" not in doc.page_content


def test_empty_position_tokens_do_not_create_spurious_pages(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
):
    """Ignore empty backend text runs without losing the actual extracted words."""
    extract = pdf_inspector.extract_text_with_positions_bytes

    def with_empty_token(**kwargs):
        return [SimpleNamespace(text="", page=99), *extract(**kwargs)]

    monkeypatch.setattr(
        pdf_inspector, "extract_text_with_positions_bytes", with_empty_token
    )
    docs = PdfInspectorParser(mode="page", pages=[1], extract_positions=True).parse(
        Blob.from_path(plain_text_pdf)
    )
    assert [doc.metadata["page"] for doc in docs] == [2]
    assert "plaintextsentinel-foxtrot" in docs[0].page_content


@pytest.mark.parametrize(
    "url", ["http://[broken/report.pdf", "s3://[broken/report.pdf"]
)
def test_malformed_pdf_urls_are_not_classified_as_s3(url: str):
    assert BasePDFLoader._is_s3_url(url) is False


def test_downloaded_pdf_is_removed_on_cleanup(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
):
    """Remote extraction preserves its source URL and does not retain the download."""
    url = "https://example.test/report.pdf"
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
        Mock(
            return_value=SimpleNamespace(
                status_code=200, content=plain_text_pdf.read_bytes()
            )
        ),
    )
    loader = PdfInspectorLoader(url)
    download = Path(loader.file_path)
    doc = loader.load()[0]
    assert "plaintextsentinel-foxtrot" in doc.page_content
    assert doc.metadata["source"] == url
    assert download.is_file()
    loader.__del__()
    assert not download.parent.exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/report.pdf?token=" + "a" * 400,
        "https://bucket.s3.amazonaws.com/report.pdf?X-Amz-Signature=" + "b" * 400,
        "https://example.test/" + "c" * 400 + ".pdf",
    ],
    ids=["long-query", "presigned-s3", "long-path"],
)
def test_remote_url_does_not_become_a_temporary_filename(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Signed URLs and long remote names preserve source without local name limits."""
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.requests.get",
        Mock(
            return_value=SimpleNamespace(
                status_code=200, content=plain_text_pdf.read_bytes()
            )
        ),
    )
    loader = PdfInspectorLoader(url)
    doc = loader.load()[0]
    assert "plaintextsentinel-foxtrot" in doc.page_content
    assert doc.metadata["source"] == url
    assert loader.source == url
    assert len(Path(loader.file_path).name.encode()) < 255
    assert "?" not in Path(loader.file_path).name


@pytest.mark.parametrize("failure", ["timeout", "http-error"])
def test_failed_download_cleans_up_immediately(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Cleanup must not depend on garbage collection of a failed constructor."""
    directories: list[Path] = []
    temporary_directory = tempfile.TemporaryDirectory

    def track_directory() -> tempfile.TemporaryDirectory[str]:
        directory = temporary_directory()
        directories.append(Path(directory.name))
        return directory

    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.tempfile.TemporaryDirectory",
        track_directory,
    )
    timeout = requests.Timeout("download stalled")
    get = Mock(
        side_effect=timeout if failure == "timeout" else None,
        return_value=SimpleNamespace(status_code=404),
    )
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.requests.get", get
    )
    exception = requests.Timeout if failure == "timeout" else ValueError
    with pytest.raises(exception) as error:
        PdfInspectorLoader("https://example.test/report.pdf")
    # Keep the exception and its constructor traceback alive during this check.
    assert len(directories) == 1
    assert not directories[0].exists()
    get.assert_called_once_with(
        "https://example.test/report.pdf", headers=None, timeout=(10, 60)
    )
    if failure == "timeout":
        assert error.value is timeout
    else:
        assert "status code 404" in str(error.value)
