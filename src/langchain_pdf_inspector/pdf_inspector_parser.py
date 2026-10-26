from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.document_loaders import BaseBlobParser
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

if TYPE_CHECKING:
    from pdf_inspector import (
        PageRegionTexts,
        PagesExtractionResult,
        PdfResult,
        TextItem,
    )


def _build_base_metadata(blob: Blob) -> dict[str, Any]:
    """Build the base metadata shared by every generated `Document`.

    Always includes `source`, and attaches `pdf_type` and `total_pages` from
    `detect_pdf_bytes` when detection succeeds. `None` values are skipped.
    """

    metadata: dict[str, Any] = {"source": blob.source}
    data: bytes = blob.as_bytes()

    from pdf_inspector import detect_pdf_bytes

    try:
        result: PdfResult = detect_pdf_bytes(data=data)
    except Exception:  # noqa: BLE001 - detection failures fall back to base metadata
        return metadata

    if result.pdf_type is not None:
        metadata["pdf_type"] = result.pdf_type
    if result.page_count is not None:
        metadata["total_pages"] = result.page_count

    return metadata


class PdfInspectorParser(BaseBlobParser):
    """Parse PDFs into LangChain `Document` objects using `pdf-inspector`.

    Two extraction modes are available, selected by `mode`:

    - `"single"` (default): yields one `Document` for the whole PDF. Within
      this mode the content is produced by the first matching option in
      priority order (see `lazy_parse`): region-cropped text when
      `extract_regions` is set (one joined `Document`), positional text when
      `extract_positions` is set (one joined `Document` whose pages are joined
      with `page_delimiter`), full markdown when `output` is `"markdown"`,
      otherwise plain text.
    - `"page"`: yields one `Document` per page. `pages` is **required** (a
      non-empty list of 0-indexed pages) and the content branches on `output`:
      `"text"` emits each page's plain text (the page's items joined with a
      newline; pages with no non-empty text are skipped), `"markdown"` emits
      each page's markdown with the per-page layout flags. `output` defaults to
      `"text"`, so page mode yields per-page plain text unless
      `output="markdown"` is requested.

    `extract_positions` and `extract_regions` are mutually exclusive, and
    `extract_regions=True` requires `page_regions`. `pages` is required in
    `"page"` mode; in `"single"` mode `pages` and `page_regions` are lenient:
    when they do not apply to the chosen extraction path they are silently
    ignored rather than raising. Inputs (`pages`/`page_regions`) are 0-indexed;
    all output `page` metadata is 1-indexed. The same 0-indexed `pages`
    selection therefore addresses the same logical pages in the positional-text
    and markdown paths. See `__init__` for the full parameter documentation.

    Examples:
        Setup:

        .. code-block:: bash

            pip install -U langchain-core pdf-inspector

        Load a blob from a PDF file:

        .. code-block:: python

            from langchain_core.documents.base import Blob

            blob = Blob.from_path("./example.pdf")

        Instantiate the parser:

        .. code-block:: python

            from langchain_pdf_inspector import PdfInspectorParser

            parser = PdfInspectorParser(mode="page", pages=[0, 1, 2])

        Lazily parse the blob:

        .. code-block:: python

            docs = parser.lazy_parse(blob)
            for doc in docs:
                print(doc.page_content[:100])
                print(doc.metadata)
    """

    def __init__(
        self,
        mode: Literal["single", "page"] = "single",
        output: Literal["text", "markdown"] = "text",
        *,
        extract_positions: bool = False,
        extract_regions: bool = False,
        pages: list[int] | None = None,
        page_regions: list[tuple[int, list[list[float]]]] | None = None,
        region_delimiter: str = "\n\n",
        page_delimiter: str = "\n\n",
    ) -> None:
        """Initialize the parser.

        Args:
            mode: `"single"` for a single whole-PDF `Document` or `"page"` for
                one `Document` per page. Defaults to `"single"`.
            output: `"text"` or `"markdown"` for the content produced. In
                `"single"` mode this selects plain text vs. markdown. In
                `"page"` mode it selects per-page plain text (items joined with
                a newline) vs. per-page markdown with layout flags
                (`"markdown"`). Defaults to `"text"`.
            extract_positions: When `True` in `"single"` mode, extract
                positional text and emit one joined `Document` whose pages are
                joined with `page_delimiter`. In `"page"` mode with
                `output="text"` the same positional-text path is used per page
                (one `Document` per page, without any positions metadata).
                Mutually exclusive with `extract_regions`.
            extract_regions: When `True`, extract text only from the regions
                given in `page_regions`. In `"single"` mode this crops the whole
                document (one joined `Document`). In `"page"` mode with
                `output="text"` it crops per page (one `Document` per page).
                Requires `page_regions` and is mutually exclusive with
                `extract_positions`.
            pages: Pages to restrict extraction to, **0-indexed for every
                mode and extraction path** (e.g. `[0, 2]` selects the first and
                third pages). **Required in `"page"` mode**: a non-empty list
                must be supplied (an empty list or `None` raises
                `ValueError`). In `"single"` mode it is lenient: `None` means
                the whole document and the value is silently ignored when the
                chosen extraction path does not use it (e.g. plain-text
                extraction). Out-of-range indices are not validated: the
                positional-text path silently omits them, while the markdown
                path emits an empty `Document` for each one (flagged
                `needs_ocr=True`). Duplicate indices are collapsed to one
                `Document` per page by the positional-text path, while the
                markdown path emits one `Document` per occurrence in the
                requested order. Negative indices are invalid and make the
                underlying extraction fail.
            page_regions: Per-page regions to crop, required when
                `extract_regions=True`. Each entry is `(page, [[x0, y0, x1,
                y1], ...])`. Lenient: silently ignored unless `extract_regions`
                is active.
            region_delimiter: String used to join the extracted region texts
                (both the joined single-mode regions and the page-mode
                regions). Defaults to `"\\n\\n"`.
            page_delimiter: String used to join pages together in the
                `"single"` mode positional-text path, where all pages collapse
                into a single `Document`. Defaults to `"\\n\\n"`.

        Returns:
            None. Use the `parse` or `lazy_parse` methods to retrieve parsed
            documents with content and metadata.

        Raises:
            ValueError: If `mode`/`output` are invalid, if `mode="page"` is set
                without a non-empty `pages` list, if `extract_positions` and
                `extract_regions` are both `True`, or if
                `extract_regions=True` is set without `page_regions`.
        """
        super().__init__()

        if mode not in ("single", "page"):
            raise ValueError("mode must be either 'single' or 'page'")
        if output not in ("text", "markdown"):
            raise ValueError("output must be either 'text' or 'markdown'")
        if mode == "page" and not pages:
            raise ValueError("pages is required when mode='page'")
        if extract_positions and extract_regions:
            raise ValueError(
                "extract_positions and extract_regions are mutually exclusive; "
                "you cannot extract full positional data and region-cropped data "
                "at the same time."
            )
        if extract_regions and not page_regions:
            raise ValueError("page_regions is required when extract_regions=True")
        if not isinstance(region_delimiter, str):
            raise ValueError("region_delimiter must be a string")  # noqa: TRY004
        if not isinstance(page_delimiter, str):
            raise ValueError("page_delimiter must be a string")  # noqa: TRY004

        self.extract_plain = (extract_regions or extract_positions) is False

        if mode == "page" and output == "text" and self.extract_plain:
            raise ValueError(
                "page mode with output='text' requires extract_positions=True or extract_regions=True"
            )

        self.mode = mode
        self.output = output
        self.extract_positions = extract_positions
        self.extract_regions = extract_regions
        self.pages = pages
        self.page_regions = page_regions
        self.region_delimiter = region_delimiter
        self.page_delimiter = page_delimiter

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        """Parse `blob` and lazily yield the resulting `Document` objects.

        Dispatches to the matching extraction path based on
        `output`/`extract_positions`/`extract_regions`: plain text,
        positional text, region-cropped text or markdown (see `__init__`).
        Every yielded `Document` carries the base detection metadata (`source`,
        `pdf_type`, `total_pages`) built by `_build_base_metadata`.

        Yields:
            `Document` objects with the extracted content and metadata.

        Raises:
            ImportError: If the `pdf_inspector` package is not installed.
        """
        try:
            import pdf_inspector  # noqa: F401 - availability check
        except ImportError:
            raise ImportError(
                "`pdf_inspector` package not found, please install it with "
                "`pip install pdf-inspector`"
            )

        base_metadata: dict[str, Any] = _build_base_metadata(blob)

        if self.output == "text" and self.extract_regions:
            yield from self._extract_text_from_regions(blob, base_metadata)
        elif self.output == "text" and self.extract_positions:
            yield from self._extract_text_with_positions(blob, base_metadata)
        elif self.output == "text" and self.extract_plain:
            yield from self._extract_plain_text(blob, base_metadata)
        elif self.output == "markdown":
            yield from self._extract_markdown(blob, base_metadata)

    def parse(self, blob: Blob) -> list[Document]:
        """Parse `blob` and return the resulting `Document` objects as a list."""
        return list(self.lazy_parse(blob))

    def _extract_plain_text(
        self, blob: Blob, base_metadata: dict[str, Any]
    ) -> Iterator[Document]:
        """Extract the whole PDF as plain text and yield a single `Document`."""
        from pdf_inspector import extract_text_bytes

        data: bytes = blob.as_bytes()

        try:
            result: str = extract_text_bytes(data=data)
        except Exception as e:
            raise RuntimeError("Failed to extract plain text from the PDF.") from e

        metadata: dict[str, Any] = dict(base_metadata)
        metadata["page"] = 1

        yield Document(page_content=result, metadata=metadata)

    def _extract_text_with_positions(
        self, blob: Blob, base_metadata: dict[str, Any]
    ) -> Iterator[Document]:
        """Extract positional text, yielding one joined `Document` in single mode or one per page."""
        from pdf_inspector import extract_text_with_positions_bytes

        data: bytes = blob.as_bytes()
        # The public ``pages`` contract is 0-indexed, but upstream's
        # ``extract_text_with_positions_bytes`` expects 1-indexed page numbers.
        pages: list[int] | None = (
            [page + 1 for page in self.pages]
            if self.mode == "page" and self.pages is not None
            else None
        )

        try:
            result: list[TextItem] = extract_text_with_positions_bytes(
                data=data, pages=pages
            )
        except Exception as e:
            raise RuntimeError(
                "Failed to extract text with positions from the PDF."
            ) from e

        page_items: dict[int, list[TextItem]] = {}
        for item in result:
            if not item.text:
                continue
            page_items.setdefault(item.page, []).append(item)

        metadata = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1

            yield Document(
                page_content=self.page_delimiter.join(
                    [
                        " ".join([item.text for item in page_item])
                        for page_item in page_items.values()
                    ]
                ),
                metadata=metadata,
            )
        else:
            for page, text_items in page_items.items():
                page_metadata: dict[str, Any] = dict(base_metadata)
                page_metadata["page"] = page

                yield Document(
                    page_content=" ".join(item.text for item in text_items),
                    metadata=page_metadata,
                )

    def _extract_text_from_regions(
        self, blob: Blob, base_metadata: dict[str, Any]
    ) -> Iterator[Document]:
        """Extract text cropped to `page_regions`, yielding one joined `Document` in single mode or one per page."""
        from pdf_inspector import extract_text_in_regions_bytes

        data: bytes = blob.as_bytes()
        assert self.page_regions is not None

        try:
            result: list[PageRegionTexts] = extract_text_in_regions_bytes(
                data, self.page_regions
            )
        except Exception as e:
            raise RuntimeError(
                "Failed to extract text in the requested page regions."
            ) from e

        metadata = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1
            page_texts: list[str] = [
                self.region_delimiter.join(
                    region.text for region in item.regions if region.text
                )
                for item in result
            ]

            yield Document(
                page_content=self.page_delimiter.join(page_texts),
                metadata=metadata,
            )
        else:
            for item in result:
                page_metadata: dict[str, Any] = dict(base_metadata)
                page_metadata["page"] = item.page + 1
                page_text: str = self.region_delimiter.join(
                    [region.text for region in item.regions if region.text]
                )

                yield Document(
                    page_content=page_text,
                    metadata=page_metadata,
                )

    def _extract_markdown(
        self, blob: Blob, base_metadata: dict[str, Any]
    ) -> Iterator[Document]:
        """Extract per-page markdown, yielding one joined `Document` in single mode or one per page with layout flags."""
        from pdf_inspector import extract_pages_markdown_bytes

        data: bytes = blob.as_bytes()

        try:
            result: PagesExtractionResult = extract_pages_markdown_bytes(
                data=data, pages=self.pages
            )
        except Exception as e:
            raise RuntimeError(
                "Failed to extract per-page markdown from the PDF."
            ) from e

        metadata = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1

            yield Document(
                page_content=self.page_delimiter.join(
                    [item.markdown for item in result.pages]
                ),
                metadata=metadata,
            )
        else:
            for item in result.pages:
                page_number = item.page + 1

                needs_ocr: bool = item.needs_ocr or (
                    page_number in result.pages_needing_ocr
                )
                has_tables: bool = page_number in result.pages_with_tables
                has_multicolumn_layout: bool = page_number in result.pages_with_columns

                page_metadata: dict[str, Any] = dict(base_metadata)
                page_metadata.update(
                    {
                        "page": page_number,
                        "needs_ocr": needs_ocr,
                        "has_tables": has_tables,
                        "has_multicolumn_layout": has_multicolumn_layout,
                    }
                )

                yield Document(page_content=item.markdown, metadata=page_metadata)
