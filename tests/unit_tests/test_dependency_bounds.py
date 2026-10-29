"""Guard against bound-testing jobs silently testing newer or incompatible versions."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from tests import check_dependency_bounds


@pytest.mark.parametrize(
    ("installed", "minimum", "expected_error"),
    [
        ("2.31.0", True, None),
        ("2.34.2", False, None),
        ("2.34.2", True, "expected minimum 2.31"),
        ("3.0.0", False, "violates requests<3,>=2.31"),
        ("2.30.0", False, "violates requests<3,>=2.31"),
    ],
)
def test_check_dependencies_validates_range_and_exact_minimum(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    installed: str,
    minimum: bool,
    expected_error: str | None,
) -> None:
    monkeypatch.setattr(check_dependency_bounds, "version", lambda _: installed)
    problems = check_dependency_bounds.check_dependencies(
        ["requests>=2.31,<3"], minimum=minimum
    )
    assert f"requests=={installed}" in capsys.readouterr().out
    if expected_error is None:
        assert problems == []
    else:
        assert any(expected_error in problem for problem in problems)


def test_minimum_check_rejects_an_undeclared_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check_dependency_bounds, "version", lambda _: "2.31.0")
    assert check_dependency_bounds.check_dependencies(["requests<3"], minimum=True) == [
        "requests has no declared >= lower bound"
    ]


def test_check_dependencies_reports_a_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_: str) -> str:
        raise PackageNotFoundError("requests")

    monkeypatch.setattr(check_dependency_bounds, "version", missing)
    assert check_dependency_bounds.check_dependencies(
        ["requests>=2.31"], minimum=False
    ) == ["requests is not installed"]


def test_check_dependencies_respects_environment_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lookup(_: str) -> str:
        pytest.fail("inactive platform requirements must not be looked up")

    monkeypatch.setattr(check_dependency_bounds, "version", unexpected_lookup)
    assert (
        check_dependency_bounds.check_dependencies(
            ['requests>=2.31; python_version < "3.0"'], minimum=True
        )
        == []
    )
