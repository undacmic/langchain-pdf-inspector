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
    """Factory for a fixture that returns the absolute path to a built PDF.

    The PDFs are produced by ``tests/fixtures/build_fixtures.py`` (LaTeX), so
    they may be absent on machines without a LaTeX engine. In that case the
    fixture skips the test with an actionable message rather than failing.
    """

    @pytest.fixture
    def _fixture(fixtures_dir: Path) -> Path:
        path = fixtures_dir / name
        if not path.is_file():
            pytest.skip(
                f"Fixture PDF {name!r} not found. Build the fixtures with "
                "`uv run python tests/fixtures/build_fixtures.py` "
                "(requires a LaTeX engine such as pdflatex or tectonic)."
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
