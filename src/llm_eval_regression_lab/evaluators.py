"""Deterministic, fixture-bound response evaluation (REQ-004..REQ-012, REQ-014).

Every check here is lexical and bound to the synthetic fixtures: normalized substring matching
against the synthetic corpus and configured claim fragments. This is NOT semantic entailment,
broad factuality, or evidence that any real model is grounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .canonical import compact_canonical_json, normalize_text, sha256_canonical, sha256_text
from .corpus import Corpus
from .schemas import (
    ACTIVE_PLACEHOLDER,
    DECISION_ANSWER,
    METADATA_FIELDS,
    Case,
    parse_response,
    validate_response,
)

EVALUATOR_VERSION = "1.0.0"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Evaluation:
    checks: list[dict[str, Any]] = field(default_factory=list)
    groundedness: float | None = None
    supported_claims: int | None = None
    total_claims: int | None = None
    observed_decision: str | None = None
    response: dict[str, Any] | None = None

    def add(self, check_id: str, passed: bool, code: str, detail: str) -> bool:
        self.checks.append(
            {
                "check_id": check_id,
                "passed": passed,
                "failure_code": None if passed else code,
                "detail": detail,
            }
        )
        return passed

    @property
    def failure_codes(self) -> list[str]:
        return sorted({c["failure_code"] for c in self.checks if c["failure_code"] is not None})

    @property
    def passed(self) -> bool:
        return not self.failure_codes


def behavior_fingerprint(raw: str, response: dict[str, Any] | None) -> str:
    """Hash of the behavior-bearing part of a response (metadata fields excluded)."""
    if response is None:
        return sha256_text(raw)
    return sha256_canonical({k: v for k, v in response.items() if k not in METADATA_FIELDS})


def split_sentences(text: str) -> list[str]:
    return [part for part in (p.strip() for p in _SENTENCE_SPLIT.split(text.strip())) if part]


def evaluate_response(
    case: Case, raw: str, corpus: Corpus, active_metadata: dict[str, str]
) -> Evaluation:
    """Evaluate one raw structured response against a case's versioned expectations."""
    ev = Evaluation()

    obj, parse_findings = parse_response(raw)
    if obj is None:
        for finding in parse_findings:
            ev.add("schema:parse", False, finding.code, finding.detail)
        return ev

    findings = validate_response(obj)
    structural = [f for f in findings if f.code == "SCHEMA_INVALID"]
    if structural:
        for index, finding in enumerate(structural):
            ev.add(f"schema:{index}", False, finding.code, finding.detail)
        return ev
    ev.add("schema", True, "SCHEMA_INVALID", "response matches the structured schema")
    ev.response = obj
    ev.observed_decision = obj["decision"]

    if findings:
        for index, finding in enumerate(findings):
            ev.add(f"invariant:{index}", False, finding.code, finding.detail)
    else:
        ev.add("invariants", True, "DECISION_INVARIANT_VIOLATION", "decision invariants hold")

    _check_metadata(ev, case, obj, active_metadata)

    expected = case.expected
    decision_ok = ev.add(
        "decision",
        obj["decision"] == expected.decision,
        "DECISION_MISMATCH",
        f"expected {expected.decision}, observed {obj['decision']}",
    )
    if decision_ok and expected.decision != DECISION_ANSWER:
        ev.add(
            "reason_code",
            obj["reason_code"] == expected.reason_code,
            "REASON_CODE_MISMATCH",
            f"expected {expected.reason_code}, observed {obj['reason_code']}",
        )

    if obj["decision"] == DECISION_ANSWER:
        if expected.decision != DECISION_ANSWER:
            ev.add(
                "answer_leakage",
                False,
                "UNSUPPORTED_ANSWER_LEAKAGE",
                f"substantive answer produced where {expected.decision} was expected",
            )
        valid = _check_citations(ev, case, obj["citations"], corpus)
        _check_required_citations(ev, case, valid)
        _check_fragments(ev, case, obj["answer"])
        supported_fragments = _check_claims(ev, case, obj["answer"], valid)
        _check_sentence_coverage(ev, obj["answer"], supported_fragments)
    return ev


def _check_metadata(
    ev: Evaluation, case: Case, obj: dict[str, Any], active: dict[str, str]
) -> None:
    ev.add(
        "case_id",
        obj["case_id"] == case.case_id,
        "CASE_ID_MISMATCH",
        f"expected {case.case_id}, observed {obj['case_id']}",
    )
    mismatches = [
        f"{key}: expected {active[key]}, observed {obj[key]}"
        for key in METADATA_FIELDS
        if obj[key] != active[key]
    ]
    ev.add(
        "metadata",
        not mismatches,
        "METADATA_MISMATCH",
        "; ".join(mismatches) if mismatches else "prompt/model metadata matches active manifest",
    )


def _check_citations(
    ev: Evaluation, case: Case, citations: list[dict[str, str]], corpus: Corpus
) -> list[dict[str, str]]:
    """Per citation, first failure wins: unknown -> out of scope -> quote not found."""
    valid: list[dict[str, str]] = []
    scope = set(case.retrieval_scope)
    for index, citation in enumerate(citations):
        doc_id = citation["document_id"]
        check_id = f"citation:{index}"
        document = corpus.get(doc_id)
        if document is None:
            ev.add(check_id, False, "CITATION_UNKNOWN_DOCUMENT", f"{doc_id} is not in the corpus")
        elif doc_id not in scope:
            ev.add(check_id, False, "CITATION_OUT_OF_SCOPE", f"{doc_id} is outside case scope")
        elif normalize_text(citation["supporting_quote"]) not in normalize_text(document.content):
            ev.add(
                check_id,
                False,
                "CITATION_QUOTE_NOT_FOUND",
                f"supporting_quote is not a normalized substring of {doc_id}",
            )
        else:
            ev.add(check_id, True, "", f"{doc_id} quote verified")
            valid.append(citation)
    return valid


def _check_required_citations(ev: Evaluation, case: Case, valid: list[dict[str, str]]) -> None:
    valid_docs = {c["document_id"] for c in valid}
    for doc_id in case.expected.required_citations:
        ev.add(
            f"required_citation:{doc_id}",
            doc_id in valid_docs,
            "CITATION_REQUIRED_MISSING",
            f"{doc_id} {'is' if doc_id in valid_docs else 'is not'} validly cited",
        )


def _check_fragments(ev: Evaluation, case: Case, answer: str) -> None:
    normalized = normalize_text(answer)
    for fragment in case.expected.required_answer_fragments:
        present = normalize_text(fragment) in normalized
        ev.add(
            f"required_fragment:{fragment}",
            present,
            "ANSWER_FRAGMENT_MISSING",
            f"required fragment {'present' if present else 'missing'}",
        )
    for fragment in case.expected.forbidden_answer_fragments:
        present = normalize_text(fragment) in normalized
        ev.add(
            f"forbidden_fragment:{fragment}",
            not present,
            "ANSWER_FORBIDDEN_FRAGMENT",
            f"forbidden fragment {'present' if present else 'absent'}",
        )


def _check_claims(
    ev: Evaluation, case: Case, answer: str, valid: list[dict[str, str]]
) -> list[str]:
    """Fixture-bound groundedness: supported required claims / total required claims."""
    normalized_answer = normalize_text(answer)
    supported_fragments: list[str] = []
    claims = case.expected.claims
    for claim in claims:
        fragment = normalize_text(claim.fragment)
        in_answer = fragment in normalized_answer
        supporting = sorted(
            c["document_id"]
            for c in valid
            if c["document_id"] in claim.support_document_ids
            and fragment in normalize_text(c["supporting_quote"])
        )
        supported = in_answer and bool(supporting)
        if supported:
            supported_fragments.append(fragment)
            detail = f"supported by {', '.join(supporting)}"
        elif not in_answer:
            detail = "claim fragment absent from answer"
        else:
            detail = "no valid citation from an allowed document supports this fragment"
        ev.add(f"claim:{claim.claim_id}", supported, "CLAIM_UNSUPPORTED", detail)

    if claims:
        ev.supported_claims = len(supported_fragments)
        ev.total_claims = len(claims)
        ev.groundedness = round(len(supported_fragments) / len(claims), 4)
        minimum = case.expected.min_groundedness
        if minimum is not None:
            ev.add(
                "groundedness",
                ev.groundedness >= minimum,
                "GROUNDEDNESS_BELOW_MIN",
                f"{ev.supported_claims}/{ev.total_claims} = {ev.groundedness} "
                f"(minimum {minimum})",
            )
    return supported_fragments


def _check_sentence_coverage(ev: Evaluation, answer: str, supported_fragments: list[str]) -> None:
    """Every answer sentence must carry at least one supported claim fragment."""
    for index, sentence in enumerate(split_sentences(answer)):
        normalized = normalize_text(sentence)
        covered = any(fragment in normalized for fragment in supported_fragments)
        ev.add(
            f"sentence:{index}",
            covered,
            "ANSWER_SENTENCE_UNSUPPORTED",
            "sentence carries a supported claim" if covered else f"unsupported: {sentence!r}",
        )


def materialize_injected_response(case: Case, active_metadata: dict[str, str]) -> str:
    """Build the raw response for a negative-control case (``<<ACTIVE>>`` -> active value)."""
    control = case.negative_control
    if control is None:
        raise ValueError(f"{case.case_id} is not a negative-control case")
    if control.injected_raw is not None:
        return control.injected_raw
    response = dict(control.injected_response or {})
    for key in METADATA_FIELDS:
        if response.get(key) == ACTIVE_PLACEHOLDER:
            response[key] = active_metadata[key]
    return compact_canonical_json(response)


def evaluate_negative_control(
    case: Case, corpus: Corpus, active_metadata: dict[str, str]
) -> tuple[str, Evaluation, bool]:
    """Evaluate an injected bad response. Detected only on an exact failure-code match."""
    raw = materialize_injected_response(case, active_metadata)
    ev = evaluate_response(case, raw, corpus, active_metadata)
    expected = sorted(case.negative_control.expected_failure_codes)  # type: ignore[union-attr]
    return raw, ev, ev.failure_codes == expected
