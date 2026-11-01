"""Shared fixtures. The whole test session runs with network access blocked (NFR-002)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from llm_eval_regression_lab.canonical import compact_canonical_json, read_json
from llm_eval_regression_lab.manifests import fixture_manifest_path, load_model_manifest
from llm_eval_regression_lab.offline import enforce_offline
from llm_eval_regression_lab.regression import run_suite
from llm_eval_regression_lab.schemas import CONTROLLED_MESSAGES, Case, parse_case
from llm_eval_regression_lab.suite import load_suite

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = PROJECT_ROOT / "testdata" / "cases" / "manifest.json"
CASES_DIR = PROJECT_ROOT / "testdata" / "cases" / "v1"
GOLDEN_PATH = PROJECT_ROOT / "testdata" / "golden" / "baseline_results_v1.json"
APPROVALS_PATH = PROJECT_ROOT / "testdata" / "approvals" / "candidate_v2_approvals.json"

enforce_offline()


@pytest.fixture(scope="session")
def suite():
    return load_suite(SUITE_PATH)


@pytest.fixture(scope="session")
def corpus(suite):
    return suite.corpus


@pytest.fixture(scope="session")
def baseline_manifest():
    return load_model_manifest(fixture_manifest_path(PROJECT_ROOT, "baseline"))


@pytest.fixture(scope="session")
def candidate_manifest():
    return load_model_manifest(fixture_manifest_path(PROJECT_ROOT, "candidate"))


@pytest.fixture(scope="session")
def active(baseline_manifest) -> dict[str, str]:
    return baseline_manifest.active_metadata()


@pytest.fixture(scope="session")
def baseline_artifact(suite, baseline_manifest):
    return run_suite(suite, baseline_manifest, "baseline")


@pytest.fixture(scope="session")
def candidate_artifact(suite, candidate_manifest):
    return run_suite(suite, candidate_manifest, "candidate")


def raw_case(filename: str) -> dict[str, Any]:
    return copy.deepcopy(read_json(CASES_DIR / filename))


def load_case(filename: str, **overrides: Any) -> Case:
    """Load a v1 case file, optionally overriding top-level fields, and parse it."""
    obj = raw_case(filename)
    obj.update(overrides)
    return parse_case(obj)


def response(case_id: str, active: dict[str, str], **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "case_id": case_id,
        "decision": "answer",
        "answer": "Travel requests must be submitted at least 14 days before departure.",
        "citations": [
            {
                "document_id": "SYN-001",
                "supporting_quote": "Travel requests must be submitted at least 14 days before "
                "departure.",
            }
        ],
        "reason_code": None,
        "message": None,
    }
    body.update(active)
    body.update(fields)
    return body


def non_answer(case_id: str, active: dict[str, str], decision: str, reason: str, **fields: Any):
    return response(
        case_id,
        active,
        decision=decision,
        answer=None,
        citations=[],
        reason_code=reason,
        message=CONTROLLED_MESSAGES[reason],
        **fields,
    )


def raw(obj: dict[str, Any]) -> str:
    return compact_canonical_json(obj)


def dump(obj: Any) -> str:
    return json.dumps(obj)
