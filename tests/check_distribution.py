"""Check that built distributions contain the expected files and metadata.

Run after ``uv build``::

    python3 tests/check_distribution.py

This uses only the standard library so CI can run it without syncing the
project environment. It intentionally does not build anything.
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"

WHEEL_FILES = {
    "langchain_pdf_inspector/__init__.py",
    "langchain_pdf_inspector/pdf_inspector_loader.py",
    "langchain_pdf_inspector/pdf_inspector_parser.py",
    "langchain_pdf_inspector/py.typed",
}

SDIST_FILES = {
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "src/langchain_pdf_inspector/__init__.py",
    "src/langchain_pdf_inspector/pdf_inspector_loader.py",
    "src/langchain_pdf_inspector/pdf_inspector_parser.py",
    "src/langchain_pdf_inspector/py.typed",
    "tests/unit_tests/document_loaders/test_pdf_inspector_parser.py",
}


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def _check_wheel(path: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        for expected in WHEEL_FILES:
            if expected not in names:
                problems.append(f"wheel missing {expected}")
        if any(name.startswith("tests/") for name in names):
            problems.append("wheel unexpectedly contains tests/")
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            problems.append("wheel must contain exactly one METADATA file")
        else:
            metadata = archive.read(metadata_names[0]).decode("utf-8")
            if "Name: langchain-pdf-inspector" not in metadata:
                problems.append("wheel METADATA name is wrong")
            if "Requires-Python: >=3.12" not in metadata:
                problems.append("wheel METADATA Requires-Python is wrong")
            if "pdf-inspector" not in metadata or "1.25.2" not in metadata:
                problems.append("wheel METADATA pdf-inspector dependency is wrong")
            if "<2" not in metadata:
                problems.append("wheel METADATA pdf-inspector upper bound is missing")
    return problems


def _check_sdist(path: Path) -> list[str]:
    problems: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getnames()
    # Strip the single top-level ``langchain-pdf-inspector-*/`` directory.
    relative = {name.split("/", 1)[1] for name in members if "/" in name}
    for expected in SDIST_FILES:
        if expected not in relative:
            problems.append(f"sdist missing {expected}")

    fixture_names = {
        fixture.name for fixture in (REPO_ROOT / "tests" / "fixtures").glob("*.pdf")
    }
    for name in sorted(fixture_names):
        expected = f"tests/fixtures/{name}"
        if expected not in relative:
            problems.append(f"sdist missing checked-in fixture {expected}")
    return problems


def main() -> int:
    wheels = sorted(DIST_DIR.glob("*.whl"))
    sdists = sorted(DIST_DIR.glob("*.tar.gz"))
    if len(wheels) != 1:
        return _fail(f"expected exactly one wheel in {DIST_DIR}, found {len(wheels)}")
    if len(sdists) != 1:
        return _fail(f"expected exactly one sdist in {DIST_DIR}, found {len(sdists)}")

    problems = [*_check_wheel(wheels[0]), *_check_sdist(sdists[0])]
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1

    print(f"Distribution contents OK: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
