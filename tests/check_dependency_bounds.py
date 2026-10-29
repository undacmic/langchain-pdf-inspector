"""Report installed runtime versions and optionally enforce exact declared floors.

Run after syncing a compatibility environment, without re-syncing it::

    uv run --no-sync python tests/check_dependency_bounds.py --minimum
"""

from __future__ import annotations

import argparse
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_dependencies(dependencies: list[str], *, minimum: bool) -> list[str]:
    """Return actionable errors for missing, out-of-range, or non-floor versions."""
    problems: list[str] = []
    for dependency in dependencies:
        requirement = Requirement(dependency)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            installed = Version(version(requirement.name))
        except PackageNotFoundError:
            problems.append(f"{requirement.name} is not installed")
            continue
        print(f"{requirement.name}=={installed} (declared: {requirement.specifier})")
        if installed not in requirement.specifier:
            problems.append(f"{requirement.name}=={installed} violates {requirement}")
        if minimum:
            floors = [
                Version(specifier.version)
                for specifier in requirement.specifier
                if specifier.operator == ">="
            ]
            if not floors:
                problems.append(f"{requirement.name} has no declared >= lower bound")
            elif installed != max(floors):
                problems.append(
                    f"{requirement.name}=={installed}; expected minimum {max(floors)}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum", action="store_true")
    args = parser.parse_args()
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    problems = check_dependencies(
        project["project"]["dependencies"], minimum=args.minimum
    )
    for problem in problems:
        print(f"ERROR: {problem}")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
