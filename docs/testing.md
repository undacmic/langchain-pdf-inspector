# Testing and code quality

## Required checks

Run from the repository root after `uv sync --group dev --locked`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python tests/fixtures/build_fixtures.py --check
uv run pytest
uv build
python3 tests/check_distribution.py
```

CI runs these checks. The pre-commit hooks also run lint, formatting, typing,
and the full test suite for Python changes. Ruff checks include import sorting,
Python modernization, and Bugbear's correctness rules in addition to its default
checks. Mypy runs in strict mode over `src`, including fully parameterized public
API types.

## Compatibility and dependency bounds

CI and publishing call the same `.github/workflows/compatibility.yml` workflow.
Every matrix job runs the full fixture-backed suite and independently enforces
100% statement and branch coverage; results are not combined to hide gaps.

| Platform | Python | Dependencies |
| --- | --- | --- |
| Ubuntu | 3.12, 3.13, 3.14 | Committed `uv.lock` |
| macOS (`macos-15`) | 3.12 | Committed `uv.lock` |
| Windows | 3.12 | Committed `uv.lock` |
| Ubuntu | 3.12, 3.14 | Lowest direct versions and latest allowed versions |

The locked jobs use `uv sync --group dev --locked`. Bound-testing jobs use
`--upgrade` and `--resolution lowest-direct` or `--resolution highest` to resolve
freshly within `pyproject.toml`'s constraints. `lowest-direct` minimizes direct
requirements while allowing compatible current transitive dependencies; it does
not try to minimize the entire transitive graph. The additional
`tests/check_dependency_bounds.py --minimum` check requires every active runtime
dependency to equal its declared `>=` floor, so a resolver silently choosing a
newer version cannot produce a false lower-bound pass. A floor that cannot be
installed with the other requirements fails the job and needs explicit review.

To reproduce a bound test, use a **disposable checkout**: these commands rewrite
its lockfile and environment. Do not commit the generated bound-testing lockfile.

```bash
uv sync --python 3.12 --group dev --upgrade --resolution lowest-direct
uv run --no-sync python tests/check_dependency_bounds.py --minimum
uv pip check
uv run --no-sync pytest

uv sync --python 3.14 --group dev --upgrade --resolution highest
uv run --no-sync python tests/check_dependency_bounds.py
uv pip check
uv run --no-sync pytest
```

All post-resolution commands use `--no-sync` where applicable to preserve the
selected environment. CI also runs weekly on Monday at 06:23 UTC and can be
triggered manually, catching upstream dependency changes without a source commit.
The provisioned-model OCR smoke test remains opt-in in every matrix job.

## Action pins and automated updates

Every third-party workflow action is pinned to a full commit SHA with its release
tag in a same-line comment. `.github/dependabot.yml` schedules weekly, grouped
update PRs for GitHub Actions and the native `uv` ecosystem. Python updates are
`lockfile-only`: changing the library's minimum versions or supported major
ranges remains an explicit decision. Dependabot PRs must pass the same checks;
no automatic merge or publishing authority is granted.

When updating an action manually, verify its upstream release reference and use
the peeled commit for annotated tags, not the tag-object SHA. Keep the release
comment current so Dependabot can track the pin.

## Coverage is a gate, not the test specification

`pyproject.toml` configures coverage over the entire `langchain_pdf_inspector`
package, including modules that tests never import. Branch measurement is enabled
in the coverage configuration, so it also applies outside pytest. The full suite
fails below **100% statement and branch coverage**; there must be no missing
executable statements or branch destinations.

A focused development run may use `uv run pytest path/to/test.py --no-cov`.
That is not a substitute for the full coverage-gated suite before merging.

Do not meet the threshold by omitting production modules, adding coverage
exclusions to executable behavior, or calling code without asserting its result.
The type-checking-only imports are not runtime behavior. Every new behavior or bug
fix needs a test that would fail if that behavior regressed.

## LangChain contracts

The integration implements LangChain's `BaseLoader` and `BaseBlobParser`
interfaces. Follow the upstream [document-loader interface][loaders] and
[BaseLoader implementation contract][base-loader], and consult the
[standard-test guidance][standard-tests] for applicable integration types.
The contract tests here exercise the loader/parser interfaces directly rather
than applying a chat-model or vector-store suite to a PDF loader.

- Implement synchronous streaming in `lazy_load()` / `lazy_parse()`. Do not
  materialize the parser's full document list in the loader before yielding.
  Upstream extraction APIs may still extract a whole PDF before yielding pages;
  the adapter must not add another eager document-consumption step.
- Leave `load()`, `aload()`, and `alazy_load()` to the `BaseLoader` adapters.
  Test that eager, streaming, and inherited async loading preserve content,
  ordering, and metadata.
- Return ordinary `Document` instances with string content and a stable `source`.
  Test page selection and the distinction between 0-indexed inputs and 1-indexed
  page metadata. Assert the documented caller-metadata override behavior.
- Verify that blob parsing and path loading agree. Test that downstream parser
  failures are propagated without preventing an earlier document from being
  consumed.

## Meaningful tests

- Prefer checked-in real PDFs for extraction semantics: assert recognizable
  content, absence of excluded text, page order/count, layout flags, and metadata
  values. Type assertions or non-empty output alone are not sufficient.
- Mock external boundaries for downloads, unavailable OCR runtimes/models, and
  backend failures or unusual metadata. Do not mock away the extraction behavior
  a test claims to verify. Preserve and assert exception causes for failures.
- Cover malformed/truncated PDFs, empty and image-only pages, empty crops,
  out-of-range and duplicate selections, and downloaded-file cleanup.
- Register new PDF fixtures in `tests/unit_tests/conftest.py` and
  `tests/fixtures/build_fixtures.py`. Check in the PDF and its source; the routine
  suite must fail, not skip, if a required fixture is missing. Running tests
  requires neither TeX nor network access.
- Keep OCR model downloads out of the routine suite. The explicitly enabled,
  provisioned-model OCR smoke test may skip by default; deterministic tests must
  still cover OCR routing, option forwarding, provenance, and failure handling.
- Prefer semantic assertions over byte-for-byte PDF or renderer-dependent markup
  snapshots. Parameterize equivalent contracts across extraction paths without
  weakening path-specific assertions.

[loaders]: https://docs.langchain.com/oss/python/integrations/document_loaders
[base-loader]: https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/document_loaders/base.py
[standard-tests]: https://docs.langchain.com/oss/python/contributing/standard-tests-langchain
