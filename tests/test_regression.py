"""Suite integrity, version tracking, run artifacts, golden baseline, comparison and gate.

REQ-002, REQ-012, REQ-013, REQ-015, REQ-016, REQ-017, REQ-019, SAFE-005, SAFE-006.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from conftest import APPROVALS_PATH, GOLDEN_PATH, PROJECT_ROOT

from llm_eval_regression_lab.canonical import (
    canonical_json,
    read_json,
    sha256_json_file,
    sha256_text_file,
)
from llm_eval_regression_lab.evaluators import EVALUATOR_VERSION
from llm_eval_regression_lab.manifests import ManifestError, load_model_manifest
from llm_eval_regression_lab.regression import (
    ComparisonError,
    compare_runs,
    load_approvals,
    run_suite,
)
from llm_eval_regression_lab.reporting import NON_CLAIMS
from llm_eval_regression_lab.suite import SuiteIntegrityError, load_suite

INTENTIONAL = {"rag-insufficient-001", "rag-supported-multi-001"}


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def testdata(tmp_path) -> Path:
    """A disposable copy of testdata/; returns the copied manifest path."""
    shutil.copytree(PROJECT_ROOT / "testdata", tmp_path / "testdata")
    return tmp_path / "testdata" / "cases" / "manifest.json"


@pytest.fixture
def manifests_copy(tmp_path) -> Path:
    shutil.copytree(PROJECT_ROOT / "model_manifests", tmp_path / "model_manifests")
    shutil.copytree(PROJECT_ROOT / "prompts", tmp_path / "prompts")
    return tmp_path


def approvals():
    return load_approvals(APPROVALS_PATH)


def golden():
    return read_json(GOLDEN_PATH)


def classes(report):
    return {c["case_id"]: c["classification"] for c in report["cases"]}


# ---- REQ-002 suite integrity ------------------------------------------------------------------


def test_suite_manifest_integrity_passes(suite):
    assert suite.suite_id == "rag-regression-suite"
    assert suite.suite_version == "1.0.0"
    ids = [e.case.case_id for e in suite.cases]
    assert ids == sorted(ids) and len(ids) == 10
    assert all(len(e.sha256) == 64 for e in suite.cases)


def test_case_hash_tampering_is_rejected(testdata):
    path = testdata.parent / "v1" / "supported_single_source.json"
    obj = read_json(path)
    obj["expected"]["min_groundedness"] = 0.5  # silently weaken an expectation
    write_json(path, obj)
    with pytest.raises(SuiteIntegrityError, match="sha256 mismatch"):
        load_suite(testdata)


def test_case_version_requires_change_log_entry(testdata):
    manifest = read_json(testdata)
    manifest["change_log"] = [
        c for c in manifest["change_log"] if c["case_id"] != "rag-refusal-001"
    ]
    write_json(testdata, manifest)
    with pytest.raises(SuiteIntegrityError, match="no change_log entry"):
        load_suite(testdata)


def test_duplicate_case_version_rejected(testdata):
    manifest = read_json(testdata)
    manifest["cases"].append(dict(manifest["cases"][0]))
    write_json(testdata, manifest)
    with pytest.raises(SuiteIntegrityError, match="duplicate case version"):
        load_suite(testdata)


def test_superseded_case_file_must_be_retained(testdata):
    # Proper expectation change: new v2 file + bumped version + superseded entry + change log.
    v1 = testdata.parent / "v1" / "supported_single_source.json"
    v2_dir = testdata.parent / "v2"
    v2_dir.mkdir()
    obj = read_json(v1)
    obj["case_version"] = "1.1.0"
    obj["expected"]["forbidden_answer_fragments"].append("same day")
    v2 = v2_dir / "supported_single_source.json"
    write_json(v2, obj)
    manifest = read_json(testdata)
    for entry in manifest["cases"]:
        if entry["case_id"] == "rag-supported-001":
            entry["status"] = "superseded"
    manifest["cases"].append(
        {
            "case_id": "rag-supported-001",
            "case_version": "1.1.0",
            "path": "v2/supported_single_source.json",
            "sha256": sha256_json_file(v2),
            "status": "active",
        }
    )
    manifest["change_log"].append(
        {
            "case_id": "rag-supported-001",
            "case_version": "1.1.0",
            "change": "expectation_changed",
            "reason": "test: forbid 'same day' wording",
        }
    )
    write_json(testdata, manifest)
    loaded = load_suite(testdata)
    active = {e.case.case_id: e.case.case_version for e in loaded.cases}
    assert active["rag-supported-001"] == "1.1.0"

    # Deleting the historical file is rejected.
    v1.unlink()
    with pytest.raises(SuiteIntegrityError, match="historical files must be kept"):
        load_suite(testdata)


# ---- REQ-012 prompt/model tracking ------------------------------------------------------------


def test_prompt_hash_pin_mismatch_rejected(manifests_copy):
    prompt = manifests_copy / "prompts" / "rag_answering_v1.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\n6. Be extra helpful.\n",
                      encoding="utf-8")
    with pytest.raises(ManifestError, match="sha256 mismatch"):
        load_model_manifest(manifests_copy / "model_manifests" / "deterministic-baseline-v1.json")


def test_prompt_hash_is_line_ending_independent(manifests_copy):
    prompt = manifests_copy / "prompts" / "rag_answering_v1.md"
    lf_hash = sha256_text_file(prompt)
    text = prompt.read_bytes().decode("utf-8").replace("\r\n", "\n")
    prompt.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert b"\r\n" in prompt.read_bytes()
    assert sha256_text_file(prompt) == lf_hash
    manifest = load_model_manifest(
        manifests_copy / "model_manifests" / "deterministic-baseline-v1.json"
    )
    assert manifest.prompt.sha256 == lf_hash


def test_behavior_revision_changes_with_rules(manifests_copy, baseline_manifest):
    path = manifests_copy / "model_manifests" / "deterministic-baseline-v1.json"
    obj = read_json(path)
    obj["description"] = "documentation-only edit"
    write_json(path, obj)
    doc_only = load_model_manifest(path)
    assert doc_only.behavior_revision == baseline_manifest.behavior_revision
    assert doc_only.manifest_sha256 != baseline_manifest.manifest_sha256

    obj["behavior"]["answer_rules"][0]["answer"] = "Travel requests are due 14 days ahead."
    write_json(path, obj)
    assert load_model_manifest(path).behavior_revision != baseline_manifest.behavior_revision


# ---- REQ-019 simulators are declared test doubles ---------------------------------------------


def test_model_manifests_declare_test_doubles_not_ai(manifests_copy, baseline_manifest,
                                                     candidate_manifest):
    for manifest in (baseline_manifest, candidate_manifest):
        assert manifest.kind == "rule_based_test_double"
    for name in ("deterministic-baseline-v1.json", "deterministic-candidate-v2.json"):
        assert read_json(PROJECT_ROOT / "model_manifests" / name)["is_ai_inference"] is False
    path = manifests_copy / "model_manifests" / "deterministic-baseline-v1.json"
    obj = read_json(path)
    obj["is_ai_inference"] = True
    write_json(path, obj)
    with pytest.raises(ManifestError, match="is_ai_inference"):
        load_model_manifest(path)


def test_candidate_differs_only_by_documented_variants():
    base = read_json(PROJECT_ROOT / "model_manifests" / "deterministic-baseline-v1.json")
    cand = read_json(PROJECT_ROOT / "model_manifests" / "deterministic-candidate-v2.json")
    assert base["behavior"]["retrieval"] == cand["behavior"]["retrieval"]
    assert base["behavior"]["refusal_rules"] == cand["behavior"]["refusal_rules"]
    base_rules = {r["rule_id"]: r for r in base["behavior"]["answer_rules"]}
    cand_rules = {r["rule_id"]: r for r in cand["behavior"]["answer_rules"]}
    changed = {rid for rid in cand_rules if base_rules.get(rid) != cand_rules[rid]}
    assert set(base_rules) <= set(cand_rules)  # nothing silently removed
    documented = {
        n["rule_id"]
        for n in cand["documented_intentional_regressions"] + cand["documented_approved_changes"]
    }
    assert changed == documented
    assert {n["case_id"] for n in cand["documented_intentional_regressions"]} == INTENTIONAL


# ---- REQ-013 / REQ-017 run artifact and golden ------------------------------------------------


def test_baseline_run_passes_all_cases(baseline_artifact):
    summary = baseline_artifact["summary"]
    assert summary == {
        "total_cases": 10,
        "behavior_cases": 5,
        "behavior_passed": 5,
        "behavior_failed": 0,
        "negative_controls": 5,
        "controls_detected": 5,
        "controls_missed": 0,
        "run_passed": True,
    }


def test_baseline_run_matches_golden_bytes(baseline_artifact):
    assert canonical_json(baseline_artifact).encode("utf-8") == GOLDEN_PATH.read_bytes()


def test_run_artifact_records_versions_and_non_claims(baseline_artifact, suite):
    a = baseline_artifact
    assert a["synthetic_benchmark_only"] is True
    assert a["non_claims"] == NON_CLAIMS
    assert a["fixture_mode"] == "deterministic-offline"
    assert a["evaluator_version"] == EVALUATOR_VERSION
    assert a["suite"] == {
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "manifest_sha256": suite.manifest_sha256,
    }
    assert a["corpus"]["corpus_version"] == "synthetic-corpus-v1"
    assert a["corpus"]["sha256"] == suite.corpus.sha256
    assert a["prompt"]["prompt_id"] == "rag_answering"
    assert a["prompt"]["prompt_version"] == "1.0.0"
    assert a["model"]["kind"] == "rule_based_test_double"
    assert a["model"]["is_ai_inference"] is False
    assert len(a["model"]["behavior_revision"]) == 64
    for case in a["cases"]:
        assert case["case_version"] == "1.0.0"
        assert len(case["case_sha256"]) == 64
        assert len(case["behavior_fingerprint"]) == 64


# ---- REQ-015 / REQ-016 comparison and gate ----------------------------------------------------


def test_candidate_comparison_surfaces_intentional_regressions(candidate_artifact):
    items, sha = approvals()
    report = compare_runs(golden(), candidate_artifact, items, strict=True, approvals_sha256=sha)
    cls = classes(report)
    assert {cid for cid, c in cls.items() if c == "regression"} == INTENTIONAL
    assert cls["rag-supported-001"] == "pass"
    assert next(c for c in report["cases"] if c["case_id"] == "rag-supported-001")["approved"]
    assert report["counts"] == {
        "pass": 3,
        "regression": 2,
        "expected_failure_demo": 5,
        "new_or_unapproved_behavior": 0,
    }
    multi = next(c for c in report["cases"] if c["case_id"] == "rag-supported-multi-001")
    assert (multi["baseline_groundedness"], multi["candidate_groundedness"]) == (1.0, 0.5)
    assert report["gate"]["result"] == "fail"
    assert sorted(report["gate"]["blocking_cases"]) == sorted(INTENTIONAL)
    # Non-strict mode still blocks on regressions.
    assert compare_runs(golden(), candidate_artifact, items)["gate"]["result"] == "fail"


def test_identical_runs_compare_as_pass(baseline_artifact):
    report = compare_runs(golden(), baseline_artifact, strict=True)
    assert report["gate"]["result"] == "pass"
    assert report["counts"]["pass"] == 5
    assert report["counts"]["expected_failure_demo"] == 5


def _baseline_with(case_from_candidate: str, candidate_artifact):
    """Golden baseline with exactly one case swapped in from the candidate run."""
    mixed = copy.deepcopy(golden())
    mixed["cases"] = [
        next(c for c in candidate_artifact["cases"] if c["case_id"] == case_from_candidate)
        if case["case_id"] == case_from_candidate
        else case
        for case in mixed["cases"]
    ]
    return mixed


def test_strict_mode_fails_on_unapproved_behavior_change(candidate_artifact):
    changed = _baseline_with("rag-supported-001", candidate_artifact)
    strict = compare_runs(golden(), changed, strict=True)
    assert classes(strict)["rag-supported-001"] == "new_or_unapproved_behavior"
    assert strict["gate"]["result"] == "fail"
    assert compare_runs(golden(), changed, strict=False)["gate"]["result"] == "pass"
    items, _ = approvals()
    assert compare_runs(golden(), changed, items, strict=True)["gate"]["result"] == "pass"


def test_approval_is_pinned_to_fingerprints(candidate_artifact):
    changed = _baseline_with("rag-supported-001", candidate_artifact)
    items, _ = approvals()
    for field, value in (("candidate_fingerprint", "0" * 64), ("baseline_fingerprint", "f" * 64),
                         ("case_version", "9.9.9")):
        tampered = [dict(items[0], **{field: value})]
        report = compare_runs(golden(), changed, tampered, strict=True)
        assert classes(report)["rag-supported-001"] == "new_or_unapproved_behavior", field
        assert report["gate"]["result"] == "fail"


def test_approvals_cannot_suppress_regressions(candidate_artifact):
    g = {c["case_id"]: c for c in golden()["cases"]}
    k = {c["case_id"]: c for c in candidate_artifact["cases"]}
    blanket = [
        {
            "case_id": cid,
            "case_version": "1.0.0",
            "baseline_fingerprint": g[cid]["behavior_fingerprint"],
            "candidate_fingerprint": k[cid]["behavior_fingerprint"],
            "approved_by": "test",
            "reason": "attempt to approve a regression",
        }
        for cid in sorted(INTENTIONAL)
    ]
    report = compare_runs(golden(), candidate_artifact, blanket, strict=True)
    assert {cid for cid, c in classes(report).items() if c == "regression"} == INTENTIONAL
    assert report["gate"]["result"] == "fail"
    assert sorted(report["unused_approvals"]) == sorted(f"{c}@1.0.0" for c in INTENTIONAL)


def test_new_case_classified_as_new_or_unapproved(baseline_artifact):
    candidate = copy.deepcopy(baseline_artifact)
    extra = copy.deepcopy(candidate["cases"][0])
    extra["case_id"] = "rag-zz-new-001"
    candidate["cases"].append(extra)
    report = compare_runs(golden(), candidate, strict=True)
    assert classes(report)["rag-zz-new-001"] == "new_or_unapproved_behavior"
    assert report["gate"]["blocking_cases"] == ["rag-zz-new-001"]


def test_missing_case_in_candidate_is_regression(baseline_artifact):
    candidate = copy.deepcopy(baseline_artifact)
    candidate["cases"] = [c for c in candidate["cases"] if c["case_id"] != "rag-refusal-001"]
    report = compare_runs(golden(), candidate)
    assert classes(report)["rag-refusal-001"] == "regression"
    assert report["gate"]["result"] == "fail"


def test_incomparable_artifacts_are_rejected(baseline_artifact):
    for mutate, message in [
        (lambda a: a["corpus"].update(sha256="0" * 64), "corpus"),
        (lambda a: a.update(evaluator_version="9.0.0"), "evaluator_version"),
        (lambda a: a.update(synthetic_benchmark_only=False), "synthetic_benchmark_only"),
        (lambda a: a["suite"].update(suite_id="other-suite"), "suite_id"),
        (lambda a: a.update(artifact_schema_version="0.1.0"), "artifact_schema_version"),
    ]:
        candidate = copy.deepcopy(baseline_artifact)
        mutate(candidate)
        with pytest.raises(ComparisonError, match=message):
            compare_runs(golden(), candidate)


# ---- SAFE-005 / SAFE-006 ----------------------------------------------------------------------


def test_comparison_report_carries_non_claims(candidate_artifact):
    report = compare_runs(golden(), candidate_artifact)
    assert report["synthetic_benchmark_only"] is True
    assert report["non_claims"] == NON_CLAIMS


def test_comparator_ignores_documented_intentional_regressions(
    manifests_copy, suite, candidate_artifact
):
    # Erase the documentation of the intentional regressions: behavior is unchanged, so the
    # run's case results are identical and the comparator still reports both regressions.
    path = manifests_copy / "model_manifests" / "deterministic-candidate-v2.json"
    obj = read_json(path)
    obj["documented_intentional_regressions"] = []
    write_json(path, obj)
    undocumented = run_suite(suite, load_model_manifest(path), "candidate")
    assert undocumented["cases"] == candidate_artifact["cases"]
    report = compare_runs(golden(), undocumented, strict=True)
    assert {cid for cid, c in classes(report).items() if c == "regression"} == INTENTIONAL
    assert "documented_intentional_regressions" not in json.dumps(candidate_artifact)
