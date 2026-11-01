# Validation: `llm-eval-regression-lab`

- **Spec date:** 2026-10-31
- **Purpose:** maps every requirement in [`requirements.md`](requirements.md) to its implementation,
  named tests, exact commands, expected results, output artifact and failure interpretation.
- **Enforcement:** `tests/test_traceability.py` checks two things. Every requirement ID appears in
  the matrix in §3. Every `tests/...::test_...` reference in this file names a test that exists.

## 1. Global commands

All commands run from the project root inside the activated `.venv`.

| # | Command | Expected result |
|---|---|---|
| G1 | `python -m pytest -q` | All tests pass, 0 failures |
| G2 | `python -m ruff check .` | `All checks passed!` |
| G3 | `python -m llm_eval_regression_lab.cli validate-suite --suite testdata/cases/manifest.json` | Exit 0, `SUITE OK` |
| G4 | `python -m llm_eval_regression_lab.cli run --fixture baseline --suite testdata/cases/manifest.json --output artifacts/baseline_run.json` | Exit 0. The artifact is byte-identical to `testdata/golden/baseline_results_v1.json` |
| G5 | `python -m llm_eval_regression_lab.cli run --fixture candidate --suite testdata/cases/manifest.json --output artifacts/candidate_run.json` | Exit 1 (candidate has failing behavior cases). The artifact is written |
| G6 | `python -m llm_eval_regression_lab.cli compare --baseline testdata/golden/baseline_results_v1.json --candidate artifacts/candidate_run.json --approvals testdata/approvals/candidate_v2_approvals.json --strict --output artifacts/comparison.json` | Exit 1. `regression` for `rag-insufficient-001` and `rag-supported-multi-001` |
| G7 | `python scripts/run_demo.py` | Exit 0. Prints `BASELINE: PASS` and `CANDIDATE STRICT COMPARISON: FAILED (expected demonstration)` |

Failure interpretation, all commands: a failure means either a control or contract is broken, or
the fixtures or specs drifted. Never "fix" a failure by weakening an assertion or editing the golden
file without a reviewed, versioned change (see README, "Adding a case").

## 2. Per-requirement validation

### REQ-001 Synthetic, versioned corpus
- **Implementation:** `src/llm_eval_regression_lab/corpus.py` (`load_corpus`, `validate_corpus_dict`)
- **Tests:** `tests/test_schemas.py::test_corpus_loads_with_synthetic_flags_and_hash`,
  `tests/test_schemas.py::test_corpus_rejects_non_synthetic_document`,
  `tests/test_schemas.py::test_corpus_rejects_duplicate_ids_and_version_mismatch`
- **Command:** `python -m pytest -q tests/test_schemas.py -k corpus`
- **Expected:** 3 passed. The corpus loads 5 documents under `synthetic-corpus-v1`. Bad corpora
  raise `SchemaError`.
- **Artifact:** `corpus` block of the run artifact (`corpus_version`, `sha256`, `document_count`).
- **Failure means:** the loader accepts non-synthetic, duplicate or inconsistent documents.

### REQ-002 Versioned case manifest
- **Implementation:** `src/llm_eval_regression_lab/suite.py` (`load_suite`)
- **Tests:** `tests/test_regression.py::test_suite_manifest_integrity_passes`,
  `tests/test_regression.py::test_case_hash_tampering_is_rejected`,
  `tests/test_regression.py::test_case_version_requires_change_log_entry`,
  `tests/test_regression.py::test_duplicate_case_version_rejected`,
  `tests/test_regression.py::test_superseded_case_file_must_be_retained`
- **Command:** `python -m pytest -q tests/test_regression.py -k "suite_manifest or tampering or change_log or duplicate_case or superseded"`
- **Expected:** 5 passed. Each tampering scenario raises `SuiteIntegrityError`.
- **Artifact:** `suite` block (`suite_id`, `suite_version`, `manifest_sha256`). Each case has
  `case_sha256`.
- **Failure means:** historical expectations could be silently overwritten.

### REQ-003 Case contract
- **Implementation:** `src/llm_eval_regression_lab/schemas.py` (`parse_case`)
- **Tests:** `tests/test_schemas.py::test_all_suite_cases_satisfy_case_contract`,
  `tests/test_schemas.py::test_case_contract_rejects_missing_or_unknown_fields`,
  `tests/test_schemas.py::test_answer_case_requires_claims_and_citations`
- **Command:** `python -m pytest -q tests/test_schemas.py -k case`
- **Expected:** 3 passed.
- **Artifact:** none (input contract).
- **Failure means:** cases could omit expectations, scope or synthetic labelling.

### REQ-004 Structured response schema
- **Implementation:** `src/llm_eval_regression_lab/schemas.py` (`parse_response`, `validate_response`)
- **Tests:** `tests/test_schemas.py::test_valid_answer_response_passes_schema`,
  `tests/test_schemas.py::test_malformed_json_is_rejected`,
  `tests/test_schemas.py::test_missing_and_extra_fields_are_rejected`,
  `tests/test_schemas.py::test_invalid_decision_value_is_rejected`,
  `tests/test_schemas.py::test_bad_semver_and_citation_shape_are_rejected`
- **Command:** `python -m pytest -q tests/test_schemas.py -k "response or malformed or fields or decision_value or semver"`
- **Expected:** 5 passed. Malformed inputs yield `SCHEMA_INVALID`.
- **Artifact:** `failure_codes` per case (see `rag-malformed-001` in the golden file).
- **Failure means:** malformed simulator output could be scored as valid.

### REQ-005 Decision-specific invariants
- **Implementation:** `src/llm_eval_regression_lab/schemas.py` (`validate_response`,
  `CONTROLLED_MESSAGES`)
- **Tests:** `tests/test_schemas.py::test_answer_requires_text_and_citation`,
  `tests/test_schemas.py::test_insufficient_evidence_forbids_answer_and_citations`,
  `tests/test_schemas.py::test_refusal_requires_documented_reason_code`,
  `tests/test_schemas.py::test_controlled_message_must_match_reason_code`
- **Command:** `python -m pytest -q tests/test_schemas.py -k "requires or forbids or controlled"`
- **Expected:** 4 passed.
- **Artifact:** `failure_codes` (`UNSUPPORTED_ANSWER_LEAKAGE`, `DECISION_INVARIANT_VIOLATION`).
- **Failure means:** a refusal or insufficient-evidence response could leak an answer.

### REQ-006 Deterministic retrieval
- **Implementation:** `src/llm_eval_regression_lab/retrieval.py` (`tokenize`, `retrieve`)
- **Tests:** `tests/test_retrieval.py::test_tokenize_is_lowercase_and_drops_stopwords`,
  `tests/test_retrieval.py::test_retrieval_respects_scope`,
  `tests/test_retrieval.py::test_retrieval_orders_by_score_then_document_id`,
  `tests/test_retrieval.py::test_retrieval_excludes_zero_overlap_and_empty_scope`,
  `tests/test_retrieval.py::test_retrieval_applies_top_k`,
  `tests/test_retrieval.py::test_retrieval_is_repeatable`
- **Command:** `python -m pytest -q tests/test_retrieval.py`
- **Expected:** 6 passed.
- **Artifact:** `retrieved_document_ids` per case.
- **Failure means:** retrieval is unstable, or it leaks documents outside the case scope.

### REQ-007 Citation validation
- **Implementation:** `src/llm_eval_regression_lab/evaluators.py` (`_check_citations`)
- **Tests:** `tests/test_evaluators.py::test_out_of_scope_citation_fails`,
  `tests/test_evaluators.py::test_unknown_document_citation_fails`,
  `tests/test_evaluators.py::test_invented_quote_with_valid_id_fails`,
  `tests/test_evaluators.py::test_quote_match_is_normalized`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k "citation or quote"`
- **Expected:** 4 passed.
- **Artifact:** `checks` entries with `check_id` `citation:<n>`.
- **Failure means:** fabricated or out-of-scope citations could pass.

### REQ-008 Answer fragment checks
- **Implementation:** `src/llm_eval_regression_lab/evaluators.py` (`_check_fragments`)
- **Tests:** `tests/test_evaluators.py::test_missing_required_fragment_fails`,
  `tests/test_evaluators.py::test_forbidden_fragment_fails`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k fragment`
- **Expected:** 2 passed.
- **Artifact:** `checks` entries `required_fragment:*` and `forbidden_fragment:*`.
- **Failure means:** wrong or prohibited content could pass.

### REQ-009 Fixture-bound groundedness and claim coverage
- **Implementation:** `src/llm_eval_regression_lab/evaluators.py` (`_check_claims`,
  `_check_sentence_coverage`)
- **Tests:** `tests/test_evaluators.py::test_supported_single_source_case_passes_with_full_groundedness`,
  `tests/test_evaluators.py::test_supported_multi_source_attributes_each_claim`,
  `tests/test_evaluators.py::test_groundedness_is_fixture_bound_proportion`,
  `tests/test_evaluators.py::test_unsupported_additional_claim_fails_claim_coverage`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k "grounded or claim or multi_source"`
- **Expected:** 4 passed. A partial attribution yields groundedness `0.5`.
- **Artifact:** `groundedness`, `supported_claims` and `total_claims` per case.
- **Failure means:** unsupported claims could pass, or the score is miscomputed.

### REQ-010 Insufficient-evidence pathway
- **Implementation:** `src/llm_eval_regression_lab/simulator.py`,
  `src/llm_eval_regression_lab/evaluators.py`
- **Tests:** `tests/test_evaluators.py::test_insufficient_evidence_case_has_no_answer_leakage`,
  `tests/test_evaluators.py::test_empty_context_yields_stable_insufficient_evidence`,
  `tests/test_evaluators.py::test_answer_leakage_where_non_answer_expected_is_detected`,
  `tests/test_evaluators.py::test_wrong_reason_code_is_detected`,
  `tests/test_evaluators.py::test_same_question_answers_when_evidence_in_scope`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k "insufficient or empty_context or leakage or reason_code or in_scope"`
- **Expected:** 5 passed.
- **Artifact:** `rag-insufficient-001` and `rag-no-context-001` results.
- **Failure means:** the system could guess an answer where no evidence exists.

### REQ-011 Refusal pathway
- **Implementation:** `src/llm_eval_regression_lab/simulator.py` (refusal rules first),
  `src/llm_eval_regression_lab/evaluators.py`
- **Tests:** `tests/test_evaluators.py::test_policy_refusal_has_reason_and_no_prohibited_detail`,
  `tests/test_evaluators.py::test_refusal_is_checked_before_retrieval`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k refusal`
- **Expected:** 2 passed.
- **Artifact:** `rag-refusal-001` result.
- **Failure means:** a restricted request could get an answer, or be confused with missing evidence.

### REQ-012 Prompt and model version tracking
- **Implementation:** `src/llm_eval_regression_lab/manifests.py`,
  `src/llm_eval_regression_lab/evaluators.py` (`_check_metadata`)
- **Tests:** `tests/test_regression.py::test_prompt_hash_pin_mismatch_rejected`,
  `tests/test_regression.py::test_prompt_hash_is_line_ending_independent`,
  `tests/test_regression.py::test_behavior_revision_changes_with_rules`,
  `tests/test_evaluators.py::test_metadata_version_mismatch_fails`,
  `tests/test_evaluators.py::test_case_id_mismatch_fails`
- **Command:** `python -m pytest -q tests/test_regression.py tests/test_evaluators.py -k "prompt_hash or behavior_revision or metadata or case_id_mismatch"`
- **Expected:** 5 passed.
- **Artifact:** `prompt` and `model` blocks of the run artifact.
- **Failure means:** results could be attributed to the wrong prompt or behavior version.

### REQ-013 Canonical run artifact
- **Implementation:** `src/llm_eval_regression_lab/regression.py` (`run_suite`),
  `src/llm_eval_regression_lab/canonical.py`
- **Tests:** `tests/test_regression.py::test_run_artifact_records_versions_and_non_claims`,
  `tests/test_regression.py::test_baseline_run_passes_all_cases`
- **Command:** `python -m pytest -q tests/test_regression.py -k "run_artifact or baseline_run_passes"`
- **Expected:** 2 passed.
- **Artifact:** `artifacts/baseline_run.json`.
- **Failure means:** the provenance of a result cannot be reconstructed.

### REQ-014 Negative-control cases
- **Implementation:** `src/llm_eval_regression_lab/evaluators.py` (`evaluate_negative_control`)
- **Tests:** `tests/test_evaluators.py::test_negative_controls_match_expected_failure_codes_exactly`,
  `tests/test_evaluators.py::test_missed_negative_control_fails_run`,
  `tests/test_evaluators.py::test_over_reported_control_is_not_detected`
- **Command:** `python -m pytest -q tests/test_evaluators.py -k control`
- **Expected:** 3 passed. All 5 controls are `control_detected` in the baseline run.
- **Artifact:** `status: control_detected` for the five negative-control cases.
- **Failure means:** the evaluator no longer catches a known-bad output class.

### REQ-015 Baseline vs candidate comparison
- **Implementation:** `src/llm_eval_regression_lab/regression.py` (`compare_runs`)
- **Tests:** `tests/test_regression.py::test_candidate_comparison_surfaces_intentional_regressions`,
  `tests/test_regression.py::test_identical_runs_compare_as_pass`,
  `tests/test_regression.py::test_new_case_classified_as_new_or_unapproved`,
  `tests/test_regression.py::test_missing_case_in_candidate_is_regression`,
  `tests/test_regression.py::test_incomparable_artifacts_are_rejected`
- **Command:** `python -m pytest -q tests/test_regression.py -k "comparison or compare or new_case or missing_case or incomparable"`
- **Expected:** 5 passed.
- **Artifact:** `artifacts/comparison.json`.
- **Failure means:** behavior changes could go unclassified.

### REQ-016 Gate, approvals and exit codes
- **Implementation:** `src/llm_eval_regression_lab/regression.py` (`compare_runs`,
  `load_approvals`), `src/llm_eval_regression_lab/cli.py`
- **Tests:** `tests/test_regression.py::test_strict_mode_fails_on_unapproved_behavior_change`,
  `tests/test_regression.py::test_approval_is_pinned_to_fingerprints`,
  `tests/test_regression.py::test_approvals_cannot_suppress_regressions`,
  `tests/test_offline_demo.py::test_cli_strict_compare_fails_for_candidate`,
  `tests/test_offline_demo.py::test_cli_compare_baseline_against_golden_passes`,
  `tests/test_offline_demo.py::test_cli_run_exit_codes`
- **Command:** `python -m pytest -q tests/test_regression.py tests/test_offline_demo.py -k "strict or approval or cli_compare or cli_run_exit"`
- **Expected:** 6 passed. The strict candidate compare exits 1, and the baseline against the golden
  file exits 0.
- **Artifact:** the `gate` block of `artifacts/comparison.json`.
- **Failure means:** a regression or unapproved change could pass CI silently.

### REQ-017 Golden baseline
- **Implementation:** `testdata/golden/baseline_results_v1.json`,
  `src/llm_eval_regression_lab/regression.py`
- **Tests:** `tests/test_regression.py::test_baseline_run_matches_golden_bytes`,
  `tests/test_offline_demo.py::test_cli_baseline_run_is_byte_stable_across_processes`
- **Command:** `python -m pytest -q -k "golden or byte_stable"`
- **Expected:** 2 passed.
- **Artifact:** the golden file.
- **Failure means:** the baseline drifted. Review the diff, then version the change deliberately.

### REQ-018 Demo script
- **Implementation:** `scripts/run_demo.py`
- **Tests:** `tests/test_offline_demo.py::test_demo_script_reports_baseline_pass_and_expected_regression`
- **Command:** `python scripts/run_demo.py`
- **Expected:** exit 0. The output contains `BASELINE: PASS` and
  `CANDIDATE STRICT COMPARISON: FAILED (expected demonstration)`.
- **Artifact:** `artifacts/demo/` (baseline runs, candidate run, comparison JSON and Markdown).
- **Failure means:** the documented demonstration no longer matches the system's behavior.

### REQ-019 Simulators are declared test doubles
- **Implementation:** `model_manifests/*.json`, `src/llm_eval_regression_lab/simulator.py`
- **Tests:** `tests/test_regression.py::test_model_manifests_declare_test_doubles_not_ai`,
  `tests/test_regression.py::test_candidate_differs_only_by_documented_variants`
- **Command:** `python -m pytest -q tests/test_regression.py -k "declare_test_doubles or documented_variants"`
- **Expected:** 2 passed.
- **Artifact:** `model.kind` in the run artifacts.
- **Failure means:** the candidate changed in undocumented ways, or the simulators are mislabelled.

### NFR-001 Determinism
- **Implementation:** `src/llm_eval_regression_lab/canonical.py`, sorted iteration everywhere
- **Tests:** `tests/test_offline_demo.py::test_cli_baseline_run_is_byte_stable_across_processes`,
  `tests/test_offline_demo.py::test_no_timestamps_or_absolute_paths_in_golden`,
  `tests/test_retrieval.py::test_retrieval_is_repeatable`
- **Command:** `python -m pytest -q -k "byte_stable or timestamps or repeatable"`
- **Expected:** 3 passed. Two subprocess runs with `PYTHONHASHSEED=1` and `=4242` are byte-identical.
- **Artifact:** `artifacts/baseline_run.json` and the golden file.
- **Failure means:** the output depends on hidden state.

### NFR-002 Offline execution
- **Implementation:** `src/llm_eval_regression_lab/offline.py`, `tests/conftest.py`
- **Tests:** `tests/test_offline_demo.py::test_offline_guard_blocks_network`,
  `tests/test_traceability.py::test_source_has_no_network_or_model_sdk_imports`
- **Command:** `python -m pytest -q -k "offline_guard or network"`
- **Expected:** 2 passed.
- **Artifact:** none.
- **Failure means:** a code path could reach the network.

### NFR-003 Minimal, pinned toolchain
- **Implementation:** `pyproject.toml`, `requirements-dev.lock`
- **Tests:** `tests/test_traceability.py::test_runtime_dependencies_are_empty_and_dev_pinned`
- **Command:** `python -m pytest -q tests/test_traceability.py -k dependencies`
- **Expected:** 1 passed.
- **Artifact:** none.
- **Failure means:** an unpinned or runtime dependency was introduced.

### NFR-004 Lint cleanliness
- **Implementation:** `[tool.ruff]` in `pyproject.toml`
- **Tests:** `tests/test_traceability.py::test_ruff_check_passes`
- **Command:** `python -m ruff check .`
- **Expected:** `All checks passed!`
- **Artifact:** none.
- **Failure means:** there are lint findings to fix in the code. Do not ignore them.

### NFR-005 Portability of evidence
- **Implementation:** `src/llm_eval_regression_lab/canonical.py` (`write_canonical_json`,
  `sha256_text_file`)
- **Tests:** `tests/test_offline_demo.py::test_artifacts_use_lf_and_relative_paths`,
  `tests/test_regression.py::test_prompt_hash_is_line_ending_independent`
- **Command:** `python -m pytest -q -k "lf_and_relative or line_ending"`
- **Expected:** 2 passed.
- **Artifact:** the golden file (LF only, no drive letters).
- **Failure means:** the evidence would differ between machines or checkouts.

### NFR-006 Spec-to-test traceability
- **Implementation:** this file, `tests/test_traceability.py`
- **Tests:** `tests/test_traceability.py::test_every_requirement_has_validation_entry`,
  `tests/test_traceability.py::test_validation_references_existing_tests`,
  `tests/test_traceability.py::test_specs_exist_with_required_sections`
- **Command:** `python -m pytest -q tests/test_traceability.py -k "requirement or references or specs"`
- **Expected:** 3 passed.
- **Artifact:** none.
- **Failure means:** the specs and the implementation drifted.

### SAFE-001 No network, model SDK or vector store
- **Implementation:** the import policy across `src/`
- **Tests:** `tests/test_traceability.py::test_source_has_no_network_or_model_sdk_imports`,
  `tests/test_traceability.py::test_runtime_dependencies_are_empty_and_dev_pinned`
- **Command:** `python -m pytest -q tests/test_traceability.py -k "imports or dependencies"`
- **Expected:** 2 passed.
- **Artifact:** none.
- **Failure means:** a forbidden client was introduced.

### SAFE-002 No secrets
- **Implementation:** `.gitignore`, fixture policy
- **Tests:** `tests/test_traceability.py::test_no_secret_files_or_credential_patterns`,
  `tests/test_traceability.py::test_gitignore_excludes_env_and_artifacts`
- **Command:** `python -m pytest -q tests/test_traceability.py -k "secret or gitignore"`
- **Expected:** 2 passed.
- **Artifact:** none.
- **Failure means:** a secret-like file or pattern exists. Remove it and do not commit.

### SAFE-003 No Git operations
- **Implementation:** the import policy across `src/`, `scripts/`, `tests/`
- **Tests:** `tests/test_traceability.py::test_source_does_not_invoke_subprocess_or_git`
- **Command:** `python -m pytest -q tests/test_traceability.py -k git`. The procedural check, run
  once at build time, is `Test-Path .git`, which must return `False`. It is recorded in
  BUILD_REPORT.md.
- **Expected:** 1 passed.
- **Artifact:** BUILD_REPORT.md §Safety confirmations.
- **Failure means:** code could alter version-control state.

### SAFE-004 Synthetic data only
- **Implementation:** `testdata/corpus/synthetic_corpus_v1.json`, `testdata/cases/v1/*.json`
- **Tests:** `tests/test_schemas.py::test_corpus_loads_with_synthetic_flags_and_hash`,
  `tests/test_schemas.py::test_all_suite_cases_satisfy_case_contract`,
  `tests/test_traceability.py::test_fixtures_are_labelled_synthetic`
- **Command:** `python -m pytest -q -k "synthetic or case_contract"`
- **Expected:** 3 passed.
- **Artifact:** `corpus` block of the run artifact.
- **Failure means:** non-synthetic data may have entered the fixtures.

### SAFE-005 Benchmark evidence vs production non-claims
- **Implementation:** `src/llm_eval_regression_lab/reporting.py` (`NON_CLAIMS`), README.md
- **Tests:** `tests/test_regression.py::test_run_artifact_records_versions_and_non_claims`,
  `tests/test_regression.py::test_comparison_report_carries_non_claims`,
  `tests/test_traceability.py::test_readme_contains_non_claims_statement`
- **Command:** `python -m pytest -q -k non_claims`
- **Expected:** 3 passed.
- **Artifact:** the `non_claims` field in every artifact.
- **Failure means:** the evidence could be misread as a production claim.

### SAFE-006 Intentional regression is never hidden
- **Implementation:** `src/llm_eval_regression_lab/regression.py`, `scripts/run_demo.py`
- **Tests:** `tests/test_regression.py::test_comparator_ignores_documented_intentional_regressions`,
  `tests/test_offline_demo.py::test_demo_script_reports_baseline_pass_and_expected_regression`,
  `tests/test_offline_demo.py::test_demo_fails_if_regression_disappears`
- **Command:** `python -m pytest -q -k "documented_intentional or demo"`
- **Expected:** 3 passed.
- **Artifact:** `artifacts/demo/comparison.json`.
- **Failure means:** a regression could be suppressed or mislabelled as a pass.

## 3. Traceability matrix

| ID | Implementation | Tests |
|---|---|---|
| REQ-001 | `corpus.py` | `test_schemas.py::test_corpus_loads_with_synthetic_flags_and_hash`, `test_corpus_rejects_non_synthetic_document`, `test_corpus_rejects_duplicate_ids_and_version_mismatch` |
| REQ-002 | `suite.py` | `test_regression.py::test_suite_manifest_integrity_passes`, `test_case_hash_tampering_is_rejected`, `test_case_version_requires_change_log_entry`, `test_duplicate_case_version_rejected`, `test_superseded_case_file_must_be_retained` |
| REQ-003 | `schemas.py` | `test_schemas.py::test_all_suite_cases_satisfy_case_contract`, `test_case_contract_rejects_missing_or_unknown_fields`, `test_answer_case_requires_claims_and_citations` |
| REQ-004 | `schemas.py` | `test_schemas.py::test_valid_answer_response_passes_schema`, `test_malformed_json_is_rejected`, `test_missing_and_extra_fields_are_rejected`, `test_invalid_decision_value_is_rejected`, `test_bad_semver_and_citation_shape_are_rejected` |
| REQ-005 | `schemas.py` | `test_schemas.py::test_answer_requires_text_and_citation`, `test_insufficient_evidence_forbids_answer_and_citations`, `test_refusal_requires_documented_reason_code`, `test_controlled_message_must_match_reason_code` |
| REQ-006 | `retrieval.py` | `test_retrieval.py` (6 tests) |
| REQ-007 | `evaluators.py` | `test_evaluators.py::test_out_of_scope_citation_fails`, `test_unknown_document_citation_fails`, `test_invented_quote_with_valid_id_fails`, `test_quote_match_is_normalized` |
| REQ-008 | `evaluators.py` | `test_evaluators.py::test_missing_required_fragment_fails`, `test_forbidden_fragment_fails` |
| REQ-009 | `evaluators.py` | `test_evaluators.py::test_supported_single_source_case_passes_with_full_groundedness`, `test_supported_multi_source_attributes_each_claim`, `test_groundedness_is_fixture_bound_proportion`, `test_unsupported_additional_claim_fails_claim_coverage` |
| REQ-010 | `simulator.py`, `evaluators.py` | `test_evaluators.py::test_insufficient_evidence_case_has_no_answer_leakage`, `test_empty_context_yields_stable_insufficient_evidence`, `test_answer_leakage_where_non_answer_expected_is_detected`, `test_wrong_reason_code_is_detected`, `test_same_question_answers_when_evidence_in_scope` |
| REQ-011 | `simulator.py`, `evaluators.py` | `test_evaluators.py::test_policy_refusal_has_reason_and_no_prohibited_detail`, `test_refusal_is_checked_before_retrieval` |
| REQ-012 | `manifests.py`, `evaluators.py` | `test_regression.py::test_prompt_hash_pin_mismatch_rejected`, `test_prompt_hash_is_line_ending_independent`, `test_behavior_revision_changes_with_rules`; `test_evaluators.py::test_metadata_version_mismatch_fails`, `test_case_id_mismatch_fails` |
| REQ-013 | `regression.py`, `canonical.py` | `test_regression.py::test_run_artifact_records_versions_and_non_claims`, `test_baseline_run_passes_all_cases` |
| REQ-014 | `evaluators.py` | `test_evaluators.py::test_negative_controls_match_expected_failure_codes_exactly`, `test_missed_negative_control_fails_run`, `test_over_reported_control_is_not_detected` |
| REQ-015 | `regression.py` | `test_regression.py::test_candidate_comparison_surfaces_intentional_regressions`, `test_identical_runs_compare_as_pass`, `test_new_case_classified_as_new_or_unapproved`, `test_missing_case_in_candidate_is_regression`, `test_incomparable_artifacts_are_rejected` |
| REQ-016 | `regression.py`, `cli.py` | `test_regression.py::test_strict_mode_fails_on_unapproved_behavior_change`, `test_approval_is_pinned_to_fingerprints`, `test_approvals_cannot_suppress_regressions`; `test_offline_demo.py::test_cli_strict_compare_fails_for_candidate`, `test_cli_compare_baseline_against_golden_passes`, `test_cli_run_exit_codes` |
| REQ-017 | golden file, `regression.py` | `test_regression.py::test_baseline_run_matches_golden_bytes`; `test_offline_demo.py::test_cli_baseline_run_is_byte_stable_across_processes` |
| REQ-018 | `scripts/run_demo.py` | `test_offline_demo.py::test_demo_script_reports_baseline_pass_and_expected_regression` |
| REQ-019 | `model_manifests/`, `simulator.py` | `test_regression.py::test_model_manifests_declare_test_doubles_not_ai`, `test_candidate_differs_only_by_documented_variants` |
| NFR-001 | `canonical.py` | `test_offline_demo.py::test_cli_baseline_run_is_byte_stable_across_processes`, `test_no_timestamps_or_absolute_paths_in_golden`; `test_retrieval.py::test_retrieval_is_repeatable` |
| NFR-002 | `offline.py`, `tests/conftest.py` | `test_offline_demo.py::test_offline_guard_blocks_network`; `test_traceability.py::test_source_has_no_network_or_model_sdk_imports` |
| NFR-003 | `pyproject.toml`, `requirements-dev.lock` | `test_traceability.py::test_runtime_dependencies_are_empty_and_dev_pinned` |
| NFR-004 | `pyproject.toml` | `test_traceability.py::test_ruff_check_passes` |
| NFR-005 | `canonical.py` | `test_offline_demo.py::test_artifacts_use_lf_and_relative_paths`; `test_regression.py::test_prompt_hash_is_line_ending_independent` |
| NFR-006 | `validation.md`, `test_traceability.py` | `test_traceability.py::test_every_requirement_has_validation_entry`, `test_validation_references_existing_tests`, `test_specs_exist_with_required_sections` |
| SAFE-001 | `src/` import policy | `test_traceability.py::test_source_has_no_network_or_model_sdk_imports`, `test_runtime_dependencies_are_empty_and_dev_pinned` |
| SAFE-002 | `.gitignore` | `test_traceability.py::test_no_secret_files_or_credential_patterns`, `test_gitignore_excludes_env_and_artifacts` |
| SAFE-003 | `src/`, `scripts/`, `tests/` | `test_traceability.py::test_source_does_not_invoke_subprocess_or_git`. Procedural: `Test-Path .git` returns `False` |
| SAFE-004 | `testdata/` | `test_schemas.py::test_corpus_loads_with_synthetic_flags_and_hash`, `test_all_suite_cases_satisfy_case_contract`; `test_traceability.py::test_fixtures_are_labelled_synthetic` |
| SAFE-005 | `reporting.py`, README.md | `test_regression.py::test_run_artifact_records_versions_and_non_claims`, `test_comparison_report_carries_non_claims`; `test_traceability.py::test_readme_contains_non_claims_statement` |
| SAFE-006 | `regression.py`, `scripts/run_demo.py` | `test_regression.py::test_comparator_ignores_documented_intentional_regressions`; `test_offline_demo.py::test_demo_script_reports_baseline_pass_and_expected_regression`, `test_demo_fails_if_regression_disappears` |
