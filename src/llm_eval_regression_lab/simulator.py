"""Rule-based test double standing in for an LLM/RAG system under test (REQ-010, REQ-011, REQ-019).

This is NOT AI inference. Behavior is fully declared in the model manifest:

1. Refusal rules are checked first, before retrieval (REQ-011).
2. Deterministic retrieval over the case scope; empty context -> ``NO_RETRIEVED_CONTEXT``.
3. The first answer rule (in declared order) whose trigger terms all appear in the question and
   whose cited documents were all retrieved produces a fixed answer with fixed citations.
4. Otherwise -> ``EVIDENCE_NOT_FOUND``.

The simulator does not validate its own citations; that is the evaluator's job.
"""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import compact_canonical_json
from .corpus import Corpus
from .manifests import ModelManifest
from .retrieval import retrieve, tokenize
from .schemas import (
    CONTROLLED_MESSAGES,
    DECISION_ANSWER,
    DECISION_INSUFFICIENT,
    DECISION_REFUSAL,
    Case,
)


@dataclass(frozen=True)
class SimulationResult:
    raw_response: str
    retrieved_document_ids: tuple[str, ...]
    rule_id: str | None


def _response(case: Case, manifest: ModelManifest, **fields: object) -> str:
    body: dict[str, object] = {
        "case_id": case.case_id,
        "answer": None,
        "citations": [],
        "reason_code": None,
        "message": None,
    }
    body.update(fields)
    body.update(manifest.active_metadata())
    return compact_canonical_json(body)


def _non_answer(case: Case, manifest: ModelManifest, decision: str, reason_code: str) -> str:
    return _response(
        case,
        manifest,
        decision=decision,
        reason_code=reason_code,
        message=CONTROLLED_MESSAGES[reason_code],
    )


def simulate(case: Case, corpus: Corpus, manifest: ModelManifest) -> SimulationResult:
    question_tokens = set(tokenize(case.question))

    for rule in manifest.refusal_rules:
        if set(rule.trigger_terms) <= question_tokens:
            raw = _non_answer(case, manifest, DECISION_REFUSAL, rule.reason_code)
            return SimulationResult(raw, (), rule.rule_id)

    retrieved = retrieve(case.question, corpus, case.retrieval_scope, manifest.top_k)
    retrieved_ids = tuple(item.document_id for item in retrieved)
    if not retrieved_ids:
        raw = _non_answer(case, manifest, DECISION_INSUFFICIENT, "NO_RETRIEVED_CONTEXT")
        return SimulationResult(raw, retrieved_ids, None)

    for rule in manifest.answer_rules:
        cited = {citation["document_id"] for citation in rule.citations}
        if set(rule.trigger_terms) <= question_tokens and cited <= set(retrieved_ids):
            raw = _response(
                case,
                manifest,
                decision=DECISION_ANSWER,
                answer=rule.answer,
                citations=[dict(citation) for citation in rule.citations],
            )
            return SimulationResult(raw, retrieved_ids, rule.rule_id)

    raw = _non_answer(case, manifest, DECISION_INSUFFICIENT, "EVIDENCE_NOT_FOUND")
    return SimulationResult(raw, retrieved_ids, None)
