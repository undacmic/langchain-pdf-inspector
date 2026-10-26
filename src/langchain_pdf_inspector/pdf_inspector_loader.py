"""LangChain document loader integration for `pdf-inspector`.

Provides `BasePDFLoader`, which resolves local, web and S3 PDF paths (downloading
web paths to a temporary file), and `PdfInspectorLoader`, which parses those
paths into LangChain `Document` objects using the `pdf-inspector` library.
"""

from __future__ import annotations

import os
import re
import tempfile
from abc import ABC
from collections.abc import Iterator
from pathlib import PurePath
from typing import Literal
from urllib.parse import urlparse

import requests
from langchain_core.document_loaders import BaseLoader
from langchain_core.document_loaders.blob_loaders import Blob
from langchain_core.documents import Document

from .pdf_inspector_parser import PdfInspectorParser


class BasePDFLoader(BaseLoader, ABC):
    """Base Loader class for `PDF` files.

    If the file is a web path, it will download it to a temporary file, use it, then
        clean up the temporary file after completion.
    """

    def __init__(self, file_path: str | PurePath, *, headers: dict | None = None):
        """Initialize with a file path.

        Args:
            file_path: Either a local, S3 or web path to a PDF file.
            headers: Headers to use for GET request to download a file from a web path.
        """
        self.file_path = str(file_path)
        self.web_path = None
        self.headers = headers
        if "~" in self.file_path:
            self.file_path = os.path.expanduser(self.file_path)

        # If the file is a web path or S3, download it to a temporary file,
        # and use that. It's better to use a BlobLoader.
        if not os.path.isfile(self.file_path) and self._is_valid_url(self.file_path):
            self.temp_dir = tempfile.TemporaryDirectory()
            _, suffix = os.path.splitext(self.file_path)
            if self._is_s3_presigned_url(self.file_path):
                suffix = urlparse(self.file_path).path.split("/")[-1]
            temp_pdf = os.path.join(self.temp_dir.name, f"tmp{suffix}")
            self.web_path = self.file_path
            if not self._is_s3_url(self.file_path):
                r = requests.get(self.file_path, headers=self.headers)
                if r.status_code != 200:
                    raise ValueError(
                        "Check the url of your file; returned status code "
                        f"{r.status_code}"
                    )

                with open(temp_pdf, mode="wb") as f:
                    f.write(r.content)
                self.file_path = str(temp_pdf)
        elif not os.path.isfile(self.file_path):
            raise ValueError(f"File path {self.file_path} is not a valid file or url")

    def __del__(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """Check if the url is valid."""
        parsed = urlparse(url)
        return bool(parsed.netloc) and bool(parsed.scheme)

    @staticmethod
    def _is_s3_url(url: str) -> bool:
        """check if the url is S3"""
        try:
            result = urlparse(url)
            return bool(result.scheme == "s3" and result.netloc)
        except ValueError:
            return False

    @staticmethod
    def _is_s3_presigned_url(url: str) -> bool:
        """Check if the url is a presigned S3 url."""
        try:
            result = urlparse(url)
            return bool(re.search(r"\.s3\.amazonaws\.com$", result.netloc))
        except ValueError:
            return False

    @property
    def source(self) -> str:
        return self.web_path if self.web_path is not None else self.file_path


class PdfInspectorLoader(BasePDFLoader):
    """Load PDF files into LangChain `Document` objects via `pdf-inspector`.

    Thin wrapper around `PdfInspectorParser` that resolves a local, web or S3
    PDF path (downloading web paths to a temporary file via `BasePDFLoader`)
    and merges optional caller-supplied `metadata` on top of each parsed
    document.

    `mode`/`output`/`extract_positions`/`extract_regions`/`pages`/
    `page_regions`/`region_delimiter`/`page_delimiter` are forwarded to
    `PdfInspectorParser`; see its `__init__` for the semantics of each option.
    Every parsed `Document` carries the base metadata (`source`, `pdf_type`,
    `total_pages`) built by the parser.

    Examples:
        Setup:

        .. code-block:: bash

            pip install -U langchain-core pdf-inspector

        Instantiate the loader:

        .. code-block:: python

            from langchain_pdf_inspector import PdfInspectorLoader

            loader = PdfInspectorLoader(file_path="./example.pdf")

        Lazy load documents:

        .. code-block:: python

            docs_lazy = loader.lazy_load()
            for doc in docs_lazy:
                print(doc.page_content[:100])
                print(doc.metadata)

    """

    def __init__(
        self,
        file_path: str | PurePath,
        headers: dict | None = None,
        extract_images: bool = False,
        *,
        mode: Literal["single", "page"] = "single",
        output: Literal["text", "markdown"] = "text",
        extract_positions: bool = False,
        extract_regions: bool = False,
        pages: list[int] | None = None,
        page_regions: list[tuple[int, list[list[float]]]] | None = None,
        region_delimiter: str = "\n\n",
        page_delimiter: str = "\n\n",
        metadata: dict | None = None,
    ) -> None:
        """Initialize the loader.

        Args:
            file_path: Local, web, or S3 path to a PDF file.
            headers: Headers used for the GET request when `file_path` is a
                web URL.
            extract_images: Reserved for future image extraction. Only `False`
                is currently supported; `True` raises `NotImplementedError`.
            mode: `"single"` or `"page"` extraction mode, forwarded to
                `PdfInspectorParser`. Defaults to `"single"`.
            output: `"text"` or `"markdown"`, forwarded to
                `PdfInspectorParser`. In `"page"` mode this selects per-page
                plain text (`"text"`) vs. per-page markdown with layout flags
                (`"markdown"`). Defaults to `"text"`.
            extract_positions: Attach positional `TextItem` data when `True`.
                Mutually exclusive with `extract_regions`.
            extract_regions: Crop text to `page_regions` when `True`.
                Mutually exclusive with `extract_positions`.
            pages: Pages to restrict extraction to (0-indexed). **Required in
                `"page"` mode** (a non-empty list; an empty list or `None`
                raises `ValueError`). Lenient in `"single"` mode.
            page_regions: Regions to crop when `extract_regions=True`. Each
                entry is `(page, [[x0, y0, x1, y1], ...])`. Coordinates are in
                PDF points with a top-left origin and `y` increasing downward,
                relative to the visible page box (CropBox intersected with
                MediaBox), **not** the MediaBox.
            region_delimiter: String used to join the extracted region texts.
                Forwarded to `PdfInspectorParser`; defaults to `"\\n\\n"`.
            page_delimiter: String used to join pages together in the
                `"single"` mode positional-text path, where all pages collapse
                into a single `Document`. Forwarded to `PdfInspectorParser`;
                defaults to `"\\n\\n"`.
            metadata: Optional caller-supplied metadata merged on top of each
                parsed `Document`'s metadata; on a key conflict the caller
                value wins.

        Returns:
            None. Use the `load`, `lazy_load` methods to retrieve
            parsed documents with content and metadata.

        Raises:
            NotImplementedError: If `extract_images` is `True`.
            ImportError: If the `pdf_inspector` package is not installed.
            ValueError: If the parser's option validation fails, e.g.
                `mode="page"` without a non-empty `pages` list.
        """
        if extract_images:
            raise NotImplementedError(
                "extract_images=True is not yet implemented by langchain-pdf-inspector"
            )
        try:
            import pdf_inspector  # noqa:F401
        except ImportError:
            raise ImportError(
                "`pdf_inspector` package not found, please install it with "
                "`pip install pdf-inspector`"
            )
        super().__init__(file_path, headers=headers)
        self.parser: PdfInspectorParser = PdfInspectorParser(
            mode=mode,
            output=output,
            extract_positions=extract_positions,
            extract_regions=extract_regions,
            pages=pages,
            page_regions=page_regions,
            region_delimiter=region_delimiter,
            page_delimiter=page_delimiter,
        )
        self.metadata: dict | None = metadata

    def _merge_metadata(self, document: Document) -> Document:
        """Merge caller-supplied `metadata` on top of a parsed `Document`.

        Caller metadata always wins over the parser-produced metadata on key
        conflicts, mirroring the standard LangChain `DocumentLoader` contract.
        """
        return Document(
            page_content=document.page_content,
            metadata={**document.metadata, **(self.metadata or {})},
        )

    def lazy_load(self) -> Iterator[Document]:
        """Load PDF file into `Document` objects.

        Parses the PDF and yields a single `Document` (`mode="single"`, the
        default), one `Document` per page (`mode="page"`), or one `Document`
        for the whole file when `extract_positions` is set in single mode. In
        `mode="page"` the content branches on `output`: `"text"` yields
        per-page plain text (items joined with a newline; empty pages skipped),
        `"markdown"` yields per-page markdown with layout flags. `output`
        defaults to `"text"`.

        The `extract_positions`/`extract_regions` options select positional or
        region-cropped output, and `pages`/`page_regions` select the pages to
        process (subject to the disjoint rules enforced by `PdfInspectorParser`).
        Every `Document` carries the base detection metadata (`source`,
        `pdf_type`, `total_pages`) built by the parser, plus the branch-specific
        keys. All `page` metadata is 1-indexed.

        Any caller-supplied `metadata` (passed to the constructor) is merged on
        top of the parser metadata for every yielded `Document`; on a key
        conflict the caller value wins.

        Image extraction (`extract_images=True`) is not yet implemented and
        raises `NotImplementedError` at construction time.

        Yields:
            `Document` objects with the extracted content and merged metadata.

        Raises:
            FileNotFoundError: If the file is missing.
        """
        if self.web_path:
            with open(self.file_path, "rb") as f:
                data = f.read()
            blob: Blob = Blob.from_data(data, path=self.web_path)
        else:
            blob = Blob.from_path(self.file_path)
        for document in self.parser.parse(blob):
            yield self._merge_metadata(document)
