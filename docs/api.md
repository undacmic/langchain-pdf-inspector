# API reference

```python
from langchain_pdf_inspector import PdfInspectorLoader, PdfInspectorParser
```

`PdfInspectorLoader` wraps `PdfInspectorParser` with path resolution (local,
HTTP(S), and S3), temporary-file handling, and caller metadata merging.

## `PdfInspectorParser`

A `BaseBlobParser` that turns one `Blob` into `Document` objects.

```python
PdfInspectorParser(
    mode="single",                 # or "page"
    output="text",                 # or "markdown"
    *,
    extract_positions=False,
    extract_regions=False,
    pages=None,
    page_regions=None,
    region_delimiter="\n\n",
    page_delimiter="\n\n",
    ocr_mode="off",                # "off" | "auto" | "force"
    offline=True,
    model_directory=None,
    dpi=150.0,
    minimum_confidence=0.0,
    hosted_recommendation_confidence=0.5,
    password=None,
    include_position_metadata=False,
    include_structure=False,
    include_diagnostics=False,
)
```

Use `parse(blob)` for a list or `lazy_parse(blob)` to stream.

## `PdfInspectorLoader`

A `BasePDFLoader` that forwards the parser options and merges caller metadata.

```python
PdfInspectorLoader(
    file_path,
    headers=None,
    extract_images=False,
    *,
    # every PdfInspectorParser option above, plus:
    metadata=None,
)
```

`load()` / `lazy_load()` yield documents; `aload()` / `alazy_load()` run the
same synchronous work in a thread executor. `extract_images=True` is reserved
and raises `NotImplementedError`.

## Content and page selection

- `mode="single"` emits one document for the whole PDF (or the joined selected
  pages on the positional, region, and OCR paths).
- `mode="page"` emits one document per page. It requires a non-empty `pages`
  list. With `output="text"` it also requires `extract_positions=True` or
  `extract_regions=True`; with `output="markdown"` it emits per-page Markdown
  plus `needs_ocr`, `has_tables`, and `has_multicolumn_layout` flags.
- `pages` inputs are **0-indexed for every mode and extraction path**. All
  emitted `page` values and metadata page lists are **1-indexed**. Negative
  indices raise `ValueError`.
- In single mode `pages` is lenient: it is ignored by paths that do not use it,
  including plain text and single-mode positional extraction.
- Out-of-range pages are omitted rather than emitted empty. The positional
  path deduplicates repeated page indices. The Markdown and OCR page paths
  preserve the requested order and duplicates; OCR single mode joins requested
  pages in that order with `page_delimiter`.
- `extract_positions` and `extract_regions` are mutually exclusive.
  `extract_regions=True` requires `page_regions`. Region options apply to
  `output="text"`; Markdown output ignores them.
- `region_delimiter` joins regions on one page. `page_delimiter` joins pages in
  the joined single-mode positional, region, and OCR outputs.

### Coordinates

- Region rectangles are `(page, [[x0, y0, x1, y1], ...])` in PDF points with a
  **top-left origin** and `y` increasing downward. They are relative to the
  **visible page box** (`CropBox ∩ MediaBox`), not the MediaBox.
- Positioned items use PDF points from the visible box's lower-left corner with
  `y` increasing upward.
- On a predominantly rotated page, upstream re-bases positioned items into a
  turned left-to-right frame and reports it in `page_rotations`
  (`"cw"`/`"ccw"`); the PDF `/Rotate` entry is not applied.
- The positioned-with-rotations upstream API has no page argument, so the
  integration extracts all items and applies `pages` locally in page mode.

## OCR

`ocr_mode="auto"` routes only pages rejected by native extraction;
`"force"` OCRs every selected page. Both require `output="markdown"` and reject
`extract_positions`, `extract_regions`, and `page_regions`.

`offline=True` is the default and prohibits model downloads. Set
`offline=False` only to permit acquisition of the pinned model. The package
ships no PDFium, ONNX Runtime, or OCR model files; provision them with the
upstream [`pdf-inspector` v1.25.2 OCR runtime guide](https://github.com/firecrawl/pdf-inspector/blob/v1.25.2/docs/ocr-runtime.md)
and pass an explicit `model_directory`, or warm the upstream managed cache.
`dpi` must be positive and finite; `minimum_confidence` and
`hosted_recommendation_confidence` must be in `[0, 1]`.

`password` is forwarded to the OCR API. While OCR is enabled, a non-empty
password cannot be combined with `include_structure` or
`include_diagnostics`, because the 1.25.2 detection and structure APIs are not
password-aware. An empty string counts as no password.

## Metadata

Base metadata always includes `source`. When detection succeeds it also adds
`pdf_type`, `total_pages`, and non-empty document information fields (`title`,
`author`, `subject`, `keywords`, `creator`, `producer`, `creation_date`,
`mod_date`). Missing or empty values are omitted.

Opt-in groups are additive, JSON-compatible, and never replace
`page_content`:

### `positions` (`include_position_metadata=True`)

Requires `extract_positions=True` and `output="text"`. Contains every released
`TextItem` field (`text`, `x`, `y`, `width`, `height`, `rotation`,
`advance_known`, `font`, `font_tag`, `font_size`, `page`, `is_bold`,
`is_italic`, `font_weight`, `bold_source`, `fixed_pitch`, `fill_color`,
`stroke_color`, `render_mode`, `is_underline`, `is_strikeout`,
`baseline_shift`, `item_type`, `mcid`) plus `page_rotations`. Colour tuples
become lists. Page mode scopes both lists to the page; single mode retains all
items and their 1-indexed page associations. Empty non-text records are kept.

### `structure` (`include_structure=True`)

Shape: `{"elements": [{"page": 1, "mcid": 0, "role": "H1"}, ...]}`. Roles are
resolved through `/RoleMap`; join to positioned items by `(page, mcid)`.
Untagged PDFs return `{"elements": []}`. Page mode follows the effective
content branch: text region extraction uses the 0-indexed pages in
`page_regions`, while other page-mode paths (including Markdown) use `pages`.
Single mode retains all pages. Structure never rewrites Markdown or reading
order.

### `diagnostics` (`include_diagnostics=True`)

Contains native detection fields (`pdf_type`, `confidence`,
`is_complex_layout`, `pages_needing_ocr`, `ocr_reasons_by_page`,
`pages_with_tables`, `pages_with_columns`, `has_encoding_issues`,
`cmap_gaps`). The non-OCR Markdown path replaces the layout/OCR-routing lists
with the Markdown extraction result's values. With OCR enabled, an `ocr`
subgroup adds result counters/timings and per-page provenance (`source`, model
name/revision, render DPI, confidence, timings, warnings); page Markdown is
omitted because it is the content.

Page mode filters page-number lists, OCR reasons, and `ocr.pages` to the
current page. Scalars and `cmap_gaps` remain document-level. Page-mode OCR
pre-indexes the result so each document gets independent scoped values,
including for repeated pages.

Detection or structure failures are raised when the relevant group is
requested; the default detection fallback remains silent when diagnostics are
not requested.

### Caller precedence

`PdfInspectorLoader` merges `metadata` last on every document. Caller values
override parser-produced keys, including `positions`, `structure`, and
`diagnostics`.

## Errors

- `ValueError` for invalid options and unsupported combinations.
- `ImportError` when `pdf_inspector` is unavailable.
- `RuntimeError` when a requested extraction or metadata group fails; the
  upstream exception is preserved as `__cause__`. OCR failures add offline,
  model-directory, and runtime-library guidance.
