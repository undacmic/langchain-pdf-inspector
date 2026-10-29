"""Behavioral contracts for LangChain's loader and blob-parser interfaces."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.document_loaders import BaseBlobParser, BaseLoader
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorLoader, PdfInspectorParser

PAGE_OPTIONS = [
    {"output": "markdown"},
    {"extract_positions": True},
    {
        "extract_regions": True,
        "page_regions": [
            (0, [[0.0, 0.0, 612.0, 792.0]]),
            (1, [[0.0, 0.0, 612.0, 792.0]]),
            (2, [[0.0, 0.0, 612.0, 792.0]]),
        ],
    },
]


def test_lazy_load_does_not_consume_later_documents(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A consumer can receive page one before parsing a later page fails."""
    loader = PdfInspectorLoader(plain_text_pdf, metadata={"tenant": "acme"})
    events: list[str] = []
    failure = RuntimeError("later page failed")

    def lazy_parse(blob: Blob) -> Iterator[Document]:
        events.append("first page")
        yield Document(page_content="first page", metadata={"source": blob.source})
        events.append("later page")
        raise failure

    monkeypatch.setattr(loader.parser, "lazy_parse", lazy_parse)
    documents = loader.lazy_load()
    assert events == []
    first = next(documents)
    assert first.page_content == "first page"
    assert first.metadata == {"source": str(plain_text_pdf), "tenant": "acme"}
    assert events == ["first page"]
    with pytest.raises(RuntimeError, match="later page failed") as error:
        next(documents)
    assert error.value is failure
    assert events == ["first page", "later page"]


@pytest.mark.parametrize(
    "options", PAGE_OPTIONS, ids=["markdown", "positions", "regions"]
)
def test_inherited_async_loading_matches_sync_documents(
    plain_text_pdf: Path, options: dict[str, Any]
) -> None:
    """BaseLoader's async adapters retain content, page numbering, and metadata."""
    loader = PdfInspectorLoader(
        plain_text_pdf,
        mode="page",
        pages=[0, 1, 2],
        metadata={"tenant": "acme"},
        **options,
    )
    assert isinstance(loader, BaseLoader)
    expected = loader.load()
    assert [doc.metadata["page"] for doc in expected] == [1, 2, 3]
    assert "opening paragraph" in expected[0].page_content
    assert "plaintextsentinel-foxtrot" in expected[1].page_content
    assert "plaintextsentinel-golf" in expected[2].page_content
    for doc in expected:
        assert isinstance(doc, Document)
        assert doc.metadata["source"] == str(plain_text_pdf)
        assert doc.metadata["tenant"] == "acme"
        assert doc.metadata["total_pages"] == 3

    async def load_async() -> tuple[list[Document], list[Document]]:
        eager = await loader.aload()
        lazy = [doc async for doc in loader.alazy_load()]
        return eager, lazy

    eager, lazy = asyncio.run(load_async())
    assert eager == expected
    assert lazy == expected


@pytest.mark.parametrize(
    "options", PAGE_OPTIONS, ids=["markdown", "positions", "regions"]
)
def test_blob_parser_and_loader_emit_equivalent_documents(
    plain_text_pdf: Path, options: dict[str, Any]
) -> None:
    """Blob parsing and path loading obey the same LangChain Document contract."""
    parser = PdfInspectorParser(mode="page", pages=[0, 1, 2], **options)
    assert isinstance(parser, BaseBlobParser)
    blob = Blob.from_path(plain_text_pdf)
    expected = PdfInspectorLoader(
        plain_text_pdf, mode="page", pages=[0, 1, 2], **options
    ).load()
    assert len(expected) == 3
    assert parser.parse(blob) == expected
    assert list(parser.lazy_parse(blob)) == expected
