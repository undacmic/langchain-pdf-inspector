"""Build the checked-in PDF fixtures for testing.

This script compiles each ``.tex`` source under ``tests/fixtures/tex/`` into a
``.pdf`` in the fixtures directory using the installed LaTeX engine, then
writes two small deterministic PDFs directly from this script:

- ``tagged_structure.pdf``: a two-page tagged PDF with H1/P/Code/P roles on
  page 1 and a P role on page 2. It pins the released structure-tree
  ``(page, mcid, role)`` contract and page-mode scoping.
- ``rotated_text.pdf``: a page whose text is drawn rotated 90 degrees, pinning
  the released ``extract_text_with_positions_and_rotations`` frame contract
  (``page_rotations`` reports ``"ccw"``).

The generated PDFs are checked in, so tests and CI never need a TeX engine.
Use ``--check`` to verify every required checked-in PDF is present without
running either builder::

    uv run python tests/fixtures/build_fixtures.py --check

Regenerate them (a local TeX engine is required only for this step)::

    uv run python tests/fixtures/build_fixtures.py

Engine: ``pdflatex`` (pdfTeX). The build uses whatever pdflatex is installed
(the latest available); it only fails if ``pdflatex`` is not on ``PATH`` at
all. The checked-in LaTeX fixtures were generated with pdfTeX 3.141592653-2.6
(TeX Live 2026) plus ``cm-super`` so ``\\usepackage[T1]{fontenc}`` emits Type 1
fonts with a ToUnicode CMap.

Design note: the fixtures are intentionally staged for incremental complexity:

- Stage 1 (text-only): ``plain_text``, ``headings``, ``lists``, ``two_column``.
- Stage 2 (tables): ``tables``.
- Stage 3 (image / complex layout): ``complex_layout``, which embeds
  ``sample.png``.
- Stage 4 (document info): ``document_info``, whose ``\\pdfinfo`` dictionary
  carries title/author/subject/keywords/creator/producer/dates.
- Cross-cutting: ``cropbox_offset``, whose CropBox has a non-zero lower-left
  origin. It pins the region-coordinate contract: region boxes are measured
  from the top-left of the visible page box (CropBox intersected with
  MediaBox), not the MediaBox.

Later stages slot in as an additional ``.tex`` source + ``SOURCES`` entry with
no change to the engine/cleanup logic below.

The canonical image asset is the tracked ``tests/fixtures/sample.png``; the
build copies it to ``tests/fixtures/tex/sample.png`` so pdflatex can resolve
``\\includegraphics{sample.png}`` (see ``_ensure_image``).

Build with::

    uv run python tests/fixtures/build_fixtures.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
TEX_DIR = FIXTURES_DIR / "tex"

# Stage 1 text-only, Stage 2 tables, Stage 3 complex-layout+image, and Stage 4
# document-info fixtures. ``cropbox_offset`` is the region-coordinate contract
# fixture: its CropBox has a non-zero lower-left origin, so the visible page box
# differs from the MediaBox. Add new stems here as later stages land.
SOURCES = [
    "plain_text",
    "headings",
    "lists",
    "two_column",
    "tables",
    "complex_layout",
    "cropbox_offset",
    "document_info",
]

# Small deterministic fixtures written directly by this script (no TeX).
PROGRAMMATIC_SOURCES = [
    "tagged_structure",
    "rotated_text",
]

# Every PDF the test suite requires. CI runs ``--check`` so a missing tracked
# fixture fails before pytest with the exact names.
REQUIRED_PDFS = [
    *(f"{stem}.pdf" for stem in SOURCES),
    *(f"{stem}.pdf" for stem in PROGRAMMATIC_SOURCES),
]

# Engine. All fixtures are pdflatex-compatible, so we fix the engine to
# pdflatex (pdfTeX) rather than auto-detecting from a list. We use whatever
# version of pdflatex is installed.
ENGINE = "pdflatex"

# Auxiliary files produced alongside each PDF; removed so only PDFs remain.
AUX_SUFFIXES = (".aux", ".log", ".out", ".toc", ".synctex.gz")

# ``tests/fixtures/sample.png`` is the single tracked (canonical) image asset.
# pdflatex resolves ``\includegraphics{sample.png}`` relative to the current
# working directory and the input ``.tex`` dir (``tests/fixtures/tex/``), so
# ``tests/fixtures/tex/sample.png`` is a *generated copy* created by this build
# and intentionally not tracked (see ``.gitignore``). This function guarantees
# the copy exists before compiling.
IMAGE_SOURCE = FIXTURES_DIR / "sample.png"
IMAGE_DEST = TEX_DIR / "sample.png"


def _ensure_image() -> None:
    """Make ``tests/fixtures/tex/sample.png`` available to pdflatex.

    ``tests/fixtures/sample.png`` is the single canonical, tracked asset. The
    copy in ``tests/fixtures/tex/`` is a generated artifact for compilation and
    is not tracked. Re-creating it here makes builds reproducible from the
    single tracked asset even on a fresh checkout.
    """
    if not IMAGE_SOURCE.is_file():
        raise FileNotFoundError(
            f"Missing canonical image fixture: {IMAGE_SOURCE}\n"
            "Please restore tests/fixtures/sample.png (it is the single tracked "
            "source image) and re-run this script."
        )
    TEX_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(IMAGE_SOURCE, IMAGE_DEST)


def compile_source(tex_path: Path) -> None:
    """Compile ``tex_path`` into ``FIXTURES_DIR`` (run once; PDF is the artifact)."""
    subprocess.run(
        [
            ENGINE,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={FIXTURES_DIR}",
            str(tex_path),
        ],
        check=True,
    )


def cleanup_aux(out_base: Path) -> None:
    """Delete the auxiliary files the engine wrote next to the PDF.

    ``out_base`` is the fixture output path *without* extension (the engine is
    invoked with ``-output-directory=FIXTURES_DIR``, so the aux files land in
    ``FIXTURES_DIR`` rather than next to the ``.tex`` source).
    """
    for suffix in AUX_SUFFIXES:
        aux = out_base.with_suffix(suffix)
        if aux.is_file():
            aux.unlink()


def _pdf_stream(data: bytes) -> bytes:
    """Wrap uncompressed content in a PDF stream object body."""
    return f"<< /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def _build_pdf(objects: list[bytes], root: int = 1) -> bytes:
    """Assemble numbered objects into a deterministic, uncompressed PDF."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {root} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _tagged_structure_pdf() -> bytes:
    """Build a small, valid tagged PDF with roles/MCIDs across two pages."""
    page_one = b"""/Span << /MCID 0 >> BDC
BT /F1 24 Tf 72 700 Td (Tagged Structure Fixture) Tj ET
EMC
/Span << /MCID 1 >> BDC
BT /F1 12 Tf 72 660 Td (This paragraph carries taggedsentinel-alpha.) Tj ET
EMC
/Span << /MCID 2 >> BDC
BT /F2 12 Tf 72 630 Td (taggedsentinel-code) Tj ET
EMC
/Span << /MCID 3 >> BDC
BT /F1 12 Tf 72 600 Td (Closing taggedsentinel-beta paragraph.) Tj ET
EMC
"""
    page_two = b"""/Span << /MCID 0 >> BDC
BT /F1 12 Tf 72 700 Td (taggedsentinel-page-two) Tj ET
EMC
"""
    objects = [
        # 1 catalog, 2 page tree
        (
            b"<< /Type /Catalog /Pages 2 0 R /StructTreeRoot 8 0 R "
            b"/MarkInfo << /Marked true >> >>"
        ),
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        # 3-7 pages, shared resources, content streams
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources 6 0 R /Contents 5 0 R /StructParents 0 /Tabs /S >>"
        ),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources 6 0 R /Contents 7 0 R /StructParents 1 /Tabs /S >>"
        ),
        _pdf_stream(page_one),
        b"<< /Font << /F1 16 0 R /F2 17 0 R >> >>",
        _pdf_stream(page_two),
        # 8-14 structure tree and elements
        b"<< /Type /StructTreeRoot /K [9 0 R] /ParentTree 15 0 R >>",
        (
            b"<< /Type /StructElem /S /Document /P 8 0 R "
            b"/K [10 0 R 11 0 R 12 0 R 13 0 R 14 0 R] >>"
        ),
        b"<< /Type /StructElem /S /H1 /P 9 0 R /Pg 3 0 R /K 0 >>",
        b"<< /Type /StructElem /S /P /P 9 0 R /Pg 3 0 R /K 1 >>",
        b"<< /Type /StructElem /S /Code /P 9 0 R /Pg 3 0 R /K 2 >>",
        b"<< /Type /StructElem /S /P /P 9 0 R /Pg 3 0 R /K 3 >>",
        b"<< /Type /StructElem /S /P /P 9 0 R /Pg 4 0 R /K 0 >>",
        # 15 parent tree: page 0's immediate parents are the four page-1
        # StructElems (10-13); page 1's immediate parent is its page-2
        # StructElem (14). The Document element 9 is the tree root, not the
        # immediate parent for either page.
        (b"<< /Nums [0 [10 0 R 11 0 R 12 0 R 13 0 R] 1 [14 0 R]] >>"),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    ]
    return _build_pdf(objects)


def _rotated_text_pdf() -> bytes:
    """Build a one-page PDF whose text is drawn rotated 90 degrees CCW."""
    content = b"""q
BT /F1 18 Tf 0 1 -1 0 300 100 Tm (rotatedsentinel-oscar) Tj ET
BT /F1 18 Tf 0 1 -1 0 330 160 Tm (rotatedsentinel-papa) Tj ET
Q
"""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources 4 0 R /Contents 5 0 R >>"
        ),
        b"<< /Font << /F1 6 0 R >> >>",
        _pdf_stream(content),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
    ]
    return _build_pdf(objects)


def build_programmatic_fixtures() -> list[Path]:
    """Write the deterministic tagged and rotated PDF fixtures."""
    builders = {
        "tagged_structure": _tagged_structure_pdf,
        "rotated_text": _rotated_text_pdf,
    }
    built: list[Path] = []
    for stem, builder in builders.items():
        path = FIXTURES_DIR / f"{stem}.pdf"
        path.write_bytes(builder())
        built.append(path)
    return built


def check_fixtures() -> int:
    """Fail with an actionable list when a required checked-in PDF is missing."""
    missing = [
        name
        for name in REQUIRED_PDFS
        if not (FIXTURES_DIR / name).is_file()
        or (FIXTURES_DIR / name).stat().st_size == 0
    ]
    if missing:
        print(
            "ERROR: required checked-in PDF fixture(s) are missing or empty:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  tests/fixtures/{name}", file=sys.stderr)
        print(
            "Restore the tracked PDFs (or regenerate them with "
            "`uv run python tests/fixtures/build_fixtures.py`).",
            file=sys.stderr,
        )
        return 1

    print(f"All {len(REQUIRED_PDFS)} required checked-in PDF fixtures are present.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        return check_fixtures()
    if args:
        print(f"ERROR: unknown arguments: {' '.join(args)}", file=sys.stderr)
        return 2
    if shutil.which(ENGINE) is None:
        print(
            f"ERROR: no LaTeX engine found. This script requires {ENGINE} "
            "(pdfTeX) and it is not on PATH.",
            file=sys.stderr,
        )
        print(
            "On macOS: `brew install --cask mactex-no-gui` (or `basictex`) "
            f"provides {ENGINE}; or add its bin dir to PATH, e.g. "
            '`export PATH="/Library/TeX/texbin:$PATH"`.',
            file=sys.stderr,
        )
        return 1

    # Make the canonical image available to pdflatex before compiling.
    _ensure_image()

    built: list[Path] = []
    for stem in SOURCES:
        tex_path = TEX_DIR / f"{stem}.tex"
        if not tex_path.is_file():
            print(f"ERROR: missing LaTeX source: {tex_path}", file=sys.stderr)
            return 1
        compile_source(tex_path)
        out_base = FIXTURES_DIR / tex_path.stem
        built.append(out_base.with_suffix(".pdf"))
        cleanup_aux(out_base)

    built.extend(build_programmatic_fixtures())

    print(
        f"Built {len(built)} PDF fixture(s): {len(SOURCES)} with {ENGINE}, "
        f"{len(PROGRAMMATIC_SOURCES)} programmatically."
    )
    for pdf in sorted(built):
        print(f"  {pdf.name} ({pdf.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
