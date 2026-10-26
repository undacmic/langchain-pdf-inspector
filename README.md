# langchain-pdf-inspector

A LangChain `DocumentLoader` integration that wraps the Rust-backed [`pdf-inspector`](https://pypi.org/project/pdf-inspector/) library to load PDFs as plain text, markdown, positional text, or region-cropped text. It is designed as a `langchain_community`-style document loader integration.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](LICENSE)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![LangChain Core](https://img.shields.io/badge/langchain--core-1.5+-blue.svg)](https://python.langchain.com/docs/introduction/)
[![pdf-inspector](https://img.shields.io/badge/pdf--inspector-1.25.2+-blue.svg)](https://pypi.org/project/pdf-inspector/)
[![PyPI](https://img.shields.io/pypi/v/langchain-pdf-inspector.svg)](https://pypi.org/project/langchain-pdf-inspector/)

## Introduction

`langchain-pdf-inspector` gives you a standard LangChain document loader for PDF files, backed by the Rust-powered `pdf-inspector` package. It returns `langchain_core.documents.Document` objects that plug straight into LangChain chains, retrievers, and vector stores.

## Features

`langchain-pdf-inspector` is built on two small classes. `PdfInspectorParser` (a `BaseBlobParser`) parses a single `Blob` into `Document`s across extraction paths — plain text, markdown (headings, lists, and tables preserved), positional text (text items with bounding boxes), region-cropped text (cropped to `[x0, y0, x1, y1]` rectangles), and opt-in selective OCR — each in one of two modes: `mode="single"` (one `Document` for the whole PDF, the default) or `mode="page"` (one `Document` per page). It also offers opt-in JSON-compatible positioned-text, tagged-structure, and diagnostic metadata. `PdfInspectorLoader` (a `BasePDFLoader`) wraps the parser, resolves local, web (HTTP/HTTPS), and S3 paths, downloads remote files to a temporary file, and merges caller-supplied metadata on top of every `Document`. Because the heavy lifting is done by the Rust-backed `pdf-inspector` package, extraction is fast and accurate for both text-based and scanned PDFs.

> [!NOTE]
> `langchain-pdf-inspector` is a standalone package (version `0.3.0`) published on [PyPI](https://pypi.org/project/langchain-pdf-inspector/). It imports from its own `langchain_pdf_inspector` namespace, so use `from langchain_pdf_inspector import PdfInspectorLoader` rather than a `langchain_community` import.

## Requirements

- Python 3.12 or higher
- langchain-core 1.5.3 or higher (below 2.0)
- pdf-inspector 1.25.2 or higher (below 2.0)

## Installation

Install `langchain-pdf-inspector` from PyPI:

```bash
pip install langchain-pdf-inspector
# or with uv
uv add langchain-pdf-inspector
```

Installing `langchain-pdf-inspector` also installs its required runtime dependencies, `langchain-core` and `pdf-inspector`. `pdf-inspector` is a required dependency; if it is missing, constructing the loader or parser raises a friendly `ImportError` telling you to run `pip install pdf-inspector`.

To install from source instead, clone the repository and run `pip install .` (or `uv add .`) from the repo root.

## Usage

Create a loader from a local file, a web URL, or an S3 path:

```python
from langchain_pdf_inspector import PdfInspectorLoader

# Local file
loader = PdfInspectorLoader("path/to/report.pdf")

# Web URL
loader = PdfInspectorLoader("https://example.com/report.pdf")

# With optional caller metadata
loader = PdfInspectorLoader(
    "report.pdf",
    metadata={"tenant": "acme", "document_id": "R-42"},
)
```

Call `load()` to get a list of `Document` objects:

```python
loader = PdfInspectorLoader("path/to/report.pdf")

for doc in loader.load():
    print(doc.page_content)
    print(doc.metadata)
```

Use `lazy_load()` to stream documents:

```python
loader = PdfInspectorLoader("report.pdf", mode="page", pages=[0, 1, 2])

for doc in loader.lazy_load():
    print(doc.metadata["page"], doc.page_content[:80])
```

Every `Document` carries `source` and a 1-indexed `page`; `pdf_type` and `total_pages` are attached whenever page detection succeeds. The PDF's own document information is surfaced too, under the `pdf-inspector` field names: `title`, `author`, `subject`, `keywords`, `creator`, `producer`, `creation_date`, and `mod_date` (all strings). Fields the PDF does not provide — or provides as empty — are omitted rather than emitted as `null`. Caller-supplied metadata is merged on top of these keys, and wins on conflicts, including the opt-in metadata groups described below.

All new extraction and metadata features are opt-in, so existing calls keep their content and metadata shape. New groups are ordinary JSON-compatible values: `positions` (positioned items and rotated-page frames), `structure` (tagged-PDF `page`/`mcid`/`role` associations), and `diagnostics` (native detection, layout, encoding, and OCR provenance). They are additive and never replace `page_content`.

### One document per page

`mode="page"` splits the PDF into one `Document` per page and requires `pages`, a non-empty list of 0-indexed pages. `pages` is 0-indexed for every mode and extraction path, so the same selection returns the same logical pages from positional text and markdown. Negative indices raise `ValueError`. Out-of-range indices are not validated: both paths silently omit pages that do not exist (markdown skips them using the detected page count, so it no longer emits an empty `Document` for them). Duplicate indices yield one `Document` per page from positional text, but one `Document` per occurrence (in the requested order) from markdown. In page mode the content branches on `output`: `output="markdown"` yields per-page markdown with layout flags (`needs_ocr`, `has_tables`, `has_multicolumn_layout`); `output="text"` yields per-page positional or region-cropped text and requires `extract_positions` or `extract_regions`:

```python
loader = PdfInspectorLoader(
    "report.pdf", mode="page", pages=[0, 1, 2], output="markdown"
)
for doc in loader.load():
    print(doc.metadata["page"], doc.metadata.get("has_tables"))
```

### Markdown

Use `output="markdown"` in single mode to get the whole file as one `Document` of markdown, preserving headings, lists, and tables:

```python
loader = PdfInspectorLoader("report.pdf", mode="single", output="markdown")
doc = loader.load()[0]
print(doc.page_content)
```

### Selective OCR

OCR is opt-in and offline-first. `ocr_mode` defaults to `"off"`, which leaves every existing extraction path untouched. Set `output="markdown"` and `ocr_mode="auto"` to route only pages that native extraction rejects, or `"force"` to OCR every selected page:

```python
loader = PdfInspectorLoader(
    "scan.pdf",
    output="markdown",
    ocr_mode="auto",  # "off" (default), "auto", or "force"
    mode="page",
    pages=[0, 1],  # 0-indexed inputs; metadata is 1-indexed
    model_directory="/opt/models/pp-ocrv6-small",  # provisioned model
    offline=True,  # default: no downloads
)
for doc in loader.load():
    print(doc.metadata["page"], doc.page_content[:120])
```

Enabled OCR requires `output="markdown"` and rejects `extract_positions`, `extract_regions`, and `page_regions` with explicit errors rather than silently ignoring them. In page mode, OCR emits one `Document` per requested page in the requested order, including duplicates; single mode joins the selected page Markdown with `page_delimiter`. Out-of-range pages are omitted when the detected page count is available. Both modes keep 1-indexed `page` metadata.

**Offline and model provisioning.** `offline=True` is the default and is passed explicitly to `pdf-inspector`; an OCR-routed page therefore never downloads a model unless you pass `offline=False`. The wheel embeds no PDFium, ONNX Runtime, or OCR models, and this package neither installs nor downloads them. Provisioning is an explicit operator step:

1. **Install the release-tested shared libraries.** `pdf-inspector` 1.25.2's [pinned OCR runtime guide](https://github.com/firecrawl/pdf-inspector/blob/v1.25.2/docs/ocr-runtime.md) validates [Firecrawl PDFium `native-v7988`](https://github.com/firecrawl/pdfium-rs/releases/tag/native-v7988) (PDFium `153.0.7988.0`) and [ONNX Runtime `1.27.0`](https://github.com/microsoft/onnxruntime/releases/tag/v1.27.0). Download the matching platform archives from those releases, verify the published checksums (the PDFium release publishes `SHA256SUMS`; ONNX Runtime publishes a SHA-256 for each asset), and point the loader at the extracted libraries:

   ```bash
   export PDFIUM_LIB_PATH=/absolute/path/to/libpdfium.dylib  # or .so/.dll
   export ORT_DYLIB_PATH=/absolute/path/to/libonnxruntime.dylib
   ```

   The pinned guide lists the exact archives for Linux x64/ARM64, macOS Apple Silicon, and Windows x64. ONNX Runtime 1.27.0 has no Intel macOS asset, so local OCR on that target needs a compatible custom build. macOS and Windows external-runtime paths are preview status upstream; Linux x64 is the end-to-end CI-tested path.

2. **Provide the pinned PP-OCRv6 Small model set.** The 1.25.2 manifest (`pp-ocrv6-small`, revision `oar-ocr-v0.7.0`) requires exactly these three files, about 31 MB in total. `pdf-inspector` SHA-256-verifies them before use:

   | File | Bytes | SHA-256 |
   |---|---|---|
   | `pp-ocrv6_small_det.onnx` | 9,880,512 | `d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e` |
   | `pp-ocrv6_small_rec.onnx` | 21,159,378 | `5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634` |
   | `ppocrv6_dict.txt` | 74,947 | `b5f2bfe2bdd9448429e3e82b51c789775d9b42f2403d082b00662eb77e401c5d` |

   **Option A, managed cache with one explicit opt-in download.** Run a real OCR call with `offline=False` once. The first routed page downloads and verifies the pinned artifacts into the managed cache; later calls with `offline=True` reuse them without network access:

   ```python
   from pathlib import Path

   import pdf_inspector

   data = Path("scan.pdf").read_bytes()
   # Explicitly permits the pinned download; use a one-page selection to warm
   # the cache without OCRing the whole document. Runtime libraries are needed.
   pdf_inspector.process_pdf_with_ocr_bytes(
       data, mode="force", page_numbers=[1], offline=False
   )
   ```

   The managed cache root is `PDF_INSPECTOR_MODEL_CACHE` when set and non-empty; otherwise it is the platform cache directory plus `pdf-inspector/models`. The effective model directory appends `pp-ocrv6-small/oar-ocr-v0.7.0`, so the files land at:

   ```text
   $PDF_INSPECTOR_MODEL_CACHE/pp-ocrv6-small/oar-ocr-v0.7.0/
     pp-ocrv6_small_det.onnx
     pp-ocrv6_small_rec.onnx
     ppocrv6_dict.txt
   ```

   With no environment override, use the platform cache root instead (on macOS `~/Library/Caches/pdf-inspector/models/...`, on Linux `${XDG_CACHE_HOME:-~/.cache}/pdf-inspector/models/...`, on Windows `%LOCALAPPDATA%\pdf-inspector\models\...`).

   **Option B, explicit `model_directory`.** Put the three files directly in one directory and pass that directory verbatim as `model_directory`. Unlike the managed cache, `model_directory` gets no `pp-ocrv6-small/oar-ocr-v0.7.0` suffix, and `pdf-inspector` never mutates or supplements an explicit directory from the network:

   ```bash
   mkdir -p /opt/models/pp-ocrv6-small
   # Place the three verified files directly inside /opt/models/pp-ocrv6-small.
   ```

   ```python
   loader = PdfInspectorLoader(
       "scan.pdf",
       output="markdown",
       ocr_mode="auto",
       model_directory="/opt/models/pp-ocrv6-small",
       offline=True,
   )
   ```

3. **Run offline.** With the managed cache warm or `model_directory` complete, keep `offline=True` (the default). A missing/incomplete model or runtime raises a `RuntimeError` whose message explains the offline default, `model_directory`, and the runtime library paths, and whose `__cause__` is the original upstream exception.

Forwarded tuning options are `dpi` (default `150.0`), `minimum_confidence` (default `0.0`), `hosted_recommendation_confidence` (default `0.5`), and `password`.

A non-empty `password` is supported when OCR runs without rich metadata groups. It **cannot** be combined with `include_structure` or `include_diagnostics` while `ocr_mode` is enabled: `pdf-inspector` 1.25.2's `detect_pdf_bytes` and `extract_structure_elements_bytes` APIs are not password-aware, so the constructor raises an actionable `ValueError` before any upstream call. Run OCR without those groups, or decrypt the PDF separately first. An empty password is treated as no password and is not rejected.

Add `include_diagnostics=True` to receive per-page OCR provenance (`source`, model name/revision, confidence, render DPI, timings, warnings) under `metadata["diagnostics"]["ocr"]`. The per-page Markdown is omitted from metadata because it is already the document content. Routine tests never download models; see [Development](#development) for the opt-in real-model test.

### Rich positioned and tagged metadata

These flags only add metadata groups; they do not change content, Markdown, headings, reading order, page numbering, or existing selection semantics.

```python
loader = PdfInspectorLoader(
    "report.pdf",
    extract_positions=True,  # required to enrich positional text
    include_position_metadata=True,  # adds metadata["positions"]
    include_structure=True,  # adds metadata["structure"]
    include_diagnostics=True,  # adds metadata["diagnostics"]
)
doc = loader.load()[0]
print(doc.metadata["positions"]["items"][0])
print(doc.metadata["positions"]["page_rotations"])
print(doc.metadata["structure"]["elements"])
```

`positions` contains all released `TextItem` fields (`text`, `x`, `y`, `width`, `height`, `rotation`, `advance_known`, `font`, `font_tag`, `font_size`, `page`, `is_bold`, `is_italic`, `font_weight`, `bold_source`, `fixed_pitch`, `fill_color`, `stroke_color`, `render_mode`, `is_underline`, `is_strikeout`, `baseline_shift`, `item_type`, `mcid`) plus `page_rotations` (`page`, `rotation` = `"ccw"`/`"cw"`). Page mode scopes both lists to the corresponding page; single mode retains each item's 1-indexed page association and all rotated-page frames. Colour tuples are emitted as JSON lists.

Coordinates keep the upstream contract: PDF points from the lower-left corner of the **visible page box** (`CropBox ∩ MediaBox`), with `y` increasing upward. On a page whose text is predominantly drawn rotated, upstream re-bases the items into a synthetic left-to-right frame and reports that page in `page_rotations`; PDF `/Rotate` is not applied.

`structure` is the tagged-PDF structure tree as `{"elements": [{"page": 1, "mcid": 0, "role": "H1"}, ...]}`. Roles are standard structure names resolved through `/RoleMap` (for example `H1`, `P`, `Code`, `Table`, `TD`). Join to positioned items by `(page, mcid)`; items outside marked content have `mcid: null`. Page mode scopes elements to the page and follows the effective content branch: text region extraction uses the 0-indexed pages in `page_regions`, while other page-mode paths—including `output="markdown"`, where regions are not used—use `pages`. Single mode retains all pages. Untagged PDFs deliberately emit `{"elements": []}` when the group is requested. Structure metadata never rewrites Markdown or reading order.

`diagnostics` contains native `detect_pdf_bytes` fields (`pdf_type`, `confidence`, `is_complex_layout`, `pages_needing_ocr`, `ocr_reasons_by_page`, `pages_with_tables`, `pages_with_columns`, `has_encoding_issues`, `cmap_gaps`) and, for the non-OCR Markdown path, the verified layout/OCR-routing lists from the Markdown extraction. When OCR is enabled it also includes `diagnostics["ocr"]` with the result-level counters/timings and one provenance entry per page. In page mode page-number lists, OCR reasons, and `ocr.pages` are scoped to the current page; document-wide scalars and `cmap_gaps` remain document-level. If detection or structure extraction fails while its group is opted in, the error is raised with its original cause rather than silently omitting metadata.

### Positional text

Set `extract_positions=True` to extract text items with their positional data. In single mode all pages collapse into one joined `Document` (pages joined with `page_delimiter`); in page mode you get one `Document` per page:

```python
loader = PdfInspectorLoader(
    "report.pdf", mode="page", pages=[0, 1, 2], extract_positions=True
)
for doc in loader.load():
    print(doc.metadata["page"], doc.page_content)
```

This path returns text only. Set `include_position_metadata=True` alongside `extract_positions=True` (and `output="text"`) to attach the rich `positions` group described above.

### Region extraction

Set `extract_regions=True` and pass `page_regions` to crop text to `[x0, y0, x1, y1]` rectangles. `extract_regions` requires `page_regions` and is mutually exclusive with `extract_positions`:

Region coordinates are in PDF points with a **top-left origin** and `y` increasing downward, measured relative to the **visible page box** — the intersection of the page's CropBox and MediaBox. They are *not* relative to the MediaBox. The two coincide when the CropBox starts at `(0, 0)`, which is the common case; on pages with a non-zero CropBox origin, measure from the top-left of the visible (cropped) area instead.

```python
# Single mode: one joined Document cropped to the given regions
loader = PdfInspectorLoader(
    "report.pdf",
    extract_regions=True,
    page_regions=[(0, [[10.0, 10.0, 200.0, 200.0]])],
)
for doc in loader.load():
    print(doc.metadata["page"], doc.page_content)

# Page mode: one region-cropped Document per page
loader = PdfInspectorLoader(
    "report.pdf",
    mode="page",
    pages=[0, 1, 2],
    extract_regions=True,
    page_regions=[(0, [[10.0, 10.0, 200.0, 200.0]])],
)
for doc in loader.load():
    print(doc.metadata["page"], doc.page_content)
```

### Using the parser directly

`PdfInspectorParser` parses a `Blob` directly when you do not need path resolution or metadata merging:

```python
from langchain_core.document_loaders.blob_loaders import Blob
from langchain_pdf_inspector import PdfInspectorParser

parser = PdfInspectorParser(mode="page", pages=[0, 1, 2], extract_positions=True)
blob = Blob.from_path("report.pdf")
docs = list(parser.lazy_parse(blob))  # or parser.parse(blob) for a list
```

### Async loading

`aload()` and `alazy_load()` are inherited from `BaseLoader` and run the synchronous parsing work in a thread executor:

```python
loader = PdfInspectorLoader("report.pdf")
docs = await loader.aload()

async for doc in loader.alazy_load():
    print(doc.page_content)
```

### API reference

- `PdfInspectorLoader` (`src/langchain_pdf_inspector/pdf_inspector_loader.py`) — a `BasePDFLoader` subclass that resolves local, web, and S3 paths, forwards extraction/OCR/metadata options to the parser, and merges caller metadata on top of every `Document`. Implements `lazy_load()`; `load()`, `aload()`, and `alazy_load()` come from `BaseLoader`.
- `PdfInspectorParser` (`src/langchain_pdf_inspector/pdf_inspector_parser.py`) — a `BaseBlobParser` subclass that parses a `Blob` into `Document`s across the plain-text, Markdown, positional, region, and OCR paths in two modes, with opt-in rich metadata groups. Implements `lazy_parse()` and `parse()`.
- The full released-API audit, exact option/schema contract, compatibility guarantees, and test plan are in [`docs/api-update-plan.md`](docs/api-update-plan.md).

## Development

Install the development group with `uv`:

```bash
uv sync --group dev
```

The repo ships a [dev container](.devcontainer/devcontainer.json) (VS Code, Python 3.12, `uv`, and TeX Live with `cm-super`) that runs `uv sync --group dev` automatically on create. TeX is only useful for regenerating fixtures; tests and CI do not need it.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv build
python3 tests/check_distribution.py   # after uv build
```

**Opt-in real OCR integration test.** Routine CI is offline with respect to OCR model downloads and skips this test. Follow [Provisioning the pinned OCR runtime and model](#selective-ocr) first, then point the test at the directory that *directly* contains the three model files:

```bash
# macOS managed cache created by Option A above:
export PDF_INSPECTOR_REAL_OCR_MODEL_DIR="$HOME/Library/Caches/pdf-inspector/models/pp-ocrv6-small/oar-ocr-v0.7.0"
# Linux managed cache:
# export PDF_INSPECTOR_REAL_OCR_MODEL_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/pdf-inspector/models/pp-ocrv6-small/oar-ocr-v0.7.0"
# Or the exact custom directory passed as model_directory in Option B:
# export PDF_INSPECTOR_REAL_OCR_MODEL_DIR="/opt/models/pp-ocrv6-small"

export PDF_INSPECTOR_REAL_OCR=1
uv run pytest tests/unit_tests/document_loaders/test_pdf_inspector_ocr.py -k real_provisioned_model
```

`PDF_INSPECTOR_REAL_OCR_MODEL_DIR` is forwarded verbatim as the parser's `model_directory`; it must contain `pp-ocrv6_small_det.onnx`, `pp-ocrv6_small_rec.onnx`, and `ppocrv6_dict.txt` directly. Do not point it at the cache root or at `pdf-inspector/models`. The test uses `ocr_mode="force"` with `offline=True`, so it never downloads a model; it fails, rather than silently skips, if the runtime or model is incomplete. Real OCR was not executed in this environment because PDFium/ONNX Runtime and a model were not installed; the runtime/model versions and paths above were verified against the pinned 1.25.2 documentation and source, not by executing OCR.

## Test fixtures

All required PDFs are **checked in** under `tests/fixtures/`, so `uv run pytest` and CI need no TeX installation and never skip missing integration coverage. The eight LaTeX fixtures are staged for incremental complexity: `plain_text`, `headings`, `lists`, `two_column`, `tables`, `complex_layout`, `cropbox_offset` (whose CropBox has a non-zero origin, pinning the region-coordinate contract), and `document_info` (which populates the PDF document information dictionary via `\pdfinfo`). `tagged_structure` and `rotated_text` are small deterministic PDFs written directly by the builder for the released structure-tree and rotation-frame contracts.

Verify the checked-in fixtures without TeX:

```bash
uv run python tests/fixtures/build_fixtures.py --check
```

Regenerate them (requires `pdflatex`/pdfTeX on `PATH` only for this step):

```bash
uv run python tests/fixtures/build_fixtures.py
```

On macOS, `brew install --cask mactex-no-gui` (or `basictex`) provides pdflatex, or install a lightweight TeX Live/TinyTeX distribution and add its bin directory to `PATH`, for example `export PATH="/Library/TeX/texbin:$PATH"`. The LaTeX fixtures were generated with pdfTeX 3.141592653-2.6 (TeX Live 2026) and `cm-super`, which provides the Type 1 EC-font outlines with a ToUnicode CMap needed for reliable text extraction. The builder retains the `.tex` sources and the canonical `sample.png`; the PDFs are reproducible from those assets. Keep the regenerated PDFs checked in after verifying `uv run pytest`.

## Licensing

- **Open source** — the `langchain-pdf-inspector` integration code is licensed under the [MIT License](LICENSE).
- **Third-party** — the wrapped `pdf-inspector` package is distributed under its own license; see that package for details.

---

## Contributing

Contributions are welcome. Report bugs, request features, or open a pull request on the repository.

- [Report an issue](https://github.com/undacmic/langchain-pdf-inspector/issues)
- [Repository](https://github.com/undacmic/langchain-pdf-inspector)

## ⭐ Support this project

If you find this useful, please consider giving it a star — it helps others discover it!

[![Star on GitHub](https://img.shields.io/github/stars/undacmic/langchain-pdf-inspector.svg?style=for-the-badge&label=Star&logo=github)](https://github.com/undacmic/langchain-pdf-inspector/)
