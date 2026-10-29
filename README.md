# langchain-pdf-inspector

A LangChain document loader and blob parser for PDFs, backed by the Rust-based
[`pdf-inspector`](https://pypi.org/project/pdf-inspector/) library. It extracts
plain text, Markdown, positioned text, region-cropped text, and opt-in OCR, and
returns ordinary `langchain_core.documents.Document` objects.

[![PyPI](https://img.shields.io/pypi/v/langchain-pdf-inspector.svg)](https://pypi.org/project/langchain-pdf-inspector/)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Coverage: 100% lines and branches](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](#development)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Installation

```bash
pip install langchain-pdf-inspector
# or
uv add langchain-pdf-inspector
```

Requires Python 3.12+, `langchain-core>=1.5.3,<2`, and
`pdf-inspector>=1.25.2,<2`. `pdf-inspector` is a required runtime dependency;
if it is missing, constructing the loader or parsing a blob raises a clear
`ImportError`.

## Quick start

```python
from langchain_pdf_inspector import PdfInspectorLoader

loader = PdfInspectorLoader("report.pdf")
for doc in loader.load():  # or loader.lazy_load()
    print(doc.metadata["page"], doc.page_content[:80])
```

The loader accepts local paths and `http(s)://` URLs, including presigned S3
HTTPS URLs. Bare `s3://` URIs are rejected; use a presigned URL or download the
PDF locally first. Downloads use a 10-second connection timeout and a 60-second
read timeout. Remote files are downloaded to a temporary file, which is removed
when the loader is released (or immediately if downloading fails). For direct blob parsing without path resolution, use
`PdfInspectorParser`:

```python
from langchain_core.documents.base import Blob
from langchain_pdf_inspector import PdfInspectorParser

docs = PdfInspectorParser(output="markdown").parse(Blob.from_path("report.pdf"))
```

`load()` and `parse()` return lists; `lazy_load()` and `lazy_parse()` stream
documents. The inherited async methods (`aload()`, `alazy_load()`) run the
synchronous work in a thread executor.

## Key options

| Option | Default | Effect |
|---|---|---|
| `mode` | `"single"` | One document for the PDF, or one per page with `"page"`. |
| `output` | `"text"` | Plain text or layout-aware Markdown. |
| `pages` | `None` | 0-indexed page selection. Required and non-empty in page mode. |
| `extract_positions` | `False` | Positioned text items. |
| `extract_regions` | `False` | Text cropped to `page_regions`; mutually exclusive with positions. |
| `page_regions` | `None` | `(page, [[x0, y0, x1, y1], ...])` crops; required with regions. |
| `region_delimiter` / `page_delimiter` | `"\n\n"` | Join region text / pages in joined single-mode output. |
| `ocr_mode` | `"off"` | `"auto"` or `"force"` OCR; requires `output="markdown"`. |
| `offline` | `True` | Prohibits OCR model downloads unless explicitly `False`. |
| `model_directory` | `None` | Provisioned OCR model directory. |
| `metadata` | `None` | Caller metadata merged last, so it wins on conflicts. |

The opt-in metadata flags are `include_position_metadata` (requires
`extract_positions=True` and `output="text"`), `include_structure`, and
`include_diagnostics`. See the [API reference](docs/api.md) for every option and
the metadata schemas.

### Pages and selection

- `pages` inputs are **0-indexed**; emitted `page` metadata is **1-indexed**.
- Page mode requires a non-empty `pages` list. With `output="text"`, it also
  requires `extract_positions` or `extract_regions`; use `output="markdown"` for
  per-page Markdown with `needs_ocr`, `has_tables`, and
  `has_multicolumn_layout` flags.
- In single mode `pages` is lenient and is ignored by extraction paths that do
  not use it; negative indices are always rejected.
- Out-of-range pages are omitted rather than emitted empty. The positional
  path deduplicates repeated page indices; the Markdown and OCR page paths
  preserve requested order and duplicates.
- OCR page mode emits one document per requested page in the requested order,
  including duplicates, while single mode joins selected page Markdown with
  `page_delimiter`.

### Regions and coordinates

Region rectangles use PDF points with a **top-left origin** and `y` increasing
downward, relative to the **visible page box** (`CropBox ∩ MediaBox`), not the
MediaBox. On a page with a non-zero CropBox origin, measure from the top-left of
the cropped area.

```python
loader = PdfInspectorLoader(
    "report.pdf",
    extract_regions=True,
    page_regions=[(0, [[10.0, 10.0, 200.0, 120.0]])],
)
```

Positioned-text coordinates keep upstream semantics: PDF points from the
visible box's lower-left corner with `y` increasing upward. For a
predominantly rotated page, items use upstream's turned frame and
`positions["page_rotations"]` names it; the PDF `/Rotate` entry is not applied.
Structure metadata never rewrites headings, Markdown, or reading order.

### OCR

OCR is opt-in and offline-first. Set `output="markdown"` and `ocr_mode="auto"`
to OCR only pages that native extraction rejects, or `"force"` to OCR every
selected page.

```python
loader = PdfInspectorLoader(
    "scan.pdf",
    output="markdown",
    ocr_mode="auto",
    pages=[0, 1],  # 0-indexed inputs; metadata is 1-indexed
    model_directory="/opt/models/pp-ocrv6-small",
    offline=True,  # default: never download
)
```

The package installs no PDFium, ONNX Runtime, or OCR models. Provision the
upstream-pinned runtime and PP-OCRv6 Small model set using the
[`pdf-inspector` v1.25.2 OCR runtime guide](https://github.com/firecrawl/pdf-inspector/blob/v1.25.2/docs/ocr-runtime.md),
then either place the model files directly in `model_directory` or warm
`pdf-inspector`'s managed cache once with `offline=False`. Missing runtimes or
models raise a `RuntimeError` with the original exception as `__cause__`.

A non-empty `password` is supported for OCR alone, but cannot be combined with
`include_structure` or `include_diagnostics` while OCR is enabled: the
`pdf-inspector` 1.25.2 detection and structure APIs are not password-aware. An
empty string is treated as no password.

### Metadata

Every document carries `source`; detection also adds `pdf_type`, `total_pages`,
and non-empty PDF document information fields (`title`, `author`, `subject`,
`keywords`, `creator`, `producer`, `creation_date`, `mod_date`). Opt-in groups
are additive JSON-compatible values:

- `positions`: positioned items plus `page_rotations`.
- `structure`: tagged-PDF `page`/`mcid`/`role` elements; join by `(page, mcid)`.
- `diagnostics`: detection fields and, with OCR, per-page provenance and timings.

Page mode scopes page lists, OCR provenance, and structure elements to the
document's page; single mode retains all associations. Caller-supplied
`metadata` is merged last and overrides parser keys, including these groups.

## Development

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest                       # enforces 100% line and branch coverage
uv run python tests/fixtures/build_fixtures.py --check
uv build
python3 tests/check_distribution.py
```

Fixtures are checked in under `tests/fixtures/`, so tests need no TeX.
Regenerate them only when changing the fixtures (requires `pdflatex` and
`cm-super`):

```bash
uv run python tests/fixtures/build_fixtures.py
```

The routine suite never downloads OCR models. To run the opt-in real-model test,
provision the runtime and model first, then point the test at a directory that
directly contains the model files:

```bash
export PDF_INSPECTOR_REAL_OCR=1
export PDF_INSPECTOR_REAL_OCR_MODEL_DIR=/path/to/pp-ocrv6-small
uv run pytest tests/unit_tests/document_loaders/test_pdf_inspector_ocr.py \
  -k real_provisioned_model --no-cov
```

Add `--no-cov` to focused test runs; the default coverage gate applies to the
full suite. See [testing and code-quality standards](docs/testing.md) for the
LangChain interface contracts, meaningful-test requirements, and coverage policy.
CI tests Python 3.12–3.14 on Linux, plus Python 3.12 on macOS and Windows, with
additional minimum/latest-allowed dependency checks on Python 3.12 and 3.14.

## Links

- [API reference](docs/api.md)
- [PyPI](https://pypi.org/project/langchain-pdf-inspector/)
- [Repository](https://github.com/undacmic/langchain-pdf-inspector)
- [Issues](https://github.com/undacmic/langchain-pdf-inspector/issues)
- [upstream `pdf-inspector`](https://pypi.org/project/pdf-inspector/)

The integration code is MIT-licensed; `pdf-inspector` has its own license.
