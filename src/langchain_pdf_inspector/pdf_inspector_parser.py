from __future__ import annotations

import copy
import math
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.document_loaders import BaseBlobParser
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

if TYPE_CHECKING:
    from pdf_inspector import (
        FontCMapGaps,
        OcrPageProvenance,
        OcrPageResult,
        OcrPdfResult,
        PageOcrReasons,
        PageRegionTexts,
        PageRotation,
        PagesExtractionResult,
        PdfResult,
        PositionedText,
        StructureElement,
        TextItem,
    )

_OCR_MODES = ("off", "auto", "force")

# Page lists that the native detection diagnostics scopes in page mode. Every
# entry is 1-indexed, matching the upstream contracts.
_DIAGNOSTIC_PAGE_LIST_FIELDS = (
    "pages_needing_ocr",
    "pages_with_tables",
    "pages_with_columns",
)

# Additional 1-indexed page lists carried by the OCR result diagnostics.
_OCR_DIAGNOSTIC_PAGE_LIST_FIELDS = (
    "pages_recommended_for_ocr",
    "pages_routed_to_ocr",
    "pages_recommending_hosted",
)


def _document_info_metadata(result: PdfResult) -> dict[str, str]:
    """Extract non-empty PDF document info fields using the upstream names.

    Returns the `title`, `author`, `subject`, `keywords`, `creator`,
    `producer`, `creation_date`, and `mod_date` entries that are present and
    non-empty. Missing, `None`, and empty values are skipped rather than
    emitted as nulls.
    """
    fields: dict[str, str | None] = {
        "title": result.title,
        "author": result.author,
        "subject": result.subject,
        "keywords": result.keywords,
        "creator": result.creator,
        "producer": result.producer,
        "creation_date": result.creation_date,
        "mod_date": result.mod_date,
    }
    return {key: value for key, value in fields.items() if value}


def _ocr_reasons_metadata(
    reasons: list[PageOcrReasons],
) -> list[dict[str, Any]]:
    """Serialize upstream OCR reasons while retaining their field names."""
    return [
        {"page": reason.page, "reasons": list(reason.reasons)} for reason in reasons
    ]


def _cmap_gaps_metadata(gaps: list[FontCMapGaps]) -> list[dict[str, Any]]:
    """Serialize upstream font CMap gaps as ordinary JSON-compatible values."""
    return [
        {
            "font": gap.font,
            "codes": gap.codes,
            "interpolated": gap.interpolated,
            "unmapped": gap.unmapped,
        }
        for gap in gaps
    ]


def _detection_diagnostics(result: PdfResult) -> dict[str, Any]:
    """Build the native detection diagnostics group from a `PdfResult`.

    Every list of page numbers is 1-indexed, matching `pdf-inspector`.
    """
    return {
        "pdf_type": result.pdf_type,
        "confidence": result.confidence,
        "is_complex_layout": result.is_complex_layout,
        "pages_needing_ocr": list(result.pages_needing_ocr),
        "ocr_reasons_by_page": _ocr_reasons_metadata(result.ocr_reasons_by_page),
        "pages_with_tables": list(result.pages_with_tables),
        "pages_with_columns": list(result.pages_with_columns),
        "has_encoding_issues": result.has_encoding_issues,
        "cmap_gaps": _cmap_gaps_metadata(result.cmap_gaps),
    }


def _text_item_metadata(item: TextItem) -> dict[str, Any]:
    """Serialize one released `TextItem` using its upstream field names.

    Coordinates keep their upstream semantics (PDF points from the visible page
    box's lower-left corner, y growing upward). Colour tuples become JSON lists.
    """
    return {
        "text": item.text,
        "x": item.x,
        "y": item.y,
        "width": item.width,
        "height": item.height,
        "rotation": item.rotation,
        "advance_known": item.advance_known,
        "font": item.font,
        "font_tag": item.font_tag,
        "font_size": item.font_size,
        "page": item.page,
        "is_bold": item.is_bold,
        "is_italic": item.is_italic,
        "font_weight": item.font_weight,
        "bold_source": item.bold_source,
        "fixed_pitch": item.fixed_pitch,
        "fill_color": list(item.fill_color) if item.fill_color is not None else None,
        "stroke_color": list(item.stroke_color)
        if item.stroke_color is not None
        else None,
        "render_mode": item.render_mode,
        "is_underline": item.is_underline,
        "is_strikeout": item.is_strikeout,
        "baseline_shift": item.baseline_shift,
        "item_type": item.item_type,
        "mcid": item.mcid,
    }


def _page_rotations_metadata(
    rotations: list[PageRotation],
) -> list[dict[str, Any]]:
    """Serialize the turned coordinate frames of predominantly rotated pages."""
    return [
        {"page": rotation.page, "rotation": rotation.rotation} for rotation in rotations
    ]


def _structure_element_metadata(element: StructureElement) -> dict[str, Any]:
    """Serialize one tagged-PDF structure reference with upstream names."""
    return {
        "page": element.page,
        "mcid": element.mcid,
        "role": element.role,
    }


def _ocr_provenance_metadata(provenance: OcrPageProvenance) -> dict[str, Any]:
    """Serialize one page's OCR provenance without any result object."""
    model: dict[str, str] | None = None
    if provenance.ocr_model is not None:
        model = {
            "name": provenance.ocr_model.name,
            "revision": provenance.ocr_model.revision,
        }
    return {
        "page_number": provenance.page_number,
        "source": provenance.source,
        "ocr_model": model,
        "render_dpi": provenance.render_dpi,
        "ocr_confidence": provenance.ocr_confidence,
        "timings": {
            "render_ms": provenance.timings.render_ms,
            "ocr_ms": provenance.timings.ocr_ms,
            "assembly_ms": provenance.timings.assembly_ms,
        },
        "warnings": list(provenance.warnings),
        "hosted_recommended": provenance.hosted_recommended,
    }


def _ocr_diagnostics_metadata(result: OcrPdfResult) -> dict[str, Any]:
    """Build the OCR diagnostics subgroup from an `OcrPdfResult`.

    Page Markdown is deliberately omitted: it is the document content, not
    metadata. Per-page provenance keeps the upstream `page_number` association.
    """
    return {
        "page_count": result.page_count,
        "pages_recommended_for_ocr": list(result.pages_recommended_for_ocr),
        "pages_routed_to_ocr": list(result.pages_routed_to_ocr),
        "pages_recommending_hosted": list(result.pages_recommending_hosted),
        "ocr_reasons_by_page": _ocr_reasons_metadata(result.ocr_reasons_by_page),
        "pages_with_tables": list(result.pages_with_tables),
        "pages_with_columns": list(result.pages_with_columns),
        "is_complex": result.is_complex,
        "processing_time_ms": result.processing_time_ms,
        "render_time_ms": result.render_time_ms,
        "ocr_time_ms": result.ocr_time_ms,
        "pages": [
            {
                "page_number": page.page_number,
                "provenance": _ocr_provenance_metadata(page.provenance),
            }
            for page in result.pages
        ],
    }


def _index_page_values(
    values: list[Any], key: str | None = None
) -> dict[int, list[Any]]:
    """Group page-associated values by page, preserving order and duplicates."""
    grouped: dict[int, list[Any]] = {}
    for value in values:
        page = value if key is None else value[key]
        grouped.setdefault(page, []).append(value)
    return grouped


class _PageDiagnosticsIndex:
    """Pre-index diagnostics for repeated page-document emission.

    Diagnostic values are serialized once and page-specific lists are grouped
    once. Scoping a page then copies only that page's entries instead of
    scanning the whole result for every emitted `Document`; every call returns
    independent mutable values, including for repeated pages.
    """

    def __init__(self, diagnostics: dict[str, Any]) -> None:
        self._diagnostics = diagnostics
        self._page_lists = {
            field: _index_page_values(diagnostics[field])
            for field in _DIAGNOSTIC_PAGE_LIST_FIELDS
            if field in diagnostics
        }
        self._reasons = _index_page_values(
            diagnostics.get("ocr_reasons_by_page", []), "page"
        )
        self._ocr: dict[str, Any] = diagnostics["ocr"]
        self._ocr_page_lists: dict[str, dict[int, list[Any]]] = {
            field: _index_page_values(self._ocr[field])
            for field in (
                *_DIAGNOSTIC_PAGE_LIST_FIELDS,
                *_OCR_DIAGNOSTIC_PAGE_LIST_FIELDS,
            )
            if field in self._ocr
        }
        self._ocr_reasons: dict[int, list[Any]] = _index_page_values(
            self._ocr.get("ocr_reasons_by_page", []), "page"
        )
        self._ocr_pages: dict[int, list[Any]] = _index_page_values(
            self._ocr.get("pages", []), "page_number"
        )

    def scoped(self, page: int) -> dict[str, Any]:
        """Return independent page-scoped diagnostics for `page`."""
        scoped: dict[str, Any] = {}
        for field, value in self._diagnostics.items():
            if field in self._page_lists:
                scoped[field] = list(self._page_lists[field].get(page, ()))
            elif field == "ocr_reasons_by_page":
                scoped[field] = copy.deepcopy(self._reasons.get(page, []))
            elif field == "ocr":
                scoped[field] = self._scoped_ocr(page)
            else:
                scoped[field] = copy.deepcopy(value)
        return scoped

    def _scoped_ocr(self, page: int) -> dict[str, Any]:
        """Return independent page-scoped OCR diagnostics for `page`."""
        scoped: dict[str, Any] = {}
        for field, value in self._ocr.items():
            if field in self._ocr_page_lists:
                scoped[field] = list(self._ocr_page_lists[field].get(page, ()))
            elif field == "ocr_reasons_by_page":
                scoped[field] = copy.deepcopy(self._ocr_reasons.get(page, []))
            elif field == "pages":
                scoped[field] = copy.deepcopy(self._ocr_pages.get(page, []))
            else:
                scoped[field] = copy.deepcopy(value)
        return scoped


def _scope_diagnostics_metadata(
    diagnostics: dict[str, Any], page: int
) -> dict[str, Any]:
    """Return a copy of `diagnostics` scoped to one 1-indexed page.

    Page-number lists and detection OCR reason entries are filtered to `page`;
    scalar document-wide fields and `cmap_gaps` (which upstream does not
    associate with pages) are retained as document-level context.
    """
    scoped: dict[str, Any] = dict(diagnostics)
    for field in _DIAGNOSTIC_PAGE_LIST_FIELDS:
        scoped[field] = [value for value in scoped[field] if value == page]
    scoped["ocr_reasons_by_page"] = [
        reason
        for reason in scoped.get("ocr_reasons_by_page", [])
        if reason["page"] == page
    ]
    return scoped


def _markdown_diagnostics(
    base_metadata: dict[str, Any], result: PagesExtractionResult
) -> dict[str, Any]:
    """Merge per-page Markdown layout diagnostics over detection diagnostics.

    Detection exposes the document fields but does not populate the layout
    lists; the Markdown extraction result is the verified source for table,
    column, and OCR-routing flags. Keeping the detection fields preserves the
    encoding/CMap diagnostics.
    """
    diagnostics: dict[str, Any] = dict(base_metadata.get("diagnostics", {}))
    diagnostics.update(
        {
            "pages_with_tables": list(result.pages_with_tables),
            "pages_with_columns": list(result.pages_with_columns),
            "pages_needing_ocr": list(result.pages_needing_ocr),
            "ocr_reasons_by_page": _ocr_reasons_metadata(result.ocr_reasons_by_page),
            "is_complex_layout": result.is_complex,
        }
    )
    return diagnostics


def _build_page_metadata(
    base_metadata: dict[str, Any],
    page: int,
    *,
    include_diagnostics: bool,
) -> dict[str, Any]:
    """Build page-mode metadata, optionally scoped diagnostics included."""
    metadata: dict[str, Any] = dict(base_metadata)
    metadata["page"] = page
    if include_diagnostics and "diagnostics" in metadata:
        metadata["diagnostics"] = _scope_diagnostics_metadata(
            metadata["diagnostics"], page
        )
    return metadata


def _build_base_metadata(
    blob: Blob, *, include_diagnostics: bool = False
) -> dict[str, Any]:
    """Build the base metadata shared by every generated `Document`.

    Always includes `source`, and attaches `pdf_type` and `total_pages` from
    `detect_pdf_bytes` when detection succeeds. When detection succeeds, the
    PDF's own document info fields are merged in via `_document_info_metadata`.

    Detection failures keep the historical silent fallback unless
    `include_diagnostics=True` is requested: opt-in diagnostics must not vanish
    silently, so the failure is then raised with its original cause.
    """

    metadata: dict[str, Any] = {"source": blob.source}
    data: bytes = blob.as_bytes()

    from pdf_inspector import detect_pdf_bytes

    try:
        result: PdfResult = detect_pdf_bytes(data=data)
    except Exception as e:
        if include_diagnostics:
            raise RuntimeError(
                "Failed to extract PDF detection diagnostics from the PDF."
            ) from e
        # Keep the historical base-metadata fallback when diagnostics were not
        # requested.
        return metadata

    if result.pdf_type is not None:
        metadata["pdf_type"] = result.pdf_type
    if result.page_count is not None:
        metadata["total_pages"] = result.page_count

    metadata.update(_document_info_metadata(result))

    if include_diagnostics:
        metadata["diagnostics"] = _detection_diagnostics(result)

    return metadata


class PdfInspectorParser(BaseBlobParser):
    """Parse PDFs into LangChain `Document` objects using `pdf-inspector`.

    Two extraction modes are available, selected by `mode`:

    - `"single"` (default): yields one `Document` for the whole PDF. Within
      this mode the content is produced by the first matching option in
      priority order (see `lazy_parse`): OCR markdown when `ocr_mode` is
      `"auto"` or `"force"` (one joined `Document` whose selected pages are
      joined with `page_delimiter`), region-cropped text when
      `extract_regions` is set (one joined `Document`), positional text when
      `extract_positions` is set (one joined `Document` whose pages are joined
      with `page_delimiter`), full markdown when `output` is `"markdown"`,
      otherwise plain text.
    - `"page"`: yields one `Document` per page. `pages` is **required** (a
      non-empty list of 0-indexed pages) and the content branches on `output`:
      `"text"` emits each page's plain text (the page's items joined with a
      space; pages with no non-empty text are skipped), `"markdown"` emits
      each page's markdown with the per-page layout flags, and OCR markdown
      emits one `Document` per requested page. `output` defaults to `"text"`,
      so page mode yields per-page plain text unless `output="markdown"` is
      requested; OCR requires `output="markdown"`.

    `extract_positions` and `extract_regions` are mutually exclusive, and
    `extract_regions=True` requires `page_regions`. `pages` is required in
    `"page"` mode; in `"single"` mode `pages` and `page_regions` are lenient:
    when they do not apply to the chosen extraction path they are silently
    ignored rather than raising. Inputs (`pages`/`page_regions`) are 0-indexed
    and negative `pages` entries raise `ValueError`; all output `page` metadata
    is 1-indexed. The same 0-indexed `pages` selection therefore addresses the
    same logical pages in the positional-text and markdown paths. See
    `__init__` for the full `pages` contract and the OCR-specific
    order/duplicate rules.

    Region coordinates (`page_regions`) are `[x0, y0, x1, y1]` rectangles in
    PDF points with a **top-left origin** and `y` increasing downward, measured
    relative to the **visible page box**: the intersection of the page's
    CropBox and MediaBox. They are *not* relative to the MediaBox. The two are
    identical when the CropBox starts at `(0, 0)`, but differ on cropped pages;
    on those, use coordinates from the top-left of the visible (cropped) area.

    OCR is opt-in and offline-first: `ocr_mode` defaults to `"off"`, and OCR
    (including `"auto"`) requires `output="markdown"`, rejects positional and
    region extraction, and never downloads a model unless `offline=False`
    is passed explicitly. `model_directory` points at a provisioned model;
    `dpi`, `minimum_confidence`,
    `hosted_recommendation_confidence`, and `password` forward the
    released `pdf-inspector` tuning options. A non-empty `password` cannot be
    combined with `include_structure` or `include_diagnostics` while OCR is
    enabled: `pdf-inspector` 1.25.2's detection and structure APIs are not
    password-aware, so that combination is rejected at construction time. Use
    OCR without those groups or decrypt the PDF separately first.

    Rich metadata is also opt-in. `include_position_metadata` enriches
    positional-text documents with a JSON-compatible `positions` group
    containing the released `TextItem` fields and the turned-page frames;
    `include_structure` adds a `structure` group of tagged-PDF
    `page`/`mcid`/`role` references; and `include_diagnostics` adds a
    `diagnostics` group with native detection and, for OCR, provenance data.
    These groups never replace or rewrite `page_content`, and caller metadata
    still wins on conflicts through the loader. Position coordinates keep
    upstream semantics: PDF points from the visible page box's lower-left
    corner with `y` growing upward; on a predominantly rotated page the items
    are in upstream's turned frame and `positions["page_rotations"]` names it.
    Structure metadata never rewrites headings, Markdown, or reading order.

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

            parser = PdfInspectorParser(
                mode="page", pages=[0, 1, 2], output="markdown"
            )

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
        ocr_mode: Literal["off", "auto", "force"] = "off",
        offline: bool = True,
        model_directory: str | None = None,
        dpi: float = 150.0,
        minimum_confidence: float = 0.0,
        hosted_recommendation_confidence: float = 0.5,
        password: str | None = None,
        include_position_metadata: bool = False,
        include_structure: bool = False,
        include_diagnostics: bool = False,
    ) -> None:
        """Initialize the parser.

        Args:
            mode: `"single"` for a single whole-PDF `Document` or `"page"` for
                one `Document` per page. Defaults to `"single"`.
            output: `"text"` or `"markdown"` for the content produced. In
                `"single"` mode this selects plain text vs. markdown. In
                `"page"` mode it selects per-page plain text (items joined with
                spaces) vs. per-page markdown with layout flags
                (`"markdown"`). Defaults to `"text"`.
            extract_positions: When `True` in `"single"` mode, extract
                positional text and emit one joined `Document` whose pages are
                joined with `page_delimiter`. In `"page"` mode with
                `output="text"` the same positional-text path is used per page
                (one `Document` per page; positions metadata is added only when
                `include_position_metadata=True`).
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
                extraction). **Negative indices raise `ValueError`.** This is
                the authoritative `pages` contract; the class docstring, the
                loader, and the README summarize it rather than restating it.
                Out-of-range indices are not validated: the positional-text
                path silently omits them, and the markdown path skips them when
                the detected page count is available (so no empty `Document` is
                emitted for a nonexistent page). Duplicate indices are collapsed
                to one `Document` per page by the positional-text path, while
                the markdown path emits one `Document` per occurrence in the
                requested order.
            page_regions: Per-page regions to crop, required when
                `extract_regions=True`. Each entry is `(page, [[x0, y0, x1,
                y1], ...])`. Coordinates are in PDF points with a top-left
                origin and `y` increasing downward, relative to the visible
                page box (CropBox intersected with MediaBox), **not** the
                MediaBox. Lenient: silently ignored unless `extract_regions`
                is active.
            region_delimiter: String used to join the extracted region texts
                (both the joined single-mode regions and the page-mode
                regions). Defaults to `"\\n\\n"`.
            page_delimiter: String used to join pages together in the
                `"single"` mode positional-text and OCR paths, where all
                selected pages collapse into a single `Document`. Defaults to
                `"\\n\\n"`.
            ocr_mode: `"off"` (default) keeps the existing extraction paths
                untouched. `"auto"` runs native extraction and routes only
                pages that need OCR, while `"force"` OCRs every selected page.
                Both enabled modes require `output="markdown"` and reject
                `extract_positions`/`extract_regions`/`page_regions`.
            offline: When `True` (the default), prohibit OCR model
                downloads. Pass `False` explicitly to permit downloading the
                pinned model; `model_directory` avoids the download by
                pointing at an already-provisioned model.
            model_directory: Optional directory containing the provisioned
                OCR model. Forwarded to `pdf-inspector`.
            dpi: OCR render DPI, forwarded to `pdf-inspector`. Defaults to
                `150.0`.
            minimum_confidence: Minimum OCR confidence in `[0, 1]`,
                forwarded to `pdf-inspector`. Defaults to `0.0`.
            hosted_recommendation_confidence: Confidence threshold in
                `[0, 1]` for upstream hosted-OCR recommendations, forwarded to
                `pdf-inspector`. Defaults to `0.5`.
            password: Optional PDF password, forwarded to the OCR API. It is
                supported on its own; when `ocr_mode` is enabled, a non-empty
                password cannot be combined with `include_structure` or
                `include_diagnostics` because `pdf-inspector` 1.25.2's
                detection and structure APIs are not password-aware. Use OCR
                without those groups, or decrypt the PDF separately first. An
                empty string is treated as no password and is not rejected.
            include_position_metadata: When `True`, requires
                `extract_positions=True` and `output="text"`, and adds a
                JSON-compatible `positions` metadata group containing every
                released `TextItem` field plus `page_rotations`. In page mode
                each group is scoped to that page; single mode keeps each
                item's 1-indexed `page` association. Defaults to `False`.
            include_structure: When `True`, adds a JSON-compatible `structure`
                metadata group with tagged-PDF `page`/`mcid`/`role`
                references. In page mode it is scoped to the page and follows
                the effective content branch: text region extraction uses the
                0-indexed pages in `page_regions`, while other page-mode paths
                use `pages` (including `output="markdown"`, where regions are
                not used). Single mode retains all pages. Untagged PDFs yield
                an empty `elements` list. It does not rewrite Markdown,
                headings, or reading order. Defaults to `False`.
            include_diagnostics: When `True`, adds a JSON-compatible
                `diagnostics` group with native detection fields
                (`confidence`, `pages_needing_ocr`, `ocr_reasons_by_page`,
                `pages_with_tables`, `pages_with_columns`,
                `has_encoding_issues`, `cmap_gaps`, ...) and, when OCR is
                enabled, an `ocr` subgroup with per-page provenance and timing
                fields. Page-number lists and OCR provenance are scoped to the
                current page in page mode; single mode retains all
                associations. Detection/structure failures are raised rather
                than silently omitted. Defaults to `False`.

        Returns:
            None. Use the `parse` or `lazy_parse` methods to retrieve parsed
            documents with content and metadata.

        Raises:
            ValueError: If `mode`/`output` are invalid, if `mode="page"` is set
                without a non-empty `pages` list, if `pages` contains a
                negative index, if `extract_positions` and `extract_regions`
                are both `True`, if `extract_regions=True` is set without
                `page_regions`, if an OCR option is invalid, if OCR is enabled
                without `output="markdown"`, if OCR is combined with
                positional/region extraction, if an enabled-OCR non-empty
                password is combined with `include_structure` or
                `include_diagnostics`, or if
                `include_position_metadata=True` is not paired with
                `extract_positions=True` and `output="text"`.
        """
        super().__init__()

        if mode not in ("single", "page"):
            raise ValueError("mode must be either 'single' or 'page'")
        if output not in ("text", "markdown"):
            raise ValueError("output must be either 'text' or 'markdown'")
        if mode == "page" and not pages:
            raise ValueError("pages is required when mode='page'")
        if pages is not None and any(page < 0 for page in pages):
            raise ValueError(
                "pages must contain only non-negative 0-indexed page numbers"
            )
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
        if ocr_mode not in _OCR_MODES:
            raise ValueError("ocr_mode must be either 'off', 'auto', or 'force'")
        if not isinstance(offline, bool):
            raise ValueError("offline must be a bool")  # noqa: TRY004
        if model_directory is not None and not isinstance(model_directory, str):
            raise ValueError("model_directory must be a string or None")
        if (
            not isinstance(dpi, (int, float))
            or isinstance(dpi, bool)
            or not math.isfinite(float(dpi))
            or dpi <= 0
        ):
            raise ValueError("dpi must be a positive finite number")
        for name, value in (
            ("minimum_confidence", minimum_confidence),
            (
                "hosted_recommendation_confidence",
                hosted_recommendation_confidence,
            ),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"{name} must be a number between 0 and 1")
        if password is not None and not isinstance(password, str):
            raise ValueError("password must be a string or None")
        if ocr_mode != "off":
            if password not in (None, "") and (
                include_structure or include_diagnostics
            ):
                raise ValueError(
                    "password is not supported together with include_structure or "
                    "include_diagnostics when ocr_mode is enabled: pdf-inspector "
                    "1.25.2's detect_pdf_bytes and "
                    "extract_structure_elements_bytes APIs are not password-aware. "
                    "Run OCR without those metadata groups, or decrypt the PDF "
                    "separately before extraction."
                )
            if output != "markdown":
                raise ValueError(
                    "ocr_mode='auto' or 'force' requires output='markdown'"
                )
            if extract_positions or extract_regions:
                raise ValueError(
                    "OCR extraction does not support extract_positions or "
                    "extract_regions"
                )
            if page_regions is not None:
                raise ValueError("OCR extraction does not support page_regions")
        if include_position_metadata:
            if not extract_positions:
                raise ValueError(
                    "include_position_metadata=True requires extract_positions=True"
                )
            if output != "text":
                raise ValueError(
                    "include_position_metadata=True requires output='text'"
                )

        self.extract_plain = (extract_regions or extract_positions) is False

        if (
            mode == "page"
            and output == "text"
            and self.extract_plain
            and ocr_mode == "off"
        ):
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
        self.ocr_mode = ocr_mode
        self.offline = offline
        self.model_directory = model_directory
        self.dpi = float(dpi)
        self.minimum_confidence = float(minimum_confidence)
        self.hosted_recommendation_confidence = float(hosted_recommendation_confidence)
        self.password = password
        self.include_position_metadata = include_position_metadata
        self.include_structure = include_structure
        self.include_diagnostics = include_diagnostics

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        """Parse `blob` and lazily yield the resulting `Document` objects.

        Dispatches to the matching extraction path based on
        `ocr_mode`/`output`/`extract_positions`/`extract_regions`: OCR
        markdown, plain text, positional text, region-cropped text or
        per-page markdown (see `__init__`). Every yielded `Document` carries
        the base detection metadata (`source`, `pdf_type`, `total_pages`, plus
        any PDF document info fields such as `title` and `author`) built by
        `_build_base_metadata`.

        Yields:
            `Document` objects with the extracted content and metadata.

        Raises:
            ImportError: If the `pdf_inspector` package is not installed.
            RuntimeError: If a requested extraction or opt-in metadata group
                fails, including missing OCR runtime/model errors. The original
                exception is preserved as the cause.
        """
        try:
            import pdf_inspector  # noqa: F401 - availability check
        except ImportError as e:
            raise ImportError(
                "`pdf_inspector` package not found, please install it with "
                "`pip install pdf-inspector`"
            ) from e

        base_metadata: dict[str, Any] = _build_base_metadata(
            blob, include_diagnostics=self.include_diagnostics
        )
        structure_elements = (
            self._extract_structure_elements(blob) if self.include_structure else None
        )

        if self.ocr_mode != "off":
            yield from self._extract_ocr(blob, base_metadata, structure_elements)
        elif self.output == "text" and self.extract_regions:
            yield from self._extract_text_from_regions(
                blob, base_metadata, structure_elements
            )
        elif self.output == "text" and self.extract_positions:
            yield from self._extract_text_with_positions(
                blob, base_metadata, structure_elements
            )
        elif self.output == "text" and self.extract_plain:
            yield from self._extract_plain_text(blob, base_metadata, structure_elements)
        else:
            yield from self._extract_markdown(blob, base_metadata, structure_elements)

    def parse(self, blob: Blob) -> list[Document]:
        """Parse `blob` and return the resulting `Document` objects as a list."""
        return list(self.lazy_parse(blob))

    def _add_structure_metadata(
        self,
        metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
        page: int | None = None,
    ) -> None:
        """Attach the opt-in `structure` group, scoped to `page` in page mode."""
        if structure_elements is None:
            return
        elements = (
            structure_elements
            if page is None
            else [element for element in structure_elements if element["page"] == page]
        )
        metadata["structure"] = {"elements": elements}

    def _add_position_metadata(
        self,
        metadata: dict[str, Any],
        items: list[TextItem],
        rotations: list[PageRotation],
    ) -> None:
        """Attach the opt-in JSON-compatible `positions` group."""
        metadata["positions"] = {
            "items": [_text_item_metadata(item) for item in items],
            "page_rotations": _page_rotations_metadata(rotations),
        }

    def _extract_plain_text(
        self,
        blob: Blob,
        base_metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
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
        self._add_structure_metadata(metadata, structure_elements)

        yield Document(page_content=result, metadata=metadata)

    def _extract_text_with_positions(
        self,
        blob: Blob,
        base_metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
    ) -> Iterator[Document]:
        """Extract positional text, yielding one joined `Document` in single mode or one per page.

        Content keeps only non-empty text and skips pages without any. Opt-in
        ``positions`` metadata serializes every selected upstream item,
        including empty non-text records.
        """
        from pdf_inspector import extract_text_with_positions_bytes

        data: bytes = blob.as_bytes()
        # The public ``pages`` contract is 0-indexed, but upstream's
        # ``extract_text_with_positions_bytes`` expects 1-indexed page numbers.
        pages: list[int] | None = (
            [page + 1 for page in self.pages]
            if self.mode == "page" and self.pages is not None
            else None
        )

        rotations: list[PageRotation] = []
        if self.include_position_metadata:
            # Upstream exposes page rotation frames only on this variant, which
            # (verified on 1.25.2) has no `pages` argument. Extract everything
            # and apply the same 0-indexed selection locally in page mode.
            from pdf_inspector import (
                extract_text_with_positions_and_rotations_bytes,
            )

            try:
                positioned: PositionedText = (
                    extract_text_with_positions_and_rotations_bytes(data=data)
                )
            except Exception as e:
                raise RuntimeError(
                    "Failed to extract text with positions from the PDF."
                ) from e
            result = list(positioned.items)
            rotations = list(positioned.page_rotations)
            if self.mode == "page" and self.pages is not None:
                selected_pages = {page + 1 for page in self.pages}
                result = [item for item in result if item.page in selected_pages]
                rotations = [
                    rotation
                    for rotation in rotations
                    if rotation.page in selected_pages
                ]
        else:
            try:
                result = extract_text_with_positions_bytes(data=data, pages=pages)
            except Exception as e:
                raise RuntimeError(
                    "Failed to extract text with positions from the PDF."
                ) from e

        page_items: dict[int, list[TextItem]] = {}
        page_records: dict[int, list[TextItem]] = {}
        for item in result:
            page_records.setdefault(item.page, []).append(item)
            if not item.text:
                continue
            page_items.setdefault(item.page, []).append(item)

        metadata: dict[str, Any] = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1
            self._add_structure_metadata(metadata, structure_elements)
            if self.include_position_metadata:
                self._add_position_metadata(metadata, result, rotations)

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
                page_metadata: dict[str, Any] = _build_page_metadata(
                    base_metadata,
                    page,
                    include_diagnostics=self.include_diagnostics,
                )
                self._add_structure_metadata(page_metadata, structure_elements, page)
                if self.include_position_metadata:
                    self._add_position_metadata(
                        page_metadata,
                        page_records[page],
                        [rotation for rotation in rotations if rotation.page == page],
                    )

                yield Document(
                    page_content=" ".join(item.text for item in text_items),
                    metadata=page_metadata,
                )

    def _extract_text_from_regions(
        self,
        blob: Blob,
        base_metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
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

        metadata: dict[str, Any] = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1
            self._add_structure_metadata(metadata, structure_elements)
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
                page_number = item.page + 1
                page_metadata: dict[str, Any] = _build_page_metadata(
                    base_metadata,
                    page_number,
                    include_diagnostics=self.include_diagnostics,
                )
                self._add_structure_metadata(
                    page_metadata, structure_elements, page_number
                )
                page_text: str = self.region_delimiter.join(
                    [region.text for region in item.regions if region.text]
                )

                yield Document(
                    page_content=page_text,
                    metadata=page_metadata,
                )

    def _extract_markdown(
        self,
        blob: Blob,
        base_metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
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

        metadata: dict[str, Any] = dict(base_metadata)
        if self.mode == "single":
            metadata["page"] = 1
            self._add_structure_metadata(metadata, structure_elements)
            if self.include_diagnostics:
                metadata["diagnostics"] = _markdown_diagnostics(base_metadata, result)

            yield Document(
                page_content=self.page_delimiter.join(
                    [item.markdown for item in result.pages]
                ),
                metadata=metadata,
            )
        else:
            diagnostics = (
                _markdown_diagnostics(base_metadata, result)
                if self.include_diagnostics
                else None
            )
            total_pages: int | None = base_metadata.get("total_pages")
            for item in result.pages:
                page_number = item.page + 1
                # Upstream returns an empty entry for an out-of-range request;
                # skip it so both extraction paths omit nonexistent pages.
                if total_pages is not None and page_number > total_pages:
                    continue

                needs_ocr: bool = item.needs_ocr or (
                    page_number in result.pages_needing_ocr
                )
                has_tables: bool = page_number in result.pages_with_tables
                has_multicolumn_layout: bool = page_number in result.pages_with_columns

                page_metadata: dict[str, Any] = _build_page_metadata(
                    base_metadata,
                    page_number,
                    include_diagnostics=False,
                )
                if diagnostics is not None:
                    page_metadata["diagnostics"] = _scope_diagnostics_metadata(
                        diagnostics, page_number
                    )
                page_metadata.update(
                    {
                        "needs_ocr": needs_ocr,
                        "has_tables": has_tables,
                        "has_multicolumn_layout": has_multicolumn_layout,
                    }
                )
                self._add_structure_metadata(
                    page_metadata, structure_elements, page_number
                )

                yield Document(page_content=item.markdown, metadata=page_metadata)

    def _ocr_page_numbers(self, base_metadata: dict[str, Any]) -> list[int] | None:
        """Translate the 0-indexed `pages` selection to upstream's 1-indexed form.

        Out-of-range pages are dropped when detection supplied `total_pages` so
        OCR keeps the existing "omit nonexistent pages" behavior. Duplicates
        are removed before the upstream call; the requested order and
        duplicates are then restored locally by `_ordered_ocr_pages`.
        """
        if self.pages is None:
            return None
        total_pages = base_metadata.get("total_pages")
        numbers: list[int] = []
        for page in self.pages:
            number = page + 1
            if isinstance(total_pages, int) and number > total_pages:
                continue
            if number not in numbers:
                numbers.append(number)
        return sorted(numbers)

    def _ordered_ocr_pages(
        self, result: OcrPdfResult, base_metadata: dict[str, Any]
    ) -> list[tuple[int, OcrPageResult]]:
        """Return OCR page results in the requested 0-indexed order/duplicates.

        With no `pages` selection the upstream document order is retained. When
        `pages` is supplied, page mode and single mode both follow the caller's
        requested order, including repeated entries; pages upstream did not
        return (for example, out-of-range ones) are omitted.
        """
        by_page = {page.page_number: page for page in result.pages}
        if self.pages is None:
            return [(page.page_number, page) for page in result.pages]
        total_pages = base_metadata.get("total_pages")
        ordered: list[tuple[int, OcrPageResult]] = []
        for page in self.pages:
            number = page + 1
            if isinstance(total_pages, int) and number > total_pages:
                continue
            page_result = by_page.get(number)
            if page_result is not None:
                ordered.append((number, page_result))
        return ordered

    def _ocr_error_message(self, error: Exception) -> str:
        """Build an actionable OCR failure message while preserving the cause."""
        if self.offline:
            model_hint = (
                "OCR runs offline by default (offline=True). Provision the "
                "pinned OCR model with model_directory, or pass "
                "offline=False to explicitly allow the download."
            )
        else:
            model_hint = (
                "OCR model downloads are permitted (offline=False); check "
                "network access and the model cache, or provision "
                "model_directory."
            )
        runtime_hint = (
            "If the OCR runtime is missing, install compatible PDFium and ONNX "
            "Runtime shared libraries and set PDFIUM_LIB_PATH and ORT_DYLIB_PATH."
        )
        return (
            "Failed to extract OCR markdown from the PDF. "
            f"{model_hint} {runtime_hint} Underlying error: {error}"
        )

    def _extract_ocr(
        self,
        blob: Blob,
        base_metadata: dict[str, Any],
        structure_elements: list[dict[str, Any]] | None,
    ) -> Iterator[Document]:
        """Extract OCR Markdown through the released selective-OCR API.

        Page mode preserves the caller's requested order and duplicates (the
        upstream call normalizes both); single mode joins the selected page
        Markdown with `page_delimiter`. All page metadata remains 1-indexed.
        """
        from pdf_inspector import process_pdf_with_ocr_bytes

        data: bytes = blob.as_bytes()
        page_numbers = self._ocr_page_numbers(base_metadata)

        try:
            result: OcrPdfResult = process_pdf_with_ocr_bytes(
                data,
                mode=self.ocr_mode,
                page_numbers=page_numbers,
                password=self.password,
                dpi=self.dpi,
                minimum_confidence=self.minimum_confidence,
                hosted_recommendation_confidence=(
                    self.hosted_recommendation_confidence
                ),
                model_directory=self.model_directory,
                offline=self.offline,
            )
        except Exception as e:
            raise RuntimeError(self._ocr_error_message(e)) from e

        ordered_pages = self._ordered_ocr_pages(result, base_metadata)

        diagnostics: dict[str, Any] | None = None
        page_diagnostics: _PageDiagnosticsIndex | None = None
        if self.include_diagnostics:
            diagnostics = dict(base_metadata.get("diagnostics", {}))
            diagnostics["ocr"] = _ocr_diagnostics_metadata(result)
            if self.mode == "page":
                page_diagnostics = _PageDiagnosticsIndex(diagnostics)

        if self.mode == "single":
            metadata: dict[str, Any] = dict(base_metadata)
            metadata["page"] = 1
            self._add_structure_metadata(metadata, structure_elements)
            if diagnostics is not None:
                metadata["diagnostics"] = diagnostics

            yield Document(
                page_content=self.page_delimiter.join(
                    [page_result.markdown for _, page_result in ordered_pages]
                ),
                metadata=metadata,
            )
            return

        for page_number, page_result in ordered_pages:
            page_metadata: dict[str, Any] = _build_page_metadata(
                base_metadata,
                page_number,
                include_diagnostics=False,
            )
            self._add_structure_metadata(page_metadata, structure_elements, page_number)
            if page_diagnostics is not None:
                page_metadata["diagnostics"] = page_diagnostics.scoped(page_number)

            yield Document(
                page_content=page_result.markdown,
                metadata=page_metadata,
            )

    def _extract_structure_elements(self, blob: Blob) -> list[dict[str, Any]]:
        """Extract opt-in tagged-PDF `(page, mcid, role)` associations.

        The upstream bytes API takes 1-indexed pages. Single mode keeps its
        existing lenient behavior and extracts all pages. In page mode the
        selected pages follow the effective content branch: the 0-indexed
        pages in `page_regions` for text region extraction, otherwise
        `pages` (including Markdown output, where regions are not used).
        Untagged PDFs return an empty list. Failures are raised rather than
        silently omitted.
        """
        from pdf_inspector import extract_structure_elements_bytes

        data: bytes = blob.as_bytes()
        pages: list[int] | None = None
        if self.mode == "page":
            if self.output == "text" and self.extract_regions:
                assert self.page_regions is not None
                pages = sorted({page + 1 for page, _ in self.page_regions})
            else:
                # Page mode requires a non-empty ``pages`` list at construction.
                assert self.pages is not None
                pages = sorted({page + 1 for page in self.pages})

        try:
            elements = extract_structure_elements_bytes(data=data, pages=pages)
        except Exception as e:
            raise RuntimeError(
                "Failed to extract tagged-PDF structure metadata from the PDF."
            ) from e

        return [_structure_element_metadata(element) for element in elements]
