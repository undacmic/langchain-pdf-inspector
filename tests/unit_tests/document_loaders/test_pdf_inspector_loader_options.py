"""Loader forwarding, precedence, and fixture-availability regressions."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import pytest
from langchain_core.documents import Document
from langchain_core.documents.base import Blob

from langchain_pdf_inspector import PdfInspectorLoader


class _RecordingParser:
    """Record the loader's forwarded parser options and yield a fixed document."""

    instances: ClassVar[list[_RecordingParser]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    def parse(self, blob: Blob) -> list[Document]:
        return [
            Document(
                page_content="fake",
                metadata={
                    "source": "fake",
                    "page": 1,
                    "positions": {"items": [], "page_rotations": []},
                    "structure": {"elements": []},
                    "diagnostics": {"pdf_type": "text_based"},
                },
            )
        ]


@pytest.mark.requires("pdf_inspector")
def test_loader_forwards_ocr_and_rich_metadata_options(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loader is a thin forwarder for every new parser option."""
    _RecordingParser.instances.clear()
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.PdfInspectorParser",
        _RecordingParser,
    )

    PdfInspectorLoader(
        str(plain_text_pdf),
        mode="page",
        output="markdown",
        pages=[0, 1],
        ocr_mode="auto",
        offline=False,
        model_directory="/models/ocr",
        dpi=180.0,
        minimum_confidence=0.3,
        hosted_recommendation_confidence=0.8,
        include_structure=True,
        include_diagnostics=True,
    )

    kwargs = _RecordingParser.instances[0].kwargs
    assert kwargs["ocr_mode"] == "auto"
    assert kwargs["offline"] is False
    assert kwargs["model_directory"] == "/models/ocr"
    assert kwargs["dpi"] == 180.0
    assert kwargs["minimum_confidence"] == 0.3
    assert kwargs["hosted_recommendation_confidence"] == 0.8
    assert kwargs["include_structure"] is True
    assert kwargs["include_diagnostics"] is True
    assert kwargs["pages"] == [0, 1]


@pytest.mark.requires("pdf_inspector")
def test_loader_forwards_ocr_password_without_metadata_groups(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR password forwarding is independently supported without rich groups."""
    _RecordingParser.instances.clear()
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.PdfInspectorParser",
        _RecordingParser,
    )

    PdfInspectorLoader(
        str(plain_text_pdf),
        output="markdown",
        ocr_mode="auto",
        password="secret",
    )

    assert _RecordingParser.instances[0].kwargs["password"] == "secret"


@pytest.mark.requires("pdf_inspector")
@pytest.mark.parametrize(
    "groups",
    [
        {"include_structure": True},
        {"include_diagnostics": True},
        {"include_structure": True, "include_diagnostics": True},
    ],
)
def test_loader_rejects_ocr_password_with_metadata_groups_before_upstream(
    plain_text_pdf: Path, groups: dict[str, bool]
) -> None:
    """Parser-owned password/metadata restriction fires through the loader."""
    with (
        mock.patch("pdf_inspector.process_pdf_with_ocr_bytes") as ocr_mock,
        mock.patch("pdf_inspector.detect_pdf_bytes") as detect_mock,
        mock.patch("pdf_inspector.extract_structure_elements_bytes") as structure_mock,
        pytest.raises(ValueError, match="not password-aware"),
    ):
        PdfInspectorLoader(
            str(plain_text_pdf),
            output="markdown",
            ocr_mode="auto",
            password="secret",
            **groups,
        )

    ocr_mock.assert_not_called()
    detect_mock.assert_not_called()
    structure_mock.assert_not_called()


@pytest.mark.requires("pdf_inspector")
def test_loader_forwards_position_metadata(
    plain_text_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loader forwards the positioned-metadata opt-in."""
    _RecordingParser.instances.clear()
    monkeypatch.setattr(
        "langchain_pdf_inspector.pdf_inspector_loader.PdfInspectorParser",
        _RecordingParser,
    )

    PdfInspectorLoader(
        str(plain_text_pdf),
        extract_positions=True,
        include_position_metadata=True,
    )

    assert _RecordingParser.instances[0].kwargs["include_position_metadata"] is True


@pytest.mark.requires("pdf_inspector")
def test_caller_metadata_wins_over_opt_in_groups(
    tagged_structure_pdf: Path,
) -> None:
    """Caller metadata overrides parser-produced rich groups, not only scalars."""
    loader = PdfInspectorLoader(
        str(tagged_structure_pdf),
        include_structure=True,
        include_diagnostics=True,
        metadata={
            "page": 99,
            "structure": {"elements": ["caller"]},
            "diagnostics": {"caller": True},
        },
    )
    docs = loader.load()
    assert docs
    for doc in docs:
        assert doc.metadata["page"] == 99
        assert doc.metadata["structure"] == {"elements": ["caller"]}
        assert doc.metadata["diagnostics"] == {"caller": True}


@pytest.mark.requires("pdf_inspector")
def test_caller_metadata_wins_over_positions(plain_text_pdf: Path) -> None:
    """Caller values also win over the positioned-text group."""
    loader = PdfInspectorLoader(
        str(plain_text_pdf),
        extract_positions=True,
        include_position_metadata=True,
        metadata={"positions": "caller"},
    )
    docs = loader.load()
    assert docs[0].metadata["positions"] == "caller"


@pytest.mark.requires("pdf_inspector")
def test_loader_rejects_unsupported_ocr_combinations(plain_text_pdf: Path) -> None:
    """Parser-owned validation still runs through the loader."""
    with pytest.raises(ValueError, match="requires output='markdown'"):
        PdfInspectorLoader(str(plain_text_pdf), ocr_mode="auto")
    with pytest.raises(ValueError, match="does not support extract_positions"):
        PdfInspectorLoader(
            str(plain_text_pdf),
            output="markdown",
            ocr_mode="auto",
            extract_positions=True,
        )


def test_checked_in_pdf_fixtures_are_present_without_tex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every required fixture is checked in; ``--check`` needs no TeX engine."""
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tests" / "fixtures" / "build_fixtures.py"
    # Sanitize PATH so the check cannot accidentally rely on a local TeX
    # installation; the script uses an absolute interpreter path.
    monkeypatch.setenv("PATH", os.defpath)
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "required checked-in PDF fixtures are present" in result.stdout
