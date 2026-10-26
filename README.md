# langchain-pdf-inspector

A LangChain `DocumentLoader` integration that wraps the Rust-backed [`pdf-inspector`](https://pypi.org/project/pdf-inspector/) library to load PDFs as plain text, markdown, positional text, or region-cropped text. It is designed as a `langchain_community`-style document loader integration.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.1.1-blue.svg)](LICENSE)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![LangChain Core](https://img.shields.io/badge/langchain--core-1.5+-blue.svg)](https://python.langchain.com/docs/introduction/)
[![pdf-inspector](https://img.shields.io/badge/pdf--inspector-1.25.2+-blue.svg)](https://pypi.org/project/pdf-inspector/)
[![PyPI](https://img.shields.io/pypi/v/langchain-pdf-inspector.svg)](https://pypi.org/project/langchain-pdf-inspector/)

## Introduction

`langchain-pdf-inspector` gives you a standard LangChain document loader for PDF files, backed by the Rust-powered `pdf-inspector` package. It returns `langchain_core.documents.Document` objects that plug straight into LangChain chains, retrievers, and vector stores.

## Features

`langchain-pdf-inspector` is built on two small classes. `PdfInspectorParser` (a `BaseBlobParser`) parses a single `Blob` into `Document`s across four extraction paths — plain text, markdown (headings, lists, and tables preserved), positional text (text items with bounding boxes), and region-cropped text (cropped to `[x0, y0, x1, y1]` rectangles) — each in one of two modes: `mode="single"` (one `Document` for the whole PDF, the default) or `mode="page"` (one `Document` per page). `PdfInspectorLoader` (a `BasePDFLoader`) wraps the parser, resolves local, web (HTTP/HTTPS), and S3 paths, downloads remote files to a temporary file, and merges caller-supplied metadata on top of every `Document`. Because the heavy lifting is done by the Rust-backed `pdf-inspector` package, extraction is fast and accurate for both text-based and scanned PDFs.

> [!NOTE]
> `langchain-pdf-inspector` is a standalone package (version `0.1.1`) published on [PyPI](https://pypi.org/project/langchain-pdf-inspector/). It imports from its own `langchain_pdf_inspector` namespace, so use `from langchain_pdf_inspector import PdfInspectorLoader` rather than a `langchain_community` import.

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

Every `Document` carries `source` and a 1-indexed `page`; `pdf_type` and `total_pages` are attached whenever page detection succeeds. The PDF's own document information is surfaced too, under the `pdf-inspector` field names: `title`, `author`, `subject`, `keywords`, `creator`, `producer`, `creation_date`, and `mod_date` (all strings). Fields the PDF does not provide — or provides as empty — are omitted rather than emitted as `null`. Caller-supplied metadata is merged on top of these keys, and wins on conflicts.

### One document per page

`mode="page"` splits the PDF into one `Document` per page and requires `pages`, a non-empty list of 0-indexed pages. In page mode the content branches on `output`: `output="markdown"` yields per-page markdown with layout flags (`needs_ocr`, `has_tables`, `has_multicolumn_layout`); `output="text"` yields per-page positional or region-cropped text and requires `extract_positions` or `extract_regions`:

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

### Positional text

Set `extract_positions=True` to extract text items with their positional data. In single mode all pages collapse into one joined `Document` (pages joined with `page_delimiter`); in page mode you get one `Document` per page:

```python
loader = PdfInspectorLoader(
    "report.pdf", mode="page", pages=[0, 1, 2], extract_positions=True
)
for doc in loader.load():
    print(doc.metadata["page"], doc.page_content)
```

### Region extraction

Set `extract_regions=True` and pass `page_regions` to crop text to `[x0, y0, x1, y1]` rectangles. `extract_regions` requires `page_regions` and is mutually exclusive with `extract_positions`:

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

- `PdfInspectorLoader` (`src/langchain_pdf_inspector/pdf_inspector_loader.py`) — a `BasePDFLoader` subclass that resolves local, web, and S3 paths, forwards extraction options to the parser, and merges caller metadata on top of every `Document`. Implements `lazy_load()`; `load()`, `aload()`, and `alazy_load()` come from `BaseLoader`.
- `PdfInspectorParser` (`src/langchain_pdf_inspector/pdf_inspector_parser.py`) — a `BaseBlobParser` subclass that parses a `Blob` into `Document`s across four extraction paths and two modes. Implements `lazy_parse()` and `parse()`.

## Development

Install the development group with `uv`:

```bash
uv sync --group dev
```

The repo ships a [dev container](.devcontainer/devcontainer.json) (VS Code, Python 3.12, `uv`, and TeX Live) that runs `uv sync --group dev` automatically on create.

- **Type checking** — `uv run mypy src`
- **Linting** — `uv run ruff check .`
- **Tests** — `uv run pytest`

## Creating Test Documents

Test fixtures are PDFs compiled from LaTeX sources under `tests/fixtures/tex/` by `tests/fixtures/build_fixtures.py`. Seven fixtures are staged for incremental complexity — `plain_text`, `headings`, `lists`, `two_column`, `tables`, `complex_layout`, and `document_info` (which populates the PDF document information dictionary via `\pdfinfo`). The `.tex` sources are tracked; the built PDFs are gitignored build artifacts.

Build them with:

```bash
uv run python tests/fixtures/build_fixtures.py
```

The script requires `pdflatex` (pdfTeX) on `PATH`. On macOS, `brew install --cask mactex-no-gui` (or `basictex`) provides it; otherwise add its bin directory to `PATH`, for example `export PATH="/Library/TeX/texbin:$PATH"`.

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
