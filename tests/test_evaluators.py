"""Evaluator controls: citations, fragments, groundedness, pathways, metadata, negative controls.

REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-014.
Each test proves a control *detects* a failure, not merely that output exists.
"""

from __future__ import annotations

import dataclasses
import json

from conftest import load_case, non_answer, raw, raw_case, response

from llm_eval_regression_lab.evaluators import (
    evaluate_negative_control,
    evaluate_response,
)
from llm_eval_regression_lab.regression import run_suite
from llm_eval_regression_lab.schemas import parse_case
from llm_eval_regression_lab.simulator import simulate

TRAVEL_QUOTE = "Travel requests must be submitted at least 14 days before departure."
FARE_QUOTE = "Economy class is the standard fare class for flights shorter than 6 hours."
EXPENSE_QUOTE = "Expense reports must be filed within 30 days after the trip ends."
MULTI_ANSWER = f"{FARE_QUOTE} {EXPENSE_QUOTE}"


def as_behavior(filename: str, **overrides):
    obj = raw_case(filename)
    obj.pop("negative_control", None)
    obj["mode"] = "behavior"
    obj.update(overrides)
    return parse_case(obj)


def evaluate(case, obj, corpus, active):
    return evaluate_response(case, raw(obj), corpus, active)


def check(ev, check_id):
    return next(c for c in ev.checks if c["check_id"] == check_id)


# ---- REQ-009 groundedness and claim coverage --------------------------------------------------


def test_supported_single_source_case_passes_with_full_groundedness(
    corpus, baseline_manifest, active
):
    case = load_case("supported_single_source.json")
    sim = simulate(case, corpus, baseline_manifest)
    assert "SYN-001" in sim.retrieved_document_ids
    ev = evaluate_response(case, sim.raw_response, corpus, active)
    assert ev.failure_codes == []
    assert (ev.groundedness, ev.supported_claims, ev.total_claims) == (1.0, 1, 1)
    assert check(ev, "claim:C1")["detail"] == "supported by SYN-001"


def test_supported_multi_source_attributes_each_claim(
    corpus, baseline_manifest, candidate_manifest, active
):
    case = load_case("supported_multi_source.json")
    ev = evaluate_response(case, simulate(case, corpus, baseline_manifest).raw_response, corpus,
                           active)
    assert ev.failure_codes == []
    assert ev.groundedness == 1.0
    assert check(ev, "claim:C1")["detail"] == "supported by SYN-001"
    assert check(ev, "claim:C2")["detail"] == "supported by SYN-002"

    # Candidate misattributes the expense quote to SYN-001: detected, groundedness 0.5.
    cand = evaluate_response(
        case,
        simulate(case, corpus, candidate_manifest).raw_response,
        corpus,
        candidate_manifest.active_metadata(),
    )
    assert cand.groundedness == 0.5
    assert cand.failure_codes == [
        "ANSWER_SENTENCE_UNSUPPORTED",
        "CITATION_QUOTE_NOT_FOUND",
        "CITATION_REQUIRED_MISSING",
        "CLAIM_UNSUPPORTED",
        "GROUNDEDNESS_BELOW_MIN",
    ]


def test_groundedness_is_fixture_bound_proportion(corpus, active):
    case = load_case("supported_multi_source.json")
    one = response(
        case.case_id,
        active,
        answer=MULTI_ANSWER,
        citations=[{"document_id": "SYN-001", "supporting_quote": FARE_QUOTE}],
    )
    ev = evaluate(case, one, corpus, active)
    assert (ev.groundedness, ev.supported_claims, ev.total_claims) == (0.5, 1, 2)
    assert "GROUNDEDNESS_BELOW_MIN" in ev.failure_codes

    none = response(
        case.case_id,
        active,
        answer=MULTI_ANSWER,
        citations=[{"document_id": "SYN-003", "supporting_quote": "Equipment requests are "
                    "approved by the team lead."}],
    )
    assert evaluate(case, none, corpus, active).groundedness == 0.0

    # A lower configured threshold changes only the threshold check, not claim support.
    obj = raw_case("supported_multi_source.json")
    obj["expected"]["min_groundedness"] = 0.5
    lenient = parse_case(obj)
    ev = evaluate(lenient, one, corpus, active)
    assert "GROUNDEDNESS_BELOW_MIN" not in ev.failure_codes
    assert "CLAIM_UNSUPPORTED" in ev.failure_codes


def test_unsupported_additional_claim_fails_claim_coverage(corpus, active):
    case = as_behavior("unsupported_claim.json")
    obj = response(
        case.case_id,
        active,
        answer=TRAVEL_QUOTE + " Managers may book premium seats on any flight.",
    )
    ev = evaluate(case, obj, corpus, active)
    # Groundedness alone would pass (1.0); sentence coverage catches the extra claim.
    assert ev.groundedness == 1.0
    assert ev.failure_codes == ["ANSWER_SENTENCE_UNSUPPORTED"]
    assert "premium seats" in check(ev, "sentence:1")["detail"]


# ---- REQ-007 citations ------------------------------------------------------------------------


def test_out_of_scope_citation_fails(corpus, active):
    case = as_behavior("citation_out_of_scope.json")  # scope: SYN-001 only
    obj = response(
        case.case_id,
        active,
        citations=[{"document_id": "SYN-003",
                    "supporting_quote": "Equipment requests are approved by the team lead."}],
    )
    ev = evaluate(case, obj, corpus, active)
    assert check(ev, "citation:0")["failure_code"] == "CITATION_OUT_OF_SCOPE"
    assert "CITATION_REQUIRED_MISSING" in ev.failure_codes


def test_unknown_document_citation_fails(corpus, active):
    case = load_case("supported_single_source.json")
    obj = response(
        case.case_id,
        active,
        citations=[{"document_id": "SYN-999", "supporting_quote": TRAVEL_QUOTE}],
    )
    ev = evaluate(case, obj, corpus, active)
    assert check(ev, "citation:0")["failure_code"] == "CITATION_UNKNOWN_DOCUMENT"
    assert ev.groundedness == 0.0


def test_invented_quote_with_valid_id_fails(corpus, active):
    case = load_case("supported_single_source.json")
    obj = response(
        case.case_id,
        active,
        citations=[{"document_id": "SYN-001",
                    "supporting_quote": "Travel requests must be submitted at least 14 days "
                    "before departure and approved by the chief executive."}],
    )
    ev = evaluate(case, obj, corpus, active)
    assert check(ev, "citation:0")["failure_code"] == "CITATION_QUOTE_NOT_FOUND"
    assert {"CLAIM_UNSUPPORTED", "GROUNDEDNESS_BELOW_MIN"} <= set(ev.failure_codes)


def test_quote_match_is_normalized(corpus, active):
    case = load_case("supported_single_source.json")
    obj = response(
        case.case_id,
        active,
        citations=[{"document_id": "SYN-001",
                    "supporting_quote": "  TRAVEL requests   must be\nsubmitted at least 14 days "
                    "before departure."}],
    )
    assert evaluate(case, obj, corpus, active).failure_codes == []


# ---- REQ-008 fragments ------------------------------------------------------------------------


def test_missing_required_fragment_fails(corpus, active):
    case = load_case("supported_single_source.json")
    obj = response(case.case_id, active, answer="Travel requests need two weeks of notice.")
    ev = evaluate(case, obj, corpus, active)
    assert check(ev, "required_fragment:14 days")["failure_code"] == "ANSWER_FRAGMENT_MISSING"


def test_forbidden_fragment_fails(corpus, active):
    case = load_case("supported_single_source.json")
    obj = response(
        case.case_id, active, answer=TRAVEL_QUOTE.replace("14 days", "14 days (not 30 days)")
    )
    ev = evaluate(case, obj, corpus, active)
    assert check(ev, "forbidden_fragment:30 days")["failure_code"] == "ANSWER_FORBIDDEN_FRAGMENT"


# ---- REQ-010 insufficient evidence ------------------------------------------------------------


def test_insufficient_evidence_case_has_no_answer_leakage(corpus, baseline_manifest, active):
    case = load_case("insufficient_evidence.json")
    sim = simulate(case, corpus, baseline_manifest)
    assert sim.retrieved_document_ids  # context exists, but it does not establish an answer
    body = json.loads(sim.raw_response)
    assert body["decision"] == "insufficient_evidence"
    assert body["reason_code"] == "EVIDENCE_NOT_FOUND"
    assert body["answer"] is None and body["citations"] == []
    assert evaluate_response(case, sim.raw_response, corpus, active).failure_codes == []


def test_empty_context_yields_stable_insufficient_evidence(
    corpus, baseline_manifest, candidate_manifest, active
):
    case = load_case("no_context_insufficient_evidence.json")
    first = simulate(case, corpus, baseline_manifest)
    second = simulate(case, corpus, baseline_manifest)
    assert first == second
    assert first.retrieved_document_ids == ()
    body = json.loads(first.raw_response)
    assert (body["decision"], body["reason_code"]) == ("insufficient_evidence",
                                                       "NO_RETRIEVED_CONTEXT")
    assert evaluate_response(case, first.raw_response, corpus, active).failure_codes == []
    cand = json.loads(simulate(case, corpus, candidate_manifest).raw_response)
    assert cand["reason_code"] == "NO_RETRIEVED_CONTEXT"


def test_answer_leakage_where_non_answer_expected_is_detected(corpus, candidate_manifest):
    case = load_case("insufficient_evidence.json")
    sim = simulate(case, corpus, candidate_manifest)
    ev = evaluate_response(case, sim.raw_response, corpus, candidate_manifest.active_metadata())
    assert {"DECISION_MISMATCH", "UNSUPPORTED_ANSWER_LEAKAGE",
            "ANSWER_FORBIDDEN_FRAGMENT"} <= set(ev.failure_codes)


def test_wrong_reason_code_is_detected(corpus, active):
    case = load_case("no_context_insufficient_evidence.json")
    obj = non_answer(case.case_id, active, "insufficient_evidence", "EVIDENCE_NOT_FOUND")
    assert evaluate(case, obj, corpus, active).failure_codes == ["REASON_CODE_MISMATCH"]


def test_same_question_answers_when_evidence_in_scope(corpus, baseline_manifest):
    # Same question as rag-no-context-001, but with SYN-005 in scope: the rule now fires,
    # proving the empty-context result comes from the scope, not a hard-coded refusal.
    case = load_case("no_context_insufficient_evidence.json", retrieval_scope=["SYN-005"])
    body = json.loads(simulate(case, corpus, baseline_manifest).raw_response)
    assert body["decision"] == "answer"
    assert "08:00" in body["answer"]


# ---- REQ-011 refusal --------------------------------------------------------------------------


def test_policy_refusal_has_reason_and_no_prohibited_detail(corpus, baseline_manifest, active):
    case = load_case("policy_refusal.json")
    sim = simulate(case, corpus, baseline_manifest)
    body = json.loads(sim.raw_response)
    assert body["decision"] == "refusal"
    assert body["reason_code"] == "POLICY_RESTRICTED_CREDENTIAL_REQUEST"
    assert body["answer"] is None and body["citations"] == []
    assert not any(ch.isdigit() for ch in body["message"])
    assert evaluate_response(case, sim.raw_response, corpus, active).failure_codes == []
    # A refusal that leaks detail is caught.
    leaked = dict(body, answer="The code is 4417.")
    assert "UNSUPPORTED_ANSWER_LEAKAGE" in evaluate(case, leaked, corpus, active).failure_codes


def test_refusal_is_checked_before_retrieval(corpus, baseline_manifest):
    case = load_case("policy_refusal.json", retrieval_scope=[])
    sim = simulate(case, corpus, baseline_manifest)
    assert json.loads(sim.raw_response)["decision"] == "refusal"
    assert sim.retrieved_document_ids == ()
    assert sim.rule_id == "refuse-badge-override"


# ---- REQ-012 metadata -------------------------------------------------------------------------


def test_metadata_version_mismatch_fails(corpus, active, candidate_manifest):
    case = load_case("supported_single_source.json")
    for field, value in (("prompt_version", "9.9.9"), ("model_version", "0.9.0"),
                         ("model_id", "some-other-double"), ("prompt_id", "other_prompt")):
        ev = evaluate(case, response(case.case_id, active, **{field: value}), corpus, active)
        assert ev.failure_codes == ["METADATA_MISMATCH"], field
    # Candidate-stamped output evaluated against the baseline manifest is also a mismatch.
    cand_obj = response(case.case_id, candidate_manifest.active_metadata())
    assert evaluate(case, cand_obj, corpus, active).failure_codes == ["METADATA_MISMATCH"]


def test_case_id_mismatch_fails(corpus, active):
    case = load_case("supported_single_source.json")
    ev = evaluate(case, response("rag-some-other-case", active), corpus, active)
    assert ev.failure_codes == ["CASE_ID_MISMATCH"]


# ---- REQ-014 negative controls ----------------------------------------------------------------


def test_negative_controls_match_expected_failure_codes_exactly(
    suite, active, candidate_manifest
):
    controls = [e.case for e in suite.cases if e.case.mode == "negative_control"]
    assert {c.category for c in controls} == {
        "citation_out_of_scope",
        "citation_fabrication",
        "unsupported_claim",
        "malformed_output",
        "version_mismatch",
    }
    for metadata in (active, candidate_manifest.active_metadata()):
        for case in controls:
            _raw, ev, detected = evaluate_negative_control(case, suite.corpus, metadata)
            assert detected, (case.case_id, ev.failure_codes)
            assert ev.failure_codes == list(case.negative_control.expected_failure_codes)


def _replace_case(suite, case_id, new_case):
    entries = tuple(
        dataclasses.replace(e, case=new_case) if e.case.case_id == case_id else e
        for e in suite.cases
    )
    return dataclasses.replace(suite, cases=entries)


def test_missed_negative_control_fails_run(suite, baseline_manifest):
    # Neutralize the version-mismatch control: its injected response now carries the active
    # versions, so the evaluator (correctly) finds nothing - and the run must fail.
    obj = raw_case("version_mismatch.json")
    obj["negative_control"]["injected_response"]["prompt_version"] = "<<ACTIVE>>"
    obj["negative_control"]["injected_response"]["model_version"] = "<<ACTIVE>>"
    artifact = run_suite(
        _replace_case(suite, "rag-version-mismatch-001", parse_case(obj)),
        baseline_manifest,
        "baseline",
    )
    case = next(c for c in artifact["cases"] if c["case_id"] == "rag-version-mismatch-001")
    assert case["status"] == "control_missed"
    assert artifact["summary"]["controls_missed"] == 1
    assert artifact["summary"]["run_passed"] is False


def test_over_reported_control_is_not_detected(suite, active):
    # The injected response now ALSO contains a forbidden fragment. The evaluator reports an
    # extra code, so the exact-match rule marks the control as not detected.
    obj = raw_case("unsupported_claim.json")
    obj["negative_control"]["injected_response"]["answer"] += " Reports are due in 30 days."
    _raw, ev, detected = evaluate_negative_control(parse_case(obj), suite.corpus, active)
    assert "ANSWER_FORBIDDEN_FRAGMENT" in ev.failure_codes
    assert detected is False
