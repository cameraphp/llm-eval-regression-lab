# Plan: `llm-eval-regression-lab`

- **Spec date:** 2026-10-31
- **Status:** implemented. This plan stays in sync with the code. `tests/test_traceability.py` enforces
  the sync between the specs and the tests.
- **Companion specs:** [`requirements.md`](requirements.md) (what), [`validation.md`](validation.md) (proof)

## 1. Purpose

This is a small, local, offline reference implementation of **evaluation and regression controls** for
an LLM/RAG-style answering workflow. It does not run an LLM. A deterministic, rule-based **test double**
(the "simulator") stands in for the system under test. A transparent evaluator checks every structured
response against versioned synthetic expectations.

The project shows that the controls run as designed **on this synthetic fixture suite only**. It is not
a model benchmark. It does not show that any real model is grounded, safe, or accurate.

## 2. Scope

In scope:

- A small synthetic corpus (five fictional documents) with a version and a content hash.
- A versioned case manifest. Each case is pinned by SHA-256 and has a change-log entry.
- A strict structured-response schema with decision-specific invariants (`answer`,
  `insufficient_evidence`, `refusal`).
- Deterministic token-overlap retrieval over the case's allowed retrieval scope.
- Two declarative, rule-based simulators: **baseline** (approved behavior) and **candidate** (mostly
  identical, with documented intentional regressions).
- Lexical, fixture-bound checks for citations, answer fragments, claim support and groundedness.
- Negative-control cases. Each injects a known-bad response and must be caught with an exact,
  expected set of failure codes.
- Canonical, byte-stable run artifacts, a committed golden baseline, and a baseline-vs-candidate
  comparator with a strict gate.
- A CLI and a demo script. Both are offline and deterministic.

Non-goals:

- Calling any real LLM, embedding model, vector database, cloud API, telemetry endpoint or web API.
- Semantic entailment, broad factuality, retrieval quality, safety evaluation, or production monitoring.
- Public or real datasets, customer data, proprietary prompts or secrets.
- Git initialization, commits, pushes, repository creation or deployment.
- Any claim of production readiness or compliance.

## 3. Architecture and data flow

```text
testdata/cases/manifest.json ──► suite loader ──► verified Case objects (hash + change-log checked)
testdata/corpus/*.json ────────► corpus loader ─► verified Corpus (synthetic flags, version, hash)
model_manifests/*.json ────────► manifest loader ► ModelManifest (+ prompt file, SHA-256 pin verified)

for each case (sorted by case_id):
   behavior case:          simulator(case, corpus, manifest) ─► raw JSON response
   negative-control case:  injected raw response from the case file
   evaluator(case, raw, corpus, active metadata) ─► checks, failure codes, groundedness

run artifact (canonical JSON) ─► artifacts/<name>.json        (generated, git-ignored)
golden baseline ───────────────► testdata/golden/baseline_results_v1.json (reviewed, committed)
comparator(golden, candidate artifact, approvals) ─► classifications + gate exit code
```

Modules (`src/llm_eval_regression_lab/`):

| Module | Responsibility |
|---|---|
| `canonical.py` | Canonical JSON, SHA-256 helpers, LF-normalized file hashing, text normalization |
| `schemas.py` | Data contracts, controlled vocabularies, response schema and decision invariants |
| `corpus.py` | Corpus loading and validation |
| `suite.py` | Suite manifest loading, case-hash and change-log integrity |
| `manifests.py` | Prompt and model-manifest loading, prompt hash pin, behavior revision |
| `retrieval.py` | Deterministic tokenization and token-overlap retrieval |
| `simulator.py` | Rule-based test double (labelled as not AI inference) |
| `evaluators.py` | Response evaluation, citation/claim/groundedness checks, negative controls |
| `regression.py` | Suite runner, run artifact, comparator, approvals |
| `reporting.py` | Human-readable summaries and the non-claims statement |
| `offline.py` | Network guard for deterministic offline mode |
| `cli.py` | `run`, `compare`, `validate-suite` and `hash` commands |

## 4. Design choices

1. **Why simulators and not a real LLM.** The goal is to show that the *controls* work: schema
   validation, citation checks, groundedness thresholds and regression gating. A deterministic
   test double makes every outcome reproducible and reviewable. It needs no credentials or network,
   so a failing check always points at the code or the fixtures, never at model sampling. The
   simulators are declared as `"kind": "rule_based_test_double"` and `"is_ai_inference": false`.
2. **Declarative behavior.** Each simulator's behavior lives entirely in its model manifest:
   refusal rules, answer rules and retrieval settings. The `behavior_revision` is the SHA-256 of that
   canonical behavior block, so any behavior change produces a new revision.
3. **Lexical, fixture-bound checks.** Citations and claims are checked by normalized substring match
   against the synthetic corpus. This check is transparent and deterministic. It is **not**
   semantic entailment, and the docs say so wherever groundedness is reported.
4. **Negative controls inside the suite.** Each bad-output category (out-of-scope citation, invented
   quote, unsupported extra claim, malformed JSON, version mismatch) is a versioned case with an
   injected response and an exact expected set of failure codes. If the evaluator misses one, or
   over-reports, the suite fails.
5. **Comparison classifications.**
   - `pass`: both runs pass and behavior is unchanged, or a pinned approval covers the change.
   - `regression`: the candidate fails a case the baseline passed, a case fails in both runs, a
     negative control is missed, or a case is missing.
   - `expected_failure_demo`: a negative control is caught in both runs.
   - `new_or_unapproved_behavior`: a new case, a case version or hash drift, or changed but passing
     behavior with no pinned approval.

   Regressions can never be approved. The only way to change an expectation is to bump the case
   version.
6. **Exit codes.** `0` means success. `1` means the gate failed: a run has failing cases, or the
   comparison has blocking classifications. `2` means an input, integrity, or comparability error.
   The default compare mode blocks on `regression`. `--strict` also blocks on
   `new_or_unapproved_behavior`.

## 5. Reproducibility controls

- Fixed, versioned fixtures: the corpus, the cases, the prompts and the model manifests.
- Stable ordering: cases are sorted by `case_id`, retrieval breaks ties by `document_id`, and all
  JSON keys are sorted.
- Canonical JSON: `sort_keys=True`, `indent=2`, `ensure_ascii=False`, `\n` line endings, UTF-8, and a
  trailing newline.
- No timestamps, randomness, hostnames, usernames or absolute paths in run artifacts or the golden
  file. Paths are relative POSIX paths.
- Content hashes. JSON inputs are hashed as canonical JSON. Text inputs (prompts) are hashed as
  UTF-8 with LF line endings, so CRLF checkouts produce the same hash.
- No dependence on `PYTHONHASHSEED`. A test runs the CLI under two different seeds and compares the
  output bytes.
- Offline guard: the CLI disables `socket` connections before doing any work, and the test session
  does the same.

## 6. Fixture versioning

- A case file carries `case_id` and a semantic `case_version`. The manifest pins each case's path
  and canonical SHA-256 and lists every version in `change_log`.
- To change an expected behavior:
  1. Add a new file (for example `v2/<name>.json`) with a bumped `case_version`.
  2. Mark the old manifest entry `"status": "superseded"`. Never edit or delete the old file.
  3. Add a `change_log` entry with the reason.
  4. Regenerate and review the golden baseline.
- The suite loader rejects a hash mismatch, a missing change-log entry, a duplicate
  `(case_id, case_version)`, or a missing superseded file.
- Prompts are versioned files (`rag_answering_v1.md`, `rag_answering_v2.md`) with front matter. Each
  model manifest pins the SHA-256 of its prompt.

## 7. Risk controls

| Risk | Control |
|---|---|
| Results mistaken for real model quality | `synthetic_benchmark_only: true` and a non-claims text in every artifact, report and README |
| Simulator mistaken for AI inference | `kind` and `is_ai_inference: false` in each manifest, plus the naming in the docs |
| Silent change to expectations | Case hash pinning, change log, golden byte comparison |
| Hidden regression | The comparator ignores the candidate's documentation fields. The demo fails if the documented regression disappears or the baseline fails |
| Network or secret leakage | No runtime dependencies, offline guard, static import scan, secret-pattern scan |
| Spec drift | The traceability test checks that every requirement ID is mapped and every referenced test exists |

## 8. Toolchain

- Python 3.13.7. It is the only interpreter available locally; 3.12 was preferred, and 3.13 is
  supported. `requires-python = ">=3.11"`.
- Runtime dependencies: none (standard library only).
- Dev dependencies, pinned in `pyproject.toml` and `requirements-dev.lock`: `pytest`, `ruff`.
- A project-local `.venv`. Installing the dev tools into it is the only network use, and it happens
  at setup only.
