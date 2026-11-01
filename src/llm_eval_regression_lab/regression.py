"""Suite runner, canonical run artifacts, and baseline/candidate comparison (REQ-013..REQ-017).

Classifications (plan.md section 4.5):

- ``pass``: both runs pass with identical behavior, or a pinned approval covers the change.
- ``regression``: candidate fails a case, a case fails in both runs, a negative control is missed,
  or a case is missing from the candidate run. Regressions are never approvable.
- ``expected_failure_demo``: a negative control is detected in both runs.
- ``new_or_unapproved_behavior``: new case, case version/hash drift, or changed-but-passing
  behavior without a pinned approval.

The candidate manifest's ``documented_intentional_regressions`` field is documentation only and
is deliberately never read here (SAFE-006).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import read_json, sha256_canonical, sha256_text
from .evaluators import (
    EVALUATOR_VERSION,
    behavior_fingerprint,
    evaluate_negative_control,
    evaluate_response,
)
from .manifests import ModelManifest
from .reporting import NON_CLAIMS
from .schemas import SchemaError, is_semver
from .simulator import simulate
from .suite import Suite

ARTIFACT_SCHEMA_VERSION = "1.0.0"
COMPARISON_SCHEMA_VERSION = "1.0.0"
FIXTURE_MODE = "deterministic-offline"

PASS = "pass"
REGRESSION = "regression"
EXPECTED_FAILURE_DEMO = "expected_failure_demo"
NEW_OR_UNAPPROVED = "new_or_unapproved_behavior"
CLASSIFICATIONS = (PASS, REGRESSION, EXPECTED_FAILURE_DEMO, NEW_OR_UNAPPROVED)

APPROVAL_FIELDS = {
    "approved_by",
    "baseline_fingerprint",
    "candidate_fingerprint",
    "case_id",
    "case_version",
    "reason",
}


class ComparisonError(ValueError):
    """Raised when two run artifacts cannot be meaningfully compared."""


# --------------------------------------------------------------------------------------------
# Running a suite
# --------------------------------------------------------------------------------------------


def run_suite(suite: Suite, manifest: ModelManifest, fixture: str) -> dict[str, Any]:
    """Run every active case and return a canonical-ready run artifact (no timestamps)."""
    active = manifest.active_metadata()
    cases: list[dict[str, Any]] = []
    for entry in suite.cases:
        case = entry.case
        if case.mode == "negative_control":
            raw, ev, detected = evaluate_negative_control(case, suite.corpus, active)
            status = "control_detected" if detected else "control_missed"
            retrieved: tuple[str, ...] = ()
            rule_id = None
            expected_codes: list[str] | None = list(
                case.negative_control.expected_failure_codes  # type: ignore[union-attr]
            )
        else:
            sim = simulate(case, suite.corpus, manifest)
            raw = sim.raw_response
            ev = evaluate_response(case, raw, suite.corpus, active)
            status = "passed" if ev.passed else "failed"
            retrieved = sim.retrieved_document_ids
            rule_id = sim.rule_id
            expected_codes = None
        cases.append(
            {
                "case_id": case.case_id,
                "case_version": case.case_version,
                "case_sha256": entry.sha256,
                "case_path": entry.path,
                "category": case.category,
                "mode": case.mode,
                "status": status,
                "expected_decision": case.expected.decision,
                "observed_decision": ev.observed_decision,
                "expected_failure_codes": expected_codes,
                "failure_codes": ev.failure_codes,
                "checks": ev.checks,
                "groundedness": ev.groundedness,
                "supported_claims": ev.supported_claims,
                "total_claims": ev.total_claims,
                "min_groundedness": case.expected.min_groundedness,
                "retrieved_document_ids": list(retrieved),
                "simulator_rule_id": rule_id,
                "raw_response": raw,
                "response_sha256": sha256_text(raw),
                "behavior_fingerprint": behavior_fingerprint(raw, ev.response),
            }
        )

    behavior = [c for c in cases if c["mode"] == "behavior"]
    controls = [c for c in cases if c["mode"] == "negative_control"]
    summary = {
        "total_cases": len(cases),
        "behavior_cases": len(behavior),
        "behavior_passed": sum(c["status"] == "passed" for c in behavior),
        "behavior_failed": sum(c["status"] == "failed" for c in behavior),
        "negative_controls": len(controls),
        "controls_detected": sum(c["status"] == "control_detected" for c in controls),
        "controls_missed": sum(c["status"] == "control_missed" for c in controls),
    }
    summary["run_passed"] = summary["behavior_failed"] == 0 and summary["controls_missed"] == 0

    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "synthetic_benchmark_only": True,
        "fixture_mode": FIXTURE_MODE,
        "fixture": fixture,
        "evaluator_version": EVALUATOR_VERSION,
        "suite": {
            "suite_id": suite.suite_id,
            "suite_version": suite.suite_version,
            "manifest_sha256": suite.manifest_sha256,
        },
        "corpus": {
            "corpus_version": suite.corpus.corpus_version,
            "sha256": suite.corpus.sha256,
            "document_count": len(suite.corpus.documents),
        },
        "prompt": {
            "prompt_id": manifest.prompt.prompt_id,
            "prompt_version": manifest.prompt.prompt_version,
            "sha256": manifest.prompt.sha256,
        },
        "model": {
            "model_id": manifest.model_id,
            "model_version": manifest.model_version,
            "kind": manifest.kind,
            "is_ai_inference": False,
            "behavior_revision": manifest.behavior_revision,
            "manifest_sha256": manifest.manifest_sha256,
        },
        "cases": cases,
        "summary": summary,
        "non_claims": NON_CLAIMS,
    }


# --------------------------------------------------------------------------------------------
# Approvals
# --------------------------------------------------------------------------------------------


def load_approvals(path: Path) -> tuple[list[dict[str, str]], str]:
    """Load and validate an approvals file. Returns (approvals, sha256)."""
    try:
        obj = read_json(Path(path))
    except (OSError, ValueError) as exc:
        raise SchemaError(f"cannot read approvals file: {exc}") from exc
    if (
        not isinstance(obj, dict)
        or set(obj) != {"approvals", "approvals_schema_version", "description", "synthetic"}
        or obj["synthetic"] is not True
        or not is_semver(obj["approvals_schema_version"])
        or not isinstance(obj["approvals"], list)
    ):
        raise SchemaError("approvals: invalid file structure")
    seen: set[tuple[str, str]] = set()
    for index, approval in enumerate(obj["approvals"]):
        if not isinstance(approval, dict) or set(approval) != APPROVAL_FIELDS:
            raise SchemaError(f"approvals[{index}]: needs exactly {sorted(APPROVAL_FIELDS)}")
        if not all(isinstance(v, str) and v.strip() for v in approval.values()):
            raise SchemaError(f"approvals[{index}]: all fields must be non-empty strings")
        key = (approval["case_id"], approval["case_version"])
        if key in seen:
            raise SchemaError(f"approvals[{index}]: duplicate approval for {key}")
        seen.add(key)
    return list(obj["approvals"]), sha256_canonical(obj)


# --------------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------------


def _check_comparable(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    for name, artifact in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(artifact, dict) or artifact.get("synthetic_benchmark_only") is not True:
            raise ComparisonError(f"{name}: not a synthetic_benchmark_only run artifact")
        if artifact.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
            raise ComparisonError(f"{name}: unsupported artifact_schema_version")
    if baseline["suite"]["suite_id"] != candidate["suite"]["suite_id"]:
        raise ComparisonError("suite_id differs between runs")
    if baseline["corpus"]["sha256"] != candidate["corpus"]["sha256"]:
        raise ComparisonError("corpus sha256 differs between runs")
    if baseline["evaluator_version"] != candidate["evaluator_version"]:
        raise ComparisonError("evaluator_version differs between runs")


def _side(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture": artifact["fixture"],
        "model_id": artifact["model"]["model_id"],
        "model_version": artifact["model"]["model_version"],
        "behavior_revision": artifact["model"]["behavior_revision"],
        "prompt_id": artifact["prompt"]["prompt_id"],
        "prompt_version": artifact["prompt"]["prompt_version"],
        "prompt_sha256": artifact["prompt"]["sha256"],
        "suite_version": artifact["suite"]["suite_version"],
        "run_passed": artifact["summary"]["run_passed"],
    }


def _classify(
    b: dict[str, Any] | None,
    c: dict[str, Any] | None,
    approvals: dict[tuple[str, str], dict[str, str]],
    used: set[tuple[str, str]],
) -> tuple[str, list[str], bool]:
    if b is None:
        return NEW_OR_UNAPPROVED, ["case not present in baseline run"], False
    if c is None:
        return REGRESSION, ["case missing from candidate run"], False
    if b["case_version"] != c["case_version"] or b["case_sha256"] != c["case_sha256"]:
        return NEW_OR_UNAPPROVED, ["case version or content hash differs between runs"], False

    if b["mode"] == "negative_control":
        if c["status"] == "control_detected" and b["status"] == "control_detected":
            return EXPECTED_FAILURE_DEMO, ["known-bad response detected in both runs"], False
        if c["status"] != "control_detected":
            return REGRESSION, ["candidate run missed a negative control"], False
        return NEW_OR_UNAPPROVED, ["baseline missed this negative control; review baseline"], False

    if c["status"] != "passed":
        why = (
            "candidate fails a case the baseline passed"
            if b["status"] == "passed"
            else "case fails in both runs"
        )
        return REGRESSION, [why, "candidate failure codes: " + ", ".join(c["failure_codes"])], False
    if b["status"] != "passed":
        return NEW_OR_UNAPPROVED, ["candidate passes a case the baseline failed"], False
    if b["behavior_fingerprint"] == c["behavior_fingerprint"]:
        return PASS, ["behavior unchanged"], False

    key = (c["case_id"], c["case_version"])
    approval = approvals.get(key)
    if (
        approval is not None
        and approval["baseline_fingerprint"] == b["behavior_fingerprint"]
        and approval["candidate_fingerprint"] == c["behavior_fingerprint"]
    ):
        used.add(key)
        return PASS, [f"behavior changed; approved: {approval['reason']}"], True
    reason = "behavior changed without a pinned approval"
    if approval is not None:
        reason = "behavior changed; approval exists but fingerprints do not match"
    return NEW_OR_UNAPPROVED, [reason], False


def compare_runs(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    approvals: list[dict[str, str]] | None = None,
    *,
    strict: bool = False,
    approvals_sha256: str | None = None,
) -> dict[str, Any]:
    _check_comparable(baseline, candidate)
    approval_map = {(a["case_id"], a["case_version"]): a for a in approvals or []}
    used: set[tuple[str, str]] = set()
    b_cases = {c["case_id"]: c for c in baseline["cases"]}
    c_cases = {c["case_id"]: c for c in candidate["cases"]}

    results = []
    for case_id in sorted(set(b_cases) | set(c_cases)):
        b, c = b_cases.get(case_id), c_cases.get(case_id)
        classification, reasons, approved = _classify(b, c, approval_map, used)
        results.append(
            {
                "case_id": case_id,
                "classification": classification,
                "approved": approved,
                "reasons": reasons,
                "baseline_status": b["status"] if b else "absent",
                "candidate_status": c["status"] if c else "absent",
                "baseline_failure_codes": b["failure_codes"] if b else [],
                "candidate_failure_codes": c["failure_codes"] if c else [],
                "baseline_groundedness": b["groundedness"] if b else None,
                "candidate_groundedness": c["groundedness"] if c else None,
            }
        )

    blocking = [REGRESSION, NEW_OR_UNAPPROVED] if strict else [REGRESSION]
    blocking_cases = [r["case_id"] for r in results if r["classification"] in blocking]
    counts = {name: sum(r["classification"] == name for r in results) for name in CLASSIFICATIONS}
    unused = sorted(f"{cid}@{ver}" for (cid, ver) in set(approval_map) - used)

    return {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "synthetic_benchmark_only": True,
        "strict": strict,
        "evaluator_version": baseline["evaluator_version"],
        "baseline": _side(baseline),
        "candidate": _side(candidate),
        "approvals_sha256": approvals_sha256,
        "cases": results,
        "counts": counts,
        "unused_approvals": unused,
        "gate": {
            "blocking_classifications": blocking,
            "blocking_cases": blocking_cases,
            "result": "fail" if blocking_cases else "pass",
        },
        "non_claims": NON_CLAIMS,
    }
