# API expansion and publishing repair

## Goal / acceptance
Implement GitHub issues #6–#10 on base a077269b24594c52a944c1bcd4b06133d4766ec9: released API audit/spec, opt-in offline-first OCR, opt-in JSON-compatible position/structure/diagnostic metadata, checked-in real PDF fixtures and TeX-free CI/publishing, documentation and independent validation. Preserve existing defaults, content, page numbering and caller metadata precedence. No publishing, tags, workflow reruns or external settings changes.

## Plan
1. One implementation worker owns source/tests/docs/workflows; verify released APIs and write docs/api-update-plan.md before feature work.
2. Inspect complete diff and run lint, formatting, mypy, pytest and distribution build; exercise clean-copy tests without TeX.
3. Independent review; resolve material findings and rerun affected checks.

## Evidence / completed
- Clean initial working tree; no repository AGENTS.md found.
- Read published issues #6–#10 and CI/build configuration.
- `uv sync --group dev --locked` passed; installed released pdf-inspector 1.25.2. Verified wheel stub/runtime APIs; audit written to docs/api-update-plan.md. Python 3.12.12 used for final CI-version checks (3.14.2 also passed all checks).
- OCR implemented: `ocr_mode` off/auto/force (default off), `offline` default True, `model_directory`, `dpi`, `minimum_confidence`, `hosted_recommendation_confidence`, `password`; markdown-only; rejects positions/regions; actionable cause-preserving errors; 0→1 page translation; page mode requested order/duplicates; single-mode delimiter join; opt-in diagnostics/provenance.
- Rich metadata implemented: `include_position_metadata` (all released TextItem fields + rotation frames), `include_structure` (page/mcid/role), `include_diagnostics` (native + markdown layout + OCR provenance), page-scoped in page mode, JSON-compatible, no content rewrite, opt-in failures raised.
- Fixtures: generated 8 original LaTeX PDFs with temporary TinyTeX/pdflatex 3.141592653-2.6 (TeX Live 2026) + cm-super. Added deterministic programmatic 2-page tagged and rotated PDFs. All 10 PDFs are present in tests/fixtures and no longer gitignored (new files remain untracked pending a future commit). Builder has TeX-free `--check`; conftest fails on missing fixtures, no skips.
- CI/publish: removed apt/TeX install and fixture compilation; added fixture check, tests against checked-in PDFs, distribution content check; preserved quality gates, artifact handoff, trusted publishing. Added CI distribution build/check job.
- Tests added for OCR routing/forwarding/numbering/order/delimiters/errors/diagnostics/real auto no-model path, rich metadata serialization/scoping/tagged/rotated/caller precedence, fixture availability without TeX.
- Initial implementation checks (before review fixes): CPython 3.12.12 and 3.14.2 passed ruff/mypy/pytest (164 passed, 1 opt-in real-OCR skip). Final post-review results below supersede these counts.
- Real OCR (PDFium/ONNX/model) not executed; opt-in guarded test + README run instructions document this.

## Lead validation / review
- Local integration branch: `feat/pdf-inspector-api-and-pipeline`; no commits or pushes.
- Lead reran ruff check, ruff format --check, mypy, pytest, uv build, distribution check, fixture check, and git diff --check after the fixture correction: all passed; 165 tests passed and only the explicitly guarded real-model OCR test skipped (CPython 3.12.12).
- Lead copied every tracked/new nonignored file into a fresh temporary directory, set PATH to an empty directory, confirmed imports came from the copied source, and ran fixture check + pytest: 165 passed, 1 real-model skip, no TeX available. Removing plain_text.pdf in that copy made preflight exit 1 with an actionable error.
- Independent standards/release review found an invalid tagged-fixture ParentTree reverse mapping. Implementer corrected and regenerated it and added a raw-byte reverse-association regression; independent re-review confirmed resolution.

## Final status
All local implementation acceptance criteria covered; independent reviews and re-reviews complete with no remaining material findings. Lead reran the full quality/test/build/distribution/fixture/diff checks after all fixes on CPython 3.12.12: all pass, **176 passed, 1 opt-in real-model OCR skip**. A fresh-copy test with an empty PATH imported the copied source and reproduced 176 passed / 1 skip with no TeX. Removing a required PDF in that copy made preflight exit 1. No commits/push/tags/workflow reruns/external settings/issue closing. Issues remain open; changes are local and include untracked new files/PDFs that must accompany any future commit. Real-model OCR, encrypted-file extraction and GitHub/PyPI execution are not verified. Nonempty-password OCR intentionally rejects structure/diagnostics groups because upstream enrichment APIs cannot decrypt.

## Review resolution
- Independent review found the tagged fixture's `/ParentTree` mapped both pages to the root Document element (object 9), not each page's immediate StructElems.
- Fixed `tests/fixtures/build_fixtures.py`: `/Nums [0 [10 0 R 11 0 R 12 0 R 13 0 R] 1 [14 0 R]]` (page 0 -> MCID 0-3 parents, page 1 -> MCID 0 parent).
- Regenerated `tests/fixtures/tagged_structure.pdf` via the deterministic builder function only; `rotated_text.pdf` hash unchanged.
- Added `test_tagged_fixture_parent_tree_reverse_associations`, which parses the fixture's uncompressed object bytes directly (no rendering/pdf-inspector forward extraction) and validates `/StructParents`, `/Nums`, each immediate parent's `/Pg`/`/K` back-reference, and that the root is not an immediate parent.
- Verified: targeted metadata+OCR tests 41 passed, 1 opt-in skip; ruff check pass.

## Review resolution 2
- Finding 1: enabled OCR + non-empty `password` + `include_structure`/`include_diagnostics` was invalid because released `detect_pdf_bytes` and `extract_structure_elements_bytes` are not password-aware.
  - Parser now rejects the combination at construction before any upstream call with an actionable `ValueError` naming both APIs, the 1.25.2 limitation, OCR-without-groups, and separate decryption. Empty password remains allowed; password forwarding without groups is preserved.
  - Loader inherits the parser validation and documents the restriction.
  - Tests split password forwarding from diagnostics; added parser and loader parameterized rejections for structure/diagnostics/both with upstream mocks asserted uncalled; added empty-password acceptance.
- Finding 2: page-mode region extraction prefiltered structure by `pages`, while content used `page_regions`.
  - `_extract_structure_elements` now follows the effective branch: text region extraction uses 0-indexed `page_regions`; all other page-mode paths (including `output="markdown"`, where regions are ignored) use `pages`; single mode keeps all pages.
  - Added actual tagged-fixture regressions for differing `pages`/`page_regions` (page 2 content+tags, baseline metadata/content unchanged) and Markdown using `pages`, not regions.
  - Updated parser/loader docstrings, README, and audit doc.
- Targeted tests: 58 passed, 1 opt-in real-OCR skip; ruff check pass.
- Independent API correctness re-review confirmed both findings resolved under the explicit unsupported-combination contract, with no new material findings.

## Fresh review resolution (lead-assigned findings)
- Finding 1 (Medium): page-mode OCR `include_diagnostics` re-serialized the whole OCR result for every emitted document, including duplicate pages (N² upstream page/provenance reads).
  - TDD red: targeted `test_ocr_page_diagnostics_scan_result_once_for_many_documents` with 3 result pages and 6 page documents failed old code: 7 traversals of `result.pages` (expected <=2).
  - Fix: `_PageDiagnosticsIndex` serializes OCR diagnostics once, indexes page-number lists, OCR reasons, and serialized page/provenance entries once, then returns independent deep-copied page-scoped values per emitted document (duplicate pages included). Detection page lists/reasons are indexed on the same pass. Signatures, page ordering/duplicates/content, document-level fields/`cmap_gaps`, and JSON schema are unchanged.
  - Green: that test plus `test_ocr_page_diagnostic_copies_are_independent_per_document` pass; OCR+rich-metadata suite 50 passed, 1 opt-in real-OCR skip.
- Finding 2 (Medium): README lacked explicit pinned OCR model provisioning.
  - Verified against the **v1.25.2 tag** (commit `ef52f77850b29189048797a48b24862251f54fe7`): `docs/ocr-runtime.md` pins Firecrawl PDFium `native-v7988` (PDFium 153.0.7988.0), ONNX Runtime 1.27.0, and artifact revision `oar-ocr-v0.7.0`; `src/vision/models.rs` defines `pp-ocrv6-small` with exactly `pp-ocrv6_small_det.onnx`, `pp-ocrv6_small_rec.onnx`, `ppocrv6_dict.txt` (sizes and SHA-256s documented).
  - Verified cache layout: managed root is `PDF_INSPECTOR_MODEL_CACHE` or platform cache + `pdf-inspector/models`, then `<id>/<revision>`; explicit `model_directory` is used verbatim and never network-supplemented.
  - README now documents direct pinned runtime links, env vars, explicit opt-in warm-cache download via real `process_pdf_with_ocr_bytes(..., offline=False)`, offline reuse, exact custom directory layout, checksums, and the mapping from the resulting model directory to `PDF_INSPECTOR_REAL_OCR_MODEL_DIR`. No provisioning command was invented; no model/runtime was downloaded or installed here.
  - `docs/api-update-plan.md` updated with the verified provisioning contract and the diagnostics linearity/independence guarantee.
- Final local checks: `uv run ruff check .` pass; `uv run ruff format --check .` pass; `uv run mypy src` pass; `uv run pytest -q -rs` **178 passed, 1 opt-in real-model OCR skip**; `uv build` pass; `python3 tests/check_distribution.py` pass; `uv run python tests/fixtures/build_fixtures.py --check` pass (10 PDFs); `git diff --check` pass.
- Open: independent review pending. Not committed/merged/pushed/tagged; no external services changed. Real OCR execution remains unverified.

## Resumed audit and merge (2026-10-26)
- User approved agent-skills setup and requested implementation of audit then merge if correct. This supersedes the earlier no-push/no-merge limit for PR integration only; no tags, release publication, manual workflow reruns, or settings changes.
- Added approved AGENTS.md plus docs/agents issue-tracker, triage-labels, and single-context domain rules. Created only the four missing canonical GitHub labels; preserved existing wontfix.
- Published approved tickets: #11 parser/loader regression audit; #12 TeX-free test/distribution audit; #13 independent review/verification/merge. #13 has native blocked-by edges to #11 and #12. Original issues #6–#10 remain unchanged.
- Starting revision remains a077269b24594c52a944c1bcd4b06133d4766ec9 on feat/pdf-inspector-api-and-pipeline; origin/main matches it. All pre-existing local changes listed above are the implementation under audit and must be preserved.
- Plan: audit existing contracts and pipeline; correct only confirmed findings with regression tests; independently review standards/spec; run final quality/test/build/clean-snapshot checks; commit complete scoped change; PR to main, wait for all checks/protections, merge only the verified head.
- Acceptance: preserve defaults/selections/metadata precedence and opt-in semantics, use released 1.25.2 APIs, TeX-free real-PDF coverage and complete artifacts, no material unresolved review findings. Explicitly disclose unexecuted real-model OCR and publishing.
- Next: focused audit discovery plus fresh checks. Setup files not yet committed; no PR created or branch pushed.
- Fresh audit evidence: locked sync passed (Python 3.12.12, pdf-inspector 1.25.2). Lead independently inspected current 3.12 wheel stub and runtime signatures/result fields for OCR, positions/rotations, structure, detection and Markdown; all match the released contract. Read-only scout found no additional behavioral defect, but could not reproduce runtime/diff checks itself.
- Fresh ruff check and mypy passed; formatting initially failed one pre-existing SimpleNamespace wrapping in the OCR test. A bounded implementer corrected only that wrapping: formatting/lint/mypy now pass and OCR test file is 30 passed / 1 explicit real-model skip. Focused OCR+rich-metadata+loader-options suite before that formatting-only fix was 60 passed / 1 explicit real-model skip.
- Fixture preflight, uv build, distribution check and diff whitespace check passed. In a clean temporary snapshot with empty PATH, imports resolved to copied source, preflight passed, and removing plain_text.pdf made preflight exit 1 naming the missing fixture. Both programmatic PDFs match deterministic builder bytes; all 10 PDF payloads match the built sdist.
- Lead runtime probes confirmed auto/offline OCR restores requested [2,0,2] order/duplicates, page selection containing only nonexistent pages emits no page documents, and an empty selection returns no upstream pages (no accidental full-document OCR). No real-model OCR executed.
- Next: commit complete candidate locally to pin independent standards/spec review; then resolve findings and run final full suite in a clean TeX-free snapshot. No PR/push yet.
- Staging all new files exposed a previously hidden diff-check failure: Git treated the two small uncompressed PDFs as text and flagged PDF-required xref padding. Added narrowly scoped .gitattributes marking test PDF fixtures binary (no fixture bytes changed), so Git preserves binary treatment and does not propose text merges or line-ending conversion.
- Candidate committed locally as a1cc1033b3ef65c669029732608221b15a8778c3. Independent code-review standards and spec axes both identified loss of empty-text positioned records from rich metadata; standards additionally noted duplicated diagnostic scoping as a non-blocking judgement call.
- Lead confirmed the trigger against released 1.25.2 with a valid generated PDF containing ordinary text and an empty-URI Link annotation: upstream returns item_type='link:', text='', with geometry, but the adapter filters it out of positions.items. Existing image fixture uses a nonempty '[Image: Im1]' placeholder and did not expose the bug.
- Agreed test seam is the public PdfInspectorParser.parse(Blob) boundary from #11 (metadata preservation, unchanged content/documents). Next: one implementer uses red→green regressions at that seam, preserving historical empty-text filtering only for content/emission; no speculative diagnostic refactor.
- Implementer added RED public-seam regressions (single/page empty-link metadata; empty-only page omission/scoping) and a minimal fix: separate unfiltered per-page record index for opt-in metadata while content keeps historical text filtering. RED 3 failed on the prior behavior; GREEN 3 passed. Lead reran rich-metadata+OCR+loader-option files: 63 passed, 1 explicit real-model OCR skip; ruff check/format and mypy pass; diff check pass. No public API/doc contract change needed because the plan already promised non-text positioned items.
- Independent re-review of this follow-up could not run: subagent API returned subscription_sharing_usage_limit_exceeded. Lead performed a direct delta review (content-vs-metadata filtering, page scoping, empty-only page omission, single/page semantics, JSON/field completeness, test isolation/portability) with no additional material defect identified. This re-review limitation will be disclosed; earlier full-diff independent standards/spec reviews are complete.
- Final candidate: 2249a539273fe48e5872d21da5b4f6a9ae8ec405. Full local checks pass: ruff check, ruff format --check (22 files), mypy src, fixture preflight (10 PDFs), pytest **181 passed, 1 explicit real-model OCR skip**, clean `uv build`, distribution content check, and `git diff --check`. A clean snapshot of every tracked file, with PATH empty, imported the copied source, confirmed pdflatex unavailable, passed fixture preflight and the same **181 passed / 1 skip**, and failed preflight with exit 1 naming plain_text.pdf when it was removed.
- Remaining limitations: real-model OCR and real encrypted-file extraction were not executed; GitHub/PyPI release stages have not run. No intentional code/API contract issues remain. Duplicate diagnostic scoping was reviewed as a non-blocking maintainability judgement call, not a behavior defect.
- Next: close audit tickets #11/#12 with evidence, push branch, open PR, wait for CI/reviews, merge the verified head, then report and close #13. Original #6–#10 remain untouched. No tags, release publication, manual workflow reruns, or settings changes.
