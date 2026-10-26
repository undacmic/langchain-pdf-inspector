# pdf-inspector API expansion: audit and integration contract

Status: implemented on top of base `a077269b24594c52a944c1bcd4b06133d4766ec9`.

This document is the audit of the **released** `pdf-inspector` 1.25.2
artifacts and the integration contract implemented by
`PdfInspectorParser`/`PdfInspectorLoader`. Upstream `main` was not used as
evidence. The dependency floor stays at `pdf-inspector>=1.25.2,<2`; no released
capability required a version bump.

## Verification environment

- Resolved/installed distribution: `pdf-inspector==1.25.2` (wheel).
- Python used for verification: CPython 3.14.2 locally; CI is Python 3.12.
- Stub inspected:
  `.venv/lib/python3.14/site-packages/pdf_inspector/__init__.pyi`.
- Runtime signatures were checked with `inspect.signature` against the
  installed C extension, not inferred from documentation.
- `uv sync --group dev --locked` completed and installed the exact locked
  version.

The upstream documentation page
(<https://github.com/firecrawl/pdf-inspector/blob/main/docs/python.md>) was
used only as a discovery source. Every signature and result field below was
confirmed against the 1.25.2 wheel/stub.

## Verified released signatures and page contracts

### OCR

```python
process_pdf_with_ocr_bytes(
    data: bytes,
    *,
    mode: Literal["off", "auto", "force"] = "auto",
    page_numbers: list[int] | None = None,
    password: str | None = None,
    dpi: float = 150.0,
    minimum_confidence: float = 0.0,
    hosted_recommendation_confidence: float = 0.5,
    model_directory: str | None = None,
    offline: bool = False,
) -> OcrPdfResult
```

- `page_numbers` is **1-indexed**.
- `mode="off"` still returns the OCR result/provenance contract but does no
  external OCR work. `mode="auto"` routes only pages rejected by native
  extraction; `mode="force"` OCRs every selected page.
- The wheel embeds no PDFium, ONNX Runtime, or OCR model. A routed page needs
  compatible shared libraries and either a warm model cache,
  `model_directory`, or network access with `offline=False`.
- Verified upstream behavior when `page_numbers=[2, 1, 2]`: the result pages
  are returned in document order and deduplicated (`[1, 2]`). Our new OCR path
  defines and tests its own contract instead: page mode follows the caller's
  requested order and preserves duplicates; single mode joins the requested
  pages with `page_delimiter`. Out-of-range pages are dropped using the
  detected page count, matching the existing page-mode "omit nonexistent page"
  behavior.
- `OcrPdfResult`: `markdown`, `pages`, `page_count`,
  `pages_recommended_for_ocr`, `pages_routed_to_ocr`,
  `pages_recommending_hosted`, `ocr_reasons_by_page`, `pages_with_tables`,
  `pages_with_columns`, `is_complex`, `processing_time_ms`, `render_time_ms`,
  `ocr_time_ms`.
- `OcrPageResult`: `page_number` (1-indexed), `markdown`, `provenance`.
- `OcrPageProvenance`: `page_number`, `source`
  (`"native"`/`"ocr"`/`"fused"`), `ocr_model`
  (`name`/`revision` or `None`), `render_dpi`, `ocr_confidence`,
  `timings` (`render_ms`, `ocr_ms`, `assembly_ms`), `warnings`,
  `hosted_recommended`.
- Missing PDFium raises an actionable `ValueError` such as
  `failed to load PDFium; install a compatible PDFium shared library or set
  PDFIUM_LIB_PATH to its path`. Model provisioning failures likewise arrive as
  upstream exceptions; the integration wraps both in a `RuntimeError` with the
  original exception as `__cause__` and adds offline/model-directory/runtime
  instructions.
- The OCR bytes API accepts `password`, but the released `detect_pdf_bytes`
  and `extract_structure_elements_bytes` APIs do not. With OCR enabled, a
  non-empty password combined with `include_structure`/`include_diagnostics`
  is rejected at construction time; empty `password=""` is harmless.
- Runtime/model provisioning was verified against the `v1.25.2` tag, not
  unreleased `main`: `docs/ocr-runtime.md` pins Firecrawl PDFium
  `native-v7988` (PDFium `153.0.7988.0`), ONNX Runtime `1.27.0`, and PP-OCRv6
  Small artifact revision `oar-ocr-v0.7.0`. `src/vision/models.rs` defines
  manifest id `pp-ocrv6-small` with exactly three SHA-256-verified artifacts:
  `pp-ocrv6_small_det.onnx`, `pp-ocrv6_small_rec.onnx`, and
  `ppocrv6_dict.txt` (about 31 MB total). The managed cache root is
  `PDF_INSPECTOR_MODEL_CACHE` when set/non-empty, otherwise the platform cache
  directory plus `pdf-inspector/models`; the effective directory appends
  `pp-ocrv6-small/oar-ocr-v0.7.0`. An explicit `model_directory` is used
  verbatim as the directory containing the three files and is never mutated or
  supplemented from the network. `offline=True` prohibits downloads and is the
  integration default; only an explicit `offline=False` permits acquisition.
- The README provisioning section is documentation, not executed setup: no
  PDFium/ONNX Runtime installation or model download was performed here.

### Positioned text and rotation frames

```python
extract_text_with_positions_bytes(
    data: bytes,
    pages: list[int] | None = None,
    bold_from_weight: bool = False,
    bold_weight_threshold: int = 600,
) -> list[TextItem]

extract_text_with_positions_and_rotations_bytes(
    data: bytes,
    bold_from_weight: bool = False,
    bold_weight_threshold: int = 600,
) -> PositionedText
```

- `pages` on `extract_text_with_positions_bytes` is **1-indexed** and is used
  by the existing positional path. This did not change.
- **Verified limitation:** `extract_text_with_positions_and_rotations_bytes`
  has **no `pages` parameter**. The integration calls it without pages and
  applies page selection locally only when the new opt-in metadata is enabled.
  The pre-existing path continues to call the `pages`-aware function, so old
  selection behavior is untouched.
- `TextItem` fields: `text`, `x`, `y`, `width`, `height`, `rotation`,
  `advance_known`, `font`, `font_tag`, `font_size`, `page` (1-indexed),
  `is_bold`, `is_italic`, `font_weight`, `bold_source`, `fixed_pitch`,
  `fill_color`, `stroke_color`, `render_mode`, `is_underline`, `is_strikeout`,
  `baseline_shift`, `item_type`, `mcid`.
- Coordinate contract: `x`/`y` are PDF points relative to the **visible page
  box** (`CropBox ∩ MediaBox`, else MediaBox), origin at its lower-left corner,
  `y` growing upward. Region extraction uses the same box from its top-left
  corner. On a page whose text is predominantly rotated, upstream re-bases the
  items into a synthetic frame; `PositionedText.page_rotations` reports
  `(page, "ccw"|"cw")` for that page, and `/Rotate` is not applied. The
  `rotated_text.pdf` fixture pins `"ccw"`.

### Tagged structure

```python
extract_structure_elements_bytes(
    data: bytes,
    pages: list[int] | None = None,
) -> list[StructureElement]
```

- `pages` is **1-indexed**, matching `TextItem.page`.
- `StructureElement`: `page` (1-indexed), `mcid`, `role` (standard structure
  name such as `H1`, `P`, `Code`, `Table`, `TD`, resolved through `/RoleMap`).
- Output is sorted by `(page, mcid)`. Untagged PDFs return `[]`.
- The join is `(TextItem.page, TextItem.mcid) == (StructureElement.page,
  StructureElement.mcid)`. `TextItem.mcid` is `None` outside marked content.
- Structure data is metadata only in this integration. It does not select a
  different renderer and does not rewrite Markdown, headings, or reading order.

### Detection and Markdown diagnostics

- `detect_pdf_bytes(data)` returns `PdfResult`: `pdf_type`, `page_count`,
  `pages_needing_ocr` (1-indexed), `ocr_reasons_by_page` (`page`, `reasons`),
  `confidence`, `is_complex_layout`, `pages_with_tables`,
  `pages_with_columns` (1-indexed), `has_encoding_issues`, `cmap_gaps`
  (`font`, `codes`, `interpolated`, `unmapped`), and document info fields.
  Verified on 1.25.2: fast detection leaves the layout lists empty; the
  Markdown extraction result is the verified source for table/column/OCR flags.
- `extract_pages_markdown_bytes(data, pages=None)` takes **0-indexed**
  pages, preserves requested order, and returns `PageMarkdown.page` 0-indexed.
  `PagesExtractionResult.pages_with_tables`,
  `pages_with_columns`, and `pages_needing_ocr` are 1-indexed.
- `classify_pdf_bytes` exposes 0-indexed `pages_needing_ocr`; it is not used by
  this integration, so no page-contract mismatch is introduced.

## Gap matrix

| Capability | Existing integration before this change | 1.25.2 released API | Decision |
|---|---|---|---|
| Plain text / Markdown / regions / positional text | Supported and kept | Same plus richer fields | Do not change defaults or selection semantics |
| Selective OCR with provenance | Not exposed | `process_pdf_with_ocr_bytes` | Add opt-in `ocr_mode`, offline-first, markdown-only |
| Rotation frames | Not exposed | `extract_text_with_positions_and_rotations_bytes` | Add opt-in `positions.page_rotations`; no content rewrite |
| Rich positioned fields | Only joined text | Full `TextItem` | Add opt-in `positions.items`; all released fields |
| Tagged roles / MCIDs | Not exposed | `extract_structure_elements_bytes` | Add opt-in `structure.elements`; no content rewrite |
| Detection/encoding/OCR diagnostics | Only document info fields | `PdfResult` / `OcrPdfResult` | Add opt-in `diagnostics`; raise on opt-in failures |
| TeX-built fixtures / CI downloads | PDFs compiled in CI | Not applicable | Check in PDFs; remove TeX from CI/publish |

## Public options (parser and loader)

Existing options keep their names, defaults, and behavior:
`mode`, `output`, `extract_positions`, `extract_regions`, `pages`,
`page_regions`, `region_delimiter`, `page_delimiter` (plus loader-only
`file_path`, `headers`, `extract_images`, `metadata`).

New keyword-only options:

| Option | Default | Meaning |
|---|---|---|
| `ocr_mode` | `"off"` | `"off"`, `"auto"`, or `"force"`. Enabled modes require `output="markdown"`. |
| `offline` | `True` | Prohibits model downloads unless explicitly `False`. Forwarded as upstream `offline`. |
| `model_directory` | `None` | Provisioned model directory, forwarded verbatim. |
| `dpi` | `150.0` | Positive finite render DPI. |
| `minimum_confidence` | `0.0` | Number in `[0, 1]`. |
| `hosted_recommendation_confidence` | `0.5` | Number in `[0, 1]`. |
| `password` | `None` | Optional PDF password for OCR. A non-empty value cannot combine with `include_structure`/`include_diagnostics` while OCR is enabled (upstream 1.25.2 metadata APIs are not password-aware). Empty string is treated as no password. |
| `include_position_metadata` | `False` | Adds `positions`; requires `extract_positions=True` and `output="text"`. |
| `include_structure` | `False` | Adds `structure` from tagged PDFs. |
| `include_diagnostics` | `False` | Adds native detection and OCR diagnostics/provenance. |

Rejected combinations (explicit `ValueError`):

- Invalid `ocr_mode` or non-boolean `offline`.
- Non-string `model_directory`/`password`, non-positive/non-finite
  `dpi`, or confidence values outside `[0, 1]`.
- `ocr_mode != "off"` with `output != "markdown"`.
- `ocr_mode != "off"` with `extract_positions`, `extract_regions`, or
  `page_regions` set (no silently ignored position/region options).
- `ocr_mode != "off"` with a non-empty `password` **and**
  `include_structure` or `include_diagnostics`. `pdf-inspector` 1.25.2's
  `detect_pdf_bytes` and `extract_structure_elements_bytes` APIs are not
  password-aware; the constructor rejects this before any upstream call with
  guidance to run OCR without those groups or decrypt the PDF separately.
  An empty password is harmless and is not rejected.
- `include_position_metadata=True` without `extract_positions=True` or with
  `output != "text"`.
- All pre-existing validation still applies unchanged (page mode requires a
  non-empty `pages` list, negative indices raise, positions/regions are
  mutually exclusive, regions require `page_regions`, delimiters are strings).

Selection contract:

- All public `pages` inputs remain **0-indexed**; all emitted `page` values and
  metadata page lists remain **1-indexed**. OCR translates 0-indexed selections
  to upstream `page_numbers` explicitly.
- Existing plain/positional/region/markdown selection semantics are unchanged.
  In particular, single-mode positional extraction still ignores `pages`, and
  page-mode positional extraction still deduplicates pages.
- New OCR selection: page mode emits one `Document` per requested page in the
  requested order, duplicates included; single mode joins requested page
  Markdown with `page_delimiter` in requested order. With `pages=None` single
  mode uses upstream document order. Out-of-range pages are omitted when the
  detected page count is available.

## Metadata schemas

All groups are opt-in, are ordinary JSON-compatible values (no native extension
objects, no tuples), and are additive: `page_content` and existing metadata are
not rewritten. Caller metadata merged by the loader wins on key conflicts.

### `positions` (`include_position_metadata=True`)

```json
{
  "positions": {
    "items": [
      {
        "text": "…",
        "x": 72.0, "y": 700.0, "width": 120.0, "height": 10.0,
        "rotation": 0.0, "advance_known": true,
        "font": "Helvetica", "font_tag": "F1", "font_size": 12.0,
        "page": 1, "is_bold": false, "is_italic": false,
        "font_weight": null, "bold_source": null, "fixed_pitch": null,
        "fill_color": [0, 0, 0], "stroke_color": [0, 0, 0],
        "render_mode": 0, "is_underline": false, "is_strikeout": false,
        "baseline_shift": 0.0, "item_type": "text", "mcid": null
      }
    ],
    "page_rotations": [{"page": 1, "rotation": "ccw"}]
  }
}
```

- Page mode: each document's `items` and `page_rotations` are scoped to that
  document's page.
- Single mode: all items keep their 1-indexed `page` field; all rotation
  associations are retained.
- Coordinates and rotation frames keep the upstream contracts documented
  above; enabling this group does not change the existing text content.
- `item_type` may be a non-text item (image/link/form field) when upstream
  returns one; missing associations are `null`.

### `structure` (`include_structure=True`)

```json
{
  "structure": {
    "elements": [
      {"page": 1, "mcid": 0, "role": "H1"},
      {"page": 1, "mcid": 1, "role": "P"},
      {"page": 2, "mcid": 0, "role": "P"}
    ]
  }
}
```

- Page mode: elements are scoped to the page and follow the effective
  content branch. Text region extraction selects the 0-indexed pages in
  `page_regions`; other page-mode paths—including `output="markdown"`, where
  regions are not used—select `pages`.
- Single mode: all elements retain their 1-indexed `page`.
- Untagged PDFs: `{"elements": []}` (present because it was explicitly
  requested).
- Join to `positions.items` by `(page, mcid)`. Structure extraction failures
  raise `RuntimeError` with the upstream cause rather than silently omitting
  the group. The group never rewrites content/Markdown/reading order.

### `diagnostics` (`include_diagnostics=True`)

Native detection fields (always present when the group is requested):

```json
{
  "diagnostics": {
    "pdf_type": "text_based",
    "confidence": 0.98,
    "is_complex_layout": false,
    "pages_needing_ocr": [],
    "ocr_reasons_by_page": [{"page": 2, "reasons": ["encoding_issue"]}],
    "pages_with_tables": [1],
    "pages_with_columns": [1],
    "has_encoding_issues": false,
    "cmap_gaps": [
      {"font": "ABCDEF+Font", "codes": 10, "interpolated": 2, "unmapped": 0}
    ],
    "ocr": {
      "page_count": 3,
      "pages_recommended_for_ocr": [],
      "pages_routed_to_ocr": [],
      "pages_recommending_hosted": [],
      "ocr_reasons_by_page": [],
      "pages_with_tables": [],
      "pages_with_columns": [],
      "is_complex": false,
      "processing_time_ms": 20,
      "render_time_ms": 0,
      "ocr_time_ms": 0,
      "pages": [
        {
          "page_number": 1,
          "provenance": {
            "page_number": 1,
            "source": "native",
            "ocr_model": null,
            "render_dpi": null,
            "ocr_confidence": null,
            "timings": {"render_ms": 0, "ocr_ms": 0, "assembly_ms": 0},
            "warnings": [],
            "hosted_recommended": false
          }
        }
      ]
    }
  }
}
```

- `ocr` is present only when `ocr_mode != "off"`. Per-page `markdown` is
  omitted from metadata because it is the document content.
- For the non-OCR `output="markdown"` path, the verified layout/OCR-routing
  lists from `PagesExtractionResult` replace the empty detection lists;
  detection's encoding/CMap diagnostics are retained.
- Page mode scopes page-number lists, OCR reason entries, and
  `ocr.pages` to the current page. Scalar document fields and `cmap_gaps`
  (which upstream does not associate with pages) remain document-level.
- Page-mode OCR serializes the OCR diagnostics once and pre-indexes
  page-specific lists, reasons, and provenance. Each emitted document is
  scoped from that index with independent mutable values (including repeated
  pages), so emission stays linear in result size instead of rescanning every
  upstream page per document.
- Single mode retains all page associations.
- Detection failure when diagnostics are opted in raises `RuntimeError` with
  the original cause. The historical silent detection fallback still applies
  when diagnostics are not requested.

## Compatibility guarantees

1. With all new options at defaults, parser/loader calls produce the same
   content, document count, selection behavior, delimiters, document info
   metadata, and page numbering as before.
2. `mode="page"` still requires a non-empty 0-indexed `pages` list for the
   existing text/markdown paths. OCR does not weaken that requirement.
3. The pre-existing positional path still calls
   `extract_text_with_positions_bytes(pages=...)`; only the opt-in metadata
   path uses the rotations variant, which has no `pages` argument.
4. Existing region coordinate semantics (top-left, visible page box) are
   unchanged.
5. Caller metadata still merges last and wins on every key, including
   `positions`, `structure`, and `diagnostics`.
6. No normal test or CI run downloads an OCR model. `offline=True` is the
   default and is passed explicitly upstream.
7. Tagged structure extraction never changes Markdown/read order or content.
8. The minimum dependency remains `pdf-inspector>=1.25.2,<2`; the lockfile
   already resolves 1.25.2, so no lockfile change was needed.
9. Page-mode structure metadata follows the same effective page selection as
   the content branch (regions for text region extraction, otherwise pages).
10. An enabled-OCR non-empty password is never silently paired with
    password-blind detection/structure APIs; the unsupported combination is
    rejected at construction time.

## Test plan (implemented)

- OCR: default-off path untouched; mocked upstream routing/option forwarding
  (including 0-indexed→1-indexed translation); password forwarding without
  rich groups; password + structure/diagnostics/both rejection before any
  upstream call; empty-password acceptance; page-mode requested
  order/duplicates; single-mode delimiter joining; out-of-range omission;
  JSON diagnostics; page-mode diagnostics serialized once with linear upstream
  page/provenance reads across many documents; mutation isolation between
  duplicate/distinct page documents; actionable missing-runtime/model errors
  with preserved cause; invalid option/combination rejection; real upstream
  `auto` on a text-based fixture (no models); opt-in real-model test guarded by
  `PDF_INSPECTOR_REAL_OCR=1` + `PDF_INSPECTOR_REAL_OCR_MODEL_DIR`.
- Rich metadata: default shape unchanged; full released position fields;
  JSON serialization; page scoping; actual `rotated_text.pdf` frame; actual
  `tagged_structure.pdf` roles/MCID joins; untagged empty structure; structure
  page scoping; actual region page mode with differing `pages`/`page_regions`
  (structure follows `page_regions`, Markdown follows `pages`); diagnostics
  scoping; detection/structure failure propagation; content-unchanged
  assertions; caller metadata precedence through the loader.
- Fixtures/CI: required PDFs checked in; missing fixtures fail (no skips);
  `build_fixtures.py --check` needs no TeX; both workflows no longer install
  TeX or compile fixtures; distribution contents checked after `uv build`;
  lint/format/mypy/test/build gates retained. A clean-copy run with TeX
  absent from `PATH` passed the fixture check and the full suite.

## Implementation dependencies and limitations

- Requires the released `pdf-inspector==1.25.2` APIs listed above. Do not rely
  on unreleased `main` signatures.
- `extract_text_with_positions_and_rotations_bytes` cannot select pages
  upstream; the integration filters locally, which is documented.
- Real OCR execution (actually routing a page through PDFium/ONNX Runtime and a
  provisioned model) is **not** part of routine CI and was not executed in this
  environment (no PDFium/ONNX Runtime/model). The pinned runtime/model facts,
  cache layout, filenames, checksums, and explicit opt-in download contract were
  verified against the `v1.25.2` docs/source and documented in the README; the
  routine real-upstream test confirms `auto` returns native provenance without
  downloading anything.
- GitHub Actions/PyPI stages are not executed by this work. Locally verified:
  lint, format, mypy, pytest, `uv build`, distribution contents, and a clean
  copy without TeX. Tag creation, workflow reruns, and publishing remain
  external lead actions.
