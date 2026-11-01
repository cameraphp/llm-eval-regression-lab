"""Corpus contract, case contract, response schema, decision invariants.

REQ-001, REQ-003, REQ-004, REQ-005, SAFE-004.
"""

from __future__ import annotations

import copy

import pytest
from conftest import CASES_DIR, PROJECT_ROOT, non_answer, raw_case, response

from llm_eval_regression_lab.canonical import read_json
from llm_eval_regression_lab.corpus import load_corpus, validate_corpus_dict
from llm_eval_regression_lab.schemas import (
    CONTROLLED_MESSAGES,
    SchemaError,
    parse_case,
    parse_response,
    validate_response,
)

CORPUS_PATH = PROJECT_ROOT / "testdata" / "corpus" / "synthetic_corpus_v1.json"


def codes(findings):
    return sorted({f.code for f in findings})


# ---- REQ-001 corpus -------------------------------------------------------------------------


def test_corpus_loads_with_synthetic_flags_and_hash():
    corpus = load_corpus(CORPUS_PATH)
    assert corpus.corpus_version == "synthetic-corpus-v1"
    assert corpus.document_ids == ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")
    assert len(corpus.sha256) == 64
    raw = read_json(CORPUS_PATH)
    assert raw["synthetic"] is True
    assert all(d["synthetic"] and d["allowed_for_benchmark"] for d in raw["documents"])
    # Hash is content-based: reloading yields the same value.
    assert load_corpus(CORPUS_PATH).sha256 == corpus.sha256


@pytest.mark.parametrize("field", ["synthetic", "allowed_for_benchmark"])
def test_corpus_rejects_non_synthetic_document(field):
    raw = read_json(CORPUS_PATH)
    raw["documents"][0][field] = False
    with pytest.raises(SchemaError, match="synthetic"):
        validate_corpus_dict(raw)


def test_corpus_rejects_duplicate_ids_and_version_mismatch():
    raw = read_json(CORPUS_PATH)
    dup = copy.deepcopy(raw)
    dup["documents"][1]["document_id"] = "SYN-001"
    with pytest.raises(SchemaError, match="duplicate"):
        validate_corpus_dict(dup)
    mismatch = copy.deepcopy(raw)
    mismatch["documents"][2]["corpus_version"] = "synthetic-corpus-v0"
    with pytest.raises(SchemaError, match="corpus_version"):
        validate_corpus_dict(mismatch)
    missing = copy.deepcopy(raw)
    del missing["documents"][0]["title"]
    with pytest.raises(SchemaError, match="missing"):
        validate_corpus_dict(missing)


# ---- REQ-003 case contract ------------------------------------------------------------------


def test_all_suite_cases_satisfy_case_contract():
    files = sorted(CASES_DIR.glob("*.json"))
    assert len(files) == 10
    for path in files:
        case = parse_case(read_json(path))
        assert "synthetic" in case.synthetic_fixture_note.lower()
        assert case.mode in ("behavior", "negative_control")
        if case.mode == "negative_control":
            assert case.negative_control is not None
            assert case.negative_control.expected_failure_codes


def test_case_contract_rejects_missing_or_unknown_fields():
    for mutate, message in [
        (lambda c: c.pop("retrieval_scope"), "missing"),
        (lambda c: c.update({"surprise": 1}), "unknown"),
        (lambda c: c["expected"].pop("min_groundedness"), "missing"),
        (lambda c: c.update({"synthetic_fixture_note": "real customer data"}), "synthetic"),
        (lambda c: c.update({"case_version": "v1"}), "semantic"),
        (lambda c: c.update({"mode": "negative_control"}), "negative_control"),
    ]:
        obj = raw_case("supported_single_source.json")
        mutate(obj)
        with pytest.raises(SchemaError, match=message):
            parse_case(obj)


def test_answer_case_requires_claims_and_citations():
    obj = raw_case("supported_single_source.json")
    obj["expected"]["claims"] = []
    with pytest.raises(SchemaError, match="claims"):
        parse_case(obj)
    obj = raw_case("supported_single_source.json")
    obj["expected"]["min_groundedness"] = 1.5
    with pytest.raises(SchemaError, match="min_groundedness"):
        parse_case(obj)
    obj = raw_case("insufficient_evidence.json")
    obj["expected"]["reason_code"] = "POLICY_RESTRICTED_CREDENTIAL_REQUEST"
    with pytest.raises(SchemaError, match="reason_code"):
        parse_case(obj)


# ---- REQ-004 response schema ----------------------------------------------------------------


def test_valid_answer_response_passes_schema(active):
    obj, findings = parse_response(
        '{"case_id":"x","decision":"answer","answer":"a","citations":[{"document_id":"SYN-001",'
        '"supporting_quote":"q"}],"reason_code":null,"message":null,'
        f'"prompt_id":"{active["prompt_id"]}","prompt_version":"1.0.0",'
        f'"model_id":"{active["model_id"]}","model_version":"1.0.0"}}'
    )
    assert findings == []
    assert validate_response(obj) == []


@pytest.mark.parametrize(
    "raw",
    [
        '{"case_id": "x", "decision": "maybe", "answer": ',
        "not json at all",
        "[1, 2, 3]",
        '{"case_id": "x", "case_id": "y"}',
        '{"score": NaN}',
        "",
    ],
)
def test_malformed_json_is_rejected(raw):
    obj, findings = parse_response(raw)
    assert obj is None
    assert codes(findings) == ["SCHEMA_INVALID"]


def test_missing_and_extra_fields_are_rejected(active):
    missing = response("x", active)
    del missing["citations"]
    assert codes(validate_response(missing)) == ["SCHEMA_INVALID"]
    extra = response("x", active, confidence=0.99)
    assert codes(validate_response(extra)) == ["SCHEMA_INVALID"]


def test_invalid_decision_value_is_rejected(active):
    for decision in ("maybe", "ANSWER", None, 1):
        assert codes(validate_response(response("x", active, decision=decision))) == [
            "SCHEMA_INVALID"
        ]


def test_bad_semver_and_citation_shape_are_rejected(active):
    for fields in (
        {"prompt_version": "v1"},
        {"model_version": "1.0"},
        {"citations": [{"document_id": "SYN-001"}]},
        {"citations": [{"document_id": "SYN-001", "supporting_quote": ""}]},
        {"citations": [{"document_id": "SYN-001", "supporting_quote": "q", "page": 1}]},
        {"citations": "SYN-001"},
        {"answer": 42},
    ):
        assert codes(validate_response(response("x", active, **fields))) == ["SCHEMA_INVALID"], (
            fields
        )


# ---- REQ-005 decision invariants ------------------------------------------------------------


def test_answer_requires_text_and_citation(active):
    assert codes(validate_response(response("x", active, answer="  "))) == [
        "DECISION_INVARIANT_VIOLATION"
    ]
    assert codes(validate_response(response("x", active, citations=[]))) == [
        "DECISION_INVARIANT_VIOLATION"
    ]
    assert codes(validate_response(response("x", active, reason_code="EVIDENCE_NOT_FOUND"))) == [
        "DECISION_INVARIANT_VIOLATION"
    ]


def test_insufficient_evidence_forbids_answer_and_citations(active):
    ok = non_answer("x", active, "insufficient_evidence", "EVIDENCE_NOT_FOUND")
    assert validate_response(ok) == []
    leaked = dict(ok, answer="The allowance is 40 credits.")
    assert codes(validate_response(leaked)) == ["UNSUPPORTED_ANSWER_LEAKAGE"]
    cited = dict(ok, citations=[{"document_id": "SYN-001", "supporting_quote": "q"}])
    assert codes(validate_response(cited)) == ["UNSUPPORTED_ANSWER_LEAKAGE"]


def test_refusal_requires_documented_reason_code(active):
    ok = non_answer("x", active, "refusal", "POLICY_RESTRICTED_CREDENTIAL_REQUEST")
    assert validate_response(ok) == []
    for reason in (None, "EVIDENCE_NOT_FOUND", "BECAUSE_I_SAID_SO"):
        bad = dict(ok, reason_code=reason)
        assert codes(validate_response(bad)) == ["DECISION_INVARIANT_VIOLATION"], reason
    leaked = dict(ok, answer="The override code is 1234.")
    assert "UNSUPPORTED_ANSWER_LEAKAGE" in codes(validate_response(leaked))


def test_controlled_message_must_match_reason_code(active):
    ok = non_answer("x", active, "insufficient_evidence", "NO_RETRIEVED_CONTEXT")
    assert ok["message"] == CONTROLLED_MESSAGES["NO_RETRIEVED_CONTEXT"]
    free_text = dict(ok, message="I think the office opens at 08:00.")
    assert codes(validate_response(free_text)) == ["DECISION_INVARIANT_VIOLATION"]
    swapped = dict(ok, message=CONTROLLED_MESSAGES["EVIDENCE_NOT_FOUND"])
    assert codes(validate_response(swapped)) == ["DECISION_INVARIANT_VIOLATION"]
