"""Shared fixtures and marker configuration for the unit test suite.

This mirrors the ``langchain-community`` convention of a ``requires`` marker
that auto-skips a test when an optional runtime dependency is not installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# ``tests/fixtures`` relative to this conftest
# (``tests/unit_tests/conftest.py`` -> ``..`` is ``tests`` -> ``fixtures``).
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so ``--strict-markers`` does not fail."""
    config.addinivalue_line(
        "markers",
        "requires(package): skip the test unless the optional package "
        "`package` is importable",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip any test marked ``@pytest.mark.requires(pkg)`` when ``pkg``
    is not installed, mirroring ``langchain-community``'s convention."""
    for item in items:
        marker = item.get_closest_marker("requires")
        if marker is None:
            continue
        package = marker.args[0] if marker.args else None
        if package and importlib.util.find_spec(package) is None:
            item.add_marker(pytest.mark.skip(reason=f"requires package: {package}"))


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to ``tests/fixtures`` (where the built PDFs live)."""
    return FIXTURES_DIR


def _pdf_fixture(name: str):
    """Factory for a fixture that returns the absolute path to a checked-in PDF.

    The PDFs are checked into ``tests/fixtures/`` and never built by the test
    run, so no LaTeX engine is required. A missing fixture fails the test with
    an actionable message instead of silently skipping integration coverage.
    """

    @pytest.fixture
    def _fixture(fixtures_dir: Path) -> Path:
        path = fixtures_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            pytest.fail(
                f"Required checked-in fixture PDF {name!r} is missing or empty "
                f"at {path}. Restore the tracked PDF (CI requires it) or "
                "regenerate it with "
                "`uv run python tests/fixtures/build_fixtures.py` "
                "(regeneration requires pdflatex; running tests does not)."
            )
        return path

    return _fixture


plain_text_pdf = _pdf_fixture("plain_text.pdf")
headings_pdf = _pdf_fixture("headings.pdf")
lists_pdf = _pdf_fixture("lists.pdf")
two_column_pdf = _pdf_fixture("two_column.pdf")
tables_pdf = _pdf_fixture("tables.pdf")
complex_layout_pdf = _pdf_fixture("complex_layout.pdf")
cropbox_offset_pdf = _pdf_fixture("cropbox_offset.pdf")
document_info_pdf = _pdf_fixture("document_info.pdf")
tagged_structure_pdf = _pdf_fixture("tagged_structure.pdf")
rotated_text_pdf = _pdf_fixture("rotated_text.pdf")
