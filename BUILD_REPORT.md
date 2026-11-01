# Build report: `llm-eval-regression-lab`

- **Build date:** 2026-10-31
- **Location:** `C:\Users\camer\github\improvement-plan\llm-eval-regression-lab`
- **Status:** built and validated locally. All acceptance checks pass. At the conclusion of the
  local build and validation phase, there was no Git repository, commit, push, remote, GitHub
  repository or deployment.
- **Report scope:** this report covers the local, deterministic validation evidence. The
  subsequent owner-authorized publication and CI observation are recorded in Git history and
  GitHub Actions; this local build report does not retroactively claim them.
- **Prerequisite check:** the Priority B project (`legacy-web-hardening-lab`) has a BUILD_REPORT.md
  that records its validation: 53 automated checks passed, 0 failed. That report was the only
  check made, and Priority B was not modified.

> This project evaluates deterministic fixtures against a small synthetic benchmark. Results
> demonstrate that the included checks execute as designed for these fixtures only. They do not
> establish real LLM, RAG, safety, groundedness, or production performance.

## 1. Environment and toolchain

| Item | Value |
|---|---|
| OS | Windows 11 Pro 10.0.26200 |
| Python | 3.13.7. It is the only interpreter `py -0p` reports. 3.12 was preferred and is not installed; 3.13 is supported (`requires-python >=3.11`) |
| Virtual environment | Project-local `.venv`. Nothing was installed globally |
| Runtime dependencies | **None** (standard library only) |
| Dev dependencies | `pytest==9.1.1`, `ruff==0.16.9`. The build backend is `setuptools==80.9.0` |
| Full resolved set | `requirements-dev.lock`: colorama 0.4.6, iniconfig 2.3.1, packaging 26.3, pip 25.2, pluggy 1.7.0, Pygments 2.21.0, pytest 9.1.1, ruff 0.16.9, setuptools 80.9.0 |
| Package install | `pip install --no-deps --no-build-isolation --no-index -e .` (offline) |

The only network use was a one-time setup step: `pip install` of the three pinned dev tools from
the Python package index into `.venv`. No project code, test, CLI command or demo uses the network.

Preflight (run before any file was created):
- `Get-Location` returned `C:\Users\camer\github\improvement-plan`.
- `python --version` returned `Python 3.13.7`.
- `py -0p` listed only `-V:3.13 *`.
- `Get-ChildItem -Force` confirmed that `llm-eval-regression-lab` did not exist.

## 2. Specification-driven development and traceability

- **Order:** `plan.md`, then `requirements.md`, then `validation.md`, all written before any source
  file. Source code came only after the three specs agreed with each other.
- **Requirement IDs:** 31 in total. REQ-001 to REQ-019 are functional, NFR-001 to NFR-006 are
  non-functional, and SAFE-001 to SAFE-006 cover safety and honesty.
- **Coverage:** every ID has its own section in `validation.md` (implementation, named tests,
  command, expected result, artifact, failure meaning) and a row in the traceability matrix.
- **Enforcement:** `tests/test_traceability.py` checks that:
  - every ID in `requirements.md` has both a section and a matrix row with a named test;
  - every test name `validation.md` references exists in `tests/`.
- **Post-implementation spec edit:** one. In `validation.md`, the REQ-019 `-k` expression
  `test_doubles` was changed to `declare_test_doubles`, because the traceability test (correctly)
  treated it as a reference to a test that does not exist.

## 3. Deviations from the prompt's suggested structure

| Suggested | Built | Reason |
|---|---|---|
| `no_context_refusal.json` | `no_context_insufficient_evidence.json` | Required case 4 says empty context must yield `insufficient_evidence`, not a refusal. The name now matches the behavior |
| One `citation_fabrication.json` | Plus `citation_out_of_scope.json` | Required cases 6 (wrong/out-of-scope citation) and 7 (invented quote) are distinct failure classes |
| Response field `refusal_reason` | `reason_code` + `message` | Both non-answer pathways need controlled codes, and `message` must be the exact controlled text for its code |
| Module list | Adds `canonical.py`, `suite.py`, `manifests.py`, `offline.py` | Keeps hashing, manifest integrity, prompt/model tracking and the network guard separate and testable |
| none | `testdata/approvals/`, `requirements-dev.lock`, `tests/conftest.py` | Pinned approvals for changed-but-passing behavior, a lock artifact, and shared fixtures |

## 4. File inventory

| Area | Files |
|---|---|
| Specs | `specs/2026-10-31-llm-eval-regression/{plan,requirements,validation}.md` |
| Source (13 files) | `src/llm_eval_regression_lab/`: `__init__`, `canonical`, `schemas`, `corpus`, `suite`, `manifests`, `retrieval`, `simulator`, `evaluators`, `regression`, `reporting`, `offline`, `cli` |
| Prompts | `prompts/rag_answering_v1.md` (1.0.0), `prompts/rag_answering_v2.md` (2.0.0) |
| Model manifests | `model_manifests/deterministic-baseline-v1.json`, `model_manifests/deterministic-candidate-v2.json` |
| Fixtures | `testdata/corpus/synthetic_corpus_v1.json`, `testdata/cases/manifest.json`, 10 case files in `testdata/cases/v1/` |
| Golden evidence | `testdata/golden/baseline_results_v1.json` |
| Approvals | `testdata/approvals/candidate_v2_approvals.json` |
| Tests | `tests/conftest.py` and 6 test modules |
| Scripts | `scripts/run_demo.py` |
| Docs and config | `README.md`, `BUILD_REPORT.md`, `pyproject.toml`, `requirements-dev.lock`, `.gitignore` |
| Generated (ignored, safe to delete) | `artifacts/`, `.venv/`, `.ruff_cache/`, `src/*.egg-info/` |

## 5. Validation results

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `python -m pytest -q` | 0 | **92 passed** in about 5.5 s |
| 2 | `python -m ruff check .` | 0 | `All checks passed!` |
| 3 | `cli validate-suite --suite testdata/cases/manifest.json` | 0 | `SUITE OK`: 10 active cases, corpus `synthetic-corpus-v1` (5 documents) |
| 4 | `cli run --fixture baseline ... --output artifacts/baseline_run.json` | 0 | 5/5 behavior cases passed, 5/5 controls detected, `RUN RESULT: PASS` |
| 5 | Same command again, to `artifacts/baseline_run_2.json` | 0 | Byte-identical (see §6) |
| 6 | `cli run --fixture candidate ... --output artifacts/candidate_run.json` | 1 | 3/5 behavior cases passed (intentional), 5/5 controls detected |
| 7 | `cli compare --baseline testdata/golden/... --candidate artifacts/candidate_run.json --approvals ... --strict` | **1** | `GATE: FAIL`. Blocking: `rag-insufficient-001`, `rag-supported-multi-001` |
| 8 | `python scripts/run_demo.py` | 0 | `BASELINE: PASS`, `CANDIDATE STRICT COMPARISON: FAILED (expected demonstration)`, `DEMO RESULT: OK` |

Tests per module:

| Module | Tests |
|---|---|
| `test_schemas.py` | 21 |
| `test_retrieval.py` | 6 |
| `test_evaluators.py` | 22 |
| `test_regression.py` | 23 |
| `test_offline_demo.py` | 9 |
| `test_traceability.py` | 11 |

### Mutation check: the tests detect broken controls

Each mutation was applied to a throwaway copy in the session scratchpad, never to the project
tree, and then the full suite was run:

| Mutation | Result |
|---|---|
| Quote-substring citation check disabled | 15 failed |
| Sentence claim-coverage check disabled | 16 failed |
| Comparator allows approvals to cover failing cases | 1 failed (`test_approvals_cannot_suppress_regressions`) |

## 6. Deterministic run evidence

SHA-256, from `Get-FileHash`:

| File | SHA-256 |
|---|---|
| `artifacts/baseline_run.json` | `7953D766488E5576522D21FE11B67E2CC65C9C180A919EF17EB8C895EEC24475` |
| `artifacts/baseline_run_2.json` | `7953D766488E5576522D21FE11B67E2CC65C9C180A919EF17EB8C895EEC24475` |
| `testdata/golden/baseline_results_v1.json` | `7953D766488E5576522D21FE11B67E2CC65C9C180A919EF17EB8C895EEC24475` |

- `test_cli_baseline_run_is_byte_stable_across_processes` runs the CLI in two subprocesses
  (`PYTHONHASHSEED=1` and `=4242`) and checks that both outputs are byte-identical to the golden
  file.
- The golden file contains no timestamps, no randomness, no absolute or user-specific paths, and
  no CRLF. Separate tests assert each of these.
- No metadata is excluded from the byte comparison. Run artifacts carry no non-golden fields, so
  the whole file is compared.
- Pinned hashes:
  - corpus: `4fde3d7d…34c3ea`
  - suite manifest: `c41c13dc…a261da`
  - prompt v1: `f1118528…8a8f7d`
  - prompt v2: `f5b32920…6b40a9`
  - baseline `behavior_revision`: `1377e2be935d…`
  - candidate `behavior_revision`: `fadd5d380810…`

The golden file came from the first baseline run. Before it was committed to `testdata/golden/`,
its run summary was reviewed: 5/5 behavior cases passed, each of the 5 negative controls produced
exactly its expected codes, and groundedness was 1.0 for both answer cases. From then on, any
drift fails `test_baseline_run_matches_golden_bytes`.

## 7. Intentional regression evidence

Strict comparison of the golden baseline against the candidate (`deterministic-candidate@2.0.0`,
prompt `2.0.0`):

| Case | Classification | Detail |
|---|---|---|
| `rag-supported-multi-001` | **regression** | Expense quote misattributed to SYN-001. `CITATION_QUOTE_NOT_FOUND`, `CITATION_REQUIRED_MISSING`, `CLAIM_UNSUPPORTED`, `GROUNDEDNESS_BELOW_MIN` (1.0 → 0.5), `ANSWER_SENTENCE_UNSUPPORTED` |
| `rag-insufficient-001` | **regression** | Invented allowance leaked. `DECISION_MISMATCH`, `UNSUPPORTED_ANSWER_LEAKAGE`, `ANSWER_FORBIDDEN_FRAGMENT`, `ANSWER_SENTENCE_UNSUPPORTED` |
| `rag-supported-001` | pass (approved) | Wording change. The approval is pinned to both behavior fingerprints |
| 5 negative controls | expected_failure_demo | Detected with their exact expected codes in both runs |
| `rag-no-context-001`, `rag-refusal-001` | pass | Behavior unchanged |

Counts: pass=3, regression=2, expected_failure_demo=5, new_or_unapproved_behavior=0. Gate: `fail`,
exit 1.

Why this regression cannot be silently passed:
- Approvals never apply to regressions (`test_approvals_cannot_suppress_regressions`).
- The comparator ignores the candidate's documentation fields
  (`test_comparator_ignores_documented_intentional_regressions`).
- The demo fails if the regression disappears (`test_demo_fails_if_regression_disappears`).

## 8. Known limitations

- The checks are lexical and fixture-bound: normalized substring matching. A correct paraphrase
  can fail, and a lexically matching but misleading answer could pass. This is not semantic
  entailment or factuality checking.
- The simulators are hand-written rule tables. They exercise the evaluator and the gate. They do
  not model LLM variability.
- The suite is tiny: 5 documents and 10 cases. Retrieval is simple token overlap, with no
  stemming and no ranking-quality claims.
- Sentence splitting is regex-based (`[.!?]` followed by whitespace).
- The offline guard patches `socket` in-process. It cannot stop native extensions or child
  processes that bypass Python's `socket`, and none are used.
- SAFE-003 ("no `.git` created") is a procedural check recorded here. It is deliberately not an
  automated test, so that the suite keeps passing if the owner later initializes Git.

## 9. Safety confirmations

| Confirmation | Evidence |
|---|---|
| No real LLM, embedding, vector-store, cloud, telemetry or web API was called | No such dependency or import (`test_source_has_no_network_or_model_sdk_imports`). The offline guard was active during tests, CLI and demo |
| No API keys, `.env` files or credentials | `.env*` file count = 0. The secret-pattern scan passes |
| No customer, medical, financial, public or proprietary data | The corpus is 5 fictional "Example Org" documents, all flagged synthetic. Every case has a synthetic fixture note |
| No Git operation during the local build and validation phase | At the end of that phase, `Test-Path .git` returned `False` for the project and its parent. No `git` invocation in code, scripts or tests |
| No GitHub repository, remote or push during the local build and validation phase | None was created or configured during that phase |
| No deployment | Local files only |
| No other repository modified | All writes were inside `llm-eval-regression-lab/`. The scratchpad helper scripts live outside the project and are not part of it |
