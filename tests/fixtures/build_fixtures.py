"""Build the LaTeX-based PDF fixtures for testing.

This script compiles each ``.tex`` source under ``tests/fixtures/tex/`` into a
``.pdf`` in the fixtures directory using the installed LaTeX engine.

Engine: ``pdflatex`` (pdfTeX). The build uses whatever pdflatex is installed
(the latest available); it only fails if ``pdflatex`` is not on ``PATH`` at
all.

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


def main() -> int:
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

    print(f"Built {len(built)} PDF fixture(s) using {ENGINE}:")
    for pdf in sorted(built):
        print(f"  {pdf.name} ({pdf.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
